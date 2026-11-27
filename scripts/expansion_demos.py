"""Four bounded demos over the original API; CC0 synthetic only, no paid provider."""
import argparse,json,os,subprocess,sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic,sleep
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.expansion_baseline import running,TEXT,FILES


def main():
    p=argparse.ArgumentParser();p.add_argument('demo',choices=('rewrite','project-interview','insufficiency','recovery'))
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('preserve prior output; choose a new path')
    if a.demo=='recovery':
        # The same production worker/fault CLI; no second queue or fake ACK simulator.
        raise SystemExit(subprocess.call([sys.executable,str(ROOT/'scripts/expansion_stream_faults.py'),'--output',str(a.output)],cwd=ROOT))
    import httpx
    from job_agent.resume_workspace.api import create_resume_app
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.claim_audit import audit_claims
    from job_agent.resume_workspace.rewrite import hard_constraints
    from job_agent.knowledge.research_contract import write_new
    result={'demo':a.demo,'transport':'real_loopback_http','model':'disabled; rules only',
        'data':'CC0 synthetic only','human_quality':None,'checks':[],'traces':[],'status':'running'}
    sources={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for base in ('src','tests','scripts') for p in (ROOT/base).rglob('*.py')}
    result['source_identity']=sha256(json.dumps(sources,sort_keys=True).encode()).hexdigest()
    try:
        with TemporaryDirectory(prefix='s8-demo-') as folder:
            ws=SqliteResumeRepository(Path(folder)/'synthetic.sqlite');app=create_resume_app(ws,resolve_identity={'demo':'alice','other':'bob'}.get)
            with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer demo'},timeout=90) as c:
                def call(method,path,expected=200,**kw):
                    r=c.request(method,'/api/v2'+path,**kw);assert r.status_code==expected,(path,r.status_code)
                    return r.json() if expected!=204 else None
                source=call('POST','/sources',201,json={'kind':'original_resume','label':'CC0 synthetic','text':TEXT})
                draft=call('POST',f"/sources/{source['source_id']}/parse",201,json={'mode':'local_rules'})
                v=call('POST',f"/drafts/{draft['draft_id']}/accept",201,json={'title':'Synthetic demo','expected_source_hash':source['content_hash'],'user_reviewed':True})
                base={'version_id':v['version_id'],'expected_content_hash':v['content_hash']};rid=v['resume_id']
                if a.demo=='rewrite':
                    original=v['document']['projects'][0]['bullets'][0]['text'];normal=original.replace('使用','基于').replace('实现','开发')
                    bad=audit_claims(original,original+'显著提升求职成功率。')
                    assert not bad.acceptable and any(x.status=='unsupported' for x in bad.claims)
                    assert not hard_constraints(original,normal)
                    rw=call('POST',f'/resumes/{rid}/rewrites',201,json={**base,'request_key':'s8-demo-rewrite','source_path':'projects.0.bullets.0','jd_text':'Python 检索 实习'})
                    assert rw['status']=='awaiting_approval'
                    accepted=call('POST',f"/rewrites/{rw['run_id']}/decision",json={'action':'accept','expected_parent_version_id':v['version_id'],
                        'expected_draft_hash':rw['drafts'][-1]['draft_hash'],'user_reviewed':True})
                    assert accepted['rewrite']['independent_truth']=='not_verified' and not accepted['version']['confirmed_at']
                    result['traces'].append(call('GET',f"/rewrites/{rw['run_id']}/trace"))
                    result['checks']+=['unsupported_Chinese_outcome_rejected','normal_synonym_no_hard_violation','actual_API_approval_new_C1_original_retained']
                else:
                    project=call('POST','/projects',201,json={'name':'CC0 demo','license_note':'CC0-1.0'})
                    buf=BytesIO()
                    with ZipFile(buf,'w') as archive:
                        for name,text in {**FILES,'redis_ack.py':'def acknowledge(client, stream, group, message_id):\n    return client.xack(stream, group, message_id)\n'}.items():archive.writestr(name,text)
                    pid=project['project_id'];project=call('POST',f'/projects/{pid}/zip',201,content=buf.getvalue())
                    task=call('POST',f'/projects/{pid}/index-tasks',202,json={'request_key':'s8-demo-index','snapshot_id':project['current_snapshot']})
                    deadline=monotonic()+60
                    while task['status'] not in ('SUCCEEDED','FAILED'):
                        assert monotonic()<deadline;sleep(.05);task=call('GET','/tasks/'+task['task_id'])
                    assert task['status']=='SUCCEEDED';result['traces'].append(call('GET','/tasks/'+task['task_id']+'/trace'))
                    scope={'scope':'private_project','project_id':pid,'snapshot_id':project['current_snapshot']}
                    if a.demo=='insufficiency':
                        pack=call('POST','/evidence/retrieve',json={**scope,'query':'Redis acknowledge 我是否独立负责Redis架构？','claims':['本人主导Redis架构并显著提升求职成功率。']})
                        assert pack['answer_policy']=='needs_input' and all(x['status']=='insufficient_evidence' for x in pack['claim_assessments'])
                        result['pack_summary']={k:pack[k] for k in ('answer_policy','missing','usage','claim_assessments')}
                        assert 'Redis' not in call('GET',f"/resumes/{rid}/versions/{v['version_id']}")['document']['projects'][0]['bullets'][0]['text']
                        result['checks']+=['source_code_present_personal_contribution_still_unverified','no_resume_fact_invented','needs_input_instead_of_unsupported_result']
                    else:
                        interview=call('POST',f'/resumes/{rid}/interviews',201,json={**base,'request_key':'s8-demo-project-interview','jd_text':'save_receipt 回执与调用路径',
                            'use_retrieval':True,'track':'project','project_id':pid,'snapshot_id':project['current_snapshot']})
                        assert interview['current']['references']
                        result['traces'].append(call('GET','/interviews/'+interview['session_id']+'/trace'))
                        # Separate original technical interview demonstrates the concrete ACK counterexample.
                        view=call('POST',f'/resumes/{rid}/interviews',201,json={**base,'request_key':'s8-demo-ack','jd_text':'Checkpoint 恢复 幂等'})
                        first=view['current'];sid=view['session_id'];route='/interviews/'+sid
                        view=call('POST',route+'/answers',json={'request_key':'s8-demo-answer','question_id':first['question_id'],'expected_revision':0,
                            'answer':'事务和Redis使用幂等键记录执行标识，查询回执，不盲目重放。ACK保证业务只执行一次。'})
                        assert view['current']['followup']
                        call('POST',route+'/finish',json={'expected_revision':view['revision']})
                        review=call('GET',route+'/review');evaluation=review['assessment_details'][0]
                        assert evaluation['mode']=='deterministic_counterexample' and evaluation['points'][0]['status']=='incorrect'
                        observations=call('POST',route+'/learning-observations')['observations']
                        wrong=next(o for o in observations if o['payload']['finding']=='incorrect')
                        assert wrong['payload']['question_id']==first['question_id'] and wrong['independent_mastery']=='not_established'
                        result['traces'].append(call('GET',route+'/trace'))
                        result['checks']+=['project_question_bound_to_fixed_source','keyword_complete_wrong_ACK_forces_real_followup','completed_review_creates_source_linked_single_observation']
                for trace in result['traces']:
                    assert trace['replay_policy'].startswith('read_only_inspection')
                result['status']='passed'
    except BaseException as exc:
        result.update(status='failed',error_type=type(exc).__name__);raise
    finally:
        a.output.parent.mkdir(parents=True,exist_ok=True);write_new(a.output,result)
    print(json.dumps({'demo':a.demo,'status':result['status'],'checks':len(result['checks']),'traces':len(result['traces'])}),flush=True)


if __name__=='__main__':main()
