"""SQLite persistence extracted from CodeRAG, retaining the historical table contract."""
from hashlib import sha256
from job_agent.resume_workspace.long_term import encoded
from job_agent.resume_workspace.repository import WorkspaceNotFound

_DDL='''
CREATE TABLE IF NOT EXISTS v3_code_indexes (
    snapshot_id TEXT PRIMARY KEY REFERENCES v3_project_snapshots(snapshot_id) ON DELETE CASCADE,
    parser_version TEXT NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v3_code_symbols (
    snapshot_id TEXT NOT NULL REFERENCES v3_code_indexes(snapshot_id) ON DELETE CASCADE,
    symbol_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(snapshot_id,symbol_id));
CREATE TABLE IF NOT EXISTS v3_code_chunks (
    snapshot_id TEXT NOT NULL REFERENCES v3_code_indexes(snapshot_id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,PRIMARY KEY(snapshot_id,chunk_id));
CREATE TABLE IF NOT EXISTS v3_code_edges (
    snapshot_id TEXT NOT NULL REFERENCES v3_code_indexes(snapshot_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,target_id TEXT NOT NULL,kind TEXT NOT NULL,line INTEGER NOT NULL,
    PRIMARY KEY(snapshot_id,source_id,target_id,kind,line));
CREATE TABLE IF NOT EXISTS v3_code_vectors (
    snapshot_id TEXT NOT NULL REFERENCES v3_code_indexes(snapshot_id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,dimension INTEGER NOT NULL,payload TEXT NOT NULL,payload_hash TEXT NOT NULL,
    PRIMARY KEY(snapshot_id,model_id));
'''

class SqliteCodeIndexRepository:
    backend='sqlite'
    def __init__(self,workspace,projects):
        self.workspace=workspace;self.projects=projects
        with workspace._connection(write=True) as db:db.executescript(_DDL)

    def publish(self,owner,project_id,snapshot,report,symbols,chunks,edges,vector_artifact,*,publish_guard=None,task_claim=None):
        payload=encoded(report)
        with self.workspace._connection(write=True) as db:
            self.projects._project(db,owner,project_id)
            if publish_guard is not None:publish_guard(db)
            if not db.execute('SELECT 1 FROM v3_project_snapshots WHERE project_id=? AND snapshot_id=?',(project_id,snapshot)).fetchone():raise WorkspaceNotFound('snapshot_not_found')
            db.execute('DELETE FROM v3_code_indexes WHERE snapshot_id=?',(snapshot,))
            db.execute('INSERT INTO v3_code_indexes VALUES (?,?,?,?)',(snapshot,report['index_version'],payload,sha256(payload.encode()).hexdigest()))
            db.executemany('INSERT INTO v3_code_symbols VALUES (?,?,?)',[(snapshot,x['symbol_id'],encoded(x)) for x in symbols])
            db.executemany('INSERT INTO v3_code_chunks VALUES (?,?,?,?)',[(snapshot,c.chunk_id,c.model_dump_json(),sha256(c.model_dump_json().encode()).hexdigest()) for c in chunks])
            db.executemany('INSERT INTO v3_code_edges VALUES (?,?,?,?,?)',[(snapshot,e['source_id'],e['target_id'],e['kind'],e['line']) for e in edges])
            if vector_artifact:
                manifest,dimension,payload=vector_artifact
                db.execute('INSERT INTO v3_code_vectors VALUES (?,?,?,?,?)',(snapshot,manifest.key,dimension,payload,sha256(payload.encode()).hexdigest()))
            db.execute('UPDATE v3_projects SET index_status=? WHERE project_id=? AND current_snapshot=?',('indexed',project_id,snapshot))

    def report(self,owner,project_id,snapshot):
        with self.workspace._connection() as db:
            self.projects._project(db,owner,project_id)
            if not db.execute('SELECT 1 FROM v3_project_snapshots WHERE snapshot_id=? AND project_id=?',(snapshot,project_id)).fetchone():raise WorkspaceNotFound('snapshot_not_found')
            row=db.execute('SELECT * FROM v3_code_indexes WHERE snapshot_id=?',(snapshot,)).fetchone()
            return dict(row) if row else None

    def load(self,owner,project_id,snapshot):
        with self.workspace._connection() as db:
            self.projects._project(db,owner,project_id)
            if not db.execute('SELECT 1 FROM v3_project_snapshots WHERE project_id=? AND snapshot_id=?',(project_id,snapshot)).fetchone():raise WorkspaceNotFound('snapshot_not_found')
            row=db.execute('SELECT * FROM v3_code_indexes WHERE snapshot_id=?',(snapshot,)).fetchone()
            return {'report':dict(row) if row else None,
                'symbols':[dict(r) for r in db.execute('SELECT symbol_id,payload FROM v3_code_symbols WHERE snapshot_id=?',(snapshot,))],
                'chunks':[dict(r) for r in db.execute('SELECT payload,payload_hash FROM v3_code_chunks WHERE snapshot_id=? ORDER BY chunk_id',(snapshot,))],
                'edges':[dict(r) for r in db.execute('SELECT source_id,target_id,kind,line FROM v3_code_edges WHERE snapshot_id=? ORDER BY source_id,target_id,line',(snapshot,))]}

    def vector(self,owner,project_id,snapshot,identity):
        with self.workspace._connection() as db:
            self.projects._project(db,owner,project_id)
            row=db.execute('SELECT * FROM v3_code_vectors WHERE snapshot_id=? AND model_id=?',(snapshot,identity)).fetchone()
            return dict(row) if row else None

    def put_vector(self,owner,project_id,snapshot,identity,dimension,payload):
        with self.workspace._connection(write=True) as db:
            self.projects._project(db,owner,project_id)
            db.execute('INSERT OR IGNORE INTO v3_code_vectors VALUES (?,?,?,?,?)',(snapshot,identity,dimension,payload,sha256(payload.encode()).hexdigest()))
