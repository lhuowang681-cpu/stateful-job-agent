"""Fixed research inputs and portable cache correctness, not semantic quality gold."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from scripts.freeze_expansion_final import build
from job_agent.knowledge.evaluation_contract import EvaluationDataset
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeService
from job_agent.resume_workspace.public_seed import seed_entries
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict
from test_v3_retrieval_identity import FixtureBackend

ROOT=Path(__file__).resolve().parents[1]


def test_final_72_are_exact_source_candidates_with_explicit_scopes_and_disjoint_families():
    data=build();saved=EvaluationDataset.model_validate_json((ROOT/'docs/evaluation/expansion/candidates-v3.json').read_text(encoding='utf-8'))
    assert data==saved and len(data.cases)==72 and len(data.corpus.documents)==26
    assert sum(c.split=='dev' for c in data.cases)==36
    assert all(c.retrieval_scope and c.annotation_status=='ai_candidate' for c in data.cases)
    assert {d.kind for d in data.corpus.documents}=={'code','project_documentation','public_knowledge'}
    assert any(c.gold_requirement=='any' and len(c.gold)>1 for c in data.cases)
    assert sum(not c.answerable for c in data.cases)==4
    assert next(c for c in data.cases if c.case_id=='dev-final-02').gold[0].start_line==3


def test_fixed_v2_preserved_and_duplicate_revised_before_scoring_not_relabelled_human():
    old=EvaluationDataset.model_validate_json((ROOT/'docs/evaluation/expansion/candidates-v2.json').read_text(encoding='utf-8'))
    new=build();assert old.corpus==new.corpus
    assert old.cases[27].query!=new.cases[27].query
    assert all(c.annotation_status=='ai_candidate' for c in old.cases+new.cases)
    packet=json.loads((ROOT/'docs/evaluation/expansion/human-review-packet-v1.json').read_text(encoding='utf-8'))
    assert packet['human_reviewed_count']==0 and len(packet['cases'])==8
    assert packet['dataset_sha256']==sha256((ROOT/'docs/evaluation/expansion/candidates-v3.json').read_bytes()).hexdigest()


def test_mismatched_known_scope_cannot_borrow_gold_from_other_domain():
    raw=build().model_dump();raw['cases'][0]['retrieval_scope']='public'
    with pytest.raises(ValidationError,match='scope_mismatch'):EvaluationDataset.model_validate(raw)


@pytest.fixture
def public(tmp_path):
    ws=SqliteResumeRepository(tmp_path/'public.sqlite');backend=FixtureBackend();backend.require_prebuilt=True
    service=PublicKnowledgeService(ws,embedding_backend=backend,seed=False,prewarm=False)
    service.repository.install(seed_entries()[:4]);service.prewarm()
    return ws,backend,service


def test_public_cache_reopened_sources_restore_without_document_encoding(public):
    ws,old,service=public;payload=service.export_dense_snapshot();before=service.search('Checkpoint',method='hybrid',rerank=False)
    backend=FixtureBackend();backend.require_prebuilt=True
    reopened=PublicKnowledgeService(SqliteResumeRepository(ws.path),embedding_backend=backend,seed=False,prewarm=False)
    assert backend.documents==backend.queries==0
    result=reopened.restore_dense_snapshot(json.loads(json.dumps(payload)));assert result['restored_pools']==2
    assert backend.documents==backend.queries==0
    assert reopened.search('Checkpoint',method='hybrid',rerank=False)['hits']==before['hits']
    assert backend.documents==0 and backend.queries==1


@pytest.mark.parametrize('field,value',[('revision','new-revision'),('dimension',3),('query_template','Changed: {query}'),('max_input_tokens',512)])
def test_public_snapshot_requires_same_actual_encoder_identity(public,field,value):
    ws,backend,service=public;payload=service.export_dense_snapshot()
    other=FixtureBackend(replace(backend.identity,**{field:value}))
    restored=PublicKnowledgeService(ws,embedding_backend=other,seed=False,prewarm=False)
    with pytest.raises(WorkspaceConflict,match='identity_changed'):restored.restore_dense_snapshot(payload)
    assert other.documents==other.queries==0 and restored._embedding_cache=={}


@pytest.mark.parametrize('change',['nan','zero','dimension','boolean','hash','chunk_order','pool_missing','extra_key'])
def test_corrupted_snapshot_does_not_partially_replace_live_cache(public,change):
    ws,backend,service=public;payload=deepcopy(service.export_dense_snapshot());original=fingerprint(service.export_dense_snapshot())
    shard=payload['shards'][0]
    if change=='nan':shard['vectors'][0][0]=float('nan')
    if change=='zero':shard['vectors'][0]=[0.,0.];shard['vectors_sha256']=fingerprint(shard['vectors'])
    if change=='dimension':shard['vectors'][0].append(1.);shard['vectors_sha256']=fingerprint(shard['vectors'])
    if change=='boolean':shard['vectors'][0][0]=True
    if change=='hash':shard['vectors_sha256']='0'*64
    if change=='chunk_order':shard['chunk_ids'].reverse()
    if change=='pool_missing':payload['shards'].pop()
    if change=='extra_key':payload['raw_source']='must not be imported'
    with pytest.raises(WorkspaceConflict):service.restore_dense_snapshot(payload)
    assert fingerprint(service.export_dense_snapshot())==original


def test_public_curator_source_version_change_invalidates_saved_cache(public):
    ws,backend,service=public;payload=service.export_dense_snapshot()
    source=seed_entries()[0];source['tags']=[*source['tags'],'new-tag'];service.repository.install([source])
    with pytest.raises(WorkspaceConflict,match='identity_changed'):service.restore_dense_snapshot(payload)


def test_public_export_rejects_corrupt_live_vector_instead_of_coercing_bool(public):
    ws,backend,service=public
    next(iter(service._embedding_cache.values()))[0][0]=True
    with pytest.raises(WorkspaceConflict,match='dimensions_invalid'):service.export_dense_snapshot()
