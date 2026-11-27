"""Run with python -I: prove installed package startup/auth/source HTTP paths."""
import json,socket,threading,time,tempfile,sys,os
from pathlib import Path
import httpx,uvicorn
import job_agent,fit_verdict_engine
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository


def main():
    output=Path(sys.argv[1])
    if output.exists():raise ValueError('refuse_overwrite')
    assert 'site-packages' in job_agent.__file__ and 'site-packages' in fit_verdict_engine.__file__
    result={'python':sys.version,'job_agent_location':job_agent.__file__,'fit_verdict_location':fit_verdict_engine.__file__,
        'isolated_mode':bool(sys.flags.isolated),'launcher':'--launcher' in sys.argv[2:],'checks':[],'status':'running'}
    server=None;thread=None
    try:
        with tempfile.TemporaryDirectory(prefix='installed-smoke-') as folder:
            ws=SqliteResumeRepository(Path(folder)/'synthetic.sqlite')
            token='synthetic-smoke'
            if result['launcher']:
                token='synthetic-installed-launcher-token-000000000'
                configuration={'JOB_AGENT_WORKSPACE_API_TOKEN':token,'JOB_AGENT_WORKSPACE_DB':str(ws.path),
                    'JOB_AGENT_PROJECT_BACKEND':'sqlite','JOB_AGENT_INDEX_DISPATCH':'polling',
                    'JOB_AGENT_WORKSPACE_ENABLE_LLM':'0','JOB_AGENT_WORKSPACE_EMBEDDING':'disabled','JOB_AGENT_WORKSPACE_RERANK_PATH':''}
                previous={k:os.environ.get(k) for k in configuration}
                try:
                    os.environ.update(configuration)
                    from job_agent.resume_workspace.main import create_app
                    app=create_app()
                finally:
                    for k,v in previous.items():
                        if v is None:os.environ.pop(k,None)
                        else:os.environ[k]=v
            else:app=create_resume_app(ws,resolve_identity={token:'alice'}.get,task_worker_enabled=False,demo_only=True)
            sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128);port=sock.getsockname()[1]
            server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
            thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
            deadline=time.monotonic()+15
            while not server.started:
                if not thread.is_alive() or time.monotonic()>deadline:
                    import traceback
                    result['thread_stacks']={str(k):traceback.format_stack(v) for k,v in sys._current_frames().items()}
                    raise RuntimeError('startup_failed')
                time.sleep(.05)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=10) as client:
                assert client.get('/api/v2/resumes').status_code==401
                result['checks'].append('anonymous_401')
                headers={'Authorization':'Bearer '+token}
                response=client.post('/api/v2/sources',headers=headers,json={'kind':'original_resume',
                    'label':'Synthetic installed smoke','text':'姓名：合成同学\n项目经历\n本地原型 | 开发 | 2025\n- 使用 Python 编写本地接口。'})
                assert response.status_code==201,response.text
                source=response.json()
                response=client.post(f"/api/v2/sources/{source['source_id']}/parse",headers=headers,json={'mode':'local_rules'})
                assert response.status_code==201,response.text
                draft=response.json()
                response=client.post(f"/api/v2/drafts/{draft['draft_id']}/accept",headers=headers,json={'title':'Synthetic',
                    'expected_source_hash':source['content_hash'],'user_reviewed':True})
                assert response.status_code==201,response.text
                assert client.get('/api/v2/resumes',headers=headers).status_code==200
                result['checks'].append('real_http_source_parse_accept_list')
                if result['launcher'] and Path('frontend/dist/index.html').is_file():
                    assert client.get('/').status_code==200
                    assets=[p for p in Path('frontend/dist').rglob('*') if p.is_file()]
                    for asset in assets:
                        response=client.get('/'+asset.relative_to('frontend/dist').as_posix())
                        assert response.status_code==200,asset.name
                        if asset.suffix=='.mjs':assert 'javascript' in response.headers.get('content-type','')
                    result['frontend_assets_checked']=len(assets)
                    result['checks'].append('all_bundled_frontend_assets_including_pdf_worker_200')
            server.should_exit=True;thread.join(5)
            assert not thread.is_alive(),'server_shutdown_timeout'
            result['status']='passed'
    except Exception as exc:result.update(status='failed',error_type=type(exc).__name__)
    finally:
        if server:server.should_exit=True
        if thread:thread.join(5)
        result['server_stopped']=not thread or not thread.is_alive()
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    if result['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
