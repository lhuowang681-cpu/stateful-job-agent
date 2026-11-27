"""Real loopback HTTP learning probe or an isolated synthetic UI demo server."""
import argparse,json,os,sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic,sleep
from uuid import uuid4
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.expansion_baseline import running,TEXT,FILES


def source_identity():
    files={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for base in ('src','tests','scripts')
        for p in (ROOT/base).rglob('*.py') if '__pycache__' not in p.parts}
    return sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def main():
    import httpx
    from job_agent.resume_workspace.api import create_resume_app
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.parsing import ResumeParser
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--serve',action='store_true')
    parser.add_argument('--database',type=Path);parser.add_argument('--port',type=int,default=8119)
    parser.add_argument('--project-backend',choices=['sqlite','postgresql'],default='sqlite');parser.add_argument('--model-path')
    args=parser.parse_args()
    if args.output and args.output.exists():parser.error('output already exists')
    if args.database and args.database.exists():parser.error('use a new synthetic database')
    if not args.serve and not args.output:parser.error('output required for a probe')
    result={'phase':'S7','transport':'real_loopback_http','source_identity':source_identity(),'pid':os.getpid(),
        'data':'authored synthetic CC0 only','project_backend':args.project_backend,'checks':[],
        'human_quality_verified':False,'mastery_claim':None,'model':None}
    provider=None;bundle=None
    if args.model_path:
        from job_agent.llm.providers.local_text import OfflineTextProvider
        provider=OfflineTextProvider(args.model_path,max_output_tokens=1600,capture_synthetic_outputs=True);result['model']=provider.identity
    with TemporaryDirectory(prefix='s7-learning-http-') as folder:
        ws=SqliteResumeRepository(args.database or Path(folder)/'resume.sqlite')
        if args.project_backend=='postgresql':
            from job_agent.resume_workspace.postgres_projects import postgres_persistence
            bundle=postgres_persistence(os.environ['JOB_AGENT_TEST_PROJECT_DSN'],schema='s7_http_'+uuid4().hex)
        app=create_resume_app(ws,resolve_identity={'s7-demo':'alice','s7-other':'bob'}.get,parser=ResumeParser(provider),
            demo_only=True,frontend_dir=ROOT/'frontend/dist',project_persistence=bundle)
        if args.serve:
            from job_agent.resume_workspace.contracts import SourceCreate
            from job_agent.resume_workspace.parsing_contracts import AcceptDraft
            source=ws.add_source('alice',SourceCreate(kind='original_resume',label='S7合成演示',text=TEXT))
            draft=ws.save_draft('alice',ResumeParser().parse(source))
            ws.accept_draft('alice',draft.draft_id,AcceptDraft(title='S7合成练习',expected_source_hash=source.content_hash,user_reviewed=True))
            import uvicorn
            uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)
            return
        try:
            with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer s7-demo'},timeout=120) as c:
                def call(method,path,expected=200,**kw):
                    r=c.request(method,'/api/v2'+path,**kw);assert r.status_code==expected,(path,r.status_code,r.text[:200])
                    return None if expected==204 else r.json()
                def act(o,action,**kw):
                    return call('POST','/learning/observations/'+o['observation_id']+'/actions',json={
                        'request_key':str(uuid4()),'expected_revision':o['revision'],'action':action,**kw})
                source=call('POST','/sources',expected=201,json={'kind':'original_resume','label':'S7 Synthetic','text':TEXT})
                draft=call('POST',f"/sources/{source['source_id']}/parse",expected=201,json={'mode':'local_rules'})
                version=call('POST',f"/drafts/{draft['draft_id']}/accept",expected=201,json={'title':'S7 Synthetic',
                    'expected_source_hash':source['content_hash'],'user_reviewed':True})
                scope={};pid=None
                if bundle:
                    project=call('POST','/projects',expected=201,json={'name':'S7 HTTP source','license_note':'CC0-1.0'});pid=project['project_id']
                    buffer=BytesIO()
                    with ZipFile(buffer,'w') as archive:
                        for path,text in FILES.items():archive.writestr(path,text)
                    project=call('POST',f'/projects/{pid}/zip',expected=201,content=buffer.getvalue())
                    task=call('POST',f'/projects/{pid}/index-tasks',expected=202,json={'snapshot_id':project['current_snapshot'],'request_key':'s7-http-index'})
                    deadline=monotonic()+60
                    while task['status'] not in ('SUCCEEDED','FAILED'):
                        assert monotonic()<deadline,'index_timeout';sleep(.1);task=call('GET','/tasks/'+task['task_id'])
                    assert task['status']=='SUCCEEDED',task
                    scope={'track':'project','project_id':pid,'snapshot_id':project['current_snapshot']}
                    result['index_task']=task['task_id'];result['checks'].append('real_pg_snapshot_index_task')
                mode='llm' if provider else 'local_demo'
                view=call('POST',f"/resumes/{version['resume_id']}/interviews",expected=201,json={'request_key':'s7-http-source',
                    'version_id':version['version_id'],'expected_content_hash':version['content_hash'],'jd_text':'save_receipt 幂等键、查询回执和失败边界',
                    'use_retrieval':True,'mode':mode,'allow_external_processing':bool(provider),'max_turns':2,**scope})
                sid=view['session_id'];call('POST',f'/interviews/{sid}/learning-observations',expected=409)
                def answer(v):
                    n=call('POST',f"/interviews/{v['session_id']}/answers",json={'request_key':str(uuid4()),'expected_revision':v['revision'],
                        'question_id':v['current']['question_id'],'answer':'幂等键记录执行标识，查询回执，不盲目重放。静态源码不证明运行和个人贡献。',
                        'allow_external_processing':bool(provider)})
                    assert n['status']!='failed',n.get('error_code')
                    return n
                view=answer(view);call('POST',f'/interviews/{sid}/finish',json={'expected_revision':view['revision']})
                saved=call('POST',f'/interviews/{sid}/learning-observations');assert saved['observations']
                assert call('POST',f'/interviews/{sid}/learning-observations')['added']==0
                o=saved['observations'][0];result['observation_count']=saved['added'];result['checks'].append('answer_finish_source_observation_dedup')
                call('GET','/learning/observations/'+o['observation_id'],expected=404,headers={'Authorization':'Bearer s7-other'})
                o=act(o,'confirm');call('PUT','/learning/preferences',json={'expected_revision':0,'daily_limit':2,'cadence_days':3})
                assert call('GET','/learning/queue')['items'];o=act(o,'mark_reviewed');assert o['queue_bucket']=='reviewed'
                o=act(o,'schedule',review_in_days=0);result['checks'].append('explicit_check_preferences_and_review_schedule')
                practice=call('POST','/learning/observations/'+o['observation_id']+'/practice',json={'request_key':'s7-http-practice',
                    'expected_revision':o['revision'],'mode':mode,'allow_external_processing':bool(provider)})
                assert practice['turns']==[] and practice['current']['prompt']==o['payload']['question']
                assert not any(k in json.dumps(practice) for k in ('point_assessments','rubric_hash','evaluation_note','covered_ids'))
                practice=answer(practice);new_sid=practice['session_id']
                call('POST',f'/interviews/{new_sid}/finish',json={'expected_revision':practice['revision']})
                review=call('GET',f'/interviews/{new_sid}/review');assert review['learning_comparison']['status']=='same_recorded_conditions'
                result['comparison']=review['learning_comparison'];result['checks'].append('new_frozen_question_empty_history_hidden_rubric_same_recorded_conditions')
                new_obs=call('POST',f'/interviews/{new_sid}/learning-observations')['observations'];assert new_obs
                o=call('GET','/learning/observations/'+o['observation_id']);o=act(o,'correct',user_finding='unsure',note='合成用户明确纠正；保留原评价。')
                assert call('GET',f'/interviews/{new_sid}/review')['learning_comparison']['status']=='not_comparable'
                o=act(o,'pause');assert o['queue_bucket']=='paused';o=act(o,'resume')
                o=act(o,'withdraw',note='合成用户不再采用此题评价。');assert o['payload'] is None and o['status']=='withdrawn'
                assert all(t['assessment_withdrawn'] for t in call('GET',f'/interviews/{sid}/review')['turns'])
                result['checks'].append('user_correction_pause_resume_withdraw_control_original_history')
                removed=act(new_obs[0],'delete');assert removed['status']=='deleted' and removed['payload'] is None
                assert call('POST',f'/interviews/{new_sid}/learning-observations')['added']==0
                result['checks'].append('deleted_payload_scrubbed_and_not_recreated')
                if pid:
                    call('DELETE','/projects/'+pid,expected=204)
                    remaining=call('GET','/learning/observations')
                    assert all(i['status'] in ('invalid','withdrawn') and i['payload'] is None for i in remaining)
                    result['checks'].append('real_http_pg_project_delete_invalidates_learning_without_resurrection')
                result['status']='passed'
        except Exception as exc:
            result.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:500]);raise
        finally:
            if provider:result['model_calls']=list(provider.calls)
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            if bundle:
                import psycopg
                from psycopg import sql
                dsn=bundle.database.dsn;schema=bundle.database.schema;bundle.close()
                assert schema.startswith('s7_http_')
                with psycopg.connect(dsn,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    print(json.dumps({'status':result['status'],'checks':len(result['checks']),'model_calls':len(result.get('model_calls',[]))}))


if __name__=='__main__':main()
