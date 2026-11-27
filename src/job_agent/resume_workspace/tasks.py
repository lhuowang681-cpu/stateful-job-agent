"""Small durable local task adapter. Does not claim the v1 PG/Redis deployment."""
from contextlib import asynccontextmanager
from threading import Event,Thread
from time import time
from uuid import uuid4
import json
from fastapi import Depends
from pydantic import Field
from job_agent.schemas import StrictModel
from job_agent.backend_service.contracts import RunStatus
from job_agent.resume_workspace.long_term import LongTermRepository,encoded,digest
from job_agent.resume_workspace.code_rag import CodeRAGService,INDEX_VERSION
from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound

DDL='''
CREATE TABLE IF NOT EXISTS v3_tasks(
 task_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
 project_id TEXT NOT NULL REFERENCES v3_projects(project_id) ON DELETE CASCADE,
 snapshot_id TEXT NOT NULL REFERENCES v3_project_snapshots(snapshot_id) ON DELETE CASCADE,
 request_key TEXT NOT NULL, request_hash TEXT NOT NULL,index_version TEXT NOT NULL,
 status TEXT NOT NULL, stage TEXT NOT NULL, result TEXT,error_code TEXT,
 lease_token TEXT,lease_until REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL,updated_at REAL NOT NULL,
 UNIQUE(owner_id,request_key));
CREATE INDEX IF NOT EXISTS v3_tasks_queue ON v3_tasks(status,lease_until,created_at);
'''


class IndexTaskRequest(StrictModel):
    request_key:str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    snapshot_id:str=Field(min_length=1,max_length=100)


class TaskRepository:
    atomic_publication=False
    def __init__(self,workspace,*,clock=time,lease_seconds=30,projects=None):
        self.workspace=workspace;self.projects=projects or LongTermRepository(workspace);self.clock=clock;self.lease_seconds=lease_seconds
        with workspace._connection(write=True) as db:db.executescript(DDL)

    def submit(self,owner,project_id,request):
        self.projects.files(owner,project_id,request.snapshot_id)
        hashed=digest({'project':project_id,'snapshot':request.snapshot_id,'kind':'code_index'})
        with self.workspace._connection(write=True) as db:
            self.projects._project(db,owner,project_id)
            old=db.execute('SELECT task_id,request_hash FROM v3_tasks WHERE owner_id=? AND request_key=?',(owner,request.request_key)).fetchone()
            if old:
                if old['request_hash']!=hashed:raise WorkspaceConflict('task_request_key_conflict')
                return old['task_id']
            active=db.execute("SELECT owner_id FROM v3_tasks WHERE status IN ('QUEUED','RUNNING')").fetchall()
            if len(active)>=20 or sum(r['owner_id']==owner for r in active)>=3:raise WorkspaceConflict('task_queue_quota_reached')
            tid='task-'+uuid4().hex;now=self.clock()
            db.execute('INSERT INTO v3_tasks(task_id,owner_id,project_id,snapshot_id,request_key,request_hash,index_version,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (tid,owner,project_id,request.snapshot_id,request.request_key,hashed,INDEX_VERSION,RunStatus.QUEUED.value,'queued',now,now))
            return tid

    def get(self,owner,task_id):
        with self.workspace._connection() as db:
            r=db.execute('SELECT * FROM v3_tasks WHERE owner_id=? AND task_id=?',(owner,task_id)).fetchone()
            if r is None:raise WorkspaceNotFound('task_not_found')
            result=json.loads(r['result']) if r['result'] else None
            return {k:r[k] for k in ('task_id','project_id','snapshot_id','status','stage','attempts','created_at','updated_at','error_code')}|{'result':result}

    def claim(self):
        with self.workspace._connection(write=True) as db:
            now=self.clock()
            db.execute("UPDATE v3_tasks SET status='FAILED',stage='stopped',error_code='worker_recovery_exhausted',lease_token=NULL,updated_at=? WHERE status='RUNNING' AND lease_until<=? AND attempts>=3",(now,now))
            r=db.execute("SELECT * FROM v3_tasks WHERE status='QUEUED' OR (status='RUNNING' AND lease_until<=? AND attempts<3) ORDER BY created_at LIMIT 1",(now,)).fetchone()
            if r is None:return None
            token=uuid4().hex
            db.execute("UPDATE v3_tasks SET status='RUNNING',stage='parsing',lease_token=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE task_id=?",(token,now+self.lease_seconds,now,r['task_id']))
            return dict(r)|{'lease_token':token,'attempts':r['attempts']+1}

    def guard(self,db,claim):
        r=db.execute('SELECT status,lease_token,lease_until FROM v3_tasks WHERE task_id=?',(claim['task_id'],)).fetchone()
        if r is None or r['status']!='RUNNING' or r['lease_token']!=claim['lease_token'] or r['lease_until']<=self.clock():
            raise WorkspaceConflict('task_lease_lost')

    def heartbeat(self,claim):
        with self.workspace._connection(write=True) as db:
            self.guard(db,claim)
            db.execute('UPDATE v3_tasks SET lease_until=?,updated_at=? WHERE task_id=?',(self.clock()+self.lease_seconds,self.clock(),claim['task_id']))

    def complete(self,claim,result):
        with self.workspace._connection(write=True) as db:
            self.guard(db,claim)
            db.execute("UPDATE v3_tasks SET status='SUCCEEDED',stage='completed',result=?,lease_token=NULL,updated_at=? WHERE task_id=?",(encoded(result),self.clock(),claim['task_id']))

    def fail(self,claim,code):
        with self.workspace._connection(write=True) as db:
            self.guard(db,claim)
            db.execute("UPDATE v3_tasks SET status='FAILED',stage='stopped',error_code=?,lease_token=NULL,updated_at=? WHERE task_id=?",(code,self.clock(),claim['task_id']))

    def cancel(self,owner,task_id):
        with self.workspace._connection(write=True) as db:
            r=db.execute('SELECT status FROM v3_tasks WHERE owner_id=? AND task_id=?',(owner,task_id)).fetchone()
            if r is None:raise WorkspaceNotFound('task_not_found')
            if r['status']=='CANCELLED':return
            if r['status']!='QUEUED':raise WorkspaceConflict('only_queued_task_can_be_cancelled')
            db.execute("UPDATE v3_tasks SET status='CANCELLED',stage='cancelled',updated_at=? WHERE task_id=?",(self.clock(),task_id))

    def history(self,owner,project_id):
        with self.workspace._connection() as db:
            self.projects._project(db,owner,project_id)
            ids=[r[0] for r in db.execute('SELECT task_id FROM v3_tasks WHERE owner_id=? AND project_id=? ORDER BY created_at DESC LIMIT 100',(owner,project_id))]
        return [self.get(owner,tid) for tid in ids]


class IndexTaskWorker:
    def __init__(self,store,code,*,failpoint=None,external_dispatch=False):
        if getattr(store,'dispatch_mode','polling')=='redis' and not external_dispatch:raise WorkspaceConflict('polling_worker_disabled')
        self.store=store;self.code=code;self.failpoint=failpoint;self.stop_event=Event();self.thread=None

    def process_once(self):
        claim=self.store.claim()
        if claim is None:return False
        return self.process_claim(claim)

    def process_claim(self,claim):
        heartbeat_stop=Event()
        def heartbeat():
            while not heartbeat_stop.wait(max(.1,self.store.lease_seconds/3)):
                try:self.store.heartbeat(claim)
                except Exception:return
        renewer=Thread(target=heartbeat,daemon=True,name='local-index-lease');renewer.start()
        try:
            if claim['index_version']!=INDEX_VERSION:raise WorkspaceConflict('task_index_version_changed')
            if getattr(self.store,'atomic_publication',False):
                result=self.code.build(claim['owner_id'],claim['project_id'],claim['snapshot_id'],task_claim=claim)
            else:result=self.code.build(claim['owner_id'],claim['project_id'],claim['snapshot_id'],publish_guard=lambda db:self.store.guard(db,claim))
            if self.failpoint:self.failpoint('after_index_before_task_commit')
            if not getattr(self.store,'atomic_publication',False):self.store.complete(claim,result)
        except (WorkspaceNotFound,WorkspaceConflict) as exc:
            try:self.store.fail(claim,'source_unavailable_or_integrity_failed' if isinstance(exc,WorkspaceNotFound) else 'index_task_rejected')
            except WorkspaceConflict:pass # Old attempts cannot overwrite a new lease.
        except Exception:
            try:
                if getattr(self.store,'dispatch_mode','polling')=='redis':self.store.dispatch.retry(claim)
                else:self.store.fail(claim,'index_task_failed')
            except WorkspaceConflict:pass
        finally:
            heartbeat_stop.set();renewer.join(timeout=1)
        return True

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try:worked=self.process_once()
                except Exception:worked=False # No raw source/exception in logs; persisted lease recovers.
                if not worked:self.stop_event.wait(.2)
        self.thread=Thread(target=loop,daemon=True,name='local-durable-index-worker');self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)


def install_task_routes(app,workspace,owner,code,*,worker_enabled=True,store=None):
    store=store or TaskRepository(workspace)
    redis_mode=getattr(store,'dispatch_mode','polling')=='redis'
    if redis_mode and worker_enabled:raise WorkspaceConflict('redis_requires_independent_worker')
    worker=None if redis_mode else IndexTaskWorker(store,code)
    app.state.task_store=store;app.state.index_worker=worker
    old_lifespan=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with old_lifespan(application):
            if worker_enabled and worker:worker.start()
            try:yield
            finally:
                if worker:worker.stop()
    app.router.lifespan_context=lifespan
    @app.post('/api/v2/projects/{project_id}/index-tasks',status_code=202)
    def submit(project_id:str,request:IndexTaskRequest,user:str=Depends(owner)):
        return store.get(user,store.submit(user,project_id,request))
    @app.get('/api/v2/tasks/{task_id}')
    def get(task_id:str,user:str=Depends(owner)):return store.get(user,task_id)
    @app.get('/api/v2/projects/{project_id}/index-tasks')
    def history(project_id:str,user:str=Depends(owner)):
        return store.history(user,project_id)[:20]
    @app.post('/api/v2/tasks/{task_id}/cancel')
    def cancel(task_id:str,user:str=Depends(owner)):
        store.cancel(user,task_id);return store.get(user,task_id)
