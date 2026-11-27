"""Synthetic research artifacts over the product repositories, not a second RAG engine."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime,timezone
from hashlib import sha256
import json,math,sqlite3
from pathlib import Path
from statistics import mean,median
from time import perf_counter
from uuid import uuid4

from job_agent.knowledge.evaluation_contract import EvaluationDataset,GoldSpan,evaluate_case
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.knowledge.retrieval_policy import RetrievalSettings
from job_agent.knowledge.cache_snapshot import PublicCacheSnapshot
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery,INDEX_VERSION
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
from job_agent.resume_workspace.public_seed import seed_entries
from job_agent.resume_workspace.repository import SqliteResumeRepository

OWNER='synthetic-research-owner'
VARIANTS={
 'A_bm25':('keyword','bm25',False,False),
 'B_dense':('dense','dense',False,False),
 'C_hybrid':('hybrid','hybrid',False,False),
 'D_hybrid_rerank':('hybrid','hybrid',True,False),
 'E_code_aware_no_relations':('code_aware',None,False,False),
 'F_code_aware_relations':('code_aware',None,False,True),
 'G_flat_bm25':('flat',None,False,False)}
METRICS=('hit_any_gold','gold_span_recall','sufficient_gold_retrieved','reciprocal_rank')
ALGORITHM_FILES=[f'src/job_agent/knowledge/{s}.py' for s in (
 'bm25_index','vector_index','rrf','index_manifest','retrieval_policy','reranker','contracts',
 'evaluation_contract','cache_snapshot','qwen_embedding','markdown_chunks','research_contract')]+[
 f'src/job_agent/resume_workspace/{s}.py' for s in ('code_parser','code_rag','public_knowledge',
 'public_seed','sqlite_code_indexes','long_term','project_storage','repository','retrieval_runtime',
 'evidence_reference')]+['scripts/expansion_research.py']


def stamp():return datetime.now(timezone.utc).isoformat()
def file_hash(path):return sha256(Path(path).read_bytes()).hexdigest()
def write_new(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
def read_json(path):
    if Path(path).stat().st_size>64*1024*1024:raise ValueError('research_json_too_large')
    return json.loads(Path(path).read_text(encoding='utf-8'))
def child(root,name):
    if not isinstance(name,str) or '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('research_artifact_path_invalid')
    path=(Path(root)/name).resolve()
    if not path.is_relative_to(Path(root).resolve()):raise ValueError('research_artifact_path_escape')
    return path
def algorithm_sources(root):return {p:file_hash(Path(root)/p) for p in ALGORITHM_FILES}
def runtime_identity(runtime):
    return {'embedding':asdict(runtime.identity) if runtime.identity else None,
            'reranker':asdict(runtime.reranker.identity) if runtime.reranker else None,
            'settings':asdict(runtime.settings)}


class CountedBackend:
    """Counts actual calls; no claimed token/price estimate from text length."""
    def __init__(self,backend):
        self.backend=backend;self.identity=backend.identity
        self.require_prebuilt=True;self.documents=0;self.queries=0;self.passages=0
    def embed_documents(self,texts):
        self.documents+=1;self.passages+=len(texts);return self.backend.embed_documents(texts)
    def embed_query(self,text):self.queries+=1;return self.backend.embed_query(text)
    def counts(self):return {'document_calls':self.documents,'document_passages':self.passages,'query_calls':self.queries}


def source_files(data,split):
    prefix=split+'-code/'
    return {d.document_id.removeprefix(prefix):d.text for d in data.corpus.documents if d.split==split and d.kind!='public_knowledge'}


def _audit_db(path,scope,data,split):
    # Never accept a live user workspace merely because it has the right project.
    allowed={'v3_projects','v3_project_snapshots','v3_project_files','v3_code_indexes',
             'v3_code_symbols','v3_code_chunks','v3_code_edges','v3_code_vectors',
             'v3_public_entries','v3_public_versions','v3_public_meta'}
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if any(not name.replace('_','').isalnum() for name in names):raise ValueError('research_db_table_invalid')
        for name in names:
            if name not in allowed and db.execute('SELECT COUNT(*) FROM "'+name+'"').fetchone()[0]:
                raise ValueError('research_db_contains_nonresearch_data')
        rows=db.execute('SELECT project_id,owner_id,current_snapshot FROM v3_projects').fetchall()
        if rows!=[(scope['project_id'],OWNER,scope['snapshot_id'])]:raise ValueError('research_scope_drift')
        if db.execute('SELECT COUNT(*) FROM v3_project_snapshots').fetchone()[0]!=1:raise ValueError('research_snapshot_count')
    workspace=SqliteResumeRepository(path);projects=LongTermRepository(workspace)
    if projects.files(OWNER,scope['project_id'],scope['snapshot_id'])!=source_files(data,split):raise ValueError('research_source_drift')
    public=PublicKnowledgeService(workspace,seed=False,prewarm=False)
    expected={d.document_id:d.text for d in data.corpus.documents if d.split==split and d.kind=='public_knowledge'}
    if {e.entry_id:e.title+'\n'+e.body for e,_ in public.repository.entries()}!=expected:raise ValueError('research_public_source_drift')
    return workspace


def corpus_origin(data,kind):
    if kind not in ('synthetic','owner_project_source'):raise ValueError('research_origin_invalid')
    if kind=='owner_project_source':
        for d in data.corpus.documents:
            if (d.kind=='public_knowledge' or not d.origin.startswith(('src/job_agent/','docs/tech-specs/'))
                or len(d.source_version)!=40 or any(c not in '0123456789abcdef' for c in d.source_version)
                or not d.license.startswith('Project owner authorized internal evaluation;')):
                raise ValueError('research_owner_source_invalid')
    return kind


def public_snapshot(value,data,split):
    if value=={'empty_public_scope':True}:
        if any(d.split==split and d.kind=='public_knowledge' for d in data.corpus.documents):
            raise ValueError('research_public_scope_not_empty')
        return False
    PublicCacheSnapshot.model_validate(value);return True


def prepare(root,bundle,dataset_path,runtime,*,repeats=3,source_kind='synthetic'):
    if runtime.backend is None or runtime.reranker is None:raise ValueError('research_full_runtime_required')
    if type(repeats) is not int or not 1<=repeats<=5:raise ValueError('research_repeat_budget')
    data=EvaluationDataset.model_validate_json(Path(dataset_path).read_text(encoding='utf-8'))
    corpus_origin(data,source_kind)
    if any(c.retrieval_scope is None for c in data.cases):raise ValueError('research_explicit_scope_required')
    bundle=Path(bundle).resolve();bundle.mkdir(parents=True,exist_ok=False)
    (bundle/'dataset.json').write_bytes(Path(dataset_path).read_bytes())
    backend=CountedBackend(runtime.backend);scopes={};started=perf_counter()
    for split in ('dev','test'):
        if not any(c.split==split for c in data.cases):raise ValueError('research_split_empty')
        ws=SqliteResumeRepository(bundle/(split+'.sqlite'));projects=LongTermRepository(ws)
        p=projects.create_project(OWNER,ProjectCreate(name=('CC0 synthetic ' if source_kind=='synthetic' else 'Internal real project ')+split,
            license_note='CC0-1.0' if source_kind=='synthetic' else 'Project owner authorized internal evaluation; no redistribution license asserted'))
        p=projects.publish_files(OWNER,p['project_id'],source_files(data,split),origin='zip')
        code=CodeRAGService(ws,embedding_backend=backend,reranker=runtime.reranker,retrieval_settings=runtime.settings)
        code.build(OWNER,p['project_id'],p['current_snapshot'])
        public=PublicKnowledgeService(ws,embedding_backend=backend,reranker=runtime.reranker,
                                     retrieval_settings=runtime.settings,seed=False,prewarm=False)
        seeds={e['entry_id']:e for e in seed_entries()}
        entries=[seeds[d.document_id] for d in data.corpus.documents if d.split==split and d.kind=='public_knowledge']
        if any(e['title']+'\n'+e['body']!=next(d.text for d in data.corpus.documents if d.document_id==e['entry_id']) for e in entries):
            raise ValueError('research_seed_drift')
        public.repository.install(entries);public.prewarm()
        write_new(bundle/(split+'-public-vectors.json'),public.export_dense_snapshot() if entries else {'empty_public_scope':True})
        report,_,chunks,edges=code._load(OWNER,p['project_id'],p['current_snapshot'])
        scopes[split]={'project_id':p['project_id'],'snapshot_id':p['current_snapshot'],
            'index_identity':report['vector_index_identity'],'chunk_ids':[c.chunk_id for c in chunks],
            'edges_hash':fingerprint(edges),'public_versions':{e.entry_id:v for e,v in public.repository.entries()}}
        _audit_db(ws.path,scopes[split],data,split)
    artifacts={name:file_hash(bundle/name) for name in ('dataset.json','dev.sqlite','test.sqlite','dev-public-vectors.json','test-public-vectors.json')}
    sources=algorithm_sources(root)
    full={p.relative_to(root).as_posix():file_hash(p) for directory in ('src','tests','scripts') for p in (Path(root)/directory).rglob('*.py')}
    payload={'schema_version':'research-index-1','prepared_at_utc':stamp(),'synthetic_only':source_kind=='synthetic','source_kind':source_kind,
        'dataset_version':data.dataset_version,'corpus_snapshot':data.corpus.snapshot_id,
        'runtime':runtime_identity(runtime),'index_version':INDEX_VERSION,'scopes':scopes,'artifacts':artifacts,
        'algorithm_sources':sources,'algorithm_identity':fingerprint(sources),'full_code_identity':fingerprint(full),
        'variants':VARIANTS,'repeats':repeats,'limit':5,'annotation_status':'AI candidates; human deferred',
        'prepare_ms':round((perf_counter()-started)*1000,3),'prepare_encoder_calls':backend.counts(),
        'tokens':None,'cost':None,'missing_usage_reason':'local embedding counters only; no generative call or price ledger'}
    write_new(bundle/'manifest.json',{'payload':payload,'sha256':fingerprint(payload)})
    return payload


def inspect_bundle(root,bundle,*,strict_algorithm=True):
    bundle=Path(bundle).resolve();sealed=read_json(bundle/'manifest.json');m=sealed['payload']
    if (sealed['sha256']!=fingerprint(m) or m.get('schema_version')!='research-index-1'
        or m.get('synthetic_only') is not (m.get('source_kind','synthetic')=='synthetic')):
        raise ValueError('research_manifest_invalid')
    expected={'dataset.json','dev.sqlite','test.sqlite','dev-public-vectors.json','test-public-vectors.json'}
    if set(m['artifacts'])!=expected:raise ValueError('research_artifact_set_invalid')
    for name,digest in m['artifacts'].items():
        if file_hash(child(bundle,name))!=digest:raise ValueError('research_artifact_hash_changed:'+name)
    if m['algorithm_identity']!=fingerprint(m['algorithm_sources']):raise ValueError('research_algorithm_manifest_invalid')
    current=fingerprint(algorithm_sources(root))
    if strict_algorithm and current!=m['algorithm_identity']:raise ValueError('research_algorithm_changed')
    if m['variants']!=json.loads(json.dumps(VARIANTS)) or m['limit']!=5 or not 1<=m['repeats']<=5:
        raise ValueError('research_experiment_changed')
    RetrievalSettings(**m['runtime']['settings'])
    data=EvaluationDataset.model_validate(read_json(bundle/'dataset.json'))
    corpus_origin(data,m.get('source_kind','synthetic'))
    if data.corpus.snapshot_id!=m['corpus_snapshot'] or data.dataset_version!=m['dataset_version']:raise ValueError('research_dataset_changed')
    for split in ('dev','test'):
        _audit_db(bundle/(split+'.sqlite'),m['scopes'][split],data,split)
        value=read_json(bundle/(split+'-public-vectors.json'));public_snapshot(value,data,split)
        if value=={'empty_public_scope':True} and m['scopes'][split]['public_versions']:raise ValueError('research_public_scope_not_empty')
    # Hashes detect accidental changes, not a signature against a malicious pack producer.
    return m,data,current


def open_services(bundle,m,data,split,runtime=None):
    ws=_audit_db(Path(bundle).resolve()/(split+'.sqlite'),m['scopes'][split],data,split)
    settings=RetrievalSettings(**m['runtime']['settings'])
    if runtime is not None and runtime_identity(runtime)!=m['runtime']:raise ValueError('research_runtime_changed')
    backend=CountedBackend(runtime.backend) if runtime else None
    code=CodeRAGService(ws,embedding_backend=backend,reranker=runtime.reranker if runtime else None,retrieval_settings=settings)
    public=PublicKnowledgeService(ws,embedding_backend=backend,reranker=runtime.reranker if runtime else None,
                                 retrieval_settings=settings,seed=False,prewarm=False)
    scope=m['scopes'][split];report,_,chunks,edges=code._load(OWNER,scope['project_id'],scope['snapshot_id'])
    if (report['vector_index_identity']!=scope['index_identity'] or [c.chunk_id for c in chunks]!=scope['chunk_ids']
        or fingerprint(edges)!=scope['edges_hash'] or {e.entry_id:v for e,v in public.repository.entries()}!=scope['public_versions']):
        raise ValueError('research_index_identity_changed')
    if runtime:
        value=read_json(Path(bundle)/(split+'-public-vectors.json'))
        if public_snapshot(value,data,split):public.restore_dense_snapshot(value)
    return code,public,backend


def query_case(code,public,scope,case,variant):
    cm,pm,rerank,relations=VARIANTS[variant]
    if case.retrieval_scope=='project':
        found=code.search(OWNER,scope['project_id'],CodeQuery(snapshot_id=scope['snapshot_id'],query=case.query,
            method=cm,limit=5,expand_relations=relations,rerank=rerank))
    else:found=public.search(case.query,kind='doc',method=pm,limit=5,rerank=rerank)
    refs=[];canonical=[]
    for hit in found['hits']:
        ref=EvidenceReference.model_validate(hit['reference'])
        if case.retrieval_scope=='project':
            code.validate_reference(OWNER,ref);doc=case.split+'-code/'+ref.path
        else:public.repository.validate_reference(ref);doc=ref.source_id
        refs.append(GoldSpan(document_id=doc,content_hash=ref.content_hash,start_line=ref.start_line,end_line=ref.end_line,quote=ref.quote))
        canonical.append(ref.model_dump(mode='json'))
    if rerank and found['hits'] and not found['retrieval_trace']['rerank_applied']:raise ValueError('requested_rerank_not_applied')
    if cm in ('dense','hybrid') and case.retrieval_scope=='project' and 'fallback' in found['method_used']:raise ValueError('unexpected_dense_fallback')
    if pm in ('dense','hybrid') and case.retrieval_scope=='public' and 'fallback' in found['method_used']:raise ValueError('unexpected_dense_fallback')
    return found,refs,canonical


def summarize(rows,cases):
    """Failed answerable queries stay in the denominator and count as zero."""
    lookup={c.case_id:c for c in cases};result={}
    for variant in sorted({r['variant'] for r in rows}):
        selected=[r for r in rows if r['variant']==variant];first=[r for r in selected if r['repeat']==0]
        answerable=[r for r in first if lookup[r['case_id']].answerable];metrics={};at_k={}
        for k in ('1','3','5'):
            at_k[k]={metric:{'mean':mean(float((r.get('metrics_at_k') or {}).get(k,{}).get(metric) or 0) for r in answerable) if answerable else None,
                'cases':len(answerable)} for metric in METRICS}
        times=sorted(r['elapsed_ms'] for r in selected)
        multi=[r for r in answerable if len(lookup[r['case_id']].gold)>1]
        invalid=sum(sum(not v for v in r.get('citation_valid',[])) for r in first)
        result[variant]={'cases':len(first),'answerable_cases':len(answerable),'attempts':len(selected),
            'failed_attempts':sum(r['error'] is not None for r in selected),'metrics_at_k':at_k,
            'multi_evidence_sufficient':{'mean':mean(float((r.get('metrics') or {}).get('sufficient_gold_retrieved') or 0) for r in multi) if multi else None,'cases':len(multi)},
            'invalid_citations':invalid,'citation_count':sum(len(r.get('citation_valid',[])) for r in first),
            'unanswerable_context_cases':sum(bool((r.get('metrics') or {}).get('retrieved_context_on_unanswerable')) for r in first if not lookup[r['case_id']].answerable),
            'latency_ms':{'p50':median(times),'p95':times[math.ceil(.95*len(times))-1],'n':len(times)},
            'claim_support':None,'final_business_quality':None}
    return result


def evaluate(root,bundle,output,*,split='dev',runtime=None,variants=None,repeats=None,score_heldout=False,strict_algorithm=True):
    if split not in ('dev','test'):raise ValueError('research_split_invalid')
    if split=='test' and not score_heldout:raise ValueError('research_heldout_requires_explicit_flag')
    m,data,current=inspect_bundle(root,bundle,strict_algorithm=strict_algorithm)
    variants=list(variants or VARIANTS)
    if not variants or any(v not in VARIANTS for v in variants) or len(set(variants))!=len(variants):raise ValueError('research_variants_invalid')
    if runtime is None and variants!=['A_bm25']:raise ValueError('research_real_runtime_required')
    repetitions=m['repeats'] if repeats is None else repeats
    if repetitions!=m['repeats'] and not (split=='dev' and variants==['A_bm25'] and repetitions==1):raise ValueError('research_repeats_changed')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    if split=='test':
        # Reservation survives a crash: a failed run is evidence, never silently rescored.
        write_new(Path(bundle)/'heldout-reservation.json',{'run_directory_name':output.name,'at_utc':stamp(),'algorithm_identity':current})
    started=perf_counter();code,public,backend=open_services(bundle,m,data,split,runtime)
    cases=[c for c in data.cases if c.split==split];rows=[];run_id='eval-'+uuid4().hex
    with (output/'queries.jsonl').open('x',encoding='utf-8',newline='\n') as out:
        for variant in variants:
            for case in cases:
                if case.retrieval_scope=='public' and VARIANTS[variant][1] is None:continue
                for repeat in range(repetitions):
                    t=perf_counter();row={'run_id':run_id,'case_id':case.case_id,'split':split,'scope':case.retrieval_scope,
                        'category':case.category,'variant':variant,'repeat':repeat,'started_at_utc':stamp(),'error':None}
                    try:
                        found,refs,canonical=query_case(code,public,m['scopes'][split],case,variant)
                        row.update(metrics=evaluate_case(case,data.corpus,refs,limit=5),
                            metrics_at_k={str(k):evaluate_case(case,data.corpus,refs,limit=k) for k in (1,3,5)},
                            references=canonical,citation_valid=[True for _ in refs],
                            method_used=found['method_used'],retrieval_trace=found['retrieval_trace'],warnings=found['warnings'])
                    except Exception as exc:
                        # Fixed exception type only. Sources/paths in exception messages stay out of exports.
                        row.update(error=type(exc).__name__,metrics=None,metrics_at_k=None)
                    row.update(elapsed_ms=round((perf_counter()-t)*1000,3),ended_at_utc=stamp())
                    rows.append(row);out.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');out.flush()
    report={'schema_version':'eval-run-1','run_id':run_id,'split':split,'heldout_scored':split=='test',
        'started_at_utc':rows[0]['started_at_utc'] if rows else None,'ended_at_utc':stamp(),
        'status':'failed' if any(r['error'] for r in rows) else 'completed','dataset_hash':m['artifacts']['dataset.json'],
        'corpus_snapshot':data.corpus.snapshot_id,'index_scopes':m['scopes'],'runtime':m['runtime'],
        'runtime_loaded':runtime is not None,'algorithm_identity':current,'prepared_algorithm_identity':m['algorithm_identity'],
        'prepared_full_code_identity':m['full_code_identity'],'manifest_sha256':file_hash(Path(bundle)/'manifest.json'),
        'variants':variants,'repeats':repetitions,'quality_trial':0,'limit':5,'known_scope_experiment':True,
        'human_reviewed_count':0,'claim_support':None,'final_business_quality':None,
        'encoder_calls':backend.counts() if backend else None,'tokens':None,'cost':None,
        'usage_missing_reason':'no generative call; embedding token usage and price not provided',
        'prepare_ms':m['prepare_ms'],'elapsed_ms':round((perf_counter()-started)*1000,3),
        'raw_sha256':file_hash(output/'queries.jsonl'),'summary':summarize(rows,cases)}
    write_new(output/'run.json',report);return report


def replay(root,bundle,reference,output,*,split,runtime):
    """New directory/process is the caller's responsibility; compares every reference field."""
    m,data,_=inspect_bundle(root,bundle);saved=read_json(Path(reference)/'run.json')
    if saved['raw_sha256']!=file_hash(Path(reference)/'queries.jsonl'):raise ValueError('research_result_hash_changed')
    if saved['split']!=split or saved['manifest_sha256']!=file_hash(Path(bundle)/'manifest.json'):raise ValueError('research_reference_scope_changed')
    code,public,backend=open_services(bundle,m,data,split,runtime);cases={c.case_id:c for c in data.cases if c.split==split}
    rows=[];seen=set()
    for line in (Path(reference)/'queries.jsonl').read_text(encoding='utf-8').splitlines():
        old=json.loads(line)
        if old['repeat']!=0:continue
        key=(old['case_id'],old['variant'])
        if key in seen:raise ValueError('research_duplicate_reference_case')
        seen.add(key)
        if old['error']:raise ValueError('research_cannot_replay_failed_reference')
        found,_,refs=query_case(code,public,m['scopes'][split],cases[old['case_id']],old['variant'])
        rows.append({'case_id':old['case_id'],'variant':old['variant'],'same_references':refs==old['references'],
            'same_sparse_ids':found['retrieval_trace']['sparse_ids']==old['retrieval_trace']['sparse_ids'],
            'same_dense_ids':found['retrieval_trace']['dense_ids']==old['retrieval_trace']['dense_ids'],
            'same_fused_ids':found['retrieval_trace']['fused_ids']==old['retrieval_trace']['fused_ids']})
    expected={(c.case_id,v) for c in cases.values() for v in saved['variants'] if c.retrieval_scope=='project' or VARIANTS[v][1] is not None}
    if not rows or seen!=expected:raise ValueError('research_replay_coverage_changed')
    passed=all(all(r[k] for k in ('same_references','same_sparse_ids','same_dense_ids','same_fused_ids')) for r in rows) and backend.documents==0
    result={'schema_version':'research-replay-1','status':'passed' if passed else 'failed','at_utc':stamp(),
        'cases':len(rows),'encoder_calls':backend.counts(),'same_scope':True,'rows':rows,
        'manifest_sha256':file_hash(Path(bundle)/'manifest.json'),'reference_raw_sha256':saved['raw_sha256']}
    write_new(output,result);return result


def freeze_gate(run,output):
    if run['split']!='dev' or run['status']!='completed' or run['variants']!=['A_bm25'] or run['heldout_scored']:
        raise ValueError('gate_requires_successful_bm25_dev_baseline')
    s=run['summary']['A_bm25'];floors={}
    if s['cases']<1 or s['answerable_cases']<1 or s['citation_count']<1 or s['invalid_citations'] or s['failed_attempts']:
        raise ValueError('gate_baseline_coverage_invalid')
    for name in METRICS:
        value=s['metrics_at_k']['5'][name];n=value['cases'];avg=value['mean']
        if not n or avg is None or avg<=1/n:raise ValueError('gate_positive_baseline_required:'+name)
        floors[name]=avg-1/n
    multi=s['multi_evidence_sufficient']
    if not multi['cases'] or multi['mean'] is None:raise ValueError('gate_multi_coverage_required')
    ungated={}
    if multi['mean']>1/multi['cases']:floors['multi_evidence_sufficient']=multi['mean']-1/multi['cases']
    else:ungated['multi_evidence_sufficient']='measured baseline too low for a positive one-query-margin floor; observation only'
    gate={'schema_version':'retrieval-gate-1','dataset_hash':run['dataset_hash'],'corpus_snapshot':run['corpus_snapshot'],
        'manifest_sha256':run['manifest_sha256'],'baseline_raw_sha256':run['raw_sha256'],'runtime':run['runtime'],
        'cases':s['cases'],'answerable_cases':s['answerable_cases'],'baseline':s,'floors':floors,'ungated':ungated,
        'policy':'observed dev baseline minus one query equivalent; positive metrics only; citation validity 1, errors 0',
        'semantic_quality_gated':False,'human_reviewed_count':0}
    write_new(output,{'payload':gate,'sha256':fingerprint(gate)});return gate


def check_gate(run,path):
    sealed=read_json(path);g=sealed['payload']
    if sealed['sha256']!=fingerprint(g) or g['schema_version']!='retrieval-gate-1':raise ValueError('gate_manifest_invalid')
    if (run['split']!='dev' or run['heldout_scored'] or run['variants']!=['A_bm25'] or run['status']!='completed'
        or any(run[k]!=g[k] for k in ('dataset_hash','corpus_snapshot','manifest_sha256','runtime'))):raise ValueError('gate_scope_changed')
    if not set(METRICS)<=set(g['floors']) or set(g['floors'])-set(METRICS)-{'multi_evidence_sufficient'}:raise ValueError('gate_metrics_missing')
    if 'multi_evidence_sufficient' not in g['floors'] and not g.get('ungated',{}).get('multi_evidence_sufficient'):raise ValueError('gate_missing_observation_reason')
    if any(type(v) not in (float,int) or not math.isfinite(v) or not 0<v<=1 for v in g['floors'].values()):raise ValueError('gate_floor_invalid')
    s=run['summary']['A_bm25']
    if s['cases']!=g['cases'] or s['answerable_cases']!=g['answerable_cases'] or s['invalid_citations'] or s['failed_attempts'] or s['citation_count']<1:
        raise ValueError('gate_coverage_or_citation_failed')
    if s['multi_evidence_sufficient']['cases']!=g['baseline']['multi_evidence_sufficient']['cases']:raise ValueError('gate_multi_coverage_changed')
    failures=[]
    for name,floor in g['floors'].items():
        v=s[name] if name=='multi_evidence_sufficient' else s['metrics_at_k']['5'][name]
        base=g['baseline'][name] if name=='multi_evidence_sufficient' else g['baseline']['metrics_at_k']['5'][name]
        if not v['cases'] or v['cases']!=base['cases'] or v['mean'] is None or v['mean']+1e-12<floor:failures.append(name)
    return {'status':'failed' if failures else 'passed','failed_metrics':failures,'floors':g['floors'],'ungated':g.get('ungated',{}),
            'semantic_quality_gated':False,'candidate_algorithm_identity':run['algorithm_identity']}
