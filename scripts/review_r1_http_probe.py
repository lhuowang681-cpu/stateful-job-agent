"""Actual loopback HTTP before/after source probe with explicit synthetic output.

Run in a fresh process against a genuine baseline archive or current source.
This verifies state and side effects, never real-model semantic quality.
"""
import argparse,json,socket,sys,threading,time,tempfile
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path


@contextmanager
def running(app):
    import uvicorn
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128)
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start();deadline=time.monotonic()+15
    try:
        while not server.started:
            if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError('probe_startup_failed')
            time.sleep(.02)
        yield 'http://127.0.0.1:'+str(sock.getsockname()[1])
    finally:
        server.should_exit=True;thread.join(5);sock.close()
        if thread.is_alive():raise RuntimeError('probe_shutdown_failed')


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--expectation',choices=['before','after'],required=True);p.add_argument('--commit-label',required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('refuse_overwrite_http_probe')
    source_root=a.source_root.resolve();sys.path[:0]=[str(source_root/'src'),str(source_root)]
    import httpx
    import job_agent.resume_workspace.api as api
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.interview_collaboration import InterviewEngine
    from job_agent.resume_workspace.interview_contracts import Evaluation
    from job_agent.llm.providers.mock import result_from_raw_output
    from job_agent.llm.provider import ProviderTimeoutError
    assert Path(api.__file__).resolve().is_relative_to(source_root/'src')
    good='幂等键记录执行标识，查询回执，不盲目重放。';unknown='这个问题我暂时不会回答。'
    class Provider:
        provider_name='synthetic-http-review-r1';model='fixture-not-real-model'
        def __init__(self,variant):self.variant=variant;self.calls=0
        def generate_structured(self,**kw):
            self.calls+=1
            if self.variant=='unknown':raise ProviderTimeoutError('synthetic unknown dispatch')
            if kw['output_schema'] is Evaluation:
                data={'covered_ids':['p0','p1','p2'],'missing_ids':[],'claim_needs_evidence':False,'recommended_action':'next','note':'Explicit synthetic before/after contract probe'}
                if self.variant!='omitted':
                    data['point_assessments']=[] if self.variant=='empty' else [
                        {'point_id':f'p{i}','status':'correct','answer_quote':quote,'reason':'Synthetic source-integrity probe'}
                        for i,quote in enumerate(('幂等键记录执行标识','查询回执','不盲目重放'))]
                    if self.variant=='partial':data['point_assessments']=[{'point_id':'p0','status':'correct','answer_quote':'不会','reason':'Synthetic incomplete probe'}]
            else:data={'action':'next'}
            return result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=json.dumps(data),output_schema=kw['output_schema'],trace=kw['trace'],latency_ms=1,input_tokens=3,output_tokens=3)
    report={'transport':'real_loopback_http','source_root':str(source_root),'source_commit_label':a.commit_label,
        'provider':'explicit synthetic contract fixture; not real model','expectation':a.expectation,'rows':[],'status':'running'}
    try:
        for variant in ('omitted','empty','partial','complete','unknown'):
            with tempfile.TemporaryDirectory(prefix='review-r1-http-') as folder:
                ws=SqliteResumeRepository(Path(folder)/'state.sqlite');provider=Provider(variant)
                app=api.create_resume_app(ws,resolve_identity={'r1-http-synthetic':'alice'}.get,interview_engine=InterviewEngine(provider),task_worker_enabled=False)
                with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer r1-http-synthetic'},trust_env=False,timeout=20) as c:
                    def post(path,body=None):return c.post('/api/v2'+path,json=body)
                    source=post('/sources',{'kind':'original_resume','label':'CC0 synthetic R1 probe','text':'姓名：合成同学\n项目经历\n原型 | 开发 | 2025\n- 使用 Python 开发本地原型接口。'}).json()
                    draft=post('/sources/'+source['source_id']+'/parse',{'mode':'local_rules'}).json()
                    version=post('/drafts/'+draft['draft_id']+'/accept',{'title':'Synthetic','expected_source_hash':source['content_hash'],'user_reviewed':True}).json()
                    view=post('/resumes/'+version['resume_id']+'/interviews',{'request_key':'r1-http-start','version_id':version['version_id'],
                        'expected_content_hash':version['content_hash'],'jd_text':'Checkpoint 恢复 幂等','mode':'llm','max_turns':2,'allow_external_processing':True}).json()
                    route='/interviews/'+view['session_id'];body={'request_key':'r1-http-answer','question_id':view['current']['question_id'],
                        'expected_revision':0,'answer':good if variant=='complete' else unknown,'allow_external_processing':True}
                    response=post(route+'/answers',body);after=response.json();calls=provider.calls
                    repeat=post(route+'/answers',body)
                    assert provider.calls==calls
                    finish=post(route+'/finish',{'expected_revision':after['revision']})
                    observations=post(route+'/learning-observations')
                    with ws._connection() as db:
                        count=db.execute('SELECT COUNT(*) FROM rw_learning_observations').fetchone()[0]
                        state=json.loads(db.execute('SELECT state_json FROM rw_interviews WHERE session_id=?',(view['session_id'],)).fetchone()[0])
                    row={'variant':variant,'http_status':response.status_code,'business_status':after['status'],'revision':after['revision'],
                        'turns':len(after['turns']),'current_unchanged':after['current']==view['current'],'error_code':after.get('error_code'),
                        'provider_calls':calls,'repeat_http':repeat.status_code,'repeat_dispatched':False,'finish_http':finish.status_code,
                        'materialize_http':observations.status_code,'observation_rows':count,'model_inflight':state['model_inflight']}
                    if variant=='unknown':
                        resume=post(route+'/resume',{'allow_external_processing':True});row['resume_http']=resume.status_code
                        assert resume.status_code==409 and provider.calls==1 and count==0 and after['revision']==0 and state['model_inflight']
                    expected_advance=variant=='complete' or (a.expectation=='before' and variant in ('omitted','empty'))
                    assert after['revision']==int(expected_advance) and count==(3 if expected_advance else 0),row
                    assert response.status_code==200
                    report['rows'].append(row)
        report['status']='passed'
    finally:
        report['source_files_sha256']={f.relative_to(source_root).as_posix():sha256(f.read_bytes()).hexdigest() for f in (source_root/'src').rglob('*.py')}
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'rows':report['rows']}))


if __name__=='__main__':main()
