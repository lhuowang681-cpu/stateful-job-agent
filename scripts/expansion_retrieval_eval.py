"""Controlled-corpus dev retrieval ablation using real product services.

Known domain is an annotation in this algorithm experiment, not a product router.
The independent test split is deliberately not scoreable by this script yet.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean,median
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT))
from job_agent.knowledge.evaluation_contract import EvaluationDataset,GoldSpan,evaluate_case
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService,entry_text
from job_agent.resume_workspace.public_seed import seed_entries
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime


def controlled_scope(case):
    # This deliberately uses the dataset's domain labels. Do not present these
    # numbers as automatic cross-domain routing or end-to-end answer quality.
    return 'code' if any(g.document_id.startswith('dev-code/') for g in case.gold) or case.family.startswith('receipt-') else 'public'


def run(runtime,data,*,repeats=3,case_limit=None):
    rows=[];owner='synthetic-eval-user'
    cases=[c for c in data.cases if c.split=='dev']
    if case_limit:cases=cases[:case_limit]
    with TemporaryDirectory(prefix='expansion-dev-eval-') as directory:
        ws=SqliteResumeRepository(Path(directory)/'ws.sqlite');projects=LongTermRepository(ws)
        p=projects.create_project(owner,ProjectCreate(name='Fixed CC0 dev corpus',license_note='CC0-1.0'))
        files={d.document_id.removeprefix('dev-code/'):d.text for d in data.corpus.documents if d.document_id.startswith('dev-code/')}
        p=projects.publish_files(owner,p['project_id'],files,origin='zip')
        code=CodeRAGService(ws,embedding_backend=runtime.backend,reranker=runtime.reranker,retrieval_settings=runtime.settings)
        code.build(owner,p['project_id'],p['current_snapshot'])
        public=PublicKnowledgeService(ws,embedding_backend=runtime.backend,reranker=runtime.reranker,
                                     retrieval_settings=runtime.settings,seed=False)
        seeds={e['entry_id']:e for e in seed_entries()};install=[]
        for doc in data.corpus.documents:
            if doc.kind!='public_knowledge' or doc.split!='dev':continue
            entry=seeds[doc.document_id]
            if entry['title']+'\n'+entry['body']!=doc.text:raise ValueError('frozen_public_source_drift')
            install.append(entry)
        public.repository.install(install);public.prewarm()
        variants=[('A_bm25','keyword','bm25',False,False),('B_dense','dense','dense',False,False),
                  ('C_hybrid','hybrid','hybrid',False,False),('D_hybrid_rerank','hybrid','hybrid',True,False),
                  ('E_code_aware_no_relations','code_aware',None,False,False),
                  ('F_code_aware_relations','code_aware',None,False,True),
                  ('G_flat_bm25','flat',None,False,False)]
        for name,code_method,public_method,rerank,relations in variants:
            for case in cases:
                scope=controlled_scope(case)
                if scope=='public' and public_method is None:continue
                for repeat in range(repeats):
                    started=perf_counter();row={'case_id':case.case_id,'family':case.family,'category':case.category,
                        'scope':scope,'variant':name,'repeat':repeat,'error':None}
                    try:
                        if scope=='code':
                            found=code.search(owner,p['project_id'],CodeQuery(snapshot_id=p['current_snapshot'],query=case.query,
                                method=code_method,limit=5,expand_relations=relations,rerank=rerank))
                        else:found=public.search(case.query,kind='doc',method=public_method,limit=5,rerank=rerank)
                        refs=[]
                        for hit in found['hits']:
                            reference=EvidenceReference.model_validate(hit['reference'])
                            if scope=='code':
                                code.validate_reference(owner,reference);document_id='dev-code/'+reference.path
                            else:
                                public.repository.validate_reference(reference);document_id=reference.source_id
                            refs.append(GoldSpan(document_id=document_id,content_hash=reference.content_hash,
                                start_line=reference.start_line,end_line=reference.end_line,quote=reference.quote))
                        row.update(metrics=evaluate_case(case,data.corpus,refs,limit=5),retrieved=[r.model_dump() for r in refs],
                            metrics_at_k={str(k):evaluate_case(case,data.corpus,refs,limit=k) for k in (1,3,5)},
                            scores=[h['score'] for h in found['hits']],trace=found['retrieval_trace'],
                            method_used=found['method_used'],warnings=found['warnings'])
                        if rerank and found['hits'] and not found['retrieval_trace']['rerank_applied']:
                            row['error']='requested_real_rerank_not_applied'
                    except Exception as exc:
                        row.update(error=type(exc).__name__+':'+str(exc)[:160],metrics=None)
                    row['elapsed_ms']=round((perf_counter()-started)*1000,3);rows.append(row)
    summary={}
    for name,*_ in variants:
        selected=[r for r in rows if r['variant']==name];valid=[r for r in selected if r.get('metrics') and not r['error']]
        first=[r for r in valid if r['repeat']==0]
        metrics={}
        for metric in ('hit_any_gold','gold_span_recall','sufficient_gold_retrieved','reciprocal_rank','citation_valid_rate','retrieved_context_on_unanswerable'):
            values=[r['metrics'][metric] for r in first if r['metrics'][metric] is not None]
            metrics[metric]={'mean':mean(values) if values else None,'cases':len(values)}
        at_k={}
        for k in ('1','3','5'):
            at_k[k]={}
            for metric in ('hit_any_gold','gold_span_recall','sufficient_gold_retrieved','reciprocal_rank'):
                values=[r['metrics_at_k'][k][metric] for r in first if r['metrics_at_k'][k][metric] is not None]
                at_k[k][metric]={'mean':mean(values) if values else None,'cases':len(values)}
        summary[name]={'cases':len({r['case_id'] for r in selected}),'attempts':len(selected),'failed_attempts':sum(bool(r['error']) for r in selected),
            'metrics_at_k':at_k,
            'metrics_first_trial':metrics,'latency_p50_ms':median(r['elapsed_ms'] for r in valid) if valid else None,
            'latency_max_ms':max((r['elapsed_ms'] for r in valid),default=None)}
    return rows,summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model-path',required=True);parser.add_argument('--rerank-path',required=True)
    parser.add_argument('--device',default='cuda:0');parser.add_argument('--repeats',type=int,choices=range(1,6),default=3)
    parser.add_argument('--case-limit',type=int,choices=range(1,21));parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    path=ROOT/'docs/evaluation/expansion/candidates-v1.json';data=EvaluationDataset.model_validate_json(path.read_text(encoding='utf-8'))
    start=perf_counter()
    runtime=RetrievalRuntime.from_env({'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen','JOB_AGENT_WORKSPACE_EMBEDDING_PATH':args.model_path,
        'JOB_AGENT_WORKSPACE_EMBEDDING_DEVICE':args.device,'JOB_AGENT_WORKSPACE_RERANK_PATH':args.rerank_path,'JOB_AGENT_WORKSPACE_RERANK_DEVICE':args.device})
    loaded=perf_counter()-start;rows,summary=run(runtime,data,repeats=args.repeats,case_limit=args.case_limit)
    sources={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in (ROOT/'src').rglob('*.py')}
    sources[Path(__file__).relative_to(ROOT).as_posix()]=sha256(Path(__file__).read_bytes()).hexdigest()
    report={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'split':'dev','heldout_scored':False,
        'dataset_hash':sha256(path.read_bytes()).hexdigest(),'corpus_snapshot':data.corpus.snapshot_id,'config':asdict(runtime.settings),
        'config_identity':runtime.settings.key,'source_identity':fingerprint(sources),'model':asdict(runtime.identity),
        'reranker':asdict(runtime.reranker.identity),'annotation_status':'AI candidates; human semantic review pending',
        'domain_selection':'gold-labeled controlled corpus; not product routing quality',
        'quality_scope':'mechanical retrieval/citation only; no generated answer or human claim-support score',
        'model_load_hash_ms':round(loaded*1000,3),'total_ms':round((perf_counter()-start)*1000,3),'summary':summary,'rows':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(args.output),'attempts':len(rows),'failures':sum(bool(r['error']) for r in rows),'heldout_scored':False},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
