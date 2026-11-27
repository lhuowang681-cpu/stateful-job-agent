"""Opt-in REAL PostgreSQL/Redis contracts; fixture source is never executed."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import json,os
from time import sleep
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.postgres_projects import postgres_persistence,DB_NOW
from job_agent.resume_workspace.long_term import ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery
from job_agent.resume_workspace.tasks import IndexTaskRequest,IndexTaskWorker
from job_agent.resume_workspace.index_dispatch import IndexOutboxPublisher,RedisIndexWorker,decode_delivery
from job_agent.resume_workspace.index_streams import IndexStreamQueue


@pytest.fixture
def env(tmp_path):
    dsn=os.environ.get('JOB_AGENT_TEST_PROJECT_DSN');url=os.environ.get('JOB_AGENT_TEST_INDEX_REDIS_URL')
    if not dsn or not url:pytest.skip('real dedicated PostgreSQL and Redis required')
    schema='s6_test_'+uuid4().hex
    bundle=postgres_persistence(dsn,schema=schema,dispatch_mode='redis',lease_seconds=2)
    ws=SqliteResumeRepository(tmp_path/'resume.sqlite')
    code=CodeRAGService(ws,projects=bundle.projects,indexes=bundle.indexes);bundle.tasks.config_identity=code.indexing_config_identity
    p=bundle.projects.create_project('alice',ProjectCreate(name='CC0 Streams contract'))
    p=bundle.projects.publish_files('alice',p['project_id'],{'receipt.py':'def receipt(key, store):\n    return store.setdefault(key, "done")\n'},origin='zip')
    queue=IndexStreamQueue(url,bundle.tasks.dispatch.authority);queue.ensure_group()
    yield ws,bundle,p,code,queue
    queue._redis.delete(queue.stream_name);queue.close();bundle.close()
    import psycopg
    from psycopg import sql
    with psycopg.connect(dsn,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def submit(env,key='streams-contract-index'):
    _,b,p,_,_=env
    return b.tasks.submit('alice',p['project_id'],IndexTaskRequest(snapshot_id=p['current_snapshot'],request_key=key))


def worker(env,**kw):
    _,b,_,code,q=env
    return RedisIndexWorker(b.tasks,code,q,consumer='test-'+uuid4().hex,min_idle_ms=0,**kw)


def publish(env):
    return IndexOutboxPublisher(env[1].tasks.dispatch,env[4]).publish_once()


def sql(env,statement,args=()):
    with env[1].database._connection(write=True) as db:return _execute(db,statement,args)


def _execute(db,statement,args):
    cursor=db.execute(statement,args)
    return list(cursor) if cursor.description else []


def publications(env):
    return sql(env,'SELECT COUNT(*) AS n FROM v3_index_publications')[0]['n']


def test_task_and_outbox_are_one_atomic_idempotent_request(env,monkeypatch):
    b=env[1];dispatch=b.tasks.dispatch
    with ThreadPoolExecutor(2) as pool:ids=list(pool.map(lambda _:submit(env),range(2)))
    assert ids[0]==ids[1]
    assert sql(env,'SELECT COUNT(*) AS n FROM v3_tasks')[0]['n']==1
    assert sql(env,'SELECT COUNT(*) AS n FROM v3_index_outbox')[0]['n']==1
    old_generation=sql(env,'SELECT desired_generation FROM v3_project_snapshots')[0]['desired_generation']
    original=dispatch.enqueue
    def broken(db,tid,generation):original(db,tid,generation);raise OSError('synthetic transaction failure')
    monkeypatch.setattr(dispatch,'enqueue',broken)
    with pytest.raises(OSError):submit(env,'atomic-rollback-request')
    assert sql(env,'SELECT COUNT(*) AS n FROM v3_tasks')[0]['n']==1
    assert sql(env,'SELECT COUNT(*) AS n FROM v3_index_outbox')[0]['n']==1
    assert sql(env,'SELECT desired_generation FROM v3_project_snapshots')[0]['desired_generation']==old_generation


def test_original_http_queues_pg_outbox_and_external_worker_reads_source(env):
    ws,b,_,_,_=env
    app=create_resume_app(ws,resolve_identity={'synthetic-a':'alice','synthetic-b':'bob'}.get,project_persistence=b,task_worker_enabled=False)
    with TestClient(app) as client:
        headers={'Authorization':'Bearer synthetic-a'}
        created=client.post('/api/v2/projects',headers=headers,json={'name':'HTTP Streams project'});assert created.status_code==201
        pid=created.json()['project_id']
        p=client.post(f'/api/v2/projects/{pid}/documents',headers=headers,json={'path':'README.md','text':'# Receipt service\n'}).json()
        response=client.post(f'/api/v2/projects/{pid}/index-tasks',headers=headers,json={'request_key':'http-streams-index','snapshot_id':p['current_snapshot']})
        assert response.status_code==202,response.text
        tid=response.json()['task_id'];assert publish(env)==1
        assert worker(env).process_once()=='SUCCEEDED'
        assert client.get(f'/api/v2/tasks/{tid}',headers=headers).json()['status']=='SUCCEEDED'
        assert client.get(f'/api/v2/tasks/{tid}',headers={'Authorization':'Bearer synthetic-b'}).status_code==404
        assert client.post(f'/api/v2/projects/{pid}/search',headers=headers,json={'snapshot_id':p['current_snapshot'],'query':'Receipt'}).json()['hits']
    assert app.state.index_worker is None
    with ws._connection() as db:assert db.execute('SELECT COUNT(*) FROM v3_projects').fetchone()[0]==0


def test_redis_outage_keeps_outbox_then_recovers(env):
    from redis.exceptions import RedisError
    tid=submit(env);b=env[1]
    bad=IndexStreamQueue('unix:///tmp/job-agent-v3-never-created-s6.sock',b.tasks.dispatch.authority)
    try:assert IndexOutboxPublisher(b.tasks.dispatch,bad).publish_once()==0
    finally:bad.close()
    row=sql(env,'SELECT * FROM v3_index_outbox')[0]
    assert row['published_at'] is None and row['error_code']=='redis_unavailable'
    assert b.tasks.get('alice',tid)['status']=='QUEUED'
    sql(env,f'UPDATE v3_index_outbox SET available_at={DB_NOW}-1')
    assert publish(env)==1 and worker(env).process_once()=='SUCCEEDED'


def test_xadd_before_outbox_mark_duplicate_has_one_publication(env):
    submit(env)
    class Crash(BaseException):pass
    def fail(stage):raise Crash()
    with pytest.raises(Crash):IndexOutboxPublisher(env[1].tasks.dispatch,env[4],failpoint=fail).publish_once()
    sql(env,'UPDATE v3_index_outbox SET publisher_until=0')
    assert publish(env)==1
    assert worker(env).process_once()=='SUCCEEDED'
    assert worker(env).process_once()=='SUCCEEDED'
    assert publications(env)==1 and env[4].pending()==0 and env[4].retained_entries()==2


def test_two_consumers_compete_then_stale_attempt_is_fenced(env):
    tid=submit(env);publish(env);b=env[1];q=env[4]
    first=q.receive(consumer_name='A',block_ms=1)
    kind,a=b.tasks.dispatch.claim_delivery(first.message);assert kind=='claimed'
    assert b.tasks.dispatch.claim_delivery(first.message)[0]=='busy'
    sql(env,f'UPDATE v3_tasks SET lease_until={DB_NOW}-1')
    kind,b_claim=b.tasks.dispatch.claim_delivery(first.message);assert kind=='claimed' and b_claim['attempts']==2
    env[3].build('alice',a['project_id'],a['snapshot_id'],task_claim=b_claim)
    before=b.tasks.get('alice',tid)['result']
    with pytest.raises(WorkspaceConflict,match='lease_lost'):env[3].build('alice',a['project_id'],a['snapshot_id'],task_claim=a)
    assert b.tasks.get('alice',tid)['result']==before and publications(env)==1
    assert worker(env).process_once()=='SUCCEEDED' and q.pending()==0


def test_commit_before_ack_recovers_without_rebuild(env):
    tid=submit(env);publish(env)
    class Crash(BaseException):pass
    def fault(stage):
        if stage=='after_commit_before_ack':raise Crash()
    with pytest.raises(Crash):worker(env,failpoint=fault).process_once()
    assert env[1].tasks.get('alice',tid)['status']=='SUCCEEDED' and env[4].pending()==1
    assert worker(env).process_once()=='SUCCEEDED'
    assert publications(env)==1 and env[4].pending()==0


def test_source_deleted_during_build_cannot_resurrect_rows(env,monkeypatch):
    submit(env);publish(env);b=env[1];original=b.projects.files
    def delete_after_read(owner,pid,snapshot):
        files=original(owner,pid,snapshot);b.projects.delete_project(owner,pid);return files
    monkeypatch.setattr(b.projects,'files',delete_after_read)
    assert worker(env).process_once()=='task_deleted'
    assert publications(env)==0 and sql(env,'SELECT COUNT(*) AS n FROM v3_tasks')[0]['n']==0
    assert sql(env,'SELECT reason FROM v3_dispatch_archive')[0]['reason']=='task_deleted'
    assert env[4].pending()==0


def test_execution_retry_and_crash_recovery_have_bounds(env,monkeypatch):
    tid=submit(env);publish(env)
    def fail(*args,**kwargs):raise OSError('synthetic transient failure')
    monkeypatch.setattr(env[3],'build',fail)
    w=worker(env)
    for i in range(3):
        outcome=w.process_once();assert outcome==('FAILED' if i==2 else 'QUEUED')
        sql(env,f'UPDATE v3_index_outbox SET available_at={DB_NOW}-1')
    task=env[1].tasks.get('alice',tid)
    assert task['attempts']==3 and task['error_code']=='index_retry_exhausted'
    assert env[4].pending()==0 and publications(env)==0


def test_expired_claims_stop_at_three_and_permanent_integrity_failure(env):
    tid=submit(env);publish(env);q=env[4];delivery=q.receive(consumer_name='A',block_ms=1)
    for _ in range(3):
        assert env[1].tasks.dispatch.claim_delivery(delivery.message)[0]=='claimed'
        sql(env,f'UPDATE v3_tasks SET lease_until={DB_NOW}-1')
    assert worker(env).process(delivery)=='FAILED'
    assert env[1].tasks.get('alice',tid)['error_code']=='worker_recovery_exhausted'
    assert q.pending()==0


def test_send_exhaustion_is_visible_terminal_not_infinite_pending(env):
    tid=submit(env);d=env[1].tasks.dispatch
    bad=IndexStreamQueue('unix:///tmp/job-agent-v3-never-created-s6.sock',d.authority)
    try:
        for i in range(12):
            assert IndexOutboxPublisher(d,bad).publish_once()==0
            if i<11:assert env[1].tasks.get('alice',tid)['status']=='QUEUED'
            sql(env,f'UPDATE v3_index_outbox SET available_at={DB_NOW}-1')
    finally:bad.close()
    assert env[1].tasks.get('alice',tid)['error_code']=='dispatch_retry_exhausted'
    assert d.monitoring()['outbox']['exhausted']==1 and d.monitoring()['dispatch_failures']
    assert sql(env,'SELECT send_attempts FROM v3_index_outbox')[0]['send_attempts']==12


def test_queue_loss_reconciliation_restores_only_unfinished_tasks(env):
    tid=submit(env);publish(env);q=env[4]
    q._redis.delete(q.stream_name);q.ensure_group()
    sql(env,f'UPDATE v3_index_outbox SET published_at={DB_NOW}-100')
    assert env[1].tasks.dispatch.reconcile(age_seconds=.1)==1
    assert publish(env)==1 and worker(env).process_once()=='SUCCEEDED'
    sql(env,f'UPDATE v3_index_outbox SET published_at={DB_NOW}-100')
    assert env[1].tasks.dispatch.reconcile(age_seconds=.1)==0 and publications(env)==1


def test_bad_unknown_and_foreign_messages_archive_without_private_body(env):
    q=env[4];authority=env[1].tasks.dispatch.authority
    bodies=[{'private_source':'SYNTHETIC_DO_NOT_PERSIST_BODY'},
        {'authority':authority,'event_id':'wake-'+uuid4().hex,'task_id':'task-'+uuid4().hex,'generation':'1'},
        {'authority':'authority-'+uuid4().hex,'event_id':'wake-'+uuid4().hex,'task_id':'task-'+uuid4().hex,'generation':'1'}]
    for body in bodies:q._redis.xadd(q.stream_name,body)
    w=worker(env);assert [w.process_once() for _ in bodies]==['invalid_message','unknown_task','rejected_event']
    archives=env[1].tasks.dispatch.monitoring()['archive'];assert len(archives)==3
    assert 'SYNTHETIC_DO_NOT_PERSIST_BODY' not in json.dumps(archives) and q.pending()==0


def test_modes_are_persisted_and_old_processes_stop_after_switch(env):
    ws,b,_,code,_=env
    with pytest.raises(WorkspaceConflict,match='polling_worker_disabled'):IndexTaskWorker(b.tasks,code)
    with pytest.raises(WorkspaceConflict,match='independent_worker'):create_resume_app(ws,resolve_identity=lambda _: 'alice',project_persistence=b)
    with pytest.raises(WorkspaceConflict,match='mode_conflict'):postgres_persistence(b.database.dsn,schema=b.database.schema)
    tid=submit(env)
    with pytest.raises(WorkspaceConflict,match='quiesced'):b.tasks.dispatch.change_mode('polling')
    b.tasks.cancel('alice',tid);b.tasks.dispatch.change_mode('polling')
    with pytest.raises(WorkspaceConflict,match='mode_changed'):b.tasks.dispatch.take_pending()
    reopened=postgres_persistence(b.database.dsn,schema=b.database.schema)
    try:
        assert reopened.tasks.claim() is None
        reopened.tasks.dispatch.change_mode('redis')
        with pytest.raises(WorkspaceConflict,match='mode_changed'):b.tasks.dispatch.take_pending()
        with pytest.raises(WorkspaceConflict,match='mode_changed'):reopened.tasks.claim()
    finally:reopened.close()


def test_long_build_renews_database_lease(env,monkeypatch):
    tid=submit(env);env[1].tasks.lease_seconds=.3;publish(env);original=env[3].build
    def slow(*args,**kwargs):sleep(.75);return original(*args,**kwargs)
    monkeypatch.setattr(env[3],'build',slow)
    assert worker(env).process_once()=='SUCCEEDED'
    assert env[1].tasks.get('alice',tid)['attempts']==1


def test_reclaim_cursor_reaches_pending_tail(env):
    q=env[4];ids=[q._redis.xadd(q.stream_name,{'bad':'synthetic'}) for _ in range(25)]
    q._redis.xreadgroup(q.group_name,'A',{q.stream_name:'>'},count=25,block=1)
    seen=[]
    for _ in range(30):seen.extend(d.stream_id for d in q.reclaim(consumer_name='B',min_idle_ms=0,count=1))
    assert ids[-1] in seen


def test_last_publisher_lease_lost_at_send_limit_is_terminal_on_reconcile(env):
    tid=submit(env);dispatch=env[1].tasks.dispatch;dispatch.max_sends=1
    event=dispatch.take_pending()[0]
    sql(env,'UPDATE v3_index_outbox SET publisher_until=0')
    with pytest.raises(WorkspaceConflict,match='publisher_lease_lost'):dispatch.published(event)
    assert dispatch.reconcile(age_seconds=.1)==1
    assert env[1].tasks.get('alice',tid)['error_code']=='dispatch_retry_exhausted'
    assert dispatch.monitoring()['outbox']['exhausted']==1


def test_live_consumer_recreates_lost_group_without_acknowledging_work(env):
    tid=submit(env);publish(env);w=worker(env);q=env[4]
    q._redis.delete(q.stream_name)
    assert w.process_once() is None
    assert env[1].tasks.get('alice',tid)['status']=='QUEUED'
    sql(env,f'UPDATE v3_index_outbox SET published_at={DB_NOW}-100')
    assert env[1].tasks.dispatch.reconcile(age_seconds=.1)==1
    assert publish(env)==1 and w.process_once()=='SUCCEEDED'
