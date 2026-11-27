"""Post-formal observed-only default-mode audit; no extra heldout claim/tuning."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.rag_round3_experiment import labels_for,summarize,write_new
from job_agent.knowledge.research_contract import inspect_bundle,_audit_db,OWNER
from job_agent.knowledge.support_evaluation import LocatedSpan,evaluate_support
from job_agent.knowledge.evaluation_contract import GoldSpan
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery


def main():
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert (a.bundle/'round3-formal-reservation-v1.json').is_file()
    a.output.mkdir(parents=True,exist_ok=False);m,data,algorithm=inspect_bundle(ROOT,a.bundle,strict_algorithm=False)
    ws=_audit_db((a.bundle/'test.sqlite').resolve(),m['scopes']['test'],data,'test');scope=m['scopes']['test']
    service=CodeRAGService(ws);labels=labels_for(data);docs={d.document_id:d for d in data.corpus.documents};rows=[]
    with (a.output/'queries.jsonl').open('x',encoding='utf-8') as stream:
        for case in (c for c in data.cases if c.split=='test'):
            start=time.perf_counter();found=service.search(OWNER,scope['project_id'],CodeQuery(snapshot_id=scope['snapshot_id'],query=case.query,limit=5))
            citations=[]
            for hit in found['hits']:
                from job_agent.resume_workspace.evidence_reference import EvidenceReference
                ref=service.validate_reference(OWNER,EvidenceReference.model_validate(hit['reference']));doc=docs['test-code/'+ref.path]
                citations.append(LocatedSpan(span=GoldSpan(document_id=doc.document_id,content_hash=ref.content_hash,start_line=ref.start_line,end_line=ref.end_line,quote=ref.quote),
                    source_version=doc.source_version,corpus_snapshot=data.corpus.snapshot_id,snapshot_id=ref.snapshot_id))
            row={'case_id':case.case_id,'category':case.category,'answerable':case.answerable,'group':'observed_default_diagnostic',
                'variant':'L_default_lexical_code_aware','repeat':0,'error':None,'references':[h['reference'] for h in found['hits']],
                'score':evaluate_support(case,data.corpus,labels[case.case_id],citations,snapshot_id=scope['snapshot_id']),
                'retrieval_trace':found['retrieval_trace'],'warnings':found['warnings'],'method_used':found['method_used'],
                'elapsed_ms':round((time.perf_counter()-start)*1000,3)}
            rows.append(row);stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    result={'status':'completed','purpose':'Existing default missing from formal11 methods; observed16 only, no fresh-test claim',
            'formal_results_unchanged':True,'parameter_adjustments':0,'cases':16,'paid_calls':0,'generative_calls':0,'embedding_calls':0,
            'algorithm_identity':algorithm,'summary':summarize(rows),'human_reviewed':0}
    write_new(a.output/'run.json',result);print(json.dumps(result))


if __name__=='__main__':main()
