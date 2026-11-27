"""Static syntax extraction only. Never import/eval/execute inspected source."""
from __future__ import annotations
import ast
from dataclasses import dataclass,field,asdict
from hashlib import sha256
from pathlib import PurePosixPath
import posixpath
import re

PARSER_VERSION='code-syntax-v3-1'


def module_name(path):
    parts=list(PurePosixPath(path).with_suffix('').parts)
    if parts[-1]=='__init__':parts.pop()
    return '.'.join(parts)


def is_test_path(path):
    return bool(re.search(r'(^|/)(tests?|test_[^/]+)(/|\.)|\.(?:test|spec)\.[jt]sx?$',path,re.I))


@dataclass
class CodeSymbol:
    symbol_id:str
    path:str
    name:str
    qualified_name:str
    kind:str
    start_line:int
    end_line:int
    signature:str
    docstring:str
    language:str
    exported_as:list[str]=field(default_factory=list)


@dataclass
class RawReference:
    source_id:str
    target:str
    kind:str
    line:int


@dataclass
class ParsedFile:
    path:str
    status:str
    symbols:list[CodeSymbol]
    references:list[RawReference]
    warnings:list[str]=field(default_factory=list)


def _symbol(path,name,qualified,kind,start,end,signature,doc,language,exports=None):
    identity=f'{path}:{qualified}:{start}:{end}'
    return CodeSymbol('sym-'+sha256(identity.encode()).hexdigest()[:24],path,name,qualified,kind,start,end,signature[:1000],doc[:2000],language,exports or [])


def parse_python(path,text):
    module=_symbol(path,'<module>','<module>','module',1,max(1,len(text.splitlines())),path,'','python')
    try:tree=ast.parse(text,filename=path)
    except (SyntaxError,ValueError,RecursionError):return ParsedFile(path,'syntax_error_text',[module],[],['python_syntax_not_parsed'])
    symbols=[module];by_node={};stack=[]
    class Definitions(ast.NodeVisitor):
        def visit_ClassDef(self,node):
            self.define(node,'class')
        def visit_FunctionDef(self,node):self.define(node,'function')
        def visit_AsyncFunctionDef(self,node):self.define(node,'async_function')
        def define(self,node,kind):
            qualified='.'.join([*stack,node.name]);start=min([node.lineno,*[d.lineno for d in node.decorator_list]])
            signature=(('async ' if isinstance(node,ast.AsyncFunctionDef) else '')+'def '+node.name+'('+ast.unparse(node.args)+')') if kind!='class' else 'class '+node.name
            sym=_symbol(path,node.name,qualified,kind,start,node.end_lineno or node.lineno,signature,ast.get_docstring(node) or '','python')
            symbols.append(sym);by_node[id(node)]=sym;stack.append(node.name);self.generic_visit(node);stack.pop()
    try:Definitions().visit(tree)
    except RecursionError:return ParsedFile(path,'text_fallback',[module],[],['python_nesting_limit'])
    known={s.qualified_name:s for s in symbols};mod=module_name(path);refs=[]
    # Bindings assigned within a function shadow imports. Conservatively abstain
    # instead of guessing data flow or attributing obj.method to a same-name method.
    def local_bindings(node):
        result=set()
        class Bindings(ast.NodeVisitor):
            def visit_Name(self,n):
                if isinstance(n.ctx,(ast.Store,ast.Del)):result.add(n.id)
            def visit_FunctionDef(self,n):result.add(n.name)
            visit_AsyncFunctionDef=visit_FunctionDef
            def visit_ClassDef(self,n):result.add(n.name)
            def visit_Lambda(self,n):pass
        visitor=Bindings()
        for item in node.body:visitor.visit(item)
        args=node.args
        result.update(a.arg for a in [*args.posonlyargs,*args.args,*args.kwonlyargs])
        if args.vararg:result.add(args.vararg.arg)
        if args.kwarg:result.add(args.kwarg.arg)
        return result
    class References(ast.NodeVisitor):
        def __init__(self):self.scopes=[(module,{},set(),True)]
        def resolve(self,node):
            current,imports,locals_,self_binding_intact=self.scopes[-1]
            if isinstance(node,ast.Name):
                name=node.id
                if name in locals_:
                    nested=current.qualified_name+'.'+name
                    return mod+'.'+nested if nested in known else None
                if name in imports:return imports[name]
                context=current.qualified_name.split('.') if current.kind!='module' else []
                # In a function body, nested defs live below its qualified name.
                for n in range(len(context),-1,-1):
                    qualified='.'.join([*context[:n],name])
                    if qualified in known:return mod+'.'+qualified
                if name in locals_:return None
            if isinstance(node,ast.Attribute):
                parts=[];root=node
                while isinstance(root,ast.Attribute):parts.insert(0,root.attr);root=root.value
                if isinstance(root,ast.Name):
                    if root.id in imports:return imports[root.id]+'.'+'.'.join(parts)
                    if root.id in ('self','cls') and self_binding_intact:
                        parent=current.qualified_name.rsplit('.',1)[0]
                        if parent in known and known[parent].kind=='class':
                            return mod+'.'+parent+'.'+'.'.join(parts)
            return None
        def add(self,target,kind,line):
            if target:refs.append(RawReference(self.scopes[-1][0].symbol_id,target,kind,line))
        def visit_Import(self,node):
            for alias in node.names:
                local=alias.asname or alias.name.split('.')[0]
                target=alias.name if alias.asname else local
                self.scopes[-1][1][local]=target;self.add(alias.name,'import',node.lineno)
        def visit_ImportFrom(self,node):
            package=mod.split('.') if PurePosixPath(path).stem=='__init__' else mod.split('.')[:-1]
            target='.'.join(package[:max(0,len(package)-node.level+1)]+((node.module or '').split('.') if node.module else [])) if node.level else (node.module or '')
            for alias in node.names:
                if alias.name=='*':continue
                value=target+'.'+alias.name if target else alias.name
                self.scopes[-1][1][alias.asname or alias.name]=value;self.add(value,'import',node.lineno)
        def visit_FunctionDef(self,node):self.enter(node)
        visit_AsyncFunctionDef=visit_FunctionDef
        def visit_ClassDef(self,node):self.enter(node)
        def enter(self,node):
            current=self.scopes[-1];bindings=local_bindings(node) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) else set()
            imports={k:v for k,v in current[1].items() if k not in bindings}
            intact=not any(isinstance(n,ast.Name) and n.id in ('self','cls') and isinstance(n.ctx,ast.Store) for n in ast.walk(node))
            self.scopes.append((by_node[id(node)],imports,bindings,intact))
            # Decorators/defaults are not part of the body execution; skip rather
            # than assign misleading caller ownership to them.
            for item in node.body:self.visit(item)
            self.scopes.pop()
        def visit_Call(self,node):
            self.add(self.resolve(node.func),'call',node.lineno);self.generic_visit(node)
        def visit_Name(self,node):
            if isinstance(node.ctx,ast.Load):self.add(self.resolve(node),'reference',node.lineno)
    try:References().visit(tree)
    except RecursionError:return ParsedFile(path,'text_fallback',[module],[],['python_nesting_limit'])
    return ParsedFile(path,'python_ast',symbols,refs)


def parse_javascript(path,text):
    suffix=PurePosixPath(path).suffix.lower();language='typescript' if suffix in ('.ts','.tsx') else 'javascript'
    module=_symbol(path,'<module>','<module>','module',1,max(1,len(text.splitlines())),path,'',language)
    try:
        from tree_sitter import Language,Parser
        if language=='typescript':
            import tree_sitter_typescript as grammar
            lang=Language(grammar.language_tsx() if suffix=='.tsx' else grammar.language_typescript())
        else:
            import tree_sitter_javascript as grammar
            lang=Language(grammar.language())
        data=text.encode('utf-8');root=Parser(lang).parse(data).root_node
    except (ImportError,ValueError,TypeError):return ParsedFile(path,'text_fallback',[module],[],['tree_sitter_unavailable'])
    if root.has_error:return ParsedFile(path,'syntax_error_text',[module],[],['tree_sitter_syntax_error'])
    symbols=[module];nodes={};mod=module_name(path);imports={};refs=[]
    def content(node):return data[node.start_byte:node.end_byte].decode('utf-8') if node else ''
    def field(node,key):return node.child_by_field_name(key)
    def walk(node,parents=(),export_default=False):
        is_class=node.type in ('class_declaration','abstract_class_declaration')
        is_func=node.type in ('function_declaration','generator_function_declaration','method_definition')
        is_arrow=node.type=='variable_declarator' and field(node,'value') is not None and field(node,'value').type in ('arrow_function','function_expression')
        context=parents
        if is_class or is_func or is_arrow:
            name=content(field(node,'name'))
            if name:
                qualified='.'.join([*parents,name]);start=node.start_point.row+1
                end=node.end_point.row+(1 if node.end_point.column else 0)
                kind='class' if is_class else 'function'
                signature=content(node).split('{',1)[0].strip()
                sym=_symbol(path,name,qualified,kind,start,max(start,end),signature,'',language,
                            [mod+'.default'] if export_default else [])
                symbols.append(sym);nodes[node.id]=sym;context=(*parents,name)
        if node.type=='import_statement':
            source=content(field(node,'source')).strip('"\'')
            if source.startswith('.'):
                target=module_name(posixpath.normpath(posixpath.join(posixpath.dirname(path),source))) if PurePosixPath(source).suffix in ('.js','.jsx','.ts','.tsx') else posixpath.normpath(posixpath.join(posixpath.dirname(path),source)).replace('/','.')
                def import_nodes(n):
                    if n.type=='import_specifier':
                        original=content(field(n,'name'));alias=content(field(n,'alias')) or original
                        imports[alias]=target+'.'+original;refs.append(RawReference(module.symbol_id,target+'.'+original,'import',node.start_point.row+1));return
                    if n.type=='namespace_import':
                        names=[c for c in n.named_children if c.type=='identifier']
                        if names:imports[content(names[-1])]=target
                        return
                    if n.type=='import_clause':
                        for child in n.named_children:
                            if child.type=='identifier':imports[content(child)]=target+'.default'
                            else:import_nodes(child)
                        return
                    for child in n.named_children:import_nodes(child)
                import_nodes(node)
        is_default=node.type=='export_statement' and re.match(r'export\s+default\b',content(node)) is not None
        for child in node.named_children:walk(child,context,is_default)
    try:walk(root)
    except RecursionError:return ParsedFile(path,'text_fallback',[module],[],['javascript_nesting_limit'])
    known={s.qualified_name:s for s in symbols}
    assigned=set()
    def assignments(node):
        if node.type=='variable_declarator':
            target=field(node,'name')
            if target and target.type=='identifier':assigned.add(content(target))
        for child in node.named_children:assignments(child)
    assignments(root)
    def calls(node,current,shadow=frozenset()):
        current=nodes.get(node.id,current)
        if node.id in nodes and current.kind=='function':
            target_node=field(node,'value') if node.type=='variable_declarator' else node
            parameters=field(target_node,'parameters') or field(target_node,'parameter')
            shadow=shadow|set(re.findall(r'[A-Za-z_$][\w$]*',content(parameters)))
        if node.type=='call_expression':
            f=field(node,'function');name=content(f);target=None
            if f and f.type=='identifier':
                if name in imports and name not in shadow and name not in assigned:target=imports[name]
                elif name in shadow:target=None
                elif name in known:target=mod+'.'+name
                else:
                    prefix=current.qualified_name.rsplit('.',1)[0]
                    if prefix+'.'+name in known:target=mod+'.'+prefix+'.'+name
            elif f and f.type=='member_expression':
                obj=content(field(f,'object'));prop=content(field(f,'property'))
                if obj in imports and obj not in shadow and obj not in assigned:target=imports[obj]+'.'+prop
                elif obj=='this':
                    parent=current.qualified_name.rsplit('.',1)[0]
                    if parent in known and known[parent].kind=='class':target=mod+'.'+parent+'.'+prop
            if target:refs.append(RawReference(current.symbol_id,target,'call',node.start_point.row+1))
        for child in node.named_children:calls(child,current,shadow)
    try:calls(root,module)
    except RecursionError:return ParsedFile(path,'text_fallback',[module],[],['javascript_nesting_limit'])
    return ParsedFile(path,'tree_sitter',symbols,refs)


def parse_file(path,text):
    suffix=PurePosixPath(path).suffix.lower()
    try:
        if suffix=='.py':return parse_python(path,text)
        if suffix in {'.js','.jsx','.ts','.tsx'}:return parse_javascript(path,text)
    except RecursionError:return ParsedFile(path,'text_fallback',[],[],['syntax_nesting_limit'])
    return ParsedFile(path,'document',[],[])


def resolve_edges(parsed):
    """Only uniquely resolved full names, never basename guesses/dynamic calls."""
    lookup={}
    all_symbols={s.symbol_id:s for result in parsed for s in result.symbols}
    for sym in all_symbols.values():
        full=module_name(sym.path)+(('.'+sym.qualified_name) if sym.kind!='module' else '')
        for key in [full,*sym.exported_as]:lookup.setdefault(key,[]).append(sym)
    resolved_cache={}
    def candidates(target):
        if target in resolved_cache:return resolved_cache[target]
        exact=lookup.get(target,[])
        if exact:
            resolved_cache[target]={s.symbol_id:s for s in exact}
            return resolved_cache[target]
        matches={s.symbol_id:s for name,values in lookup.items() if name.endswith('.'+target) for s in values}
        resolved_cache[target]=matches
        return matches
    edges=[];seen=set();unresolved=0
    for result in parsed:
        for ref in result.references:
            found=candidates(ref.target)
            if len(found)!=1:unresolved+=1;continue
            target=next(iter(found.values()))
            if target.symbol_id==ref.source_id:continue
            key=(ref.source_id,target.symbol_id,ref.kind,ref.line)
            if key in seen:continue
            seen.add(key)
            edges.append({'source_id':ref.source_id,'target_id':target.symbol_id,'kind':ref.kind,'line':ref.line,
                          'certainty':'statically_resolved_reference','runtime_executed':False})
    return edges,unresolved
