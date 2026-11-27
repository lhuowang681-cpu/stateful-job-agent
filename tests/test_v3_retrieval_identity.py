"""Identity/scope/injection contracts. Fixture vectors do NOT measure quality."""
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient

from job_agent.knowledge.index_manifest import EmbeddingIdentity, manifest_for
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.code_rag import CodeRAGService, CodeQuery
from job_agent.resume_workspace.long_term import LongTermRepository, ProjectCreate
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
from job_agent.resume_workspace.repository import SqliteResumeRepository, WorkspaceConflict, WorkspaceNotFound
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime, local_model_revision


class FixtureBackend:
    def __init__(self, identity=None):
        self.identity=identity or EmbeddingIdentity('test_only','fixture','v1',2)
        self.documents=0;self.queries=0
    def embed_documents(self,texts):
        self.documents+=1
        return [[1.,.2] for _ in texts]
    def embed_query(self,text):
        self.queries+=1
        return [1.,.1]


@pytest.fixture
def setup(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'ws.sqlite');projects=LongTermRepository(ws)
    p=projects.create_project('alice',ProjectCreate(name='Synthetic fixture'))
    p=projects.publish_files('alice',p['project_id'],{
        'storage.py':'def save_receipt(key, store):\n    return store.setdefault(key, "done")\n',
        'api.py':'from storage import save_receipt\n\ndef handle(key, store):\n    return save_receipt(key, store)\n',
        'README.md':'# Synthetic fixture\nDuplicate writes reuse the saved receipt.\n'},origin='zip')
    service=CodeRAGService(ws);service.build('alice',p['project_id'],p['current_snapshot'])
    return ws,p,service


def request(p):return CodeQuery(snapshot_id=p['current_snapshot'],query='save_receipt',method='hybrid')


@pytest.mark.parametrize('change',[{'provider':'other'},{'model':'other'},{'revision':'v2'},
    {'dimension':3},{'normalization':'none'},{'query_template':'Task: {query}'},{'max_input_tokens':512},{'encoder_version':'v2'}])
def test_every_encoder_semantic_invalidates_index_identity(setup,change):
    _,p,service=setup
    _,_,chunks,_=service._load('alice',p['project_id'],p['current_snapshot'])
    identity=EmbeddingIdentity('test_only','fixture','v1',2)
    def manifest(spec):return manifest_for(chunks,corpus_kind='code',scope=('alice','p','s'),
        parser_version='p1',splitter_version='c1',embedding=spec)
    assert manifest(identity).key != manifest(replace(identity,**change)).key


def test_scope_parser_splitter_and_actual_encoder_text_change_identity(setup):
    _,p,service=setup;_,_,chunks,_=service._load('alice',p['project_id'],p['current_snapshot'])
    args=dict(corpus_kind='code',scope=('alice','p','s'),parser_version='p1',splitter_version='c1',
              embedding=EmbeddingIdentity('test_only','fixture','v1',2))
    first=manifest_for(chunks,**args).key
    for change in ({'scope':('bob','p','s')},{'parser_version':'p2'},{'splitter_version':'c2'},
                   {'corpus_kind':'project_documentation'}):
        assert manifest_for(chunks,**(args|change)).key!=first
    # chunk_id order depends on a fresh snapshot UUID; the first chunk may be a
    # README with no "return". Pick an actual code input, not a no-op replacement.
    index=next(i for i,c in enumerate(chunks) if 'return' in c.text)
    changed=list(chunks)
    changed[index]=chunks[index].model_copy(update={'text':chunks[index].text.replace('return','RETURN')})
    assert changed[index].text!=chunks[index].text
    assert manifest_for(changed,**args).key!=first


def test_revision_invalidates_persistent_vectors_and_restart_reuses(setup):
    ws,p,_=setup;backend=FixtureBackend()
    code=CodeRAGService(ws,embedding_backend=backend)
    first=code.search('alice',p['project_id'],request(p))['retrieval_trace']
    assert first['sparse_ids'] and first['dense_ids'] and backend.documents==1
    reopened=CodeRAGService(SqliteResumeRepository(ws.path),embedding_backend=backend)
    assert reopened.search('alice',p['project_id'],request(p))['retrieval_trace']['index_identity']==first['index_identity']
    assert backend.documents==1
    backend.identity=replace(backend.identity,query_template='New task: {query}')
    second=reopened.search('alice',p['project_id'],request(p))['retrieval_trace']
    assert second['index_identity']!=first['index_identity'] and backend.documents==2


def test_unauthorized_owner_cannot_trigger_embedding(setup):
    ws,p,_=setup;backend=FixtureBackend();code=CodeRAGService(ws,embedding_backend=backend)
    with pytest.raises(WorkspaceNotFound):code.search('bob',p['project_id'],request(p))
    assert backend.queries==backend.documents==0


def test_public_cache_tracks_model_and_empty_corpus_never_encodes(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'pub.sqlite');backend=FixtureBackend()
    service=PublicKnowledgeService(ws,embedding_backend=backend)
    first=service.search('RRF',method='hybrid')['retrieval_trace']['index_identity']
    service.search('RRF',method='hybrid');assert backend.documents==1
    backend.identity=replace(backend.identity,revision='v2')
    assert service.search('RRF',method='hybrid')['retrieval_trace']['index_identity']!=first
    assert backend.documents==2
    queries=backend.queries
    assert service.search('x',method='dense',tags=('missing-tag',))['hits']==[]
    assert backend.queries==queries


def test_invalid_vectors_not_cached(tmp_path):
    backend=FixtureBackend()
    backend.embed_documents=lambda texts:[[float('nan'),1.] for _ in texts]
    service=PublicKnowledgeService(SqliteResumeRepository(tmp_path/'pub.sqlite'),embedding_backend=backend)
    with pytest.raises(WorkspaceConflict,match='dimensions'):service.search('RRF',method='dense')
    assert service._embedding_cache=={}


def test_code_build_publishes_vectors_and_never_encodes_documents_on_query(setup):
    ws,p,_=setup;backend=FixtureBackend();backend.require_prebuilt=True
    service=CodeRAGService(ws,embedding_backend=backend)
    before=service.search('alice',p['project_id'],request(p))
    assert before['method_used']=='bm25_fallback' and before['warnings']==['code_dense_index_needs_rebuild']
    assert backend.documents==0
    report=service.build('alice',p['project_id'],p['current_snapshot'])
    assert backend.documents==1 and report['vector_index_identity']
    assert service.search('alice',p['project_id'],request(p))['retrieval_trace']['index_identity']==report['vector_index_identity']
    assert backend.documents==1
    # A failed new encoder cannot destroy the already published index.
    backend.embed_documents=lambda texts:[[float('nan'),1.] for _ in texts]
    with pytest.raises(WorkspaceConflict,match='values'):service.build('alice',p['project_id'],p['current_snapshot'])
    assert service.status('alice',p['project_id'],p['current_snapshot'])['vector_index_identity']==report['vector_index_identity']


def test_vector_publish_guard_rejects_stale_attempt_without_changing_artifact(setup):
    ws,p,_=setup;backend=FixtureBackend();service=CodeRAGService(ws,embedding_backend=backend)
    old=service.build('alice',p['project_id'],p['current_snapshot'])['vector_index_identity']
    backend.identity=replace(backend.identity,revision='v2')
    def lost(db):raise WorkspaceConflict('task_lease_lost')
    with pytest.raises(WorkspaceConflict,match='lease_lost'):
        service.build('alice',p['project_id'],p['current_snapshot'],publish_guard=lost)
    assert service.status('alice',p['project_id'],p['current_snapshot'])['vector_index_identity']==old
    with ws._connection() as db:
        assert [r[0] for r in db.execute('SELECT model_id FROM v3_code_vectors')]==[old]


def test_public_startup_prewarms_both_kinds_and_new_corpus_explicitly_degrades(tmp_path):
    backend=FixtureBackend();backend.require_prebuilt=True
    service=PublicKnowledgeService(SqliteResumeRepository(tmp_path/'pub.sqlite'),embedding_backend=backend)
    assert backend.documents==2
    assert service.search('RRF')['method_used']=='hybrid'
    assert service.search('checkpoint',kind='question')['method_used']=='hybrid'
    assert backend.documents==2
    entry,_=service.repository.get('doc-ast')
    service.repository.install([entry.model_copy(update={'tags':['changed']}).model_dump()])
    result=service.search('AST')
    assert result['method_used']=='bm25_fallback' and result['warnings']==['public_dense_index_needs_prewarm']
    assert backend.documents==2
    service.prewarm()
    assert service.search('AST')['method_used']=='hybrid'


def test_product_injects_same_backend_into_both_http_paths(setup):
    ws,p,_=setup;backend=FixtureBackend();runtime=RetrievalRuntime(backend,backend.identity)
    app=create_resume_app(ws,resolve_identity={'a':'alice'}.get,retrieval_runtime=runtime,task_worker_enabled=False)
    assert app.state.code_service.embedding_backend is app.state.public_knowledge.embedding_backend is backend
    with TestClient(app) as client:
        assert client.get('/api/v2/capabilities').status_code==401
        h={'Authorization':'Bearer a'}
        caps=client.get('/api/v2/capabilities',headers=h).json()['retrieval']
        assert caps['dense_loaded'] and not caps['quality_verified'] and not caps['rerank_loaded']
        assert client.post(f"/api/v2/projects/{p['project_id']}/search",headers=h,json=request(p).model_dump()).status_code==200
        result=client.get('/api/v2/knowledge/search',headers=h,params={'query':'RRF','method':'hybrid'})
        assert result.status_code==200 and result.json()['retrieval_trace']['dense_ids']
        assert 'answer_points' not in result.text


def test_default_disabled_and_explicit_bad_configuration_fails(tmp_path):
    assert not RetrievalRuntime.from_env({}).capabilities()['dense_loaded']
    for env in ({'JOB_AGENT_WORKSPACE_EMBEDDING':'unknown'},
                {'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen'},
                {'JOB_AGENT_WORKSPACE_EMBEDDING':'local_qwen','JOB_AGENT_WORKSPACE_EMBEDDING_PATH':str(tmp_path)}):
        with pytest.raises(ValueError):RetrievalRuntime.from_env(env)
    (tmp_path/'config.json').write_text('{}');(tmp_path/'model.safetensors').write_bytes(b'fake fixture not a model')
    revision=local_model_revision(tmp_path)
    (tmp_path/'model.safetensors').write_bytes(b'changed fixture')
    assert local_model_revision(tmp_path)!=revision
