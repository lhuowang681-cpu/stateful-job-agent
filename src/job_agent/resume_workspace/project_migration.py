"""Offline, non-destructive SQLite project-domain snapshot to an EMPTY PG schema.

Caller must quiesce the source writers and keep them stopped through cutover.
This migrates the project domain only; it is not a distributed live migration.
"""
from hashlib import sha256
import json,sqlite3
from pathlib import Path
from job_agent.resume_workspace.long_term import encoded,digest
from job_agent.resume_workspace.repository import WorkspaceConflict

TABLES=('v3_projects','v3_project_snapshots','v3_project_files','v3_code_indexes',
        'v3_code_symbols','v3_code_chunks','v3_code_edges','v3_code_vectors','v3_tasks')
PG_TABLES=('v3_projects','v3_project_snapshots','v3_project_files','v3_index_publications',
           'v3_index_symbols','v3_index_chunks','v3_index_edges','v3_index_vectors','v3_tasks','v3_task_events')
TASK_COLUMNS=('task_id','owner_id','project_id','snapshot_id','request_key','request_hash','index_version',
              'status','stage','result','error_code','lease_token','lease_until','attempts','created_at','updated_at')


def canonical(data):
    return {table:sorted(data.get(table,[]),key=encoded) for table in TABLES}


def sqlite_snapshot(source,backup):
    source=Path(source).resolve();backup=Path(backup).resolve()
    if not source.is_file() or source==backup:raise ValueError('migration_source_invalid')
    # Reserve the backup name: never replace a previous rollback artifact.
    backup.parent.mkdir(parents=True,exist_ok=True)
    with backup.open('xb'):pass
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as db,sqlite3.connect(backup) as target:
            db.execute('BEGIN');db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
            db.backup(target)
        with sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            existing={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'v3_projects','v3_project_snapshots','v3_project_files'}<=existing:raise WorkspaceConflict('migration_source_schema_missing')
            data=canonical({t:[dict(r) for r in db.execute('SELECT * FROM '+t)] if t in existing else [] for t in TABLES})
        validate(data)
        return data,{'source_domain_identity':digest(data),'counts':{t:len(data[t]) for t in TABLES},
            'backup_sha256':sha256(backup.read_bytes()).hexdigest(),'backup_path':str(backup),
            'stable_ids_preserved':True,'active_source_writers_allowed':False}
    except BaseException:
        # Keep even a rejected backup for diagnosis; never delete user source data.
        raise


def validate(data):
    projects={r['project_id']:r for r in data['v3_projects']}
    snapshots={r['snapshot_id']:r for r in data['v3_project_snapshots']}
    indexes={r['snapshot_id']:r for r in data['v3_code_indexes']}
    for row in projects.values():
        current=row['current_snapshot']
        if current and (current not in snapshots or snapshots[current]['project_id']!=row['project_id']):raise WorkspaceConflict('migration_current_snapshot_invalid')
    for snapshot,row in snapshots.items():
        if row['project_id'] not in projects:raise WorkspaceConflict('migration_snapshot_parent_invalid')
        files=[f for f in data['v3_project_files'] if f['snapshot_id']==snapshot]
        manifest={f['path']:f['content_hash'] for f in files}
        if any(sha256(f['text'].encode()).hexdigest()!=f['content_hash'] for f in files):raise WorkspaceConflict('migration_source_file_integrity_failed')
        if digest({'files':manifest,'origin':row['origin'],'commit_sha':row['commit_sha']})!=row['content_hash']:raise WorkspaceConflict('migration_source_manifest_invalid')
        index=indexes.get(snapshot)
        if index:
            if sha256(index['payload'].encode()).hexdigest()!=index['payload_hash']:raise WorkspaceConflict('migration_index_hash_invalid')
            report=json.loads(index['payload'])
            symbols={r['symbol_id']:sha256(r['payload'].encode()).hexdigest() for r in data['v3_code_symbols'] if r['snapshot_id']==snapshot}
            chunks={json.loads(r['payload'])['chunk_id']:sha256(r['payload'].encode()).hexdigest() for r in data['v3_code_chunks'] if r['snapshot_id']==snapshot}
            edges=[{k:r[k] for k in ('source_id','target_id','kind','line')} for r in data['v3_code_edges'] if r['snapshot_id']==snapshot]
            if report['file_manifest_hash']!=digest(manifest) or symbols!=report['symbol_payload_hashes'] or chunks!=report['chunk_payload_hashes'] or digest(sorted(edges,key=lambda e:(e['source_id'],e['target_id'],e['kind'],e['line'])))!=report['edges_hash']:
                raise WorkspaceConflict('migration_index_manifest_invalid')
    for table in TABLES[2:8]:
        for row in data[table]:
            if row['snapshot_id'] not in snapshots or (table.startswith('v3_code_') and table!='v3_code_indexes' and row['snapshot_id'] not in indexes):raise WorkspaceConflict('migration_derived_parent_invalid')
            if 'payload_hash' in row and sha256(row['payload'].encode()).hexdigest()!=row['payload_hash']:raise WorkspaceConflict('migration_payload_hash_invalid')
    for row in data['v3_tasks']:
        if row['status'] not in ('SUCCEEDED','FAILED','CANCELLED'):raise WorkspaceConflict('migration_requires_quiesced_terminal_tasks')
        p=projects.get(row['project_id']);s=snapshots.get(row['snapshot_id'])
        if not p or not s or p['owner_id']!=row['owner_id'] or s['project_id']!=row['project_id']:raise WorkspaceConflict('migration_task_scope_invalid')


def target_snapshot(db):
    data={t:[] for t in TABLES}
    for table,columns in (
        ('v3_projects','project_id,owner_id,payload,created_at,current_snapshot,index_status'),
        ('v3_project_snapshots','snapshot_id,project_id,content_hash,origin,commit_sha,metadata,created_at'),
        ('v3_project_files','snapshot_id,path,content_hash,text'),
        ('v3_tasks',','.join(TASK_COLUMNS))):
        data[table]=[dict(r) for r in db.execute('SELECT '+columns+' FROM '+table)]
    publications=list(db.execute('SELECT p.* FROM v3_index_publications p JOIN v3_project_snapshots s ON s.active_publication=p.publication_id'))
    for pub in publications:
        snapshot=pub['snapshot_id'];pid=pub['publication_id']
        data['v3_code_indexes'].append({k:pub[k] for k in ('snapshot_id','parser_version','payload','payload_hash')})
        for legacy,target,columns in (
            ('v3_code_symbols','v3_index_symbols','symbol_id,payload'),('v3_code_chunks','v3_index_chunks','chunk_id,payload,payload_hash'),
            ('v3_code_edges','v3_index_edges','source_id,target_id,kind,line'),('v3_code_vectors','v3_index_vectors','model_id,dimension,payload,payload_hash')):
            data[legacy].extend({'snapshot_id':snapshot,**dict(r)} for r in db.execute('SELECT '+columns+' FROM '+target+' WHERE publication_id=%s',(pid,)))
    return canonical(data)


def import_to_empty_postgres(bundle,data):
    from job_agent.resume_workspace.postgres_projects import PostgresIndexTaskRepository
    validate(data)
    if bundle.backend!='postgresql':raise ValueError('migration_target_postgres_required')
    publications={r['snapshot_id']:'publication-migrated-'+digest([r['snapshot_id'],r['payload_hash']])[:32] for r in data['v3_code_indexes']}
    generation={r['snapshot_id']:0 for r in data['v3_project_snapshots']};task_generations={}
    for row in sorted(data['v3_tasks'],key=lambda r:(r['created_at'],r['task_id'])):
        generation[row['snapshot_id']]+=1;task_generations[row['task_id']]=generation[row['snapshot_id']]
    with bundle.database._connection(write=True) as db:
        db.execute('LOCK TABLE '+','.join(PG_TABLES)+' IN ACCESS EXCLUSIVE MODE')
        if any(db.execute('SELECT COUNT(*) AS n FROM '+t).fetchone()['n'] for t in PG_TABLES):raise WorkspaceConflict('migration_target_not_empty')
        for row in data['v3_projects']:
            db.execute('INSERT INTO v3_projects VALUES (%s,%s,%s,%s,%s,%s)',tuple(row[k] for k in ('project_id','owner_id','payload','created_at','current_snapshot','index_status')))
        for row in data['v3_project_snapshots']:
            db.execute('INSERT INTO v3_project_snapshots VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                tuple(row[k] for k in ('snapshot_id','project_id','content_hash','origin','commit_sha','metadata','created_at'))+(generation[row['snapshot_id']],publications.get(row['snapshot_id'])))
        for row in data['v3_project_files']:
            db.execute('INSERT INTO v3_project_files VALUES (%s,%s,%s,%s)',tuple(row[k] for k in ('snapshot_id','path','content_hash','text')))
        for row in data['v3_code_indexes']:
            db.execute('INSERT INTO v3_index_publications VALUES (%s,%s,%s,%s,%s,%s)',(publications[row['snapshot_id']],)+tuple(row[k] for k in ('snapshot_id','parser_version','payload','payload_hash'))+(generation[row['snapshot_id']],))
        for legacy,target,columns in (
            ('v3_code_symbols','v3_index_symbols',('symbol_id','payload')),
            ('v3_code_chunks','v3_index_chunks',('chunk_id','payload','payload_hash')),
            ('v3_code_edges','v3_index_edges',('source_id','target_id','kind','line')),
            ('v3_code_vectors','v3_index_vectors',('model_id','dimension','payload','payload_hash'))):
            for row in data[legacy]:db.execute('INSERT INTO '+target+' VALUES ('+','.join(['%s']*(len(columns)+1))+')',(publications[row['snapshot_id']],)+tuple(row[k] for k in columns))
        reports={r['snapshot_id']:json.loads(r['payload']) for r in data['v3_code_indexes']}
        for row in data['v3_tasks']:
            columns=TASK_COLUMNS+('config_identity','generation','event_seq')
            # Terminal legacy results keep their original IDs, payloads and lease fields.
            values=tuple(row[k] for k in TASK_COLUMNS)+(reports.get(row['snapshot_id'],{}).get('indexing_config_identity','legacy-unbound'),task_generations[row['task_id']],0)
            db.execute('INSERT INTO v3_tasks('+','.join(columns)+') VALUES ('+','.join(['%s']*len(columns))+')',values)
            PostgresIndexTaskRepository.event(db,row['task_id'],'migrated_terminal')
        observed=target_snapshot(db)
        if digest(observed)!=digest(data):raise WorkspaceConflict('migration_target_verification_failed')
        # Deferred composite FKs are checked before reporting success.
        db.execute('SET CONSTRAINTS ALL IMMEDIATE')
    return {'target_domain_identity':digest(observed),'counts':{t:len(observed[t]) for t in TABLES},
        'publication_map':publications,'stable_ids_preserved':True,'atomic_import_verified':True}
