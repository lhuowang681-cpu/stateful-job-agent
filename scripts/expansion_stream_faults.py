"""Real HTTP + independent processes + owned PG/Redis index fault matrix.

Uses synthetic source, dedicated test services only. Keeps per-case schemas as
replayable diagnostic evidence; never FLUSHDB, never deletes a global stream.
"""
import argparse,json,os,subprocess,sys
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import monotonic,sleep
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.expansion_baseline import running,FILES


def main():
    import httpx
    from job_agent.resume_workspace.postgres_projects import postgres_persistence,DB_NOW
    from job_agent.resume_workspace.repository import SqliteResumeRepository
    from job_agent.resume_workspace.api import create_resume_app
    from job_agent.resume_workspace.index_streams import IndexStreamQueue
    from job_agent.resume_workspace.code_rag import CodeRAGService
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--restart-owned-redis',action='store_true');args=parser.parse_args()
    if args.output.exists():parser.error('output exists')
    dsn=os.environ['JOB_AGENT_TEST_PROJECT_DSN'];redis_url=os.environ['JOB_AGENT_TEST_INDEX_REDIS_URL']
    result={'data':'authored CC0 synthetic, imported code not executed','transport':'real_loopback_http',
        'services':'real PostgreSQL + Redis','execution':'independent subprocesses with os._exit fault points',
        'model':'disabled; index execution replay only, no text-model replay','cases':[],'status':'running'}
    source={p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for b in ('src','tests','scripts') for p in (ROOT/b).rglob('*.py') if '__pycache__' not in p.parts}
    result['source_identity']=sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        temp=args.output.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2));temp.replace(args.output)
    save()

    scenarios=['request_idempotency_conflict','redis_unavailable_then_restore','publisher_exit_after_xadd',
        'worker_exit_after_claim','old_worker_late_after_takeover','two_workers_compete','commit_before_ack_exit',
        'transaction_exit_after_derived','source_deleted_during_build','recovery_exhausted',
        'malformed_unknown_and_permanent_failure','queue_deleted_reconcile']
    if args.restart_owned_redis:scenarios.append('owned_redis_restart')
    for case in scenarios:
        schema='s6_fault_'+uuid4().hex
        row={'case':case,'schema':schema,'status':'running','processes':[],'checks':[]};result['cases'].append(row);save()
        folder=ROOT/'output/expansion'/schema;folder.mkdir(parents=True,exist_ok=False)
        bundle=postgres_persistence(dsn,schema=schema,dispatch_mode='redis',lease_seconds=.3)
        ws=SqliteResumeRepository(folder/'resume.sqlite')
        queue=IndexStreamQueue(redis_url,bundle.tasks.dispatch.authority);queue.ensure_group()
        app=create_resume_app(ws,resolve_identity={'synthetic-a':'alice','synthetic-b':'bob'}.get,
            project_persistence=bundle,task_worker_enabled=False)
        child_env={**os.environ,'JOB_AGENT_PROJECT_BACKEND':'postgresql','JOB_AGENT_PROJECT_DSN':dsn,
            'JOB_AGENT_PROJECT_SCHEMA':schema,'JOB_AGENT_INDEX_DISPATCH':'redis','JOB_AGENT_INDEX_REDIS_URL':redis_url,
            'JOB_AGENT_WORKSPACE_EMBEDDING':'disabled','JOB_AGENT_WORKSPACE_RERANK_PATH':''}
        children=[];logs=[]
        def query(statement,params=()):
            with bundle.database._connection(write=True) as db:
                cursor=db.execute(statement,params);return list(cursor) if cursor.description else []
        def launch(role='work',extra=(),*,wait=True,env_overrides=None):
            logpath=folder/f'process-{len(row["processes"])}.log';log=logpath.open('w');logs.append(log)
            command=[sys.executable,str(ROOT/'scripts/v3_index_dispatch.py'),role,'--once','--database',str(folder/'child-resume.sqlite'),
                '--lease-seconds','.3','--min-idle-ms','0',*extra]
            proc=subprocess.Popen(command,cwd=ROOT,env={**child_env,**(env_overrides or {})},stdout=log,stderr=subprocess.STDOUT)
            children.append(proc);record={'pid':proc.pid,'role':role,'arguments':list(extra),'log':str(logpath.relative_to(ROOT))};row['processes'].append(record);save()
            if wait:
                code=proc.wait(timeout=30);log.flush();record['exit_code']=code;save();return code
            return proc,record
        def wait_for(predicate,timeout=8):
            end=monotonic()+timeout
            while not predicate():
                if monotonic()>end:raise RuntimeError('condition_observation_timeout; inspect live children before retrying')
                sleep(.025)
        try:
            with running(app) as url,httpx.Client(base_url=url,headers={'Authorization':'Bearer synthetic-a'},timeout=20) as client:
                def call(method,path,**kw):
                    response=client.request(method,path,**kw);assert response.status_code<400,(path,response.status_code,response.text[:180]);return response.json() if response.content else None
                p=call('POST','/api/v2/projects',json={'name':'CC0 '+case,'license_note':'CC0-1.0'})
                from io import BytesIO
                from zipfile import ZipFile
                zipped=BytesIO()
                with ZipFile(zipped,'w') as z:
                    for name,text in FILES.items():z.writestr(name,text)
                pid=p['project_id'];p=call('POST',f'/api/v2/projects/{pid}/zip',content=zipped.getvalue());snapshot=p['current_snapshot']
                row.update(project_id=pid,snapshot_id=snapshot,authority=bundle.tasks.dispatch.authority)
                body={'snapshot_id':snapshot,'request_key':'fault-index-request'}
                task=call('POST',f'/api/v2/projects/{pid}/index-tasks',json=body);tid=task['task_id'];row['task_id']=tid;save()
                def current():return call('GET',f'/api/v2/tasks/{tid}')
                def count_publications():return query('SELECT COUNT(*) AS n FROM v3_index_publications')[0]['n']
                def expire_wait():wait_for(lambda:query(f'SELECT lease_until<={DB_NOW} AS expired FROM v3_tasks WHERE task_id=%s',(tid,))[0]['expired'])

                if case=='request_idempotency_conflict':
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(2) as pool:repeated=list(pool.map(lambda _:call('POST',f'/api/v2/projects/{pid}/index-tasks',json=body)['task_id'],range(2)))
                    assert repeated==[tid,tid]
                    newer=call('POST',f'/api/v2/projects/{pid}/documents',json={'path':'new.md','text':'# New snapshot\n'})
                    conflict=client.post(f'/api/v2/projects/{pid}/index-tasks',json={**body,'snapshot_id':newer['current_snapshot']});assert conflict.status_code==409
                    assert query('SELECT COUNT(*) AS n FROM v3_index_outbox')[0]['n']==1
                    row['checks']+=['real_HTTP_concurrent_same_key_same_task','different_snapshot_same_key_409','one_outbox']
                elif case=='redis_unavailable_then_restore':
                    # A genuinely unreachable socket, not a mocked Redis response.
                    assert launch('publish',env_overrides={'JOB_AGENT_INDEX_REDIS_URL':'unix:///tmp/job-agent-v3-not-listening.sock'})!=0
                    assert current()['status']=='QUEUED' and query('SELECT published_at FROM v3_index_outbox')[0]['published_at'] is None
                    row['checks'].append('PG_commit_survives_unreachable_real_transport')
                elif case=='publisher_exit_after_xadd':
                    assert launch('publish',['--fault','after_xadd_before_outbox_mark'])==71
                    assert queue.retained_entries()==1 and query('SELECT published_at FROM v3_index_outbox')[0]['published_at'] is None
                    # Real publisher lease expiry, no resetting the DB clock.
                    wait_for(lambda:query(f'SELECT publisher_until<={DB_NOW} AS expired FROM v3_index_outbox')[0]['expired'],timeout=15)
                    row['checks'].append('actual_publisher_exit_after_XADD_before_DB_mark')
                else:
                    assert launch('publish')==0

                if case in ('worker_exit_after_claim','transaction_exit_after_derived'):
                    baseline=0
                    fault='after_claim' if case=='worker_exit_after_claim' else 'after_derived_before_pointer'
                    assert launch('work',['--fault',fault])==71
                    assert current()['status']=='RUNNING' and count_publications()==baseline
                    expire_wait();assert launch()==0
                    assert current()['attempts']==2
                    row['checks'].append('actual_process_exit_lease_expiry_recovery_no_partial_publication')
                elif case in ('old_worker_late_after_takeover','two_workers_compete'):
                    extra=['--hold-after-claim','2']
                    if case=='two_workers_compete':extra+=['--lease-seconds','3']
                    a,ar=launch(extra=extra,wait=False)
                    wait_for(lambda:current()['status']=='RUNNING');assert a.poll() is None
                    if case=='old_worker_late_after_takeover':expire_wait()
                    assert launch()==0
                    assert a.poll() is None # B observed while A is a real live process.
                    if case=='old_worker_late_after_takeover':assert current()['status']=='SUCCEEDED'
                    ar['exit_code']=a.wait(timeout=20);assert ar['exit_code']==0
                    assert current()['status']=='SUCCEEDED'
                    assert current()['attempts']==(2 if case=='old_worker_late_after_takeover' else 1)
                    row['checks'].append('two_observed_live_PIDs_and_DB_fencing')
                elif case=='commit_before_ack_exit':
                    assert launch('work',['--fault','after_commit_before_ack'])==71
                    assert current()['status']=='SUCCEEDED' and queue.pending()==1
                    assert launch()==0 and queue.pending()==0
                    row['checks'].append('actual_commit_before_ACK_exit_redelivery_no_rebuild')
                elif case=='source_deleted_during_build':
                    proc,record=launch(extra=['--hold-after-claim','1'],wait=False)
                    wait_for(lambda:current()['status']=='RUNNING');assert proc.poll() is None
                    call('DELETE',f'/api/v2/projects/{pid}')
                    record['exit_code']=proc.wait(timeout=20);assert record['exit_code']==0
                    assert query('SELECT COUNT(*) AS n FROM v3_tasks')[0]['n']==0 and count_publications()==0
                    assert queue.pending()==0
                    row['checks'].append('source_deleted_after_real_claim_no_zombie_rows')
                elif case=='recovery_exhausted':
                    for _ in range(3):
                        assert launch('work',['--fault','after_claim'])==71;expire_wait()
                    assert launch()==0 and current()['error_code']=='worker_recovery_exhausted'
                    assert current()['attempts']==3 and count_publications()==0 and queue.pending()==0
                    row['checks'].append('three_real_process_crashes_bounded_terminal_archive')
                elif case=='malformed_unknown_and_permanent_failure':
                    query("UPDATE v3_project_files SET text='synthetic corrupted source'")
                    assert launch()==0 and current()['status']=='FAILED'
                    assert count_publications()==0
                    queue._redis.xadd(queue.stream_name,{'private_body':'SYNTHETIC_NOT_TO_ARCHIVE'})
                    queue._redis.xadd(queue.stream_name,{'authority':bundle.tasks.dispatch.authority,'task_id':'task-'+uuid4().hex,'event_id':'wake-'+uuid4().hex,'generation':'1'})
                    assert launch()==0 and launch()==0 and queue.pending()==0
                    assert 'SYNTHETIC_NOT_TO_ARCHIVE' not in json.dumps(bundle.tasks.dispatch.monitoring())
                    row['checks'].append('real_bad_unknown_and_integrity_failure_durable_safe_archive')
                elif case=='queue_deleted_reconcile':
                    queue._redis.delete(queue.stream_name);queue.ensure_group()
                    sleep(.15)
                    assert launch('reconcile',['--reconcile-age','.1'])==0
                    row['checks'].append('own_stream_deleted_PG_explicit_reconciliation')
                elif case=='owned_redis_restart':
                    config=ROOT/'output/expansion/redis-s6/redis.conf';pidfile=config.parent/'redis.pid'
                    expected_pid=int(pidfile.read_text());actual_pid=queue._redis.info('server')['process_id'];assert actual_pid==expected_pid
                    assert queue._redis.config_get('port')['port']=='0'
                    queue._redis.shutdown(nosave=True);queue.close()
                    server=ROOT/'output/deps/redis-7.2.16/src/redis-server'
                    subprocess.run([str(server),str(config)],check=True)
                    queue=IndexStreamQueue(redis_url,bundle.tasks.dispatch.authority)
                    def ready():
                        from redis.exceptions import RedisError
                        try:return queue.ping()
                        except RedisError:return False
                    wait_for(ready);queue.ensure_group()
                    row['redis_restart']={'old_pid':expected_pid,'new_pid':queue._redis.info('server')['process_id'],'only_owned_unix_socket':True}
                    assert row['redis_restart']['new_pid']!=expected_pid
                    row['checks'].append('real_owned_Redis_restart_AOF_group_and_message_survived')

                if case not in ('source_deleted_during_build','recovery_exhausted','malformed_unknown_and_permanent_failure'):
                    if current()['status']!='SUCCEEDED':
                        assert launch('publish')==0;assert launch()==0
                    # Duplicate publish case leaves another entry to ACK, never rebuild.
                    for _ in range(3):
                        if queue.pending()==0 and queue.depth()==0:break
                        assert launch()==0
                    assert current()['status']=='SUCCEEDED' and count_publications()==1
                    found=call('POST',f'/api/v2/projects/{pid}/search',json={'snapshot_id':snapshot,'query':'save_receipt callers'})
                    assert found['hits']
                    assert client.get(f'/api/v2/tasks/{tid}',headers={'Authorization':'Bearer synthetic-b'}).status_code==404
                    row['checks']+=['exactly_one_effective_publication','original_HTTP_task_search_and_cross_owner_404']
                    row['task']=current()
                if case=='source_deleted_during_build':
                    assert client.get(f'/api/v2/tasks/{tid}/trace').status_code==404
                    row['trace_status']='source_cascade_deleted_404'
                else:
                    row['trace']=call('GET',f'/api/v2/tasks/{tid}/trace')
                    assert any(e['source_stream']=='task_events' for e in row['trace']['events'])
                assert client.get(f'/api/v2/tasks/{tid}/trace',headers={'Authorization':'Bearer synthetic-b'}).status_code==404
                row['checks'].append('read_only_unified_trace_real_PG_events_and_owner_gate')
                row['stream']=queue.monitoring();row['database']=bundle.tasks.dispatch.monitoring();row['publication_count']=count_publications()
                row['status']='passed';save();print(json.dumps({'case':case,'status':'passed'}),flush=True)
        except BaseException as exc:
            row['status']='failed';row['failure_type']=type(exc).__name__;result['status']='failed';save();raise
        finally:
            for proc in children:
                if proc.poll() is None:
                    # Explicitly terminate only our recorded probe child after a failed case.
                    proc.terminate();proc.wait(timeout=5)
            for log in logs:log.close()
            queue.close();bundle.close()
    result['status']='passed';save()
    print(json.dumps({'cases':len(result['cases']),'status':result['status']}),flush=True)


if __name__=='__main__':main()
