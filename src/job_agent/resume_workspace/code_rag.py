"""Snapshot-aware retrieval: related code is a lead, not proof of user ability."""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
import json,math,re
from time import perf_counter
from typing import Literal
from fastapi import Depends,Query
from pydantic import Field
from job_agent.schemas import StrictModel
from job_agent.knowledge.bm25_index import BM25Index
from job_agent.knowledge.contracts import KnowledgeChunk,RetrievedChunk
from job_agent.knowledge.vector_index import InMemoryVectorIndex
from job_agent.knowledge.rrf import reciprocal_rank_fusion
from job_agent.knowledge.index_manifest import declared_identity, manifest_for, valid_vector
from job_agent.knowledge.retrieval_policy import RetrievalSettings,output_budget
from job_agent.knowledge.reranker import apply_rerank
from job_agent.knowledge.markdown_chunks import markdown_ranges
from job_agent.resume_workspace.code_parser import parse_file,resolve_edges,is_test_path,PARSER_VERSION
from job_agent.resume_workspace.long_term import LongTermRepository,encoded,digest
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound

INDEX_VERSION=PARSER_VERSION+'/chunks-3-markdown-1'


def public_report(report):
    return {k:v for k,v in report.items() if k not in ('symbol_payload_hashes','chunk_payload_hashes','edges_hash','vector_manifest')}



class CodeQuery(StrictModel):
    snapshot_id: str=Field(min_length=1,max_length=100)
    query: str=Field(min_length=1,max_length=600)
    method: Literal['code_aware','symbol','keyword','flat','readme','dense','hybrid']='code_aware'
    limit: int=Field(default=5,ge=1,le=20)
    expand_relations: bool=True
    rerank: bool|None=None


class IndexRequest(StrictModel):
    snapshot_id: str=Field(min_length=1,max_length=100)


def _chunks(snapshot,path,text,parsed):
    """Both flat baseline and symbol blocks share exactly the same source text."""
    lines=text.splitlines(keepends=True);prefix=[0]
    for line in lines:prefix.append(prefix[-1]+len(line))
    result={};h=sha256(text.encode()).hexdigest()
    ranges=[(1,len(lines),None,'flat')]
    functions=[s for s in parsed.symbols if s.kind not in ('module','class')]
    if path.casefold().endswith(('.md','.markdown')):
        ranges += [(start,end,None,'markdown') for start,end in markdown_ranges(text)]
    else:
        ranges += [(s.start_line,s.end_line,s.symbol_id,'ast') for s in parsed.symbols if s.kind!='module']
        if not functions:ranges.append((1,len(lines),None,'ast'))
    for start,end,symbol,kind in ranges:
        cursor=start
        while cursor<=end:
            stop=cursor;size=0
            while stop<=end and stop-cursor<80 and size+len(lines[stop-1])<=12000:
                size+=len(lines[stop-1]);stop+=1
            if stop==cursor:cursor+=1;continue # Minified/oversized line: explicit omission, not a forged partial quote.
            quote=''.join(lines[cursor-1:stop-1]);identity=f'{snapshot}:{path}:{cursor}:{stop-1}:{kind}'
            if quote.strip():
                chunk=KnowledgeChunk(chunk_id='chunk-'+sha256(identity.encode()).hexdigest()[:28],
                    document_id=snapshot+':'+path,document_version=1,document_content_hash=h,text=quote,
                    chunk_index=len(result),start_offset=prefix[cursor-1],end_offset=prefix[stop-1],
                    metadata={'path':path,'start_line':cursor,'end_line':stop-1,'symbol_id':symbol,'granularity':kind,
                              'parser_status':parsed.status,'snapshot_id':snapshot,
                              'structural_fragment':kind=='markdown' and (cursor!=start or stop-1!=end)})
                result[chunk.chunk_id]=chunk
            cursor=stop
    return list(result.values())


class CodeRAGService:
    def __init__(self,workspace,*,embedding_backend=None,embedding_identity='local-configured-embedding',
                 reranker=None,retrieval_settings=None,projects=None,indexes=None):
        self.workspace=workspace;self.projects=projects or LongTermRepository(workspace)
        self.embedding_backend=embedding_backend;self.embedding_identity=embedding_identity
        self.reranker=reranker;self.settings=retrieval_settings or RetrievalSettings()
        from job_agent.resume_workspace.sqlite_code_indexes import SqliteCodeIndexRepository
        self.indexes=indexes or SqliteCodeIndexRepository(workspace,self.projects)

    def build(self,owner,project_id,snapshot,*,publish_guard=None,task_claim=None):
        if task_claim and task_claim.get('config_identity')!=self.indexing_config_identity:raise WorkspaceConflict('task_index_config_changed')
        started=perf_counter();files=self.projects.files(owner,project_id,snapshot)
        parsed=[parse_file(path,text) for path,text in sorted(files.items())]
        edges,unresolved=resolve_edges(parsed)
        symbols=[asdict(s) for p in parsed for s in p.symbols]
        chunks=[c for p in parsed for c in _chunks(snapshot,p.path,files[p.path],p)]
        if len(chunks)>12000 or len(symbols)>15000 or len(edges)>30000:raise WorkspaceConflict('code_index_quota_reached')
        manifest={path:sha256(text.encode()).hexdigest() for path,text in sorted(files.items())}
        # Expensive encoding happens before taking the publication transaction.
        # The same fencing guard publishes every derived artifact together.
        vector_artifact=None
        ast_chunks=sorted((c for c in chunks if c.metadata['granularity'] in ('ast','markdown')),key=lambda c:c.chunk_id)
        if self.embedding_backend is not None and ast_chunks:
            try:raw=self.embedding_backend.embed_documents([c.text for c in ast_chunks])
            except Exception as exc:raise WorkspaceConflict('code_embedding_backend_failed') from exc
            dimension=len(raw[0]) if raw else 0
            if len(raw)!=len(ast_chunks) or not 1<=dimension<=8192 or any(not valid_vector(v,dimension) for v in raw):
                raise WorkspaceConflict('code_vector_dimensions_or_values_invalid')
            try:spec=declared_identity(self.embedding_backend,self.embedding_identity).with_dimension(dimension)
            except ValueError as exc:raise WorkspaceConflict('code_vector_dimensions_or_values_invalid') from exc
            vector_manifest=manifest_for(ast_chunks,corpus_kind='code',scope=(owner,project_id,snapshot),
                parser_version=PARSER_VERSION,splitter_version=INDEX_VERSION,embedding=spec)
            vectors={c.chunk_id:list(v) for c,v in zip(ast_chunks,raw)}
            vector_artifact=(vector_manifest,dimension,encoded(vectors))
        report={'snapshot_id':snapshot,'index_version':INDEX_VERSION,'indexing_config_identity':self.indexing_config_identity,'file_manifest_hash':digest(manifest),
            'symbol_payload_hashes':{s['symbol_id']:sha256(encoded(s).encode()).hexdigest() for s in symbols},
            'chunk_payload_hashes':{c.chunk_id:sha256(c.model_dump_json().encode()).hexdigest() for c in chunks},
            'edges_hash':digest(sorted([{k:e[k] for k in ('source_id','target_id','kind','line')} for e in edges],key=lambda e:(e['source_id'],e['target_id'],e['kind'],e['line']))),
            'files':len(files),'symbols':len(symbols),'chunks':len(chunks),'edges':len(edges),'unresolved_references':unresolved,
            'file_status':{p.path:p.status for p in parsed},'warnings':{p.path:p.warnings for p in parsed if p.warnings},
            'oversized_lines_omitted':sum(len(line)>12000 for text in files.values() for line in text.splitlines(keepends=True)),
            'markdown_fragments':sum(c.metadata.get('structural_fragment',False) for c in chunks),
            'runtime_executed':False,'embedding_model':spec.model if vector_artifact else None,
            'vector_index_identity':vector_artifact[0].key if vector_artifact else None,
            'vector_manifest':asdict(vector_artifact[0]) if vector_artifact else None,
            'elapsed_ms':int((perf_counter()-started)*1000)}
        published=self.indexes.publish(owner,project_id,snapshot,report,symbols,chunks,edges,vector_artifact,
            publish_guard=publish_guard,task_claim=task_claim)
        return {**public_report(report),**(published or {}),'total_elapsed_ms':int((perf_counter()-started)*1000)}

    def status(self,owner,project_id,snapshot,*,_internal=False):
        row=self.indexes.report(owner,project_id,snapshot)
        return self._report_view(row,snapshot,_internal=_internal)

    def _report_view(self,row,snapshot,*,_internal=False):
        if row is None:return {'snapshot_id':snapshot,'status':'not_indexed','dense_available':False}
        if row['parser_version']!=INDEX_VERSION:
            return {'snapshot_id':snapshot,'status':'needs_rebuild','dense_available':self.embedding_backend is not None}
        if sha256(row['payload'].encode()).hexdigest()!=row['payload_hash']:raise WorkspaceConflict('code_index_integrity_failed')
        result=json.loads(row['payload'])
        return {**(result if _internal else public_report(result)),'status':'indexed','dense_available':self.embedding_backend is not None}

    def _load(self,owner,project_id,snapshot):
        stored=self.indexes.load(owner,project_id,snapshot)
        report=self._report_view(stored['report'],snapshot,_internal=True)
        if report.get('status')!='indexed':raise WorkspaceConflict('code_index_not_ready')
        rows=stored['symbols']
        if {r['symbol_id']:sha256(r['payload'].encode()).hexdigest() for r in rows}!=report['symbol_payload_hashes']:raise WorkspaceConflict('code_symbol_integrity_failed')
        symbols=[json.loads(r['payload']) for r in rows];chunks=[]
        for row in stored['chunks']:
            if sha256(row['payload'].encode()).hexdigest()!=row['payload_hash']:raise WorkspaceConflict('code_chunk_integrity_failed')
            chunks.append(KnowledgeChunk.model_validate_json(row['payload']))
        edges=stored['edges']
        if {c.chunk_id:sha256(c.model_dump_json().encode()).hexdigest() for c in chunks}!=report['chunk_payload_hashes']:raise WorkspaceConflict('code_chunk_manifest_changed')
        if digest(sorted(edges,key=lambda e:(e['source_id'],e['target_id'],e['kind'],e['line'])))!=report['edges_hash']:raise WorkspaceConflict('code_relation_integrity_failed')
        return report,symbols,chunks,edges

    @property
    def indexing_config_identity(self):
        return digest({'index_version':INDEX_VERSION,'embedding':asdict(declared_identity(self.embedding_backend,self.embedding_identity)) if self.embedding_backend else None})

    def citation_connection(self,db,workspace):
        # A SQLite resume transaction is never a PostgreSQL project transaction.
        return db if getattr(self.projects,'workspace',None) is workspace else None

    def read_code_range(self,owner,project_id,snapshot,path,start,end,*,method='read_code_range',db=None):
        if not 1<=start<=end or end-start>=120:raise WorkspaceConflict('code_line_range_limit')
        text,version=self.projects.read_file(owner,project_id,snapshot,path,db=db);lines=text.splitlines(keepends=True)
        if end>len(lines):raise WorkspaceConflict('code_line_range_invalid')
        quote=''.join(lines[start-1:end])
        if len(quote)>12000:raise WorkspaceConflict('code_range_character_limit')
        file_hash=sha256(text.encode()).hexdigest()
        key=f'{snapshot}:{path}:{start}:{end}:{file_hash}'
        kind='test_code' if is_test_path(path) else 'code' if path.casefold().endswith(('.py','.js','.jsx','.ts','.tsx','.sql')) else 'documentation'
        return EvidenceReference(evidence_id='ev-'+sha256(key.encode()).hexdigest()[:28],scope='private_project',owner_id=owner,
            project_id=project_id,snapshot_id=snapshot,source_id=snapshot+':'+path,content_hash=file_hash,path=path,
            start_line=start,end_line=end,commit=version['commit_sha'],retrieval_method=method,evidence_kind=kind,quote=quote)

    def validate_reference(self,owner,reference:EvidenceReference,*,db=None):
        if reference.scope!='private_project' or reference.owner_id!=owner or not reference.project_id:raise WorkspaceNotFound('reference_not_found')
        actual=self.read_code_range(owner,reference.project_id,reference.snapshot_id,reference.path,reference.start_line,reference.end_line,method=reference.retrieval_method,db=db)
        fields=('evidence_id','source_id','content_hash','commit','quote','evidence_kind')
        if any(getattr(actual,k)!=getattr(reference,k) for k in fields):raise WorkspaceConflict('code_reference_invalid')
        # Do not trust caller-supplied semantic support labels.
        return actual

    def get_symbol(self,owner,project_id,snapshot,name):
        _,symbols,_,_=self._load(owner,project_id,snapshot)
        found=[s for s in symbols if name in (s['symbol_id'],s['qualified_name'])]
        if not found:found=[s for s in symbols if s['name']==name]
        if not found:raise WorkspaceNotFound('code_symbol_not_found')
        if len(found)!=1:raise WorkspaceConflict('code_symbol_ambiguous_use_id_or_qualified_name')
        symbol=found[0];end=min(symbol['end_line'],symbol['start_line']+119)
        return {'symbol':symbol,'reference':self.read_code_range(owner,project_id,snapshot,symbol['path'],symbol['start_line'],end,method='get_symbol').model_dump(mode='json'),
                'truncated_to_line_budget':end<symbol['end_line'],'runtime_executed':False}

    def find_references(self,owner,project_id,snapshot,symbol_id,*,tests_only=False,limit=10):
        _,symbols,_,edges=self._load(owner,project_id,snapshot);lookup={s['symbol_id']:s for s in symbols}
        if symbol_id not in lookup:raise WorkspaceNotFound('code_symbol_not_found')
        result=[];seen=set()
        for edge in edges:
            if edge['target_id']!=symbol_id or edge['kind']=='import':continue
            source=lookup[edge['source_id']]
            if tests_only and not is_test_path(source['path']):continue
            key=(source['symbol_id'],edge['line'])
            if key in seen:continue
            seen.add(key);line=edge['line']
            result.append({'symbol':source,'relation':edge,'reference':self.read_code_range(owner,project_id,snapshot,source['path'],max(1,line-2),min(source['end_line'],line+2),method='get_test_evidence' if tests_only else 'find_references').model_dump(mode='json'),'test_execution':'not_run'})
            if len(result)>=max(1,min(limit,20)):break
        return result

    def _dense(self,owner,project_id,snapshot,chunks,query,limit):
        if self.embedding_backend is None:raise WorkspaceConflict('local_embedding_not_configured')
        if not chunks:return [],None
        # Resolve/validate the actual dimension before reading any old cache. Scope
        # has already been authenticated by _load; it is never a client filter.
        try:q=list(self.embedding_backend.embed_query(query))
        except Exception as exc:raise WorkspaceConflict('code_embedding_backend_failed') from exc
        if not valid_vector(q):raise WorkspaceConflict('code_query_vector_dimension_invalid')
        try:spec=declared_identity(self.embedding_backend,self.embedding_identity).with_dimension(len(q))
        except ValueError as exc:raise WorkspaceConflict('code_query_vector_dimension_invalid') from exc
        manifest=manifest_for(chunks,corpus_kind='code',scope=(owner,project_id,snapshot),
                              parser_version=PARSER_VERSION,splitter_version=INDEX_VERSION,embedding=spec)
        identity=manifest.key
        row=self.indexes.vector(owner,project_id,snapshot,identity)
        if row:
            if sha256(row['payload'].encode()).hexdigest()!=row['payload_hash']:raise WorkspaceConflict('code_vector_integrity_failed')
            vectors=json.loads(row['payload']);dimension=row['dimension']
            if set(vectors)!={c.chunk_id for c in chunks}:raise WorkspaceConflict('code_vector_manifest_changed')
        else:
            if getattr(self.embedding_backend,'require_prebuilt',False):
                raise WorkspaceConflict('code_dense_index_needs_rebuild')
            try:raw=self.embedding_backend.embed_documents([c.text for c in chunks])
            except Exception as exc:raise WorkspaceConflict('code_embedding_backend_failed') from exc
            if len(raw)!=len(chunks):raise WorkspaceConflict('code_vector_count_mismatch')
            dimension=len(raw[0]) if raw else 0;vectors={c.chunk_id:list(v) for c,v in zip(chunks,raw)}
        values=list(vectors.values())
        if dimension!=len(q) or any(not valid_vector(v,dimension) for v in values):
            raise WorkspaceConflict('code_vector_dimensions_or_values_invalid')
        if not row:
            payload=encoded(vectors)
            self.indexes.put_vector(owner,project_id,snapshot,identity,dimension,payload)
        index=InMemoryVectorIndex();index.add(chunks=chunks,vectors=[vectors[c.chunk_id] for c in chunks])
        return [r for r in index.search(query_vector=q,limit=limit) if r.score>0],identity

    def search(self,owner,project_id,request:CodeQuery):
        started=perf_counter();report,symbols,all_chunks,edges=self._load(owner,project_id,request.snapshot_id)
        granularity='flat' if request.method in ('flat','readme') else 'ast'
        chunks=[c for c in all_chunks if c.metadata['granularity']==granularity or (granularity=='ast' and c.metadata['granularity']=='markdown')]
        if request.method=='readme':chunks=[c for c in chunks if c.metadata['path'].casefold().endswith('readme.md')]
        lexical=BM25Index();lexical.add(chunks)
        depth=self.settings.sparse_candidates
        sparse=[r for r in lexical.search(query=request.query,limit=depth) if r.score>0]
        used=request.method;warnings=[];dense=[];manifest_key=None
        if request.method=='dense':
            dense,manifest_key=self._dense(owner,project_id,request.snapshot_id,chunks,request.query,self.settings.dense_candidates)
            ranked=dense
        elif request.method in ('hybrid','code_aware') and self.embedding_backend is not None:
            try:
                dense,manifest_key=self._dense(owner,project_id,request.snapshot_id,chunks,request.query,self.settings.dense_candidates)
            except WorkspaceConflict as exc:
                # Integrity errors are never hidden by a lexical fallback.
                if str(exc) not in ('code_dense_index_needs_rebuild','code_embedding_backend_failed'):raise
                warnings.append(str(exc));used='bm25_fallback'
            ranked=reciprocal_rank_fusion(dense_results=dense,bm25_results=sparse,
                limit=self.settings.fusion_candidates,k=self.settings.rrf_k,dense_weight=self.settings.dense_rrf_weight) if dense else sparse
        else:
            ranked=sparse
            if request.method in ('hybrid','code_aware'):
                used='symbol_bm25_static_relations' if request.method=='code_aware' else 'bm25_fallback'
                warnings.append('semantic_embedding_not_configured; no_dense_recall_claim')
        ranked=ranked[:self.settings.fusion_candidates]
        fused_ids=[r.chunk.chunk_id for r in ranked]
        enabled=request.rerank if request.rerank is not None else (self.reranker is not None and request.method in ('hybrid','code_aware'))
        ranked,rerank_trace=apply_rerank(request.query,ranked,reranker=self.reranker,settings=self.settings,enabled=enabled)
        if rerank_trace['rerank_error']:warnings.append(rerank_trace['rerank_error'])
        if rerank_trace['rerank_applied']:used+='_rerank'
        selected=[];by_symbol={};by_id={s['symbol_id']:s for s in symbols}
        for c in chunks:
            if c.metadata.get('symbol_id'):by_symbol.setdefault(c.metadata['symbol_id'],[]).append(c)
        exact=[s for s in symbols if s['kind']!='module' and (
            re.search(r'(?<!\w)'+re.escape(s['qualified_name'])+r'(?!\w)',request.query,re.I) or
            re.search(r'(?<!\w)'+re.escape(s['name'])+r'(?!\w)',request.query,re.I))]
        exact.sort(key=lambda s:(-len(s['qualified_name']),s['path'],s['start_line']))
        if request.method in ('code_aware','symbol'):
            selected=[(c,1.0,'exact_symbol') for s in exact for c in by_symbol.get(s['symbol_id'],[])[:1]]
        if request.method!='symbol':selected.extend((r.chunk,r.score,r.retrieval_method) for r in ranked)
        unique={}
        for item in selected:unique.setdefault(item[0].chunk_id,item)
        selected=list(unique.values())[:self.settings.fusion_candidates]
        direct_ids=[c.chunk_id for c,_,_ in selected];related=[]
        if request.method=='code_aware' and request.expand_relations and self.settings.relation_candidates:
            seeds=[c.metadata.get('symbol_id') for c,_,_ in selected[:min(2,request.limit)]]
            related=[];visited=set(seeds)
            for _ in range(2):
                next_ids=[]
                for e in edges:
                    adjacent=e['target_id'] if e['source_id'] in seeds else e['source_id'] if e['target_id'] in seeds else None
                    if adjacent and adjacent not in visited:
                        visited.add(adjacent);next_ids.append(adjacent)
                        for c in by_symbol.get(adjacent,[])[:1]:related.append((c,0.0,'static_'+e['kind']))
                    if len(related)>=self.settings.relation_candidates:break
                seeds=next_ids
                if not seeds or len(related)>=self.settings.relation_candidates:break
            # Relations are leads. They cannot evict direct evidence merely by
            # existing in a static graph. Legacy order is explicit for diagnostics.
            selected=(selected[:1]+related+selected[1:] if self.settings.relation_priority=='legacy_first'
                      else selected+related)
        budgeted,budget_trace=output_budget([RetrievedChunk(chunk=c,score=score,rank=i+1,retrieval_method=method)
            for i,(c,score,method) in enumerate(selected)],limit=request.limit,settings=self.settings)
        if budget_trace['budget_omitted_ids']:warnings.append('context_budget_omitted_whole_spans')
        hits=[];seen=set()
        for candidate in budgeted:
            c,score,method=candidate.chunk,candidate.score,candidate.retrieval_method
            m=c.metadata;key=(m['path'],m['start_line'],m['end_line'])
            if key in seen:continue
            seen.add(key)
            reference=self.read_code_range(owner,project_id,request.snapshot_id,m['path'],m['start_line'],m['end_line'],method=method)
            if reference.quote!=c.text or reference.content_hash!=c.document_content_hash:raise WorkspaceConflict('code_chunk_source_mismatch')
            hits.append({'reference':reference.model_dump(mode='json'),'symbol':by_id.get(m.get('symbol_id')),
                         'score':score,'retrieval_method':method,'support':'needs_judgment'})
            if len(hits)>=request.limit:break
        return {'hits':hits,'method_requested':request.method,'method_used':used,'warnings':warnings,
                'retrieval_trace':{'schema_version':'retrieval-trace-2','index_identity':manifest_key,
                    'config_identity':self.settings.key,**budget_trace,**rerank_trace,
                    'sparse_ids':[r.chunk.chunk_id for r in sparse], 'dense_ids':[r.chunk.chunk_id for r in dense],
                    'fused_ids':fused_ids, 'candidate_depth':depth,
                    'direct_candidate_ids':direct_ids,'relation_candidate_ids':[c.chunk_id for c,_,_ in related],
                    'relation_priority':self.settings.relation_priority,'dense_rrf_weight':self.settings.dense_rrf_weight,
                    'final_evidence_ids':[h['reference']['evidence_id'] for h in hits]},
                'index_version':INDEX_VERSION,'elapsed_ms':int((perf_counter()-started)*1000),
                'static_graph_only':True,'provider_calls':0,'embedding_calls':None if self.embedding_backend is not None else 0}


def install_code_routes(app,workspace,owner,service=None):
    service=service or CodeRAGService(workspace)
    @app.post('/api/v2/projects/{project_id}/index')
    def build(project_id:str,request:IndexRequest,user:str=Depends(owner)):return service.build(user,project_id,request.snapshot_id)
    @app.get('/api/v2/projects/{project_id}/index')
    def status(project_id:str,snapshot:str=Query(min_length=1,max_length=100),user:str=Depends(owner)):return service.status(user,project_id,snapshot)
    @app.post('/api/v2/projects/{project_id}/search')
    def search(project_id:str,request:CodeQuery,user:str=Depends(owner)):return service.search(user,project_id,request)
    @app.get('/api/v2/projects/{project_id}/symbol')
    def symbol(project_id:str,snapshot:str=Query(min_length=1,max_length=100),name:str=Query(min_length=1,max_length=200),user:str=Depends(owner)):return service.get_symbol(user,project_id,snapshot,name)
    @app.get('/api/v2/projects/{project_id}/references')
    def references(project_id:str,snapshot:str=Query(min_length=1,max_length=100),symbol_id:str=Query(min_length=1,max_length=100),tests_only:bool=False,user:str=Depends(owner)):return service.find_references(user,project_id,snapshot,symbol_id,tests_only=tests_only)
    @app.get('/api/v2/projects/{project_id}/code')
    def code(project_id:str,snapshot:str=Query(min_length=1,max_length=100),path:str=Query(min_length=1,max_length=240),start:int=Query(ge=1),end:int=Query(ge=1),user:str=Depends(owner)):return service.read_code_range(user,project_id,snapshot,path,start,end).model_dump(mode='json')
    return service
