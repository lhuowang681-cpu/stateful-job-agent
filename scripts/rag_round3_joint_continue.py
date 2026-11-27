"""Continue the valid T2 project observation; never replace formal failures."""
import argparse,json,os,sqlite3,sys,time
from pathlib import Path
from contextlib import closing
from dataclasses import replace
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.rag_round3_joint import OWNER,AUTH,audit,read,write,append,code_identity,file_hash

def main():
    from fastapi.testclient import TestClient
    from job_agent.resume_workspace.api import create_resume_app
    from job_agent.resume_workspace.parsing import ResumeParser
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
    from job_agent.knowledge.research_contract import CountedBackend
    from job_agent.llm.providers.local_text import OfflineTextProvider
    p=argparse.ArgumentParser();p.add_argument('--bundle',type=Path,required=True);p.add_argument('--formal',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    runtime=RetrievalRuntime.from_env();manifest=read(a.bundle/'manifest.json');audit(a.bundle,manifest,runtime)
    formal=read(a.formal/'run.json');assert formal['source_identity']==code_identity()
    row=next(r for r in formal['rows'] if r['case']['case_id']=='T2')
    assert row['status']=='completed_source_observation' and row['target_symbol_located']
    a.output.mkdir(parents=True,exist_ok=False);ledger=a.bundle.parent/'f4-generation-reservations.jsonl';attempts=[]
    class Captured(OfflineTextProvider):
        def generate_structured(self,**kw):
            old=ledger.read_text().splitlines();assert len(old)<40 and len(attempts)<2
            reservation={'number':len(old)+1,'output':a.output.name,'trace':kw['trace'].model_dump(),'at':time.time()}
            append(ledger,reservation);attempts.append(reservation)
            try:
                result=super().generate_structured(**kw)
                append(a.output/'model-calls.jsonl',{'reservation':reservation,'result':result.model_dump(),'measurement':dict(self.calls[-1])});return result
            except Exception as e:
                append(a.output/'model-calls.jsonl',{'reservation':reservation,'exception':type(e).__name__});raise
    provider=Captured('/root/autodl-tmp/models/Qwen2.5-7B-Instruct',device='cuda:0',max_input_tokens=8192,max_output_tokens=1600,generation_seconds=25)
    assert provider.identity==read(a.formal/'model-identity.json')
    write(a.output/'model-identity.json',provider.identity)
    write(a.output/'frozen-demonstration.json',{'continued_case':'T2','formal_run_sha256':file_hash(a.formal/'run.json'),
        'formal_results_unchanged':True,'maximum_new_generations':2,'synthetic_actions_only':True,
        'history_probe_query':'当前 历史 计划 实现 部署 CURRENT_SPEC','human_reviewed':0})
    dbpath=a.output/'synthetic-continuation.sqlite'
    with closing(sqlite3.connect(a.formal/'synthetic-business.sqlite')) as src,closing(sqlite3.connect(dbpath)) as dst:src.backup(dst)
    ws=SqliteResumeRepository(dbpath);backend=CountedBackend(runtime.backend);runtime=replace(runtime,backend=backend)
    report={'source_identity':code_identity(),'formal_run_sha256':file_hash(a.formal/'run.json'),
        'continued_case':'T2','formal_results_unchanged':True,'paid_calls':0,'human_reviewed':0,'status':'running'}
    try:
      with TestClient(create_resume_app(ws,resolve_identity={'synthetic-round3-joint':OWNER}.get,
              parser=ResumeParser(provider),retrieval_runtime=runtime,task_worker_enabled=False)) as client:
        report['startup_embedding']=backend.counts()
        def post(route,body=None):
            r=client.post('/api/v2'+route,headers=AUTH,json=body);data=r.json()
            append(a.output/'http-events.jsonl',{'route':route,'status':r.status_code,'body':data});assert r.status_code==200,(route,r.status_code)
            return data
        observation=next(o for o in row['observations']['observations'] if o['payload']['point_id']=='p0')
        key=observation['observation_id'];report['original_observation']=observation;actions=[]
        for action,extra in [('confirm',{}),('correct',{'user_finding':'unsure','note':'Synthetic persona requests practice; no claim of real user mastery.'}),('mark_reviewed',{}),('schedule',{'review_in_days':0})]:
            observation=post('/learning/observations/'+key+'/actions',{'request_key':uuid4().hex,'expected_revision':observation['revision'],'action':action,**extra});actions.append(observation)
        report['synthetic_actions']=actions
        practice=post('/learning/observations/'+key+'/practice',{'request_key':uuid4().hex,
            'expected_revision':observation['revision'],'mode':'llm','allow_external_processing':True})
        report['practice_initial']=practice;initial=row['initial'];current=practice['current']
        assert not practice['turns'] and current['question_id']!=initial['question_id']
        assert current['prompt']==initial['prompt'] and current['references']==initial['references'] and current['evidence_boundary']==initial['evidence_boundary']
        result=post('/interviews/'+practice['session_id']+'/answers',{'request_key':uuid4().hex,'question_id':current['question_id'],
            'expected_revision':practice['revision'],'answer':row['case']['answer'],'allow_external_processing':True})
        report['practice_answered']=result
        assert result['status']!='failed' and result['revision']==1,'practice_model_or_contract_failed'
        report['practice_finished']=post('/interviews/'+practice['session_id']+'/finish',{'expected_revision':result['revision']})
        observations=post('/interviews/'+practice['session_id']+'/learning-observations');report['practice_observations']=observations
        assert observations['added']>0 and all(o['payload']['independent_mastery']=='not_established' for o in observations['observations'])
        report['trace']=client.get('/api/v2/interviews/'+practice['session_id']+'/trace',headers=AUTH).json()
        report['status']='completed_full_project_learning_loop'
        scope=manifest['scopes']['full']
        report['history_probe']=post('/evidence/retrieve',{'scope':'private_project','project_id':scope['project_id'],
            'snapshot_id':scope['snapshot_id'],'query':'当前 历史 计划 实现 部署 CURRENT_SPEC'})
    except Exception as e:report.update(status='failed',error_type=type(e).__name__,detail=str(e)[:1000])
    finally:
        report['provider_measurements']=list(provider.calls);report['embedding_total']=backend.counts()
        report['global_reserved_attempts']=len(ledger.read_text().splitlines());write(a.output/'run.json',report)
    print(json.dumps({'status':report['status'],'reserved':report['global_reserved_attempts']},ensure_ascii=False),flush=True)
    if report['status']!='completed_full_project_learning_loop':raise SystemExit(1)
if __name__=='__main__':main()
