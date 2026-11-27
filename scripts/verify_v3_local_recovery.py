"""Real localhost HTTP + child-worker crash/recovery using only public source."""
from pathlib import Path
from hashlib import sha256
from uuid import uuid4
from time import sleep,perf_counter
import argparse,json,subprocess,sys,os
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]


def serve(database,port):
    import uvicorn
    from scripts.demo_resume_workbench import build_demo_app
    uvicorn.run(build_demo_app(database,worker_enabled=False),host='127.0.0.1',port=port,access_log=False)


def verify():
    folder=ROOT/'output/demo-tmp'/('v3-recovery-'+uuid4().hex);folder.mkdir(parents=True)
    db=folder/'workspace.sqlite';port=8020
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    log=(folder/'service.log').open('w',encoding='utf-8')
    server=subprocess.Popen([sys.executable,__file__,'--serve',str(db),'--port',str(port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    headers={'Authorization':'Bearer job-agent-synthetic-demo-only-2026'}
    started=perf_counter()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers=headers,trust_env=False,timeout=15) as c:
            for _ in range(150):
                if server.poll() is not None:raise RuntimeError('verification_server_failed')
                try:
                    if c.get('/health/live').status_code==200:break
                except httpx.HTTPError:pass
                sleep(.1)
            else:raise RuntimeError('verification_server_timeout')
            p=c.post('/api/v2/projects',json={'name':'Public source recovery fixture','contribution':'Public Starlette reading, no authorship/runtime claim.'});p.raise_for_status();pid=p.json()['project_id']
            archive=(ROOT/'docs/demo/assets/starlette-public-0.46.2.zip').read_bytes()
            r=c.post(f'/api/v2/projects/{pid}/zip',content=archive);r.raise_for_status();snapshot=r.json()['current_snapshot']
            payload={'request_key':'live-recovery-fixed-key','snapshot_id':snapshot}
            r=c.post(f'/api/v2/projects/{pid}/index-tasks',json=payload);assert r.status_code==202
            task=r.json();assert task['status']=='QUEUED';tid=task['task_id']
            worker_args=[sys.executable,str(ROOT/'scripts/v3_task_worker.py'),'--database',str(db),'--once','--lease-seconds','2']
            failed=subprocess.run([*worker_args,'--crash-after-index'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=45,creationflags=flags)
            assert failed.returncode==70,failed.returncode
            middle=c.get(f'/api/v2/tasks/{tid}').json();assert middle['status']=='RUNNING' and middle['attempts']==1
            index=c.get(f'/api/v2/projects/{pid}/index',params={'snapshot':snapshot}).json();assert index['status']=='indexed'
            sleep(2.2)
            recovered=subprocess.run(worker_args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=45,creationflags=flags)
            assert recovered.returncode==0,recovered.returncode
            final=c.get(f'/api/v2/tasks/{tid}').json();assert final['status']=='SUCCEEDED' and final['attempts']==2
            assert c.post(f'/api/v2/projects/{pid}/index-tasks',json=payload).json()['task_id']==tid
            foreign=c.get(f'/api/v2/tasks/{tid}',headers={'Authorization':'Bearer job-agent-second-demo-user-2026'}).status_code
            assert foreign==404
            result={'scope':'real localhost HTTP and two independent worker processes; public source only',
                'archive_sha256':sha256(archive).hexdigest(),'queued':task['status'],'after_crash':middle['status'],
                'crashed_worker_exit_code':failed.returncode,'after_recovery':final['status'],'attempts':final['attempts'],
                'duplicate_request_same_task':True,'second_owner_status':foreign,
                'files_indexed':final['result']['files'],'symbols':final['result']['symbols'],
                'elapsed_seconds':round(perf_counter()-started,3),'model_calls':0,'pg_redis_used':False,
                'public_source_tests_executed':False,'fixture_directory':str(folder.relative_to(ROOT))}
            dest=ROOT/'docs/devlog/evidence/v3/f5-live-worker-recovery.json'
            dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
        log.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--serve',type=Path);parser.add_argument('--port',type=int,default=8020)
    args=parser.parse_args();serve(args.serve,args.port) if args.serve else verify()
