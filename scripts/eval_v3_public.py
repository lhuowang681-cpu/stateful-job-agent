"""Post-implementation tag-derived diagnostic. Not a blind semantic gold set."""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from statistics import mean
from time import perf_counter
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.resume_workspace.public_seed import seed_entries
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.evidence_reference import EvidenceReference


def main():
    entries=seed_entries();questions=[e for e in entries if e['kind']=='question']
    corpus_sha=sha256(json.dumps(entries,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path=ROOT/'tests/fixtures/v3_diagnostic/public_tag_queries.json'
    if not path.exists():
        queries=[]
        for entry in questions:
            for i,tag in enumerate(entry['tags'][:4]):
                gold=[e['entry_id'] for e in questions if tag.casefold() in [t.casefold() for t in e['tags']]]
                queries.append({'id':f"{entry['entry_id']}-{i}",'query':tag,'gold_questions':gold})
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'scope':'post-implementation exact-tag diagnostic; no human semantic labels',
            'corpus_sha256':corpus_sha,'queries':queries},ensure_ascii=False,indent=2),encoding='utf-8')
    raw=path.read_bytes();data=json.loads(raw)
    if corpus_sha!=data['corpus_sha256']:raise RuntimeError('diagnostic corpus changed; retain old data/results and create a new explicit dataset version')
    rows=[]
    with TemporaryDirectory(prefix='v3-public-eval-') as temp:
        service=PublicKnowledgeService(SqliteResumeRepository(Path(temp)/'public.sqlite'))
        for method in ('none','tag','bm25','hybrid'):
            for q in data['queries']:
                started=perf_counter();result={'hits':[],'method_used':'no_retrieval','warnings':[]}
                if method!='none':result=service.search(q['query'],kind='question',method=method,limit=5)
                ids=[h['entry']['entry_id'] for h in result['hits']];gold=set(q['gold_questions'])
                valid=sum(service.repository.validate_reference(EvidenceReference.model_validate(h['reference'])).quote==h['reference']['quote'] for h in result['hits'])
                rows.append({'method':method,'query_id':q['id'],'query':q['query'],'gold':q['gold_questions'],
                    'returned':ids,'recall_at_5':len(gold.intersection(ids))/len(gold),
                    'reciprocal_rank':next((1/(i+1) for i,x in enumerate(ids) if x in gold),0),
                    'duplicate_results':len(ids)-len(set(ids)),'valid_references':valid,'returned_references':len(ids),
                    'method_used':result['method_used'],'warnings':result['warnings'],'elapsed_ms':round((perf_counter()-started)*1000,3)})
    summary=[]
    for method in ('none','tag','bm25','hybrid'):
        group=[r for r in rows if r['method']==method];count=sum(r['returned_references'] for r in group)
        summary.append({'method':method,'queries':len(group),'recall_at_5_macro':mean(r['recall_at_5'] for r in group),
            'mrr':mean(r['reciprocal_rank'] for r in group),'returned_references':count,
            'citation_accuracy':sum(r['valid_references'] for r in group)/count if count else None,
            'duplicate_results':sum(r['duplicate_results'] for r in group)})
    result={'dataset_sha256':sha256(raw).hexdigest(),'corpus_sha256':corpus_sha,'scope':data['scope'],
        'unique_query_strings':len({q['query'] for q in data['queries']}),'questions_in_corpus':len(questions),
        'limitations':['Gold is exact tag membership, not semantic relevance.','Repeated query strings are reported, not independent human judgments.',
            'Tag baseline and labels share metadata: diagnostic checks routing, not generalization.','Hybrid is explicit BM25 fallback; dense and reranker NOT_RUN.'],
        'model_calls':0,'summary':summary,'rows':rows}
    result['search_index_version']='public-title-body-tags-v2'
    out=ROOT/'docs/evaluation/results/v3-public-diagnostic-v2.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('dataset_sha256','unique_query_strings','summary')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
