from dataclasses import replace
import pytest
from job_agent.knowledge.retrieval_policy import RetrievalSettings
from job_agent.knowledge.rrf import reciprocal_rank_fusion
from job_agent.knowledge.contracts import KnowledgeChunk,RetrievedChunk
from job_agent.resume_workspace.repository import SqliteResumeRepository
from job_agent.resume_workspace.long_term import LongTermRepository,ProjectCreate
from job_agent.resume_workspace.code_rag import CodeRAGService,CodeQuery


def test_weighted_fusion_is_explicit_and_bounded():
    def hit(key):
        chunk=KnowledgeChunk(chunk_id=key,document_id=key,document_version=1,document_content_hash='a'*64,
                             text=key,chunk_index=0,start_offset=0,end_offset=len(key))
        return RetrievedChunk(chunk=chunk,rank=1,score=1.,retrieval_method='test')
    dense=[hit('z-code')];sparse=[hit('a-doc')]
    old=reciprocal_rank_fusion(dense_results=dense,bm25_results=sparse,limit=2)
    explicit=reciprocal_rank_fusion(dense_results=dense,bm25_results=sparse,limit=2,dense_weight=1.)
    assert old==explicit and old[0].chunk.chunk_id=='a-doc'
    assert reciprocal_rank_fusion(dense_results=dense,bm25_results=sparse,limit=2,dense_weight=2)[0].chunk.chunk_id=='z-code'
    for invalid in (0,-1,5,float('nan'),float('inf'),True):
        with pytest.raises(ValueError):reciprocal_rank_fusion(dense_results=dense,bm25_results=sparse,limit=2,dense_weight=invalid)


def test_new_settings_change_identity_and_reject_unknown_policy():
    base=RetrievalSettings()
    assert replace(base,dense_rrf_weight=2).key!=base.key
    assert replace(base,relation_priority='legacy_first').key!=base.key
    for kw in ({'dense_rrf_weight':0},{'dense_rrf_weight':2.5},{'relation_priority':'anything'}):
        with pytest.raises(ValueError):RetrievalSettings(**kw)


def test_static_relations_fill_space_without_evicting_direct_symbols(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'research.sqlite');projects=LongTermRepository(ws)
    p=projects.create_project('alice',ProjectCreate(name='Authored priority counterexample'))
    p=projects.publish_files('alice',p['project_id'],{'a.py':'def alpha():\n    return helper()\n\ndef beta():\n    return 2\n\ndef helper():\n    return 3\n'},origin='zip')
    service=CodeRAGService(ws);service.build('alice',p['project_id'],p['current_snapshot'])
    request=CodeQuery(snapshot_id=p['current_snapshot'],query='alpha beta',limit=2,expand_relations=False)
    direct=service.search('alice',p['project_id'],request)
    fixed=service.search('alice',p['project_id'],request.model_copy(update={'expand_relations':True}))
    legacy=CodeRAGService(ws,retrieval_settings=RetrievalSettings(relation_priority='legacy_first')).search(
        'alice',p['project_id'],request.model_copy(update={'expand_relations':True}))
    names=lambda found:[h['symbol']['name'] for h in found['hits']]
    assert names(direct)==['alpha','beta'] and names(fixed)==names(direct)
    assert names(legacy)==['alpha','helper']
    for hit in fixed['hits']:service.validate_reference('alice',hit_ref(hit))
    expanded=service.search('alice',p['project_id'],request.model_copy(update={'query':'alpha','limit':5,'expand_relations':True}))
    assert names(expanded)==['alpha','helper']
    assert expanded['retrieval_trace']['context_chars']<=expanded['retrieval_trace']['context_char_budget']


def hit_ref(hit):
    from job_agent.resume_workspace.evidence_reference import EvidenceReference
    return EvidenceReference.model_validate(hit['reference'])
