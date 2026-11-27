"""Same business contract on SQLite and opt-in REAL PostgreSQL, no model quality claims."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from time import sleep
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.project_storage import sqlite_persistence,persistence_from_env
from job_agent.resume_workspace.long_term import ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery
from job_agent.resume_workspace.tasks import IndexTaskRequest,IndexTaskWorker
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime
from test_v3_retrieval_identity import FixtureBackend

FILES={'storage.py':'def receipt(key, store):\n    return store.setdefault(key, "done")\n',
       'api.py':'from storage import receipt\n\ndef handle(key, store):\n    return receipt(key, store)\n'}


@pytest.fixture(params=['sqlite','postgresql'])
def storage(request,tmp_path):
    ws=SqliteResumeRepository(tmp_path/'resume.sqlite')
    if request.param=='sqlite':bundle=sqlite_persistence(ws)
    else:
        dsn=os.environ.get('JOB_AGENT_TEST_PROJECT_DSN')
        if not dsn:pytest.skip('real PostgreSQL DSN is required')
        from job_agent.resume_workspace.postgres_projects import postgres_persistence
        bundle=postgres_persistence(dsn,schema='s5_test_'+uuid4().hex,lease_seconds=2)
    model=FixtureBackend();runtime=RetrievalRuntime(model,model.identity)
    code=CodeRAGService(ws,projects=bundle.projects,indexes=bundle.indexes,
        embedding_backend=model,embedding_identity=model.identity)
    if hasattr(bundle.tasks,'config_identity'):bundle.tasks.config_identity=code.indexing_config_identity
    p=bundle.projects.create_project('alice',ProjectCreate(name='Synthetic PG contract'))
    p=bundle.projects.publish_files('alice',p['project_id'],FILES,origin='zip')
    yield ws,bundle,p,code,runtime
    if bundle.backend=='postgresql':
        import psycopg
        from psycopg import sql
        dsn=bundle.database.dsn;schema=bundle.database.schema
        bundle.close()
        with psycopg.connect(dsn,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def request(p,key='contract-index-request'):
    return IndexTaskRequest(snapshot_id=p['current_snapshot'],request_key=key)


def test_owner_immutable_history_and_exact_reference(storage):
    _,bundle,p,code,_=storage;pid=p['project_id'];snap=p['current_snapshot']
    code.build('alice',pid,snap)
    ref=code.read_code_range('alice',pid,snap,'storage.py',1,2)
    assert code.validate_reference('alice',ref)==ref
    with pytest.raises(WorkspaceNotFound):code.validate_reference('bob',ref)
    assert bundle.projects.publish_files('alice',pid,FILES,origin='zip')['current_snapshot']==snap
    newer=bundle.projects.publish_files('alice',pid,{**FILES,'other.py':'value=2\n'},origin='zip')
    assert newer['current_snapshot']!=snap
    assert code.validate_reference('alice',ref).quote==FILES['storage.py']


def test_queue_request_conflict_owner_and_worker_publication(storage):
    _,bundle,p,code,_=storage;store=bundle.tasks;pid=p['project_id']
    tid=store.submit('alice',pid,request(p))
    assert store.submit('alice',pid,request(p))==tid
    with pytest.raises(WorkspaceNotFound):store.get('bob',tid)
    other=bundle.projects.publish_files('alice',pid,{**FILES,'new.py':'x=1\n'},origin='zip')
    with pytest.raises(WorkspaceConflict,match='key_conflict'):store.submit('alice',pid,request(other))
    assert IndexTaskWorker(store,code).process_once()
    assert store.get('alice',tid)['status']=='SUCCEEDED'
    assert code.search('alice',pid,CodeQuery(snapshot_id=p['current_snapshot'],query='receipt'))['hits']
    assert store.history('alice',pid)[0]['task_id']==tid


def test_concurrent_claim_single_winner_and_cancel(storage):
    _,bundle,p,_,_=storage;store=bundle.tasks
    tid=store.submit('alice',p['project_id'],request(p))
    with ThreadPoolExecutor(2) as pool:claims=list(pool.map(lambda _:store.claim(),range(2)))
    assert sum(c is not None for c in claims)==1
    with pytest.raises(WorkspaceConflict):store.cancel('alice',tid)
    store.fail(next(c for c in claims if c),'synthetic_failure')
    cancelled=store.submit('alice',p['project_id'],request(p,'cancel-request-key'))
    store.cancel('alice',cancelled);store.cancel('alice',cancelled)
    assert store.get('alice',cancelled)['status']=='CANCELLED' and store.claim() is None


def test_concurrent_owner_project_quota_has_one_remaining_slot(storage):
    _,bundle,_,_,_=storage
    for i in range(18):bundle.projects.create_project('alice',ProjectCreate(name=f'Synthetic quota {i}'))
    def create(i):
        try:return bundle.projects.create_project('alice',ProjectCreate(name=f'Concurrent last slot {i}'))['project_id']
        except WorkspaceConflict as exc:return str(exc)
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(create,range(2)))
    assert results.count('project_quota_reached')==1
    assert len(bundle.projects.list_projects('alice'))==20
    assert bundle.projects.create_project('bob',ProjectCreate(name='Other owner unaffected'))['project_id']


def test_snapshot_quota_dedup_and_file_limits(storage):
    _,bundle,p,_,_=storage;pid=p['project_id']
    with pytest.raises(WorkspaceConflict,match='file_rejected'):
        bundle.projects.publish_files('alice',pid,{'large.txt':'x'*(256*1024+1)},origin='zip')
    for i in range(9):p=bundle.projects.publish_files('alice',pid,{'version.py':f'value={i}\n'},origin='zip')
    assert len(p['snapshots'])==10
    assert bundle.projects.publish_files('alice',pid,{'version.py':'value=8\n'},origin='zip')['current_snapshot']==p['current_snapshot']
    with pytest.raises(WorkspaceConflict,match='snapshot_quota'):
        bundle.projects.publish_files('alice',pid,{'version.py':'value=10\n'},origin='zip')


def test_dense_cache_restart_and_delete(storage):
    ws,bundle,p,code,runtime=storage;pid=p['project_id'];snap=p['current_snapshot']
    code.build('alice',pid,snap);builds=runtime.backend.documents
    reopened=CodeRAGService(ws,projects=bundle.projects,indexes=bundle.indexes,
        embedding_backend=runtime.backend,embedding_identity=runtime.identity)
    assert reopened.search('alice',pid,CodeQuery(snapshot_id=snap,query='receipt',method='dense'))['hits']
    assert runtime.backend.documents==builds
    bundle.projects.delete_project('alice',pid)
    with pytest.raises(WorkspaceNotFound):reopened.status('alice',pid,snap)
    if bundle.backend=='postgresql':
        with bundle.database._connection() as db:
            for table in ('v3_project_snapshots','v3_project_files','v3_index_publications','v3_index_symbols','v3_index_chunks','v3_index_edges','v3_index_vectors','v3_tasks','v3_task_events'):
                assert db.execute('SELECT COUNT(*) AS n FROM '+table).fetchone()['n']==0


def test_original_http_routes_use_selected_repository_without_shadow_writes(storage):
    ws,bundle,_,_,runtime=storage
    app=create_resume_app(ws,resolve_identity={'synthetic-a':'alice','synthetic-b':'bob'}.get,
        project_persistence=bundle,retrieval_runtime=runtime,task_worker_enabled=False)
    with TestClient(app) as client:
        h={'Authorization':'Bearer synthetic-a'};b={'Authorization':'Bearer synthetic-b'}
        assert client.get('/api/v2/capabilities',headers=h).json()['project_storage']==bundle.backend
        created=client.post('/api/v2/projects',headers=h,json={'name':'HTTP project'})
        assert created.status_code==201,created.text
        pid=created.json()['project_id']
        project=client.post(f'/api/v2/projects/{pid}/documents',headers=h,json={'path':'README.md','text':'# Synthetic receipt\n'}).json()
        response=client.post(f'/api/v2/projects/{pid}/index-tasks',headers=h,json=request(project).model_dump())
        assert response.status_code==202,response.text
        tid=response.json()['task_id'];assert app.state.index_worker.process_once()
        assert client.get(f'/api/v2/tasks/{tid}',headers=h).json()['status']=='SUCCEEDED'
        assert client.get(f'/api/v2/projects/{pid}',headers=b).status_code==404
        assert client.get(f'/api/v2/tasks/{tid}',headers=b).status_code==404
    if bundle.backend=='postgresql':
        with ws._connection() as db:
            for table in ('v3_projects','v3_code_indexes','v3_tasks'):
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                assert not exists or db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0


@pytest.fixture
def pg(storage):
    if storage[1].backend!='postgresql':pytest.skip('PG atomic publication contract only')
    return storage


def test_pg_all_derived_pointer_and_task_rollback_together(pg):
    _,bundle,p,code,_=pg;pid=p['project_id'];snap=p['current_snapshot'];store=bundle.tasks
    code.build('alice',pid,snap);before=bundle.indexes.report('alice',pid,snap)['publication_id']
    tid=store.submit('alice',pid,request(p));claim=store.claim()
    def fault(stage,db):
        if stage=='before_publication_commit':raise RuntimeError('synthetic_transaction_abort')
    bundle.indexes.failpoint=fault
    with pytest.raises(RuntimeError):code.build('alice',pid,snap,task_claim=claim)
    assert bundle.indexes.report('alice',pid,snap)['publication_id']==before
    assert store.get('alice',tid)['status']=='RUNNING'
    with bundle.database._connection() as db:assert db.execute('SELECT COUNT(*) AS n FROM v3_index_publications').fetchone()['n']==1
    bundle.indexes.failpoint=None;code.build('alice',pid,snap,task_claim=claim)
    assert store.get('alice',tid)['status']=='SUCCEEDED'
    assert store.get('alice',tid)['events'][-1]['kind']=='publication_committed'


def test_pg_newer_generation_fences_live_old_worker(pg):
    _,bundle,p,code,_=pg;store=bundle.tasks;pid=p['project_id'];snap=p['current_snapshot']
    old=store.submit('alice',pid,request(p));claim=store.claim()
    new=store.submit('alice',pid,request(p,'new-generation-key'))
    with pytest.raises(WorkspaceConflict,match='superseded'):code.build('alice',pid,snap,task_claim=claim)
    assert code.status('alice',pid,snap)['status']=='not_indexed'
    assert IndexTaskWorker(store,code).process_once()
    assert store.get('alice',new)['status']=='SUCCEEDED' and store.get('alice',old)['status']=='RUNNING'
    store.fail(claim,'task_superseded')


def test_pg_expired_lease_and_changed_encoder_cannot_publish(pg):
    _,bundle,p,code,runtime=pg;store=bundle.tasks;pid=p['project_id'];snap=p['current_snapshot']
    store.lease_seconds=.3;tid=store.submit('alice',pid,request(p));old=store.claim();sleep(.4)
    fresh=store.claim();assert fresh['attempts']==2
    with pytest.raises(WorkspaceConflict,match='lease_lost'):code.build('alice',pid,snap,task_claim=old)
    changed=FixtureBackend(replace(runtime.identity,revision='different'))
    wrong=CodeRAGService(code.workspace,projects=bundle.projects,indexes=bundle.indexes,embedding_backend=changed,embedding_identity=changed.identity)
    with pytest.raises(WorkspaceConflict,match='config_changed'):wrong.build('alice',pid,snap,task_claim=fresh)
    code.build('alice',pid,snap,task_claim=fresh)
    assert store.get('alice',tid)['status']=='SUCCEEDED'


def test_invalid_backend_never_silently_falls_back(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'ws.sqlite')
    with pytest.raises(ValueError,match='backend_invalid'):persistence_from_env(ws,{'JOB_AGENT_PROJECT_BACKEND':'pg_typo'})
    with pytest.raises(ValueError,match='dsn_required'):persistence_from_env(ws,{'JOB_AGENT_PROJECT_BACKEND':'postgresql'})


def test_pg_migration_hash_ids_quotes_dense_and_sqlite_rollback(pg,tmp_path):
    from job_agent.resume_workspace.project_migration import sqlite_snapshot,import_to_empty_postgres,digest
    from job_agent.resume_workspace.long_term import LongTermRepository
    import shutil
    ws,bundle,original,pg_code,runtime=pg
    bundle.projects.delete_project('alice',original['project_id'])
    source_ws=SqliteResumeRepository(tmp_path/'migration-source.sqlite');source=sqlite_persistence(source_ws)
    old_code=CodeRAGService(source_ws,embedding_backend=runtime.backend,embedding_identity=runtime.identity)
    p=source.projects.create_project('alice',ProjectCreate(name='Migration fixture'))
    p=source.projects.publish_files('alice',p['project_id'],FILES,origin='zip')
    tid=source.tasks.submit('alice',p['project_id'],request(p));IndexTaskWorker(source.tasks,old_code).process_once()
    reference=old_code.read_code_range('alice',p['project_id'],p['current_snapshot'],'storage.py',1,2)
    newer=source.projects.publish_files('alice',p['project_id'],{**FILES,'other.py':'x=2\n'},origin='zip')
    old_code.build('alice',p['project_id'],newer['current_snapshot'])
    source.projects.create_project('bob',ProjectCreate(name='Second owner fixture'))
    data,dry=sqlite_snapshot(source_ws.path,tmp_path/'rollback-backup.sqlite')
    applied=import_to_empty_postgres(bundle,data)
    assert applied['target_domain_identity']==dry['source_domain_identity']==digest(data)
    assert applied['counts']==dry['counts']
    assert bundle.projects.get_project('alice',p['project_id'])==source.projects.get_project('alice',p['project_id'])
    assert bundle.tasks.get('alice',tid)['status']=='SUCCEEDED'
    assert pg_code.validate_reference('alice',reference)==reference
    with pytest.raises(WorkspaceNotFound):pg_code.validate_reference('bob',reference)
    docs=runtime.backend.documents
    assert pg_code.search('alice',p['project_id'],CodeQuery(snapshot_id=p['current_snapshot'],query='receipt',method='dense'))['hits']
    assert runtime.backend.documents==docs
    with pytest.raises(WorkspaceConflict,match='target_not_empty'):import_to_empty_postgres(bundle,data)
    restored=tmp_path/'restored.sqlite';shutil.copy2(tmp_path/'rollback-backup.sqlite',restored)
    rollback=CodeRAGService(SqliteResumeRepository(restored),embedding_backend=runtime.backend,embedding_identity=runtime.identity)
    assert rollback.validate_reference('alice',reference)==reference
    assert rollback.search('alice',p['project_id'],CodeQuery(snapshot_id=p['current_snapshot'],query='receipt',method='dense'))['hits']


def test_migration_rejects_active_tasks_and_corruption(tmp_path):
    from job_agent.resume_workspace.project_migration import sqlite_snapshot
    ws=SqliteResumeRepository(tmp_path/'source.sqlite');bundle=sqlite_persistence(ws)
    p=bundle.projects.create_project('alice',ProjectCreate(name='Not quiesced fixture'))
    p=bundle.projects.publish_files('alice',p['project_id'],FILES,origin='zip')
    tid=bundle.tasks.submit('alice',p['project_id'],request(p))
    with pytest.raises(WorkspaceConflict,match='quiesced_terminal'):sqlite_snapshot(ws.path,tmp_path/'rejected-active.sqlite')
    bundle.tasks.cancel('alice',tid)
    with ws._connection(write=True) as db:db.execute("UPDATE v3_project_files SET text='corrupted'")
    with pytest.raises(WorkspaceConflict,match='file_integrity'):sqlite_snapshot(ws.path,tmp_path/'rejected-corruption.sqlite')
