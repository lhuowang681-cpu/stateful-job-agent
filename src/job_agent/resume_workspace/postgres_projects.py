"""One native PostgreSQL authority for project, immutable indexes and tasks.

Resume/approval data deliberately stays in its existing transaction domain.
"""
from __future__ import annotations
from contextlib import contextmanager,nullcontext
from hashlib import sha256
import json,re
from uuid import uuid4
from job_agent.resume_workspace.long_term import encoded,digest,now,LongTermRepository
from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.project_import import checked_path,excluded,MAX_FILE_BYTES

DB_NOW='EXTRACT(EPOCH FROM clock_timestamp())'
DDL='''
CREATE TABLE v3_projects(
 project_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,
 current_snapshot TEXT,index_status TEXT NOT NULL,UNIQUE(owner_id,project_id));
CREATE INDEX v3_project_owner ON v3_projects(owner_id);
CREATE TABLE v3_project_snapshots(
 snapshot_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES v3_projects ON DELETE CASCADE,
 content_hash TEXT NOT NULL,origin TEXT NOT NULL,commit_sha TEXT,metadata TEXT NOT NULL,created_at TEXT NOT NULL,
 desired_generation BIGINT NOT NULL DEFAULT 0,active_publication TEXT,
 UNIQUE(project_id,content_hash),UNIQUE(project_id,snapshot_id));
CREATE TABLE v3_project_files(
 snapshot_id TEXT NOT NULL REFERENCES v3_project_snapshots ON DELETE CASCADE,
 path TEXT NOT NULL,content_hash TEXT NOT NULL,text TEXT NOT NULL,PRIMARY KEY(snapshot_id,path));
CREATE TABLE v3_index_publications(
 publication_id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL REFERENCES v3_project_snapshots ON DELETE CASCADE,
 parser_version TEXT NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,generation BIGINT NOT NULL,
 UNIQUE(snapshot_id,publication_id));
ALTER TABLE v3_projects ADD CONSTRAINT v3_current_snapshot_fk FOREIGN KEY(project_id,current_snapshot)
 REFERENCES v3_project_snapshots(project_id,snapshot_id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE v3_project_snapshots ADD CONSTRAINT v3_active_publication_fk FOREIGN KEY(snapshot_id,active_publication)
 REFERENCES v3_index_publications(snapshot_id,publication_id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE v3_index_symbols(publication_id TEXT NOT NULL REFERENCES v3_index_publications ON DELETE CASCADE,
 symbol_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(publication_id,symbol_id));
CREATE TABLE v3_index_chunks(publication_id TEXT NOT NULL REFERENCES v3_index_publications ON DELETE CASCADE,
 chunk_id TEXT NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(publication_id,chunk_id));
CREATE TABLE v3_index_edges(publication_id TEXT NOT NULL REFERENCES v3_index_publications ON DELETE CASCADE,
 source_id TEXT NOT NULL,target_id TEXT NOT NULL,kind TEXT NOT NULL,line INTEGER NOT NULL,
 PRIMARY KEY(publication_id,source_id,target_id,kind,line));
CREATE TABLE v3_index_vectors(publication_id TEXT NOT NULL REFERENCES v3_index_publications ON DELETE CASCADE,
 model_id TEXT NOT NULL,dimension INTEGER NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,
 PRIMARY KEY(publication_id,model_id));
CREATE TABLE v3_tasks(
 task_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,project_id TEXT NOT NULL,snapshot_id TEXT NOT NULL,
 request_key TEXT NOT NULL,request_hash TEXT NOT NULL,index_version TEXT NOT NULL,config_identity TEXT NOT NULL,
 generation BIGINT NOT NULL,status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 stage TEXT NOT NULL,result TEXT,error_code TEXT,lease_token TEXT,lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,created_at DOUBLE PRECISION NOT NULL,updated_at DOUBLE PRECISION NOT NULL,
 event_seq INTEGER NOT NULL DEFAULT 0,UNIQUE(owner_id,request_key),
 FOREIGN KEY(owner_id,project_id) REFERENCES v3_projects(owner_id,project_id) ON DELETE CASCADE,
 FOREIGN KEY(project_id,snapshot_id) REFERENCES v3_project_snapshots(project_id,snapshot_id) ON DELETE CASCADE);
CREATE INDEX v3_tasks_queue ON v3_tasks(status,lease_until,created_at);
CREATE TABLE v3_task_events(task_id TEXT NOT NULL REFERENCES v3_tasks ON DELETE CASCADE,seq INTEGER NOT NULL,
 kind TEXT NOT NULL,attempt INTEGER NOT NULL,recorded_at DOUBLE PRECISION NOT NULL,PRIMARY KEY(task_id,seq));
'''


class PostgresProjectDatabase:
    def __init__(self,dsn,*,schema='job_agent_v3'):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,47}',schema):raise ValueError('project_schema_invalid')
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        self.dsn=dsn;self.schema=schema
        # Same native driver/row/transaction pattern as legacy PG, distinct model/schema.
        with psycopg.connect(dsn,autocommit=True) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(schema)))
        self.pool=ConnectionPool(dsn,kwargs={'row_factory':dict_row,'options':f'-c search_path={schema},pg_catalog'},
            min_size=1,max_size=8,open=False)
        self.pool.open(wait=True)
        with self._connection(write=True) as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(schema+':schema',))
            db.execute('CREATE TABLE IF NOT EXISTS v3_schema_migrations(version TEXT PRIMARY KEY,ddl_hash TEXT NOT NULL)')
            prior=db.execute("SELECT ddl_hash FROM v3_schema_migrations WHERE version='project-slice-1'").fetchone()
            expected=sha256(DDL.encode()).hexdigest()
            if prior and prior['ddl_hash']!=expected:raise WorkspaceConflict('project_schema_migration_required')
            if prior is None:
                db.execute(DDL);db.execute('INSERT INTO v3_schema_migrations VALUES (%s,%s)',('project-slice-1',expected))

    @contextmanager
    def _connection(self,*,write=False):
        with self.pool.connection() as db:
            with db.transaction():
                if not write:db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                yield db

    def close(self):self.pool.close()


class PostgresProjectRepository:
    backend='postgresql'
    def __init__(self,database):self.workspace=database

    @staticmethod
    def _project(db,owner,key,*,lock=False):
        row=db.execute('SELECT * FROM v3_projects WHERE owner_id=%s AND project_id=%s'+(' FOR UPDATE' if lock else ''),(owner,key)).fetchone()
        if row is None:raise WorkspaceNotFound('project_not_found')
        return row

    def create_project(self,owner,request):
        with self.workspace._connection(write=True) as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('project-quota:'+owner,))
            if db.execute('SELECT COUNT(*) AS n FROM v3_projects WHERE owner_id=%s',(owner,)).fetchone()['n']>=20:raise WorkspaceConflict('project_quota_reached')
            key='project-'+uuid4().hex
            db.execute('INSERT INTO v3_projects VALUES (%s,%s,%s,%s,NULL,%s)',(key,owner,encoded(request.model_dump()),now(),'not_imported'))
        return self.get_project(owner,key)

    def get_project(self,owner,key):
        with self.workspace._connection() as db:
            row=self._project(db,owner,key)
            snapshots=[{**{k:s[k] for k in ('snapshot_id','content_hash','origin','commit_sha','created_at')},'metadata':json.loads(s['metadata'])}
                for s in db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=%s ORDER BY created_at DESC',(key,))]
            return {**json.loads(row['payload']),'project_id':key,'created_at':row['created_at'],'current_snapshot':row['current_snapshot'],
                'index_status':row['index_status'],'contribution_status':'self_attested_not_verified','snapshots':snapshots}

    def list_projects(self,owner):
        with self.workspace._connection() as db:
            ids=[r['project_id'] for r in db.execute('SELECT project_id FROM v3_projects WHERE owner_id=%s ORDER BY created_at DESC LIMIT 20',(owner,))]
        return [self.get_project(owner,key) for key in ids]

    def publish_files(self,owner,key,files,*,origin,commit_sha=None,metadata=None):
        if not files or len(files)>1200 or sum(len(t.encode()) for t in files.values())>24*1024*1024:raise WorkspaceConflict('project_content_limit')
        for path,text in files.items():
            checked_path(path)
            if len(text.encode())>MAX_FILE_BYTES or excluded(path,text):raise WorkspaceConflict('project_file_rejected')
        manifest={p:sha256(t.encode()).hexdigest() for p,t in sorted(files.items())}
        content_hash=digest({'files':manifest,'origin':origin,'commit_sha':commit_sha})
        with self.workspace._connection(write=True) as db:
            # Owner quota and project mutations use a consistent lock order.
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('project-quota:'+owner,))
            self._project(db,owner,key,lock=True)
            row=db.execute('SELECT snapshot_id FROM v3_project_snapshots WHERE project_id=%s AND content_hash=%s',(key,content_hash)).fetchone()
            if row:snapshot=row['snapshot_id']
            else:
                stored=db.execute('''SELECT COALESCE(SUM(octet_length(f.text)),0) AS n FROM v3_project_files f
                    JOIN v3_project_snapshots s USING(snapshot_id) JOIN v3_projects p USING(project_id) WHERE p.owner_id=%s''',(owner,)).fetchone()['n']
                if stored+sum(len(t.encode()) for t in files.values())>100*1024*1024:raise WorkspaceConflict('project_storage_quota_reached')
                if db.execute('SELECT COUNT(*) AS n FROM v3_project_snapshots WHERE project_id=%s',(key,)).fetchone()['n']>=10:raise WorkspaceConflict('project_snapshot_quota_reached')
                snapshot='snapshot-'+uuid4().hex
                db.execute('''INSERT INTO v3_project_snapshots(snapshot_id,project_id,content_hash,origin,commit_sha,metadata,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''',(snapshot,key,content_hash,origin,commit_sha,encoded(metadata or {}),now()))
                with db.cursor() as cur:cur.executemany('INSERT INTO v3_project_files VALUES (%s,%s,%s,%s)',[(snapshot,p,manifest[p],t) for p,t in sorted(files.items())])
            db.execute('UPDATE v3_projects SET current_snapshot=%s,index_status=%s WHERE project_id=%s',(snapshot,'pending_index',key))
        return self.get_project(owner,key)

    import_zip=LongTermRepository.import_zip
    add_document=LongTermRepository.add_document

    def files(self,owner,key,snapshot):
        with self.workspace._connection() as db:
            self._project(db,owner,key)
            row=db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=%s AND snapshot_id=%s',(key,snapshot)).fetchone()
            if row is None:raise WorkspaceNotFound('snapshot_not_found')
            records=list(db.execute('SELECT * FROM v3_project_files WHERE snapshot_id=%s ORDER BY path',(snapshot,)))
            manifest={r['path']:r['content_hash'] for r in records}
            if any(sha256(r['text'].encode()).hexdigest()!=r['content_hash'] for r in records):raise WorkspaceConflict('project_file_integrity_failed')
            if digest({'files':manifest,'origin':row['origin'],'commit_sha':row['commit_sha']})!=row['content_hash']:raise WorkspaceConflict('project_snapshot_integrity_failed')
            return {r['path']:r['text'] for r in records}

    def read_file(self,owner,key,snapshot,path,*,db=None):
        checked_path(path)
        with (nullcontext(db) if db is not None else self.workspace._connection()) as db:
            self._project(db,owner,key)
            version=db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=%s AND snapshot_id=%s',(key,snapshot)).fetchone()
            if version is None:raise WorkspaceNotFound('snapshot_not_found')
            manifest={r['path']:r['content_hash'] for r in db.execute('SELECT path,content_hash FROM v3_project_files WHERE snapshot_id=%s ORDER BY path',(snapshot,))}
            if digest({'files':manifest,'origin':version['origin'],'commit_sha':version['commit_sha']})!=version['content_hash']:raise WorkspaceConflict('project_snapshot_integrity_failed')
            row=db.execute('SELECT text,content_hash FROM v3_project_files WHERE snapshot_id=%s AND path=%s',(snapshot,path)).fetchone()
            if row is None:raise WorkspaceNotFound('project_file_not_found')
            if sha256(row['text'].encode()).hexdigest()!=row['content_hash']:raise WorkspaceConflict('project_file_integrity_failed')
            return row['text'],dict(version)

    def delete_project(self,owner,key):
        with self.workspace._connection(write=True) as db:
            self._project(db,owner,key,lock=True);db.execute('DELETE FROM v3_projects WHERE project_id=%s',(key,))


class PostgresIndexTaskRepository:
    atomic_publication=True
    def __init__(self,database,projects,*,lease_seconds=30,config_identity='',dispatch_mode='polling'):
        if not .3<=lease_seconds<=120:raise ValueError('task_lease_seconds_invalid')
        self.workspace=database;self.projects=projects;self.lease_seconds=lease_seconds;self.config_identity=config_identity
        from job_agent.resume_workspace.index_dispatch import IndexDispatchRepository
        self.dispatch_mode=dispatch_mode;self.dispatch=IndexDispatchRepository(database,self,dispatch_mode)

    @staticmethod
    def event(db,task_id,kind):
        row=db.execute('UPDATE v3_tasks SET event_seq=event_seq+1 WHERE task_id=%s RETURNING event_seq,attempts',(task_id,)).fetchone()
        db.execute(f'INSERT INTO v3_task_events VALUES (%s,%s,%s,%s,{DB_NOW})',(task_id,row['event_seq'],kind,row['attempts']))

    def submit(self,owner,project_id,request):
        from job_agent.resume_workspace.code_rag import INDEX_VERSION
        self.projects.files(owner,project_id,request.snapshot_id)
        if not self.config_identity:raise WorkspaceConflict('task_index_config_required')
        hashed=digest({'project':project_id,'snapshot':request.snapshot_id,'kind':'code_index'})
        with self.workspace._connection(write=True) as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('v3-task-quota',))
            self.projects._project(db,owner,project_id,lock=True)
            snapshot=db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=%s AND snapshot_id=%s FOR UPDATE',(project_id,request.snapshot_id)).fetchone()
            if snapshot is None:raise WorkspaceNotFound('snapshot_not_found')
            old=db.execute('SELECT task_id,request_hash FROM v3_tasks WHERE owner_id=%s AND request_key=%s',(owner,request.request_key)).fetchone()
            if old:
                if old['request_hash']!=hashed:raise WorkspaceConflict('task_request_key_conflict')
                return old['task_id']
            active=list(db.execute("SELECT owner_id FROM v3_tasks WHERE status IN ('QUEUED','RUNNING')"))
            if len(active)>=20 or sum(r['owner_id']==owner for r in active)>=3:raise WorkspaceConflict('task_queue_quota_reached')
            generation=snapshot['desired_generation']+1;task_id='task-'+uuid4().hex
            db.execute('UPDATE v3_project_snapshots SET desired_generation=%s WHERE snapshot_id=%s',(generation,request.snapshot_id))
            db.execute(f'''INSERT INTO v3_tasks(task_id,owner_id,project_id,snapshot_id,request_key,request_hash,index_version,
                config_identity,generation,status,stage,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'QUEUED','queued',{DB_NOW},{DB_NOW})''',
                (task_id,owner,project_id,request.snapshot_id,request.request_key,hashed,INDEX_VERSION,self.config_identity,generation))
            self.event(db,task_id,'submitted')
            self.dispatch.enqueue(db,task_id,generation)
            return task_id

    def get(self,owner,task_id):
        with self.workspace._connection() as db:
            row=db.execute('SELECT * FROM v3_tasks WHERE owner_id=%s AND task_id=%s',(owner,task_id)).fetchone()
            if row is None:raise WorkspaceNotFound('task_not_found')
            return {k:row[k] for k in ('task_id','project_id','snapshot_id','status','stage','attempts','created_at','updated_at','error_code','generation','config_identity')}|{
                'result':json.loads(row['result']) if row['result'] else None,
                'events':[dict(r) for r in db.execute('SELECT seq,kind,attempt,recorded_at FROM v3_task_events WHERE task_id=%s ORDER BY seq',(task_id,))]}

    def history(self,owner,project_id):
        with self.workspace._connection() as db:
            self.projects._project(db,owner,project_id)
            ids=[r['task_id'] for r in db.execute('SELECT task_id FROM v3_tasks WHERE owner_id=%s AND project_id=%s ORDER BY created_at DESC LIMIT 100',(owner,project_id))]
        return [self.get(owner,tid) for tid in ids]

    def claim(self):
        if self.dispatch_mode!='polling':raise WorkspaceConflict('polling_worker_disabled')
        with self.workspace._connection(write=True) as db:
            self.dispatch.assert_mode(db)
            exhausted=list(db.execute(f'''UPDATE v3_tasks SET status='FAILED',stage='stopped',error_code='worker_recovery_exhausted',
                lease_token=NULL,updated_at={DB_NOW} WHERE status='RUNNING' AND lease_until<={DB_NOW} AND attempts>=3 RETURNING task_id'''))
            for row in exhausted:self.event(db,row['task_id'],'recovery_exhausted')
            stale=list(db.execute(f'''UPDATE v3_tasks t SET status='FAILED',stage='stopped',error_code='task_superseded',updated_at={DB_NOW}
                FROM v3_project_snapshots s WHERE t.snapshot_id=s.snapshot_id AND t.generation<>s.desired_generation AND t.status='QUEUED' RETURNING t.task_id'''))
            for row in stale:self.event(db,row['task_id'],'superseded')
            row=db.execute(f'''SELECT * FROM v3_tasks WHERE status='QUEUED' OR
                (status='RUNNING' AND lease_until<={DB_NOW} AND attempts<3)
                ORDER BY created_at,task_id LIMIT 1 FOR UPDATE SKIP LOCKED''').fetchone()
            if row is None:return None
            claim=db.execute(f'''UPDATE v3_tasks SET status='RUNNING',stage='parsing',lease_token=%s,
                lease_until={DB_NOW}+%s,attempts=attempts+1,updated_at={DB_NOW} WHERE task_id=%s RETURNING *''',
                (uuid4().hex,self.lease_seconds,row['task_id'])).fetchone()
            self.event(db,row['task_id'],'claimed')
            return dict(claim)

    def guard(self,db,claim):
        self.dispatch.assert_mode(db)
        row=db.execute(f'SELECT *,lease_until>{DB_NOW} AS live FROM v3_tasks WHERE task_id=%s FOR UPDATE',(claim['task_id'],)).fetchone()
        if row is None or row['status']!='RUNNING' or not row['live'] or any(row[k]!=claim[k] for k in (
            'owner_id','project_id','snapshot_id','lease_token','generation','config_identity','index_version')):
            raise WorkspaceConflict('task_lease_lost')
        return row

    def heartbeat(self,claim):
        with self.workspace._connection(write=True) as db:
            self.guard(db,claim)
            db.execute(f'UPDATE v3_tasks SET lease_until={DB_NOW}+%s,updated_at={DB_NOW} WHERE task_id=%s',(self.lease_seconds,claim['task_id']))

    def finish_in_transaction(self,db,claim,result):
        self.guard(db,claim) # Re-check real database time after all derived writes.
        db.execute(f"UPDATE v3_tasks SET status='SUCCEEDED',stage='completed',result=%s,lease_token=NULL,updated_at={DB_NOW} WHERE task_id=%s",
            (encoded(result),claim['task_id']))
        self.event(db,claim['task_id'],'publication_committed')

    def complete(self,claim,result):raise WorkspaceConflict('task_completion_requires_publication')

    def fail(self,claim,code):
        with self.workspace._connection(write=True) as db:
            self.guard(db,claim)
            db.execute(f"UPDATE v3_tasks SET status='FAILED',stage='stopped',error_code=%s,lease_token=NULL,updated_at={DB_NOW} WHERE task_id=%s",(code,claim['task_id']))
            self.event(db,claim['task_id'],'failed')

    def cancel(self,owner,task_id):
        with self.workspace._connection(write=True) as db:
            row=db.execute('SELECT status FROM v3_tasks WHERE owner_id=%s AND task_id=%s FOR UPDATE',(owner,task_id)).fetchone()
            if row is None:raise WorkspaceNotFound('task_not_found')
            if row['status']=='CANCELLED':return
            if row['status']!='QUEUED':raise WorkspaceConflict('only_queued_task_can_be_cancelled')
            db.execute(f"UPDATE v3_tasks SET status='CANCELLED',stage='cancelled',updated_at={DB_NOW} WHERE task_id=%s",(task_id,))
            self.event(db,task_id,'cancelled')


class PostgresCodeIndexRepository:
    backend='postgresql'
    def __init__(self,database,projects,tasks):
        self.workspace=database;self.projects=projects;self.tasks=tasks;self.failpoint=None

    def _active(self,db,owner,project_id,snapshot):
        self.projects._project(db,owner,project_id)
        row=db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=%s AND snapshot_id=%s',(project_id,snapshot)).fetchone()
        if row is None:raise WorkspaceNotFound('snapshot_not_found')
        return row['active_publication']

    def publish(self,owner,project_id,snapshot,report,symbols,chunks,edges,vector_artifact,*,publish_guard=None,task_claim=None):
        from job_agent.resume_workspace.code_rag import public_report
        payload=encoded(report);publication='publication-'+uuid4().hex
        with self.workspace._connection(write=True) as db:
            self.projects._project(db,owner,project_id,lock=True)
            row=db.execute('SELECT * FROM v3_project_snapshots WHERE project_id=%s AND snapshot_id=%s FOR UPDATE',(project_id,snapshot)).fetchone()
            if row is None:raise WorkspaceNotFound('snapshot_not_found')
            if task_claim:
                self.tasks.guard(db,task_claim)
                if row['desired_generation']!=task_claim['generation']:raise WorkspaceConflict('task_superseded')
                if (task_claim['owner_id'],task_claim['project_id'],task_claim['snapshot_id'])!=(owner,project_id,snapshot):raise WorkspaceConflict('task_scope_changed')
                if task_claim['config_identity']!=report['indexing_config_identity']:raise WorkspaceConflict('task_index_config_changed')
                generation=task_claim['generation']
            else:
                generation=row['desired_generation']+1
                db.execute('UPDATE v3_project_snapshots SET desired_generation=%s WHERE snapshot_id=%s',(generation,snapshot))
            if publish_guard:publish_guard(db)
            db.execute('INSERT INTO v3_index_publications VALUES (%s,%s,%s,%s,%s,%s)',
                (publication,snapshot,report['index_version'],payload,sha256(payload.encode()).hexdigest(),generation))
            with db.cursor() as cur:
                cur.executemany('INSERT INTO v3_index_symbols VALUES (%s,%s,%s)',[(publication,s['symbol_id'],encoded(s)) for s in symbols])
                cur.executemany('INSERT INTO v3_index_chunks VALUES (%s,%s,%s,%s)',[(publication,c.chunk_id,c.model_dump_json(),sha256(c.model_dump_json().encode()).hexdigest()) for c in chunks])
                cur.executemany('INSERT INTO v3_index_edges VALUES (%s,%s,%s,%s,%s)',[(publication,e['source_id'],e['target_id'],e['kind'],e['line']) for e in edges])
            if vector_artifact:
                vm,dimension,vectors=vector_artifact
                db.execute('INSERT INTO v3_index_vectors VALUES (%s,%s,%s,%s,%s)',(publication,vm.key,dimension,vectors,sha256(vectors.encode()).hexdigest()))
            if self.failpoint:self.failpoint('after_derived_before_pointer',db)
            db.execute('UPDATE v3_project_snapshots SET active_publication=%s WHERE snapshot_id=%s',(publication,snapshot))
            db.execute("UPDATE v3_projects SET index_status='indexed' WHERE project_id=%s AND current_snapshot=%s",(project_id,snapshot))
            result={**public_report(report),'publication_id':publication,'generation':generation,'storage_backend':'postgresql'}
            if task_claim:self.tasks.finish_in_transaction(db,task_claim,result)
            if self.failpoint:self.failpoint('before_publication_commit',db)
        return {'publication_id':publication,'generation':generation,'storage_backend':'postgresql'}

    def report(self,owner,project_id,snapshot):
        with self.workspace._connection() as db:
            publication=self._active(db,owner,project_id,snapshot)
            return db.execute('SELECT * FROM v3_index_publications WHERE publication_id=%s AND snapshot_id=%s',(publication,snapshot)).fetchone() if publication else None

    def load(self,owner,project_id,snapshot):
        # Pointer and all immutable rows share one repeatable-read snapshot.
        with self.workspace._connection() as db:
            publication=self._active(db,owner,project_id,snapshot)
            report=db.execute('SELECT * FROM v3_index_publications WHERE publication_id=%s AND snapshot_id=%s',(publication,snapshot)).fetchone() if publication else None
            if publication and report is None:raise WorkspaceConflict('code_publication_scope_invalid')
            return {'report':report,'symbols':list(db.execute('SELECT symbol_id,payload FROM v3_index_symbols WHERE publication_id=%s',(publication,))),
                'chunks':list(db.execute('SELECT payload,payload_hash FROM v3_index_chunks WHERE publication_id=%s ORDER BY chunk_id',(publication,))),
                'edges':list(db.execute('SELECT source_id,target_id,kind,line FROM v3_index_edges WHERE publication_id=%s ORDER BY source_id,target_id,line',(publication,)))}

    def vector(self,owner,project_id,snapshot,identity):
        with self.workspace._connection() as db:
            publication=self._active(db,owner,project_id,snapshot)
            return db.execute('SELECT * FROM v3_index_vectors WHERE publication_id=%s AND model_id=%s',(publication,identity)).fetchone()

    def put_vector(self,owner,project_id,snapshot,identity,dimension,payload):
        with self.workspace._connection(write=True) as db:
            self.projects._project(db,owner,project_id,lock=True)
            publication=self._active(db,owner,project_id,snapshot)
            if not publication:raise WorkspaceConflict('code_index_not_ready')
            db.execute('INSERT INTO v3_index_vectors VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                (publication,identity,dimension,payload,sha256(payload.encode()).hexdigest()))


def postgres_persistence(dsn,*,schema='job_agent_v3',lease_seconds=30,dispatch_mode='polling'):
    from job_agent.resume_workspace.project_storage import ProjectPersistence
    database=PostgresProjectDatabase(dsn,schema=schema);projects=PostgresProjectRepository(database)
    try:tasks=PostgresIndexTaskRepository(database,projects,lease_seconds=lease_seconds,dispatch_mode=dispatch_mode)
    except BaseException:database.close();raise
    return ProjectPersistence(projects,PostgresCodeIndexRepository(database,projects,tasks),tasks,'postgresql',database)
