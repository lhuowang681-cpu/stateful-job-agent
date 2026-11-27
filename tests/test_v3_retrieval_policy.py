"""Budget, rank completeness, fallback and source-boundary contracts."""
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from job_agent.knowledge.contracts import KnowledgeChunk,RetrievedChunk
from job_agent.knowledge.reranker import RerankerIdentity,RerankBatch,apply_rerank
from job_agent.knowledge.retrieval_policy import RetrievalSettings,output_budget
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict
from job_agent.resume_workspace.retrieval_runtime import RetrievalRuntime


class FixtureReranker:
    identity=RerankerIdentity('test-fixture','v1','test-only')
    def score(self,query,texts):return RerankBatch(list(range(len(texts))),[20]*len(texts))


def candidates():
    return [RetrievedChunk(chunk=KnowledgeChunk(chunk_id=str(i),document_id=str(i),document_version=1,
        document_content_hash=sha256(text.encode()).hexdigest(),text=text,chunk_index=i,start_offset=0,end_offset=len(text)),
        score=1/(i+1),rank=i+1,retrieval_method='bm25') for i,text in enumerate(['source A','source B','source C'])]


@pytest.mark.parametrize('change',[{'sparse_candidates':0},{'dense_candidates':61},{'fusion_candidates':0},
    {'rerank_candidates':31},{'max_output':21},{'relation_candidates':9},{'context_char_budget':0},{'rrf_k':True}])
def test_invalid_budgets_rejected(change):
    with pytest.raises(ValueError):RetrievalSettings(**change)


def test_reranking_changes_order_but_preserves_original_chunks_and_tail_ranks():
    original=candidates();settings=RetrievalSettings(rerank_candidates=2)
    ranked,trace=apply_rerank('q',original,reranker=FixtureReranker(),settings=settings,enabled=True)
    assert [h.chunk.chunk_id for h in ranked]==['1','0','2']
    assert [h.rank for h in ranked]==[1,2,3]
    assert ranked[0].chunk==original[1].chunk and ranked[0].score==1
    assert trace['rerank_applied'] and trace['rerank_input_ids']==['0','1']
    assert original[0].score==1 and ranked[0].retrieval_metadata['score_semantics']=='raw_logit'


@pytest.mark.parametrize('mode',['short','nan','exception'])
def test_rerank_failure_retains_original_order_without_fake_scores(mode):
    class Bad(FixtureReranker):
        def score(self,q,texts):
            if mode=='exception':raise RuntimeError('private source must not leak')
            return RerankBatch([1.] if mode=='short' else [float('nan')]*len(texts))
    original=candidates();ranked,trace=apply_rerank('q',original,reranker=Bad(),settings=RetrievalSettings(),enabled=True)
    assert ranked==original and not trace['rerank_applied'] and trace['rerank_error']
    assert 'private source' not in str(trace)


def test_disabled_empty_and_missing_reranker_never_claim_a_call():
    original=candidates()
    for enabled,backend in ((False,FixtureReranker()),(True,None)):
        ranked,trace=apply_rerank('q',original,reranker=backend,settings=RetrievalSettings(),enabled=enabled)
        assert ranked==original and not trace['rerank_applied']
    assert not apply_rerank('q',[],reranker=FixtureReranker(),settings=RetrievalSettings(),enabled=True)[1]['rerank_input_ids']


def test_context_budget_omits_whole_spans_and_never_changes_quote():
    original=candidates();result,trace=output_budget(original,limit=3,settings=RetrievalSettings(context_char_budget=9))
    assert len(result)==1 and result[0].chunk.text=='source A'
    assert trace['budget_omitted_ids']==['1','2'] and trace['context_chars']<=9


def test_code_and_public_http_share_reranker_and_preserve_owner_and_rubric(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'ws.sqlite');projects=LongTermRepository(ws)
    p=projects.create_project('alice',ProjectCreate(name='Synthetic scope'))
    p=projects.publish_files('alice',p['project_id'],{'a.py':'def same_name():\n    return "one"\n',
        'b.py':'def same_name():\n    return "two"\n'},origin='zip')
    CodeRAGService(ws).build('alice',p['project_id'],p['current_snapshot'])
    reranker=FixtureReranker();app=create_resume_app(ws,resolve_identity={'a':'alice','b':'bob'}.get,
        retrieval_runtime=RetrievalRuntime(reranker=reranker),task_worker_enabled=False)
    assert app.state.code_service.reranker is app.state.public_knowledge.reranker is reranker
    with TestClient(app) as client:
        h={'Authorization':'Bearer a'}
        payload={'snapshot_id':p['current_snapshot'],'query':'same_name','method':'keyword','rerank':True}
        r=client.post(f"/api/v2/projects/{p['project_id']}/search",headers=h,json=payload)
        assert r.status_code==200 and r.json()['retrieval_trace']['rerank_applied']
        assert all(x['reference']['supports_claim']=='needs_judgment' for x in r.json()['hits'])
        assert client.post(f"/api/v2/projects/{p['project_id']}/search",headers={'Authorization':'Bearer b'},json=payload).status_code==404
        r=client.get('/api/v2/knowledge/search',headers=h,params={'query':'Checkpoint memory','kind':'question','method':'bm25','rerank':'true'})
        assert r.status_code==200 and r.json()['retrieval_trace']['rerank_applied']
        assert 'answer_points' not in r.text and 'aliases' not in r.text
        assert client.get('/api/v2/capabilities',headers=h).json()['retrieval']['rerank_loaded']


def test_embedding_operational_failure_degrades_hybrid_but_dense_is_explicit(tmp_path):
    class BrokenQuery:
        def embed_documents(self,texts):return [[1.,1.] for _ in texts]
        def embed_query(self,query):raise RuntimeError('private query must never appear in API')
    backend=BrokenQuery();ws=SqliteResumeRepository(tmp_path/'ws.sqlite');projects=LongTermRepository(ws)
    p=projects.create_project('alice',ProjectCreate(name='Synthetic failure'))
    p=projects.publish_files('alice',p['project_id'],{'a.py':'def save_receipt():\n    return "done"\n'},origin='zip')
    service=CodeRAGService(ws,embedding_backend=backend);service.build('alice',p['project_id'],p['current_snapshot'])
    result=service.search('alice',p['project_id'],CodeQuery(snapshot_id=p['current_snapshot'],query='save_receipt',method='hybrid'))
    assert result['method_used']=='bm25_fallback' and result['warnings']==['code_embedding_backend_failed']
    with pytest.raises(WorkspaceConflict,match='embedding_backend_failed'):
        service.search('alice',p['project_id'],CodeQuery(snapshot_id=p['current_snapshot'],query='save_receipt',method='dense'))
    public=PublicKnowledgeService(ws,embedding_backend=backend)
    result=public.search('Checkpoint',method='hybrid')
    assert result['method_used']=='bm25_fallback' and result['warnings']==['public_embedding_backend_failed']
    assert 'private query' not in str(result)
    with pytest.raises(WorkspaceConflict,match='embedding_backend_failed'):public.search('Checkpoint',method='dense')
