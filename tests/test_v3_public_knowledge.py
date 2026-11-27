import json
import pytest
from fastapi.testclient import TestClient
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.repository import SqliteResumeRepository,WorkspaceConflict,WorkspaceNotFound
from job_agent.resume_workspace.public_knowledge import PublicKnowledgeRepository,PublicKnowledgeService
from job_agent.resume_workspace.public_seed import seed_entries
from job_agent.resume_workspace.evidence_reference import EvidenceReference


@pytest.fixture
def service(tmp_path):return PublicKnowledgeService(SqliteResumeRepository(tmp_path/'public.sqlite'))


def test_seed_has_version_license_source_and_question_answers_never_in_search(service):
    docs=service.search('Checkpoint 长期记忆',kind='doc');assert docs['hits']
    ref=EvidenceReference.model_validate(docs['hits'][0]['reference'])
    assert ref.scope=='public_knowledge' and ref.owner_id is None and ref.supports_claim=='needs_judgment'
    assert service.repository.validate_reference(ref)==ref
    questions=service.search('checkpoint',kind='question')
    assert questions['hits']
    raw=json.dumps(questions,ensure_ascii=False)
    assert 'answer_points' not in raw and 'aliases' not in raw and 'followups' not in raw
    assert all(h['entry']['license']=='CC0-1.0' and h['entry']['source_url'].startswith('https://') for h in docs['hits'])


def test_internal_rubric_is_distinct_from_public_dto(service):
    question,version=service.private_question('question-checkpoint')
    assert len(question.answer_points)==len(question.aliases)==len(question.followups)==3
    result=service.search('Checkpoint',kind='question')
    assert all(set(h['entry']).isdisjoint({'answer_points','aliases','followups'}) for h in result['hits'])


def test_update_retains_pinned_reference_and_delete_invalidates_without_reseed(service):
    repo=service.repository;entry,version=repo.get('doc-checkpoint');old=repo.reference(entry,version,'bm25')
    updated=entry.model_copy(update={'body':entry.body+'\n新增一个明确的整理版本。'})
    repo.install([updated.model_dump()])
    assert repo.get('doc-checkpoint')[1]!=version
    assert repo.validate_reference(old).snapshot_id==version
    repo.delete('doc-checkpoint')
    with pytest.raises(WorkspaceNotFound):repo.validate_reference(old)
    reopened=PublicKnowledgeRepository(repo.workspace)
    with pytest.raises(WorkspaceNotFound):reopened.get('doc-checkpoint')


def test_duplicate_body_is_reported_not_indexed_as_distinct_entry(service):
    repo=service.repository;entry,_=repo.get('doc-ast')
    report=repo.install([entry.model_copy(update={'entry_id':'doc-duplicate'}).model_dump()])
    assert report=={'new_versions':0,'duplicate_entries_skipped':['doc-duplicate']}
    with pytest.raises(WorkspaceNotFound):repo.get('doc-duplicate')


def test_reference_tampering_and_support_label_override(service):
    entry,version=service.repository.get('doc-ast');ref=service.repository.reference(entry,version,'bm25')
    with pytest.raises(WorkspaceConflict):service.repository.validate_reference(ref.model_copy(update={'quote':'fabricated'}))
    assert service.repository.validate_reference(ref.model_copy(update={'supports_claim':'supported'})).supports_claim=='needs_judgment'


def test_empty_unknown_tag_is_empty_and_hybrid_fallback_explicit(service):
    assert service.search('this-tag-does-not-exist-999',method='tag')['hits']==[]
    result=service.search('RRF',method='hybrid')
    assert result['method_used']=='bm25_fallback' and result['warnings']
    with pytest.raises(WorkspaceConflict,match='not_configured'):service.search('RRF',method='dense')


def test_sql_payload_corruption_fails_closed(service):
    with service.repository.workspace._connection(write=True) as db:db.execute("UPDATE v3_public_versions SET payload='{}'")
    with pytest.raises(WorkspaceConflict,match='integrity'):service.search('RRF')


def test_public_knowledge_api_requires_auth_and_has_no_admin_or_rubric_route(service):
    with TestClient(create_resume_app(service.repository.workspace,resolve_identity={'a':'alice'}.get)) as client:
        assert client.get('/api/v2/knowledge/search',params={'query':'checkpoint'}).status_code==401
        h={'Authorization':'Bearer a'}
        result=client.get('/api/v2/knowledge/search',headers=h,params={'query':'checkpoint','kind':'question'})
        assert result.status_code==200 and 'answer_points' not in result.text and 'followups' not in result.text
        assert client.post('/api/v2/knowledge/install',headers=h,json=seed_entries()).status_code==404
        assert client.get('/api/v2/knowledge/status',headers=h).json()['documents']==10


def test_query_limits_and_empty_body_rejected(service):
    for q in ('','x'*601):
        with pytest.raises(WorkspaceConflict):service.search(q)
    with pytest.raises(WorkspaceConflict):service.search('a',limit=100)


def test_bm25_indexes_public_tags_without_modifying_quote_or_rubric_visibility(service):
    entry,version=service.repository.get('question-checkpoint')
    before=service.repository.reference(entry,version,'bm25')
    updated=entry.model_copy(update={'tags':['UniqueMetadataTermForSearch']})
    service.repository.install([updated.model_dump()])
    hits=service.search('UniqueMetadataTermForSearch',kind='question')['hits']
    assert hits and hits[0]['entry']['entry_id']=='question-checkpoint'
    assert 'UniqueMetadataTermForSearch' not in hits[0]['reference']['quote']
    assert service.repository.validate_reference(before).quote==before.quote
    assert 'answer_points' not in json.dumps(hits)
