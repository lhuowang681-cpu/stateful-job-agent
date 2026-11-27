from job_agent.resume_workspace.code_parser import parse_file,resolve_edges,is_test_path


def edge_names(parsed):
    symbols={s.symbol_id:s for p in parsed for s in p.symbols}
    edges,_=resolve_edges(parsed)
    return {(symbols[e['source_id']].path,symbols[e['source_id']].qualified_name,
             symbols[e['target_id']].path,symbols[e['target_id']].qualified_name,e['kind']) for e in edges}


def test_python_alias_relative_cross_file_and_test_evidence():
    files={'pkg/service.py':'def save(value):\n    """保存回执。"""\n    return value\n',
           'pkg/api.py':'from .service import save as persist\n\nasync def handle(value):\n    return persist(value)\n',
           'tests/test_service.py':'from pkg.service import save\n\ndef test_save():\n    assert save(1) == 1\n'}
    parsed=[parse_file(p,t) for p,t in files.items()];names=edge_names(parsed)
    assert ('pkg/api.py','handle','pkg/service.py','save','call') in names
    assert ('tests/test_service.py','test_save','pkg/service.py','save','call') in names
    assert parsed[0].symbols[1].docstring=='保存回执。'
    assert parsed[1].symbols[1].kind=='async_function'
    assert is_test_path('tests/test_service.py')


def test_python_dynamic_object_and_shadowed_import_not_guessed():
    source='from service import save\n\ndef handle(save):\n    return save(1)\n\ndef other(obj):\n    return obj.save(1)\n'
    parsed=[parse_file('service.py','def save(x):\n    return x\n'),parse_file('api.py',source)]
    assert not any(e[-1]=='call' for e in edge_names(parsed))


def test_python_methods_nested_symbols_and_scope():
    text='class Service:\n    def save(self):\n        return 1\n    def handle(self):\n        return self.save()\n\ndef outer():\n    def inner():\n        return 1\n    return inner()\n'
    parsed=[parse_file('service.py',text)];names=edge_names(parsed)
    assert ('service.py','Service.handle','service.py','Service.save','call') in names
    assert ('service.py','outer','service.py','outer.inner','call') in names
    for sym in parsed[0].symbols:
        assert 1<=sym.start_line<=sym.end_line<=len(text.splitlines())


def test_reassigned_self_does_not_create_false_method_edge():
    text='class C:\n    def save(self):\n        return 1\n    def handle(self, other):\n        self = other\n        return self.save()\n'
    assert not any(e[-1]=='call' for e in edge_names([parse_file('c.py',text)]))


def test_js_and_ts_real_tree_sitter_import_alias_and_arrow():
    files={'src/service.ts':'export function save(value: string): string { return value; }\n',
           'src/api.ts':'import {save as persist} from "./service";\nexport const handle = (v: string) => persist(v);\n',
           'src/client.js':'export function load(v) { return v; }\n',
           'src/run.js':'import {load} from "./client.js";\nexport function run(v) { return load(v); }\n'}
    parsed=[parse_file(p,t) for p,t in files.items()]
    assert all(p.status=='tree_sitter' for p in parsed),[p.warnings for p in parsed]
    names=edge_names(parsed)
    assert ('src/api.ts','handle','src/service.ts','save','call') in names
    assert ('src/run.js','run','src/client.js','load','call') in names


def test_js_shadowed_argument_no_false_edge_and_tsx_supported():
    parsed=[parse_file('lib.js','export function save(x) { return x; }'),
        parse_file('client.js','import {save} from "./lib";\nexport function run(save) { return save(1); }'),
        parse_file('view.tsx','export function View() { return <section>你好</section>; }')]
    assert parsed[2].status=='tree_sitter'
    assert not any(e[-1]=='call' for e in edge_names(parsed))


def test_ambiguous_module_suffix_abstains_instead_of_guessing():
    parsed=[parse_file('src/a/service.py','def save(v):\n    return v\n'),
            parse_file('lib/a/service.py','def save(v):\n    return v\n'),
            parse_file('api.py','from a.service import save\n\ndef handle(v):\n    return save(v)\n')]
    edges,unresolved=resolve_edges(parsed)
    assert edges==[] and unresolved>0


def test_malformed_code_is_explicit_text_fallback_and_never_executed():
    assert parse_file('bad.py','def broken(:\n').status=='syntax_error_text'
    assert parse_file('bad.ts','export function broken( {').status=='syntax_error_text'
    parsed=parse_file('danger.py','raise RuntimeError("do not execute me")\n\ndef safe():\n    return 1\n')
    assert parsed.status=='python_ast' and len(parsed.symbols)==2
