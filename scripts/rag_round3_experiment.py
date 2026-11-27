"""Bounded seen development and exactly one locked new16 scoring run.

Existing immutable source indices/vectors are audited and reused. Search-only
settings may differ, explicitly recorded per row; old manifests are not rebound.
"""
import argparse,json,math,resource,sys,time
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from statistics import mean,median
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.research_contract import inspect_bundle,_audit_db,CountedBackend,OWNER,runtime_identity,algorithm_sources
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.knowledge.support_evaluation import LocatedSpan,SupportLabel,evaluate_support
from job_agent.knowledge.evaluation_contract import GoldSpan
from job_agent.knowledge.retrieval_policy import RetrievalSettings
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def write_new(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
def variants(weight):
    return {'A_bm25':('keyword',False,False,1,'legacy_first'),
        'B_dense':('dense',False,False,1,'legacy_first'),
        'C_hybrid':('hybrid',False,False,1,'legacy_first'),
        'D_hybrid_rerank':('hybrid',True,False,1,'legacy_first'),
        'E_code_direct':('code_aware',False,False,1,'legacy_first'),
        'F_legacy_relations':('code_aware',False,True,1,'legacy_first'),
        'G_flat_bm25':('flat',False,False,1,'legacy_first'),
        'H_hybrid_weighted':('hybrid',False,False,weight,'legacy_first'),
        'I_code_weighted':('code_aware',False,False,weight,'legacy_first'),
        'J_preserve_direct':('code_aware',False,True,1,'preserve_direct'),
        'K_weighted_preserve':('code_aware',False,True,weight,'preserve_direct')}


def labels_for(data):
    labels={}
    for name,key in [('rag-round3-diagnostic-labels-v1.json','cases'),('rag-round3-new16-support-v1.json','labels')]:
        value=read(ROOT/'docs/evaluation/expansion'/name)
        for item in value[key]:
            label=SupportLabel.model_validate(item['label'] if key=='cases' else item)
            labels[label.case_id]=label
    result={}
    for case in data.cases:
        if case.case_id in labels:result[case.case_id]=labels[case.case_id].model_copy(update={'corpus_snapshot':data.corpus.snapshot_id})
        else:result[case.case_id]=SupportLabel(case_id=case.case_id,corpus_snapshot=data.corpus.snapshot_id,answerable=case.answerable,
            minimal_spans=case.gold,symbol_ranges=[g for g in case.gold if g.document_id.endswith('.py')],
            requirement=case.gold_requirement,rationale='Conservative original whole-span label for seen regression; not newly minimal human gold.')
    return result


def collect(runtime,bundle,split,group,configurations,repeats,emit):
    # Current search code differs deliberately; original source/index integrity
    # and actual model identities still must match. Never edit the old manifest.
    manifest,data,current=inspect_bundle(ROOT,bundle,strict_algorithm=False)
    actual=runtime_identity(runtime)
    assert actual['embedding']==manifest['runtime']['embedding'] and actual['reranker']==manifest['runtime']['reranker']
    backend=CountedBackend(runtime.backend);workspace=_audit_db(Path(bundle).resolve()/(split+'.sqlite'),manifest['scopes'][split],data,split)
    scope=manifest['scopes'][split];labels=labels_for(data);docs={d.document_id:d for d in data.corpus.documents}
    cases=[c for c in data.cases if c.split==split]
    for variant,(method,rerank,relations,weight,priority) in configurations.items():
        settings=RetrievalSettings(dense_rrf_weight=weight,relation_priority=priority)
        service=CodeRAGService(workspace,embedding_backend=backend,reranker=runtime.reranker,retrieval_settings=settings)
        for case in cases:
            for repeat in range(repeats):
                start=time.perf_counter();row={'case_id':case.case_id,'group':group,'split':split,'category':case.category,'answerable':case.answerable,
                    'variant':variant,'repeat':repeat,'settings':asdict(settings),'error':None,'references':[]}
                try:
                    found=service.search(OWNER,scope['project_id'],CodeQuery(snapshot_id=scope['snapshot_id'],query=case.query,
                        method=method,limit=5,rerank=rerank,expand_relations=relations))
                    located=[]
                    for hit in found['hits']:
                        from job_agent.resume_workspace.evidence_reference import EvidenceReference
                        ref=service.validate_reference(OWNER,EvidenceReference.model_validate(hit['reference']))
                        doc=docs[case.split+'-code/'+ref.path]
                        row['references'].append(ref.model_dump(mode='json'))
                        located.append(LocatedSpan(span=GoldSpan(document_id=doc.document_id,content_hash=ref.content_hash,
                            start_line=ref.start_line,end_line=ref.end_line,quote=ref.quote),snapshot_id=ref.snapshot_id,
                            corpus_snapshot=data.corpus.snapshot_id,source_version=doc.source_version))
                    if method in ('dense','hybrid') and 'fallback' in found['method_used']:raise ValueError('unexpected_fallback')
                    if rerank and not found['retrieval_trace']['rerank_applied']:raise ValueError('requested_rerank_not_applied')
                    row.update(score=evaluate_support(case,data.corpus,labels[case.case_id],located,snapshot_id=scope['snapshot_id']),
                        retrieval_trace=found['retrieval_trace'],warnings=found['warnings'],method_used=found['method_used'])
                except Exception as exc:row.update(error=type(exc).__name__,score=None)
                row['elapsed_ms']=round((time.perf_counter()-start)*1000,3);emit(row)
    assert backend.documents==0
    return {'group':group,'bundle':str(bundle),'prepared_algorithm':manifest['algorithm_identity'],'current_algorithm':current,
            'dataset_sha256':manifest['artifacts']['dataset.json'],'corpus_snapshot':data.corpus.snapshot_id,
            'index_scope':scope,'encoder_calls':backend.counts()}


def summarize(rows):
    result={}
    fields=('file_location_recall','symbol_range_location_recall','minimal_single_span_recall','minimal_union_sufficient',
            'minimal_union_span_recall','minimal_line_coverage','original_gold_union_sufficient')
    for group in sorted({r['group'] for r in rows}):
        result[group]={}
        for variant in sorted({r['variant'] for r in rows if r['group']==group}):
            selected=[r for r in rows if r['group']==group and r['variant']==variant];first=[r for r in selected if r['repeat']==0]
            answerable=[r for r in first if r['answerable']];times=sorted(r['elapsed_ms'] for r in selected)
            metrics={f:mean(float((r['score'] or {}).get(f) or 0) for r in answerable) if answerable else None for f in fields}
            strict=[((r['score'] or {}).get('legacy_strict_single_citation') or {}) for r in answerable]
            metrics['legacy_single_gold_sufficient']=mean(float(s.get('sufficient_gold_retrieved') or 0) for s in strict) if strict else None
            result[group][variant]={'cases':len(first),'answerable':len(answerable),'attempts':len(selected),'errors':sum(bool(r['error']) for r in selected),
                'metrics':metrics,'unanswerable_with_context':sum(bool(r['references']) for r in first if not r['answerable']),
                'latency_ms':{'p50':median(times),'p95':times[math.ceil(len(times)*.95)-1]},
                'context_chars_max':max(((r['score'] or {}).get('context_chars') or 0) for r in selected),
                'rejected_citations':sum(len((r['score'] or {}).get('rejected_citations',[])) for r in selected),
                'generated_support':None,'correct_refusal':None,'human_reviewed':0}
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['dev','formal']);p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--design-bundle',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--weight',type=int,choices=[2,4],default=2)
    p.add_argument('--lock',type=Path);p.add_argument('--model-path',required=True);p.add_argument('--rerank-path',required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);configs=variants(a.weight)
    if a.command=='formal':
        assert a.lock and a.lock.is_file();lock=read(a.lock)
        assert lock['weight']==a.weight and lock['status']=='frozen_before_new_test'
        assert lock['algorithm_identity']==fingerprint(algorithm_sources(ROOT))
        assert lock['new_dataset_sha256']==sha256((a.bundle/'dataset.json').read_bytes()).hexdigest()
        write_new(a.bundle/'round3-formal-reservation-v1.json',{'output':a.output.name,'lock_sha256':sha256(a.lock.read_bytes()).hexdigest(),
                  'note':'One formal run; any failure remains recorded. No post-test tuning.'})
    runtime=RetrievalRuntime.from_env({'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen','JOB_AGENT_WORKSPACE_EMBEDDING_PATH':a.model_path,
        'JOB_AGENT_WORKSPACE_EMBEDDING_DEVICE':'cuda:1','JOB_AGENT_WORKSPACE_RERANK_PATH':a.rerank_path,'JOB_AGENT_WORKSPACE_RERANK_DEVICE':'cuda:1'})
    rows=[];runs=[]
    with (a.output/'queries.jsonl').open('x',encoding='utf-8') as stream:
        def emit(row):rows.append(row);stream.write(json.dumps(row,ensure_ascii=False)+'\n');stream.flush()
        if a.command=='dev':
            runs.append(collect(runtime,a.bundle,'dev','seen_code_dev',configs,1,emit))
            if a.design_bundle:runs.append(collect(runtime,a.design_bundle,'test','seen_design_dev',configs,1,emit))
        else:runs.append(collect(runtime,a.bundle,'test','new16',configs,3,emit))
    import torch
    report={'version':'rag-round3-run-1','status':'failed' if any(r['error'] for r in rows) else 'completed','command':a.command,
            'weight':a.weight,'configurations':configs,'runs':runs,'summary':summarize(rows),'rows':len(rows),
            'runtime':runtime_identity(runtime),'paid_calls':0,'generative_calls':0,'human_reviewed':0,
            'source_sha256':{f.relative_to(ROOT).as_posix():sha256(f.read_bytes()).hexdigest() for f in (ROOT/'src').rglob('*.py')},
            'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'cuda1_peak_allocated_bytes':torch.cuda.max_memory_allocated(1),
            'raw_sha256':sha256((a.output/'queries.jsonl').read_bytes()).hexdigest()}
    write_new(a.output/'run.json',report);print(json.dumps({'status':report['status'],'rows':len(rows),'command':a.command}))
    if report['status']!='completed':raise SystemExit(1)


if __name__=='__main__':main()
