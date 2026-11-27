"""Reproduce the frozen mechanical code-retrieval benchmark, without model calls."""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from statistics import mean
from time import perf_counter
import argparse, json, sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery,INDEX_VERSION
from job_agent.resume_workspace.evidence_reference import EvidenceReference

FROZEN_SHA='b1e59321b5d6631f3860e3a6fc461b70eed363d0ecf0ef493292ab0f6686edec'


def run(output:Path):
    raw=(ROOT/'tests/fixtures/v3_frozen/code_queries.json').read_bytes()
    if sha256(raw).hexdigest()!=FROZEN_SHA:raise RuntimeError('frozen dataset hash changed')
    data=json.loads(raw);rows=[]
    with TemporaryDirectory(prefix='v3-code-eval-') as temp:
        workspace=SqliteResumeRepository(Path(temp)/'eval.sqlite');store=LongTermRepository(workspace)
        project=store.create_project('eval',ProjectCreate(name='Frozen mechanical benchmark'))
        project=store.publish_files('eval',project['project_id'],data['files'],origin='zip')
        service=CodeRAGService(workspace);pid=project['project_id'];snapshot=project['current_snapshot']
        index=service.build('eval',pid,snapshot)
        for method in ('readme','flat','keyword','symbol','code_aware'):
            for q in data['queries']:
                started=perf_counter()
                result=service.search('eval',pid,CodeQuery(snapshot_id=snapshot,query=q['query'],method=method,limit=5))
                hits=result['hits'];gold=set(q['gold_files']);paths=[h['reference']['path'] for h in hits]
                symbols={h['symbol']['name'] for h in hits if h['symbol']}
                valid=sum(service.validate_reference('eval',EvidenceReference.model_validate(h['reference'])).quote==h['reference']['quote'] for h in hits)
                rows.append({'method':method,'query_id':q['id'],'kind':q['kind'],'query':q['query'],
                    'gold_files':q['gold_files'],'gold_symbols':q['gold_symbols'],'returned_files':paths,
                    'returned_symbols':sorted(symbols),'references':[h['reference'] for h in hits],
                    'file_recall_at_5':len(gold.intersection(paths))/len(gold),
                    'symbol_recall_at_5':len(set(q['gold_symbols']).intersection(symbols))/len(q['gold_symbols']),
                    'reciprocal_rank':next((1/(i+1) for i,p in enumerate(paths) if p in gold),0),
                    'complete':gold.issubset(paths),'valid_references':valid,'returned_references':len(hits),
                    'elapsed_ms':round((perf_counter()-started)*1000,3),'method_used':result['method_used'],
                    'warnings':result['warnings']})
    summaries=[]
    for method in ('readme','flat','keyword','symbol','code_aware'):
        group=[r for r in rows if r['method']==method];cross=[r for r in group if r['kind']=='cross_file']
        times=sorted(r['elapsed_ms'] for r in group);count=sum(r['returned_references'] for r in group)
        summaries.append({'method':method,'queries':len(group),'file_recall_at_5_macro':mean(r['file_recall_at_5'] for r in group),
            'symbol_recall_at_5_macro':mean(r['symbol_recall_at_5'] for r in group),'mrr':mean(r['reciprocal_rank'] for r in group),
            'cross_file_complete':sum(r['complete'] for r in cross),'cross_file_total':len(cross),
            'valid_references':sum(r['valid_references'] for r in group),'returned_references':count,
            'citation_accuracy':sum(r['valid_references'] for r in group)/count if count else None,
            'p50_ms':times[(len(times)-1)//2],'p95_ms':times[int(.95*(len(times)-1))]})
    output.parent.mkdir(parents=True,exist_ok=True)
    result={'protocol':'v3-frozen-mechanical-code-v1','dataset_sha256':FROZEN_SHA,'index_version':INDEX_VERSION,
        'scope':'synthetic exact identifiers; not human semantic evaluation or real-repository generalization',
        'readme_baseline_note':'Frozen corpus contains no README: this method has zero candidates, not a quality comparison with a written README.',
        'flat_symbol_note':'Flat chunks carry no symbol metadata, so symbol recall measures symbol localization rather than file relevance.',
        'model_calls':0,'dense':'NOT_RUN: no real semantic embedding configured','reranker':'NOT_RUN',
        'index':index,'summary':summaries,'rows':rows}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'dataset_sha256':FROZEN_SHA,'summary':summaries},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'docs/evaluation/results/v3-code-frozen-v1.json')
    run(parser.parse_args().output)
