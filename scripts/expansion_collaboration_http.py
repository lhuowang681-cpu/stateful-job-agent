"""Real loopback HTTP and offline generation on authored C1 synthetic inputs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from hashlib import sha256
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from expansion_baseline import running

TEXT='姓名：合成同学\n项目经历\nAgent 原型 | 开发 | 2025\n- 我使用 Python 开发本地原型接口。'


def run(provider):
    import httpx
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.parsing import ResumeParser
    from job_agent.resume_workspace.api import create_resume_app
    result={'transport':'real_loopback_http','generation':'real_offline_text_model','data':'authored_synthetic_C1_only',
        'model':provider.identity,'human_quality':None,'checks':[]}
    with TemporaryDirectory(prefix='s4-real-roles-') as folder:
        ws=SqliteResumeRepository(Path(folder)/'state.sqlite')
        app=create_resume_app(ws,resolve_identity={'synthetic-a':'alice','synthetic-b':'bob'}.get,
            parser=ResumeParser(provider),task_worker_enabled=False,demo_only=True)
        with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer synthetic-a'},timeout=180) as client:
            def call(method,path,**kwargs):
                response=client.request(method,path,**kwargs)
                if response.status_code>=400:raise RuntimeError(f'http_{response.status_code}')
                return response.json()
            source=call('POST','/api/v2/sources',json={'kind':'original_resume','label':'CC0 synthetic','text':TEXT})
            draft=call('POST',f"/api/v2/sources/{source['source_id']}/parse",json={'mode':'local_rules'})
            version=call('POST',f"/api/v2/drafts/{draft['draft_id']}/accept",json={'title':'Synthetic roles',
                'expected_source_hash':source['content_hash'],'user_reviewed':True})
            rid=version['resume_id'];result['original_version']=version
            rewrite=call('POST',f'/api/v2/resumes/{rid}/rewrites',json={'request_key':'s4-http-rewrite',
                'version_id':version['version_id'],'expected_content_hash':version['content_hash'],'source_path':'projects.0.bullets.0',
                'jd_text':'Python Agent 实习；清晰表达已有工作，保留本地原型范围。','mode':'llm','allow_external_processing':True})
            result['rewrite']=rewrite
            decision={'action':'accept','expected_parent_version_id':version['version_id'],
                'expected_draft_hash':rewrite['drafts'][-1]['draft_hash'],'user_reviewed':True} if rewrite['drafts'] else None
            if rewrite['status']=='awaiting_approval':
                assert rewrite['drafts'][-1]['claim_audit']['acceptable']
                accepted=call('POST',f"/api/v2/rewrites/{rewrite['run_id']}/decision",json=decision)
                result['approval']=accepted
                assert accepted['rewrite']['independent_truth']=='not_verified' and not accepted['version']['confirmed_at']
                result['checks'].append('accepted_rewrite_is_new_C1_not_verified_truth')
            elif decision:
                assert client.post(f"/api/v2/rewrites/{rewrite['run_id']}/decision",json=decision).status_code==409
                result['checks'].append('nonapproved_rewrite_cannot_be_accepted')
            assert ws.get_version('alice',rid,version['version_id']).content_hash==version['content_hash']
            result['checks'].append('original_version_unchanged')
            interview=call('POST',f'/api/v2/resumes/{rid}/interviews',json={'request_key':'s4-http-interview',
                'version_id':version['version_id'],'expected_content_hash':version['content_hash'],
                'jd_text':'Checkpoint 恢复和外部请求幂等。','mode':'llm','allow_external_processing':True})
            before=interview['current'];sid=interview['session_id'];route=f'/api/v2/interviews/{sid}'
            after=call('POST',route+'/answers',json={'request_key':'s4-http-answer','question_id':before['question_id'],
                'expected_revision':0,'answer':'我会用幂等键记录执行标识，目前还不清楚超时后如何核对外部操作。','allow_external_processing':True})
            assert 'execution' not in after and 'point_assessments' not in json.dumps(after)
            assert client.get(route+'/review').status_code==409
            assert client.get(route,headers={'Authorization':'Bearer synthetic-b'}).status_code==404
            with ws._connection() as db:
                state=json.loads(db.execute('SELECT state_json FROM rw_interviews WHERE session_id=?',(sid,)).fetchone()[0])
            result['interview']={'before':before,'after':after,'internal_synthetic_state':state}
            if after['status']=='active':
                result['checks'].append('real_evaluator_interviewer_changed_next_question' if after['current']['prompt']!=before['prompt'] else 'real_roles_kept_question')
                call('POST',route+'/finish',json={'expected_revision':after['revision']})
                result['review']=call('GET',route+'/review')
            else:result['checks'].append('role_failure_saved_without_hidden_success')
            result['checks']+=['active_view_no_rubric_or_internal_state','second_owner_404','review_completion_gate']
    result['provider_history']=[dict(c) for c in provider.calls]
    return result


def main():
    global TEXT
    parser=argparse.ArgumentParser();parser.add_argument('--model-path',required=True);parser.add_argument('--device',default='cuda:0')
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--positive-control',action='store_true');args=parser.parse_args()
    if args.positive_control:TEXT='姓名：合成同学\n项目经历\nAgent 原型 | 开发 | 2025\n- 我参与了本地原型开发。我使用 Python 开发接口。'
    if args.output.exists():raise ValueError('refuse_overwrite_http_evidence')
    from job_agent.llm.providers.local_text import OfflineTextProvider
    start=monotonic();provider=OfflineTextProvider(args.model_path,device=args.device,capture_synthetic_outputs=True)
    result=run(provider);result['total_ms']=round((monotonic()-start)*1000,2)
    result['posthoc_positive_control']=args.positive_control
    result['source_identity']=sha256(json.dumps({p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
        for base in ('src','tests','scripts') for p in (ROOT/base).rglob('*.py') if '__pycache__' not in p.parts},sort_keys=True).encode()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(result['checks']),'calls':len(provider.calls),'rewrite_status':result['rewrite']['status'],
        'interview_status':result['interview']['after']['status']}))


if __name__=='__main__':main()
