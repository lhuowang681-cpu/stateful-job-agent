"""Transactional wake-ups for rebuildable indexes. PG remains authoritative."""
from dataclasses import dataclass
from hashlib import sha256
import json,re
from uuid import uuid4
from job_agent.resume_workspace.long_term import encoded
from job_agent.resume_workspace.repository import WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.postgres_projects import DB_NOW

DISPATCH_DDL='''
CREATE TABLE v3_dispatch_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 authority TEXT NOT NULL,mode TEXT NOT NULL CHECK(mode IN ('polling','redis')));
CREATE TABLE v3_index_outbox(event_id TEXT PRIMARY KEY,task_id TEXT NOT NULL UNIQUE REFERENCES v3_tasks ON DELETE CASCADE,
 generation BIGINT NOT NULL,created_at DOUBLE PRECISION NOT NULL,available_at DOUBLE PRECISION NOT NULL,
 published_at DOUBLE PRECISION,send_attempts INTEGER NOT NULL DEFAULT 0,error_code TEXT,
 publisher_token TEXT,publisher_until DOUBLE PRECISION NOT NULL DEFAULT 0,exhausted BOOLEAN NOT NULL DEFAULT FALSE);
CREATE INDEX v3_index_outbox_due ON v3_index_outbox(exhausted,published_at,available_at,publisher_until);
CREATE TABLE v3_dispatch_archive(stream_id TEXT PRIMARY KEY,event_id TEXT,task_id TEXT,reason TEXT NOT NULL,
 payload_digest TEXT NOT NULL,recorded_at DOUBLE PRECISION NOT NULL);
'''
TERMINAL={'SUCCEEDED','FAILED','CANCELLED'}


class IndexDispatchRepository:
    max_sends=12
    def __init__(self,database,tasks,mode):
        if mode not in ('polling','redis'):raise ValueError('index_dispatch_mode_invalid')
        self.database=database;self.tasks=tasks;self.mode=mode
        with database._connection(write=True) as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(database.schema+':schema',))
            prior=db.execute("SELECT ddl_hash FROM v3_schema_migrations WHERE version='index-dispatch-2'").fetchone()
            expected=sha256(DISPATCH_DDL.encode()).hexdigest()
            if prior and prior['ddl_hash']!=expected:raise WorkspaceConflict('dispatch_schema_migration_required')
            if prior is None:
                db.execute(DISPATCH_DDL)
                db.execute('INSERT INTO v3_schema_migrations VALUES (%s,%s)',('index-dispatch-2',expected))
                # Pre-S6 scopes bind polling; explicit maintenance can switch later.
                existing=db.execute('SELECT COUNT(*) AS n FROM v3_tasks').fetchone()['n']
                db.execute('INSERT INTO v3_dispatch_control VALUES (1,%s,%s)',('authority-'+uuid4().hex,'polling' if existing else mode))
            row=db.execute('SELECT * FROM v3_dispatch_control WHERE singleton=1').fetchone()
            if row['mode']!=mode:raise WorkspaceConflict('index_dispatch_mode_conflict')
            self.authority=row['authority']

    def assert_mode(self,db):
        db.execute('SELECT pg_advisory_xact_lock_shared(hashtextextended(%s,0))',(self.database.schema+':dispatch-mode',))
        current=db.execute('SELECT mode,authority FROM v3_dispatch_control WHERE singleton=1').fetchone()
        if current['mode']!=self.mode or current['authority']!=self.authority:
            raise WorkspaceConflict('index_dispatch_mode_changed')

    def change_mode(self,mode):
        if mode not in ('polling','redis'):raise ValueError('index_dispatch_mode_invalid')
        with self.database._connection(write=True) as db:
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(self.database.schema+':dispatch-mode',))
            if db.execute("SELECT 1 FROM v3_tasks WHERE status IN ('QUEUED','RUNNING') LIMIT 1").fetchone():
                raise WorkspaceConflict('dispatch_switch_requires_quiesced_tasks')
            # Rotate the persisted epoch even for A→B→A: an old A process must
            # never become authorized again simply because the mode name matches.
            db.execute('UPDATE v3_dispatch_control SET mode=%s,authority=%s WHERE singleton=1',(mode,'authority-'+uuid4().hex))
        # Deliberately do not mutate this adapter: old processes must reopen.

    def enqueue(self,db,task_id,generation):
        self.assert_mode(db)
        if self.mode=='redis':db.execute(f'''INSERT INTO v3_index_outbox(event_id,task_id,generation,created_at,available_at)
            VALUES (%s,%s,%s,{DB_NOW},{DB_NOW})''',('wake-'+uuid4().hex,task_id,generation))

    def take_pending(self,limit=20):
        if self.mode!='redis':raise WorkspaceConflict('redis_dispatch_required')
        with self.database._connection(write=True) as db:
            self.assert_mode(db)
            rows=list(db.execute(f'''SELECT o.* FROM v3_index_outbox o JOIN v3_tasks t USING(task_id)
                WHERE NOT o.exhausted AND o.published_at IS NULL AND o.available_at<={DB_NOW}
                AND o.publisher_until<={DB_NOW} AND o.send_attempts<%s
                AND (t.status='QUEUED' OR (t.status='RUNNING' AND t.lease_until<={DB_NOW}))
                ORDER BY o.created_at LIMIT %s FOR UPDATE OF o SKIP LOCKED''',(self.max_sends,max(1,min(limit,100)))))
            for row in rows:
                token=uuid4().hex
                db.execute(f'UPDATE v3_index_outbox SET publisher_token=%s,publisher_until={DB_NOW}+10,send_attempts=send_attempts+1 WHERE event_id=%s',(token,row['event_id']))
                row.update(publisher_token=token,send_attempts=row['send_attempts']+1,authority=self.authority)
            return rows

    def published(self,event):
        with self.database._connection(write=True) as db:
            self.assert_mode(db)
            row=db.execute(f'''UPDATE v3_index_outbox SET published_at={DB_NOW},publisher_token=NULL,publisher_until=0,error_code=NULL
                WHERE event_id=%s AND publisher_token=%s AND publisher_until>{DB_NOW} RETURNING event_id''',
                (event['event_id'],event['publisher_token'])).fetchone()
            if row is None:raise WorkspaceConflict('outbox_publisher_lease_lost')

    def publish_failed(self,event):
        with self.database._connection(write=True) as db:
            self.assert_mode(db)
            # Consistent task→outbox order with execution retry and reconciliation.
            task=db.execute(f'SELECT *,lease_until>{DB_NOW} AS live FROM v3_tasks WHERE task_id=%s FOR UPDATE',(event['task_id'],)).fetchone()
            row=db.execute(f'''UPDATE v3_index_outbox SET error_code='redis_unavailable',publisher_token=NULL,publisher_until=0,
                exhausted=(send_attempts>=%s),available_at={DB_NOW}+LEAST(60,POWER(2,LEAST(send_attempts-1,6)))
                WHERE event_id=%s AND publisher_token=%s AND publisher_until>{DB_NOW} RETURNING *''',
                (self.max_sends,event['event_id'],event['publisher_token'])).fetchone()
            if row and row['exhausted'] and task and (task['status']=='QUEUED' or (task['status']=='RUNNING' and not task['live'])):
                self._terminal(db,task['task_id'],'dispatch_retry_exhausted')

    def _terminal(self,db,task_id,code):
        db.execute(f"UPDATE v3_tasks SET status='FAILED',stage='stopped',error_code=%s,lease_token=NULL,updated_at={DB_NOW} WHERE task_id=%s",(code,task_id))
        self.tasks.event(db,task_id,code)

    def claim_delivery(self,message):
        with self.database._connection(write=True) as db:
            self.assert_mode(db)
            if self.mode!='redis':raise WorkspaceConflict('redis_dispatch_required')
            if message['authority']!=self.authority:return 'rejected_event',None
            row=db.execute(f'SELECT *,lease_until>{DB_NOW} AS live FROM v3_tasks WHERE task_id=%s FOR UPDATE',(message['task_id'],)).fetchone()
            event=db.execute(f'SELECT *,available_at<={DB_NOW} AS due FROM v3_index_outbox WHERE event_id=%s',(message['event_id'],)).fetchone()
            if row is None:return 'unknown_task',None
            if not event or (event['task_id'],event['generation'])!=(row['task_id'],message['generation']) or row['generation']!=message['generation']:
                return 'rejected_event',None
            if row['status'] in TERMINAL:return row['status'],dict(row)
            if row['status']=='RUNNING' and row['live']:return 'busy',None
            if event['exhausted']:
                self._terminal(db,row['task_id'],'dispatch_retry_exhausted');return 'FAILED',dict(row)
            if not event['due']:return 'deferred',None
            if row['attempts']>=3:
                self._terminal(db,row['task_id'],'worker_recovery_exhausted');return 'FAILED',dict(row)
            generation=db.execute('SELECT desired_generation FROM v3_project_snapshots WHERE snapshot_id=%s',(row['snapshot_id'],)).fetchone()
            if generation is None or generation['desired_generation']!=row['generation']:
                self._terminal(db,row['task_id'],'task_superseded');return 'FAILED',dict(row)
            if row['config_identity']!=self.tasks.config_identity:return 'configuration_mismatch',None
            claim=db.execute(f'''UPDATE v3_tasks SET status='RUNNING',stage='parsing',lease_token=%s,lease_until={DB_NOW}+%s,
                attempts=attempts+1,updated_at={DB_NOW} WHERE task_id=%s RETURNING *''',(uuid4().hex,self.tasks.lease_seconds,row['task_id'])).fetchone()
            self.tasks.event(db,row['task_id'],'claimed')
            return 'claimed',dict(claim)

    def retry(self,claim):
        with self.database._connection(write=True) as db:
            self.tasks.guard(db,claim)
            if claim['attempts']>=3:self._terminal(db,claim['task_id'],'index_retry_exhausted');return
            db.execute(f"UPDATE v3_tasks SET status='QUEUED',stage='retry_wait',error_code='index_transient_failure',lease_token=NULL,lease_until=0,updated_at={DB_NOW} WHERE task_id=%s",(claim['task_id'],))
            db.execute(f'''UPDATE v3_index_outbox SET published_at=NULL,publisher_token=NULL,publisher_until=0,
                available_at={DB_NOW}+POWER(2,%s) WHERE task_id=%s''',(claim['attempts']-1,claim['task_id']))
            self.tasks.event(db,claim['task_id'],'retry_scheduled')

    def reconcile(self,*,age_seconds=30):
        if not .1<=age_seconds<=3600:raise ValueError('reconcile_age_invalid')
        changed=0
        with self.database._connection(write=True) as db:
            self.assert_mode(db)
            rows=list(db.execute(f'''SELECT t.task_id,o.event_id,o.send_attempts,o.published_at FROM v3_tasks t JOIN v3_index_outbox o USING(task_id)
                WHERE (t.status='QUEUED' OR (t.status='RUNNING' AND t.lease_until<={DB_NOW}))
                AND ((o.published_at IS NOT NULL AND o.published_at<={DB_NOW}-%s)
                OR (o.published_at IS NULL AND o.send_attempts>=%s AND o.publisher_until<={DB_NOW}))
                ORDER BY t.created_at LIMIT 100 FOR UPDATE OF t SKIP LOCKED''',(age_seconds,self.max_sends)))
            for row in rows:
                if row['send_attempts']>=self.max_sends:
                    code='dispatch_delivery_exhausted' if row['published_at'] is not None else 'dispatch_retry_exhausted'
                    self._terminal(db,row['task_id'],code)
                    db.execute('UPDATE v3_index_outbox SET exhausted=TRUE,error_code=%s WHERE event_id=%s',(code,row['event_id']))
                else:
                    db.execute(f'UPDATE v3_index_outbox SET published_at=NULL,publisher_token=NULL,publisher_until=0,available_at={DB_NOW} WHERE event_id=%s',(row['event_id'],))
                    self.tasks.event(db,row['task_id'],'dispatch_reconciled')
                changed+=1
        return changed

    def archive(self,delivery,reason):
        allowed={'invalid_message','unknown_task','rejected_event','FAILED','task_deleted'}
        if reason not in allowed:raise ValueError('archive_reason_invalid')
        message=delivery.message or {}
        with self.database._connection(write=True) as db:
            db.execute(f'''INSERT INTO v3_dispatch_archive VALUES (%s,%s,%s,%s,%s,{DB_NOW}) ON CONFLICT DO NOTHING''',
                (delivery.stream_id,message.get('event_id'),message.get('task_id'),reason,delivery.digest))
            db.execute('''DELETE FROM v3_dispatch_archive WHERE stream_id IN
                (SELECT stream_id FROM v3_dispatch_archive ORDER BY recorded_at DESC,stream_id OFFSET 1000)''')

    def monitoring(self):
        with self.database._connection() as db:
            return {'mode':self.mode,'authority':self.authority,
                'outbox':dict(db.execute('''SELECT COUNT(*) FILTER(WHERE published_at IS NULL AND NOT exhausted) AS pending,
                    COUNT(*) FILTER(WHERE published_at IS NOT NULL) AS sent,COUNT(*) FILTER(WHERE exhausted) AS exhausted FROM v3_index_outbox''').fetchone()),
                'tasks':[dict(r) for r in db.execute('SELECT status,COUNT(*) AS count FROM v3_tasks GROUP BY status')],
                'dispatch_failures':[dict(r) for r in db.execute('SELECT event_id,task_id,send_attempts,error_code FROM v3_index_outbox WHERE exhausted LIMIT 100')],
                'archive':[dict(r) for r in db.execute('SELECT stream_id,event_id,task_id,reason,payload_digest,recorded_at FROM v3_dispatch_archive ORDER BY recorded_at DESC LIMIT 100')]}


@dataclass(frozen=True)
class IndexDelivery:
    stream_id:str
    message:dict|None
    digest:str


def decode_delivery(stream_id,fields):
    digest=sha256(encoded(fields).encode()).hexdigest()
    valid=set(fields)=={'authority','event_id','task_id','generation'} and all(isinstance(v,str) for v in fields.values())
    valid=valid and all(re.fullmatch(prefix+r'[a-f0-9]{32}',fields[key]) for key,prefix in (
        ('authority','authority-'),('event_id','wake-'),('task_id','task-')))
    valid=valid and bool(re.fullmatch(r'[1-9][0-9]{0,17}',fields['generation']))
    return IndexDelivery(stream_id,{**fields,'generation':int(fields['generation'])} if valid else None,digest)


class IndexOutboxPublisher:
    def __init__(self,repository,queue,*,failpoint=None):self.repository=repository;self.queue=queue;self.failpoint=failpoint
    def publish_once(self,limit=20):
        from redis.exceptions import RedisError
        sent=0
        # Lease only the next network operation, not an entire serial batch that
        # could expire while earlier slow sends consume its lease window.
        for _ in range(max(1,min(limit,100))):
            events=self.repository.take_pending(1)
            if not events:break
            event=events[0]
            try:self.queue.publish(event)
            except RedisError:self.repository.publish_failed(event);continue
            if self.failpoint:self.failpoint('after_xadd_before_outbox_mark')
            self.repository.published(event);sent+=1
        return sent


class RedisIndexWorker:
    def __init__(self,store,code,queue,*,consumer,min_idle_ms=1500,failpoint=None):
        from job_agent.resume_workspace.tasks import IndexTaskWorker
        if store.dispatch_mode!='redis':raise WorkspaceConflict('redis_dispatch_required')
        self.store=store;self.queue=queue;self.consumer=consumer;self.min_idle_ms=min_idle_ms;self.failpoint=failpoint
        self.executor=IndexTaskWorker(store,code,external_dispatch=True)

    def process(self,delivery):
        dispatch=self.store.dispatch
        if delivery.message is None:
            dispatch.archive(delivery,'invalid_message');self.queue.ack(delivery.stream_id);return 'invalid_message'
        disposition,claim=dispatch.claim_delivery(delivery.message)
        if disposition in ('busy','deferred','configuration_mismatch'):return disposition
        if disposition=='claimed':
            if self.failpoint:self.failpoint('after_claim')
            self.executor.process_claim(claim)
            try:disposition=self.store.get(claim['owner_id'],claim['task_id'])['status']
            except WorkspaceNotFound:disposition='task_deleted'
            if disposition not in TERMINAL|{'task_deleted'}:return disposition
            if self.failpoint:self.failpoint('after_commit_before_ack')
        if disposition in ('invalid_message','unknown_task','rejected_event','FAILED','task_deleted'):dispatch.archive(delivery,disposition)
        self.queue.ack(delivery.stream_id)
        return disposition

    def process_once(self,block_ms=200):
        from redis.exceptions import ResponseError
        try:
            deliveries=self.queue.reclaim(consumer_name=self.consumer,min_idle_ms=self.min_idle_ms,count=1)
            delivery=deliveries[0] if deliveries else self.queue.receive(consumer_name=self.consumer,block_ms=block_ms)
        except ResponseError as exc:
            if 'NOGROUP' not in str(exc):raise
            self.queue.ensure_group();self.queue.reclaim_cursor='0-0';return None
        if delivery is None:return None
        return self.process(delivery)
