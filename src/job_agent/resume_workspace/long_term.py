"""Owner-scoped job timeline and immutable project snapshots on the product DB."""
from __future__ import annotations
from contextlib import nullcontext
from datetime import datetime,UTC
from hashlib import sha256
import json
from typing import Literal
from uuid import uuid4
from pydantic import Field
from fastapi import Depends,Query,Request,Response
from job_agent.schemas import StrictModel
from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.project_import import scan_zip,checked_path,excluded,MAX_FILE_BYTES
from job_agent.resume_workspace.github_import import GitHubImport,PublicGitHubImporter


def now():return datetime.now(UTC).isoformat()
def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return sha256(encoded(value).encode()).hexdigest()
Stage=Literal['saved','applied','screening','interview','offer','rejected','withdrawn']


class JobCreate(StrictModel):
    request_key: str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    company: str=Field(min_length=1,max_length=120)
    title: str=Field(min_length=1,max_length=120)
    jd_text: str=Field(min_length=1,max_length=12000)
    url: str=Field(default='',max_length=1000)
    notes: str=Field(default='',max_length=5000)


class JobUpdate(StrictModel):
    request_key: str=Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    expected_revision: int=Field(ge=1)
    stage: Stage
    note: str=Field(default='',max_length=3000)


class JobLink(StrictModel):
    resume_id: str
    version_id: str
    interview_id: str|None=None


class ProjectCreate(StrictModel):
    name: str=Field(min_length=1,max_length=120)
    contribution: str=Field(default='',max_length=6000)
    description: str=Field(default='',max_length=6000)
    license_note: str=Field(default='私人材料，仅本用户空间使用',max_length=1000)


class ProjectDocument(StrictModel):
    path: str=Field(min_length=1,max_length=200)
    text: str=Field(min_length=1,max_length=100000)


_DDL='''
CREATE TABLE IF NOT EXISTS v3_jobs (
    job_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,payload TEXT NOT NULL,stage TEXT NOT NULL,
    revision INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
    UNIQUE(owner_id,request_key));
CREATE INDEX IF NOT EXISTS v3_job_owner ON v3_jobs(owner_id);
CREATE TABLE IF NOT EXISTS v3_job_events (
    event_id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES v3_jobs(job_id) ON DELETE CASCADE,
    request_key TEXT NOT NULL,request_hash TEXT NOT NULL,stage TEXT NOT NULL,note TEXT NOT NULL,
    revision INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(job_id,request_key));
CREATE TABLE IF NOT EXISTS v3_job_links (
    job_id TEXT NOT NULL REFERENCES v3_jobs(job_id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES rw_versions(version_id) ON DELETE CASCADE,
    interview_id TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,
    PRIMARY KEY(job_id,version_id,interview_id));
CREATE TABLE IF NOT EXISTS v3_projects (
    project_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,payload TEXT NOT NULL,
    created_at TEXT NOT NULL,current_snapshot TEXT,index_status TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS v3_project_owner ON v3_projects(owner_id);
CREATE TABLE IF NOT EXISTS v3_project_snapshots (
    snapshot_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v3_projects(project_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,origin TEXT NOT NULL,commit_sha TEXT,metadata TEXT NOT NULL,
    created_at TEXT NOT NULL,UNIQUE(project_id,content_hash));
CREATE TABLE IF NOT EXISTS v3_project_files (
    snapshot_id TEXT NOT NULL REFERENCES v3_project_snapshots(snapshot_id) ON DELETE CASCADE,
    path TEXT NOT NULL,content_hash TEXT NOT NULL,text TEXT NOT NULL,
    PRIMARY KEY(snapshot_id,path));
'''


class LongTermRepository:
    def __init__(self,workspace):
        self.workspace=workspace
        with workspace._connection(write=True) as db:db.executescript(_DDL)

    @staticmethod
    def _job(db,owner,job_id):
        row=db.execute('SELECT * FROM v3_jobs WHERE job_id=? AND owner_id=?',(job_id,owner)).fetchone()
        if row is None:raise WorkspaceNotFound('job_not_found')
        return row

    def create_job(self,owner,request:JobCreate):
        request=JobCreate.model_validate(request.model_dump());h=digest(request.model_dump(exclude={'request_key'}))
        with self.workspace._connection(write=True) as db:
            row=db.execute('SELECT * FROM v3_jobs WHERE owner_id=? AND request_key=?',(owner,request.request_key)).fetchone()
            if row:
                if row['request_hash']!=h:raise WorkspaceConflict('job_request_key_conflict')
                key=row['job_id']
            else:
                if db.execute('SELECT COUNT(*) FROM v3_jobs WHERE owner_id=?',(owner,)).fetchone()[0]>=200:raise WorkspaceConflict('job_quota_reached')
                key='job-'+uuid4().hex;t=now()
                db.execute('INSERT INTO v3_jobs VALUES (?,?,?,?,?,?,?,?,?)',(key,owner,request.request_key,h,encoded(request.model_dump(exclude={'request_key'})),'saved',1,t,t))
                db.execute('INSERT INTO v3_job_events VALUES (?,?,?,?,?,?,?,?)',('event-'+uuid4().hex,key,request.request_key,h,'saved','创建岗位',1,t))
        return self.get_job(owner,key)

    def get_job(self,owner,job_id):
        with self.workspace._connection() as db:
            row=self._job(db,owner,job_id)
            return {**json.loads(row['payload']),'job_id':job_id,'stage':row['stage'],'revision':row['revision'],
                'created_at':row['created_at'],'updated_at':row['updated_at'],
                'events':[dict(x) for x in db.execute('SELECT event_id,stage,note,revision,created_at FROM v3_job_events WHERE job_id=? ORDER BY revision',(job_id,))],
                'links':[dict(x) for x in db.execute('''SELECT l.version_id,l.interview_id,l.created_at,v.resume_id,v.sequence,v.content_hash
                    FROM v3_job_links l JOIN rw_versions v ON v.version_id=l.version_id WHERE l.job_id=? ORDER BY l.created_at''',(job_id,))]}

    def list_jobs(self,owner):
        with self.workspace._connection() as db:ids=[r[0] for r in db.execute('SELECT job_id FROM v3_jobs WHERE owner_id=? ORDER BY updated_at DESC LIMIT 200',(owner,))]
        return [self.get_job(owner,key) for key in ids]

    def update_job(self,owner,key,request:JobUpdate):
        h=digest(request.model_dump())
        with self.workspace._connection(write=True) as db:
            row=self._job(db,owner,key)
            old=db.execute('SELECT request_hash FROM v3_job_events WHERE job_id=? AND request_key=?',(key,request.request_key)).fetchone()
            if old:
                if old[0]!=h:raise WorkspaceConflict('job_request_key_conflict')
            else:
                if row['revision']!=request.expected_revision:raise WorkspaceConflict('job_revision_changed')
                t=now();revision=row['revision']+1
                db.execute('INSERT INTO v3_job_events VALUES (?,?,?,?,?,?,?,?)',('event-'+uuid4().hex,key,request.request_key,h,request.stage,request.note,revision,t))
                db.execute('UPDATE v3_jobs SET stage=?,revision=?,updated_at=? WHERE job_id=?',(request.stage,revision,t,key))
        return self.get_job(owner,key)

    def link_job(self,owner,key,request:JobLink):
        with self.workspace._connection(write=True) as db:
            self._job(db,owner,key);self.workspace._resume(db,owner,request.resume_id)
            version=self.workspace._version(db,request.resume_id,request.version_id)
            self.workspace._validate_document(db,owner,version.document)
            if request.interview_id:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='rw_interviews'").fetchone():raise WorkspaceNotFound('interview_not_found')
                row=db.execute('SELECT owner_id,resume_id,version_id FROM rw_interviews WHERE session_id=?',(request.interview_id,)).fetchone()
                if row is None or row['owner_id']!=owner or row['resume_id']!=request.resume_id:raise WorkspaceNotFound('interview_not_found')
                if row['version_id']!=request.version_id:raise WorkspaceConflict('job_interview_version_mismatch')
            db.execute('INSERT OR IGNORE INTO v3_job_links VALUES (?,?,?,?)',(key,request.version_id,request.interview_id or '',now()))
        return self.get_job(owner,key)

    def delete_job(self,owner,key):
        with self.workspace._connection(write=True) as db:self._job(db,owner,key);db.execute('DELETE FROM v3_jobs WHERE job_id=?',(key,))

    @staticmethod
    def _project(db,owner,key):
        row=db.execute('SELECT * FROM v3_projects WHERE project_id=? AND owner_id=?',(key,owner)).fetchone()
        if row is None:raise WorkspaceNotFound('project_not_found')
        return row

    def create_project(self,owner,request:ProjectCreate):
        with self.workspace._connection(write=True) as db:
            if db.execute('SELECT COUNT(*) FROM v3_projects WHERE owner_id=?',(owner,)).fetchone()[0]>=20:raise WorkspaceConflict('project_quota_reached')
            key='project-'+uuid4().hex
            db.execute('INSERT INTO v3_projects VALUES (?,?,?,?,?,?)',(key,owner,encoded(request.model_dump()),now(),None,'not_imported'))
        return self.get_project(owner,key)

    def get_project(self,owner,key):
        with self.workspace._connection() as db:
            row=self._project(db,owner,key)
            snapshots=[{**{k:s[k] for k in ('snapshot_id','content_hash','origin','commit_sha','created_at')},'metadata':json.loads(s['metadata'])} for s in db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=? ORDER BY created_at DESC',(key,))]
            return {**json.loads(row['payload']),'project_id':key,'created_at':row['created_at'],'current_snapshot':row['current_snapshot'],
                'index_status':row['index_status'],'contribution_status':'self_attested_not_verified','snapshots':snapshots}

    def list_projects(self,owner):
        with self.workspace._connection() as db:ids=[r[0] for r in db.execute('SELECT project_id FROM v3_projects WHERE owner_id=? ORDER BY created_at DESC LIMIT 20',(owner,))]
        return [self.get_project(owner,key) for key in ids]

    def publish_files(self,owner,key,files,*,origin,commit_sha=None,metadata=None):
        if not files or len(files)>1200 or sum(len(text.encode()) for text in files.values())>24*1024*1024:raise WorkspaceConflict('project_content_limit')
        for path,text in files.items():
            checked_path(path)
            if len(text.encode())>MAX_FILE_BYTES or excluded(path,text):raise WorkspaceConflict('project_file_rejected')
        manifest={p:sha256(text.encode()).hexdigest() for p,text in sorted(files.items())}
        content_hash=digest({'files':manifest,'origin':origin,'commit_sha':commit_sha})
        with self.workspace._connection(write=True) as db:
            self._project(db,owner,key)
            row=db.execute('SELECT snapshot_id FROM v3_project_snapshots WHERE project_id=? AND content_hash=?',(key,content_hash)).fetchone()
            if row:snapshot=row[0]
            else:
                stored_bytes=db.execute('''SELECT COALESCE(SUM(length(CAST(f.text AS BLOB))),0) FROM v3_project_files f
                    JOIN v3_project_snapshots s ON s.snapshot_id=f.snapshot_id JOIN v3_projects p ON p.project_id=s.project_id
                    WHERE p.owner_id=?''',(owner,)).fetchone()[0]
                if stored_bytes+sum(len(t.encode()) for t in files.values())>100*1024*1024:raise WorkspaceConflict('project_storage_quota_reached')
                count=db.execute('SELECT COUNT(*) FROM v3_project_snapshots WHERE project_id=?',(key,)).fetchone()[0]
                if count>=10:raise WorkspaceConflict('project_snapshot_quota_reached')
                snapshot='snapshot-'+uuid4().hex
                db.execute('INSERT INTO v3_project_snapshots VALUES (?,?,?,?,?,?,?)',(snapshot,key,content_hash,origin,commit_sha,encoded(metadata or {}),now()))
                db.executemany('INSERT INTO v3_project_files VALUES (?,?,?,?)',[(snapshot,p,manifest[p],text) for p,text in sorted(files.items())])
            db.execute('UPDATE v3_projects SET current_snapshot=?,index_status=? WHERE project_id=?',(snapshot,'pending_index',key))
        return self.get_project(owner,key)

    def import_zip(self,owner,key,data):
        self.get_project(owner,key)
        files,metadata=scan_zip(data)
        return self.publish_files(owner,key,files,origin='zip',metadata=metadata)

    def add_document(self,owner,key,request:ProjectDocument):
        path=checked_path(request.path)
        if not path.casefold().endswith(('.md','.txt')):raise WorkspaceConflict('project_document_type')
        project=self.get_project(owner,key)
        files=self.files(owner,key,project['current_snapshot']) if project['current_snapshot'] else {}
        files[path]=request.text
        return self.publish_files(owner,key,files,origin='document',metadata={'contribution_status':'self_attested_not_verified'})

    def files(self,owner,key,snapshot):
        with self.workspace._connection() as db:
            self._project(db,owner,key)
            row=db.execute('SELECT content_hash,origin,commit_sha FROM v3_project_snapshots WHERE project_id=? AND snapshot_id=?',(key,snapshot)).fetchone()
            if row is None:raise WorkspaceNotFound('snapshot_not_found')
            files={};manifest={}
            for f in db.execute('SELECT * FROM v3_project_files WHERE snapshot_id=? ORDER BY path',(snapshot,)):
                if sha256(f['text'].encode()).hexdigest()!=f['content_hash']:raise WorkspaceConflict('project_file_integrity_failed')
                files[f['path']]=f['text'];manifest[f['path']]=f['content_hash']
            if digest({'files':manifest,'origin':row['origin'],'commit_sha':row['commit_sha']})!=row['content_hash']:raise WorkspaceConflict('project_snapshot_integrity_failed')
            return files

    def delete_project(self,owner,key):
        with self.workspace._connection(write=True) as db:self._project(db,owner,key);db.execute('DELETE FROM v3_projects WHERE project_id=?',(key,))

    def read_file(self,owner,key,snapshot,path,*,db=None):
        """Check the manifest cheaply, then hash only the requested immutable text."""
        checked_path(path)
        with (nullcontext(db) if db is not None else self.workspace._connection()) as db:
            self._project(db,owner,key)
            version=db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=? AND snapshot_id=?',(key,snapshot)).fetchone()
            if version is None:raise WorkspaceNotFound('snapshot_not_found')
            manifest={r['path']:r['content_hash'] for r in db.execute('SELECT path,content_hash FROM v3_project_files WHERE snapshot_id=? ORDER BY path',(snapshot,))}
            if digest({'files':manifest,'origin':version['origin'],'commit_sha':version['commit_sha']})!=version['content_hash']:raise WorkspaceConflict('project_snapshot_integrity_failed')
            row=db.execute('SELECT * FROM v3_project_files WHERE snapshot_id=? AND path=?',(snapshot,path)).fetchone()
            if row is None:raise WorkspaceNotFound('project_file_not_found')
            if sha256(row['text'].encode()).hexdigest()!=row['content_hash']:raise WorkspaceConflict('project_file_integrity_failed')
            return row['text'],dict(version)


def install_long_term_routes(app,workspace,owner,*,project_store=None):
    from job_agent.resume_workspace.project_import import MAX_ARCHIVE_BYTES
    store=LongTermRepository(workspace)
    @app.post('/api/v2/jobs',status_code=201)
    def create_job(request:JobCreate,user:str=Depends(owner)):return store.create_job(user,request)
    @app.get('/api/v2/jobs')
    def jobs(user:str=Depends(owner)):return store.list_jobs(user)
    @app.get('/api/v2/jobs/{key}')
    def job(key:str,user:str=Depends(owner)):return store.get_job(user,key)
    @app.post('/api/v2/jobs/{key}/events')
    def update_job(key:str,request:JobUpdate,user:str=Depends(owner)):return store.update_job(user,key,request)
    @app.post('/api/v2/jobs/{key}/links')
    def link_job(key:str,request:JobLink,user:str=Depends(owner)):return store.link_job(user,key,request)
    @app.delete('/api/v2/jobs/{key}',status_code=204)
    def delete_job(key:str,user:str=Depends(owner)):store.delete_job(user,key);return Response(status_code=204)
    projects=project_store or store
    @app.post('/api/v2/projects',status_code=201)
    def create_project(request:ProjectCreate,user:str=Depends(owner)):return projects.create_project(user,request)
    @app.get('/api/v2/projects')
    def list_projects(user:str=Depends(owner)):return projects.list_projects(user)
    @app.get('/api/v2/projects/{key}')
    def project(key:str,user:str=Depends(owner)):return projects.get_project(user,key)
    @app.post('/api/v2/projects/{key}/zip',status_code=201)
    async def import_zip(key:str,request:Request,user:str=Depends(owner)):
        from starlette.concurrency import run_in_threadpool
        projects.get_project(user,key)
        data=bytearray()
        async for chunk in request.stream():
            if len(data)+len(chunk)>MAX_ARCHIVE_BYTES:raise WorkspaceConflict('archive_upload_limit')
            data.extend(chunk)
        return await run_in_threadpool(projects.import_zip,user,key,bytes(data))
    @app.post('/api/v2/projects/{key}/documents',status_code=201)
    def document(key:str,request:ProjectDocument,user:str=Depends(owner)):return projects.add_document(user,key,request)
    @app.post('/api/v2/projects/{key}/github',status_code=201)
    def github(key:str,request:GitHubImport,user:str=Depends(owner)):return PublicGitHubImporter(projects).import_project(user,key,request)
    @app.get('/api/v2/projects/{key}/files')
    def files(key:str,snapshot:str=Query(min_length=1,max_length=100),user:str=Depends(owner)):
        return [{'path':p,'content_hash':sha256(t.encode()).hexdigest(),'lines':len(t.splitlines())} for p,t in projects.files(user,key,snapshot).items()]
    @app.delete('/api/v2/projects/{key}',status_code=204)
    def delete_project(key:str,user:str=Depends(owner)):projects.delete_project(user,key);return Response(status_code=204)
    return store
