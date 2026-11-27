from hashlib import sha256
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.api import create_resume_app

DEV_FILES={
 'app/storage.py':'def save_receipt(request_id, store):\n    """Return a saved receipt, avoiding a duplicate write."""\n    if request_id in store:\n        return store[request_id]\n    store[request_id] = "done"\n    return store[request_id]\n',
 'app/api.py':'from .storage import save_receipt\n\ndef handle(request_id, store):\n    return save_receipt(request_id, store)\n',
 'tests/test_storage.py':'from app.storage import save_receipt\n\ndef test_duplicate():\n    store = {}\n    assert save_receipt("a", store) == save_receipt("a", store)\n',
 'README.md':'# Synthetic project\nThis is a local demonstration. No runtime results are claimed.\n',
}


@pytest.fixture
def data(tmp_path):
    workspace=SqliteResumeRepository(tmp_path/'ws.sqlite');projects=LongTermRepository(workspace)
    p=projects.create_project('alice',ProjectCreate(name='Dev project',contribution='Synthetic user contribution only'))
    p=projects.publish_files('alice',p['project_id'],DEV_FILES,origin='github',commit_sha='a'*40)
    service=CodeRAGService(workspace);service.build('alice',p['project_id'],p['current_snapshot'])
    return workspace,projects,p,service


def query(p,**kw):return CodeQuery(snapshot_id=p['current_snapshot'],query='save_receipt callers',**kw)


def test_symbol_search_relations_and_exact_citation(data):
    _,_,p,service=data;result=service.search('alice',p['project_id'],query(p))
    paths={hit['reference']['path'] for hit in result['hits']}
    assert {'app/storage.py','app/api.py','tests/test_storage.py'}<=paths
    assert result['static_graph_only'] and result['method_used']=='symbol_bm25_static_relations'
    for hit in result['hits']:
        ref=EvidenceReference.model_validate(hit['reference'])
        text=DEV_FILES[ref.path]
        assert ref.quote==''.join(text.splitlines(keepends=True)[ref.start_line-1:ref.end_line])
        assert ref.content_hash==sha256(text.encode()).hexdigest() and ref.commit=='a'*40
        assert ref.supports_claim=='needs_judgment' and ref.independent_truth=='not_verified'
        assert service.validate_reference('alice',ref)==ref


def test_symbol_read_references_and_test_files_are_not_test_results(data):
    _,_,p,service=data
    symbol=service.get_symbol('alice',p['project_id'],p['current_snapshot'],'save_receipt')
    assert symbol['reference']['start_line']==1 and not symbol['runtime_executed']
    refs=service.find_references('alice',p['project_id'],p['current_snapshot'],symbol['symbol']['symbol_id'],tests_only=True)
    assert refs and all(r['reference']['evidence_kind']=='test_code' and r['test_execution']=='not_run' for r in refs)


def test_private_owner_and_snapshot_scope(data):
    _,projects,p,service=data
    with pytest.raises(WorkspaceNotFound):service.search('bob',p['project_id'],query(p))
    other=projects.create_project('alice',ProjectCreate(name='Other'))
    with pytest.raises(WorkspaceNotFound):service.status('alice',other['project_id'],p['current_snapshot'])
    ref=service.read_code_range('alice',p['project_id'],p['current_snapshot'],'app/storage.py',1,3)
    with pytest.raises(WorkspaceNotFound):service.validate_reference('bob',ref)


@pytest.mark.parametrize('change',[{'content_hash':'0'*64},{'quote':'invented implementation'},{'commit':'b'*40},{'source_id':'different-source'},{'end_line':2}])
def test_forged_quotes_hashes_lines_commit_rejected(data,change):
    _,_,p,service=data
    ref=service.read_code_range('alice',p['project_id'],p['current_snapshot'],'app/storage.py',1,3)
    with pytest.raises(WorkspaceConflict):service.validate_reference('alice',ref.model_copy(update=change))


def test_support_label_not_trusted_from_client(data):
    _,_,p,service=data
    ref=service.read_code_range('alice',p['project_id'],p['current_snapshot'],'app/storage.py',1,3)
    assert service.validate_reference('alice',ref.model_copy(update={'supports_claim':'supported'})).supports_claim=='needs_judgment'


def test_historic_references_not_redirected_to_new_head(data):
    _,projects,p,service=data
    old=service.read_code_range('alice',p['project_id'],p['current_snapshot'],'app/storage.py',1,3)
    changed={**DEV_FILES,'app/storage.py':DEV_FILES['app/storage.py'].replace('done','updated')}
    current=projects.publish_files('alice',p['project_id'],changed,origin='github',commit_sha='b'*40)
    service.build('alice',p['project_id'],current['current_snapshot'])
    assert service.validate_reference('alice',old).commit=='a'*40
    new=service.read_code_range('alice',p['project_id'],current['current_snapshot'],'app/storage.py',1,3)
    assert new.content_hash!=old.content_hash and new.commit=='b'*40


def test_rebuild_restart_and_delete_all_derived_indexes(data):
    workspace,projects,p,service=data
    before=service.search('alice',p['project_id'],query(p))['hits']
    service.build('alice',p['project_id'],p['current_snapshot'])
    reopened=CodeRAGService(SqliteResumeRepository(workspace.path))
    assert reopened.search('alice',p['project_id'],query(p))['hits']==before
    projects.delete_project('alice',p['project_id'])
    with workspace._connection() as db:
        for table in ('v3_code_indexes','v3_code_symbols','v3_code_chunks','v3_code_edges','v3_code_vectors'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]==0


def test_parser_upgrade_exposes_rebuild_status_but_never_serves_stale_index(data):
    workspace,_,p,service=data
    with workspace._connection(write=True) as db:db.execute("UPDATE v3_code_indexes SET parser_version='old-parser'")
    assert service.status('alice',p['project_id'],p['current_snapshot'])['status']=='needs_rebuild'
    with pytest.raises(WorkspaceConflict,match='not_ready'):service.search('alice',p['project_id'],query(p))
    service.build('alice',p['project_id'],p['current_snapshot'])
    assert service.search('alice',p['project_id'],query(p))['hits']


@pytest.mark.parametrize('table,column',[('v3_code_chunks','payload'),('v3_code_symbols','payload'),('v3_code_indexes','payload')])
def test_index_corruption_fails_closed(data,table,column):
    workspace,_,p,service=data
    with workspace._connection(write=True) as db:db.execute(f'UPDATE {table} SET {column}=?',('{}',))
    with pytest.raises(WorkspaceConflict,match='integrity'):service.search('alice',p['project_id'],query(p))


def test_missing_relation_and_chunk_row_detected(data):
    workspace,_,p,service=data
    with workspace._connection(write=True) as db:db.execute('DELETE FROM v3_code_edges')
    with pytest.raises(WorkspaceConflict,match='relation_integrity'):service.search('alice',p['project_id'],query(p))


def test_no_dense_model_is_explicit_and_zero_hit_not_negative_ability(data):
    _,_,p,service=data
    with pytest.raises(WorkspaceConflict,match='not_configured'):service.search('alice',p['project_id'],query(p,method='dense'))
    result=service.search('alice',p['project_id'],CodeQuery(snapshot_id=p['current_snapshot'],query='zqxv_unseen_symbol_999',method='symbol'))
    assert result['hits']==[] and result['provider_calls']==0


class LocalEmbeddingFixture:
    """Tests persistence and shape, NOT semantic quality."""
    def __init__(self):self.documents=0;self.queries=0
    def embed_documents(self,texts):self.documents+=1;return [[1.0 if 'save_receipt' in t else .1,1.0] for t in texts]
    def embed_query(self,text):self.queries+=1;return [1.,.1]


def test_dense_vectors_persist_and_rebuild_invalidates_cache(data):
    workspace,_,p,_=data;backend=LocalEmbeddingFixture();service=CodeRAGService(workspace,embedding_backend=backend,embedding_identity='TEST_FIXTURE_NOT_SEMANTIC')
    assert service.search('alice',p['project_id'],query(p,method='dense'))['hits']
    assert backend.documents==1
    reopened=CodeRAGService(SqliteResumeRepository(workspace.path),embedding_backend=backend,embedding_identity='TEST_FIXTURE_NOT_SEMANTIC')
    reopened.search('alice',p['project_id'],query(p,method='hybrid'));assert backend.documents==1
    reopened.build('alice',p['project_id'],p['current_snapshot'])
    reopened.search('alice',p['project_id'],query(p,method='dense'));assert backend.documents==2


@pytest.mark.parametrize('broken',['dimension','nan','zero'])
def test_invalid_embedding_vectors_rejected(data,broken):
    workspace,_,p,_=data
    class Bad(LocalEmbeddingFixture):
        def embed_documents(self,texts):
            return [[1.0,0.0] if i==0 else ([1.0] if broken=='dimension' else [float('nan'),1.] if broken=='nan' else [0.,0.]) for i,_ in enumerate(texts)]
    service=CodeRAGService(workspace,embedding_backend=Bad())
    with pytest.raises(WorkspaceConflict,match='vectors|values|dimensions'):service.search('alice',p['project_id'],query(p,method='dense'))


def test_http_index_symbol_code_owner_scope(data):
    workspace,_,p,_=data
    with TestClient(create_resume_app(workspace,resolve_identity={'a':'alice','b':'bob'}.get)) as client:
        h={'Authorization':'Bearer a'};prefix=f"/api/v2/projects/{p['project_id']}"
        response=client.post(prefix+'/search',headers=h,json=query(p).model_dump())
        assert response.status_code==200,response.text
        status=client.get(prefix+'/index',headers=h,params={'snapshot':p['current_snapshot']}).json()
        assert status['status']=='indexed' and 'symbol_payload_hashes' not in status
        sym=client.get(prefix+'/symbol',headers=h,params={'snapshot':p['current_snapshot'],'name':'save_receipt'}).json()
        assert sym['reference']['path']=='app/storage.py'
        assert client.post(prefix+'/search',headers={'Authorization':'Bearer b'},json=query(p).model_dump()).status_code==404


def test_line_budget_and_oversized_line_are_explicit(data):
    _,projects,p,service=data
    with pytest.raises(WorkspaceConflict,match='line_range'):service.read_code_range('alice',p['project_id'],p['current_snapshot'],'app/storage.py',1,122)
    other=projects.create_project('alice',ProjectCreate(name='Minified'))
    other=projects.publish_files('alice',other['project_id'],{'bundle.js':'const data = "'+'x'*13000+'";'},origin='zip')
    report=service.build('alice',other['project_id'],other['current_snapshot'])
    assert report['oversized_lines_omitted']==1 and report['chunks']==0
