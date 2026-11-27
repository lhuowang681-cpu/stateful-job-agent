"""Durable local queue and real index writes; no model/PG/Redis claims."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService
from job_agent.resume_workspace.tasks import TaskRepository,IndexTaskRequest,IndexTaskWorker
from job_agent.resume_workspace.api import create_resume_app


@pytest.fixture
def env(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'task.sqlite');projects=LongTermRepository(ws)
    p=projects.create_project('alice',ProjectCreate(name='Synthetic async'))
    p=projects.publish_files('alice',p['project_id'],{'app.py':'def receipt(key):\n    return key\n'},origin='zip')
    code=CodeRAGService(ws);clock=[100.0];store=TaskRepository(ws,clock=lambda:clock[0])
    return ws,projects,p,code,clock,store


def submit(env,key='index-request-key'):
    _,_,p,_,_,store=env
    return store.submit('alice',p['project_id'],IndexTaskRequest(request_key=key,snapshot_id=p['current_snapshot']))


def test_submit_is_persistent_idempotent_and_payload_conflicts(env):
    ws,projects,p,_,_,store=env;tid=submit(env)
    assert submit(env)==tid
    reopened=TaskRepository(SqliteResumeRepository(ws.path))
    assert reopened.get('alice',tid)['status']=='QUEUED'
    other=projects.create_project('alice',ProjectCreate(name='Other'))
    other=projects.publish_files('alice',other['project_id'],{'other.py':'value=1\n'},origin='zip')
    with pytest.raises(WorkspaceConflict,match='key_conflict'):
        store.submit('alice',other['project_id'],IndexTaskRequest(request_key='index-request-key',snapshot_id=other['current_snapshot']))


def test_atomic_claim_has_single_winner_and_old_worker_is_fenced(env):
    ws,_,p,code,clock,store=env;tid=submit(env)
    with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(lambda _:store.claim(),range(2)))
    first=next(c for c in claims if c);assert sum(c is not None for c in claims)==1
    clock[0]+=31;second=store.claim();assert second['lease_token']!=first['lease_token']
    with pytest.raises(WorkspaceConflict,match='lease_lost'):
        code.build('alice',p['project_id'],p['current_snapshot'],publish_guard=lambda db:store.guard(db,first))
    with pytest.raises(WorkspaceConflict,match='lease_lost'):store.complete(first,{'stale':True})
    assert code.status('alice',p['project_id'],p['current_snapshot'])['status']=='not_indexed'
    result=code.build('alice',p['project_id'],p['current_snapshot'],publish_guard=lambda db:store.guard(db,second))
    store.complete(second,result)
    assert store.get('alice',tid)['status']=='SUCCEEDED'


def test_crash_after_index_commit_recovers_without_duplicate_index_rows(env):
    ws,_,p,code,clock,store=env;tid=submit(env)
    class Crash(BaseException):pass
    def fault(stage):
        assert stage=='after_index_before_task_commit'
        raise Crash()
    with pytest.raises(Crash):IndexTaskWorker(store,code,failpoint=fault).process_once()
    assert store.get('alice',tid)['status']=='RUNNING'
    assert code.status('alice',p['project_id'],p['current_snapshot'])['status']=='indexed'
    with ws._connection() as db:before=db.execute('SELECT COUNT(*) FROM v3_code_symbols').fetchone()[0]
    clock[0]+=31
    assert IndexTaskWorker(store,code).process_once()
    assert store.get('alice',tid)['status']=='SUCCEEDED' and store.get('alice',tid)['attempts']==2
    with ws._connection() as db:assert db.execute('SELECT COUNT(*) FROM v3_code_symbols').fetchone()[0]==before
    assert not IndexTaskWorker(store,code).process_once()


def test_recovery_attempts_are_bounded(env):
    _,_,_,_,clock,store=env;tid=submit(env)
    for _ in range(3):assert store.claim();clock[0]+=31
    assert store.claim() is None
    result=store.get('alice',tid)
    assert result['status']=='FAILED' and result['error_code']=='worker_recovery_exhausted'


def test_queued_cancel_is_idempotent_but_running_cancel_rejected(env):
    _,_,_,_,_,store=env;tid=submit(env)
    store.cancel('alice',tid);store.cancel('alice',tid)
    assert store.claim() is None and store.get('alice',tid)['status']=='CANCELLED'
    running=submit(env,'another-index-key');store.claim()
    with pytest.raises(WorkspaceConflict,match='only_queued'):store.cancel('alice',running)
    with pytest.raises(WorkspaceNotFound):store.cancel('bob',running)


def test_delete_project_cascades_tasks_and_derived_rows(env):
    ws,projects,p,code,_,store=env;submit(env);claim=store.claim()
    projects.delete_project('alice',p['project_id'])
    with pytest.raises(WorkspaceNotFound):code.build('alice',p['project_id'],p['current_snapshot'])
    with ws._connection() as db:assert db.execute('SELECT COUNT(*) FROM v3_tasks').fetchone()[0]==0
    with pytest.raises(WorkspaceConflict):store.complete(claim,{})


def test_queue_owner_quota_and_no_raw_error_leak(env):
    _,_,_,code,_,store=env
    for i in range(3):submit(env,f'quota-index-key-{i}')
    with pytest.raises(WorkspaceConflict,match='quota'):submit(env,'quota-index-key-4')
    class Broken:
        def build(self,*a,**kw):raise RuntimeError('private-synthetic-marker-never-log')
    worker=IndexTaskWorker(store,Broken());worker.process_once()
    with store.workspace._connection() as db:r=db.execute("SELECT task_id FROM v3_tasks WHERE status='FAILED'").fetchone()
    result=store.get('alice',r['task_id'])
    assert result['error_code']=='index_task_failed' and 'private-synthetic' not in str(result)


def test_heartbeat_extends_lease_and_old_heartbeat_cannot_steal(env):
    _,_,_,_,clock,store=env;submit(env);first=store.claim();clock[0]+=20;store.heartbeat(first)
    clock[0]+=15;assert store.claim() is None
    clock[0]+=16;assert store.claim()
    with pytest.raises(WorkspaceConflict):store.heartbeat(first)


def test_real_http_submission_worker_progress_and_result(env):
    ws,_,p,_,_,_=env;app=create_resume_app(ws,resolve_identity={'a':'alice','b':'bob'}.get)
    a={'Authorization':'Bearer a'};b={'Authorization':'Bearer b'}
    with TestClient(app) as c:
        url=f"/api/v2/projects/{p['project_id']}/index-tasks"
        payload={'request_key':'http-index-key','snapshot_id':p['current_snapshot']}
        assert c.post(url,json=payload).status_code==401
        assert c.post(url,headers=b,json=payload).status_code==404
        r=c.post(url,headers=a,json=payload);assert r.status_code==202
        tid=r.json()['task_id'];assert c.get(f'/api/v2/tasks/{tid}',headers=b).status_code==404
        completed=None
        for _ in range(100):
            v=c.get(f'/api/v2/tasks/{tid}',headers=a).json()
            if v['status']=='SUCCEEDED':completed=v;break
            Event().wait(.02)
        assert completed and completed['result']['symbols']>=1
        assert c.post(url,headers=a,json=payload).json()['task_id']==tid
        assert c.get(url,headers=a).json()[0]['task_id']==tid
        assert c.get(f"/api/v2/projects/{p['project_id']}/index",headers=a,params={'snapshot':p['current_snapshot']}).json()['status']=='indexed'


def test_queued_http_task_survives_app_restart(env):
    ws,_,p,_,_,_=env;a={'Authorization':'Bearer a'}
    with TestClient(create_resume_app(ws,resolve_identity={'a':'alice'}.get,task_worker_enabled=False)) as c:
        tid=c.post(f"/api/v2/projects/{p['project_id']}/index-tasks",headers=a,json={
            'request_key':'restart-index-key','snapshot_id':p['current_snapshot']}).json()['task_id']
        assert c.get(f'/api/v2/tasks/{tid}',headers=a).json()['status']=='QUEUED'
    with TestClient(create_resume_app(SqliteResumeRepository(ws.path),resolve_identity={'a':'alice'}.get)) as c:
        for _ in range(100):
            result=c.get(f'/api/v2/tasks/{tid}',headers=a).json()
            if result['status']=='SUCCEEDED':break
            Event().wait(.02)
        assert result['status']=='SUCCEEDED'
