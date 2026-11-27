from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.contracts import (
    PersonalInfo, Project, ResumeCreate, ResumeDocument, ResumeFact, SourceCreate,
    SourceSpan, VersionCreate,
)
from job_agent.resume_workspace.repository import (
    InvalidProvenance, SqliteResumeRepository, WorkspaceConflict, WorkspaceNotFound,
)


@pytest.fixture
def repo(tmp_path):
    return SqliteResumeRepository(tmp_path / "workspace.sqlite")


def source(repo, *, owner="alice", kind="original_resume"):
    return repo.add_source(owner, SourceCreate(kind=kind, label="合成材料", text="演示同学\nPython\nFastAPI"))


def fact(record, key, text):
    start = record.text.index(text)
    return ResumeFact(fact_id=key, text=text, source=SourceSpan(
        source_id=record.source_id, content_hash=record.content_hash, start=start, end=start + len(text)))


def document(record):
    return ResumeDocument(personal=PersonalInfo(name=fact(record, "name", "演示同学")),
                          skills=[fact(record, "python", "Python"), fact(record, "fastapi", "FastAPI")])


def create(repo, *, owner="alice"):
    return repo.create_resume(owner, ResumeCreate(title="合成简历", document=document(source(repo, owner=owner))))


def revise(repo, version, *, owner="alice"):
    doc = ResumeDocument.model_validate(version.document.model_dump())
    doc.skills.reverse()
    return repo.save_version(owner, version.resume_id, VersionCreate(
        expected_parent_version_id=version.version_id, document=doc, note="调整顺序"))


@pytest.mark.parametrize("kind,allowed", [
    ("original_resume", True), ("user_statement", True), ("job_description", False), ("reference", False),
])
def test_candidate_sources_are_separate_from_jd_and_references(repo, kind, allowed):
    request = ResumeCreate(title="合成", document=document(source(repo, kind=kind)))
    if allowed:
        assert repo.create_resume("alice", request).confirmed_at is None
    else:
        with pytest.raises(InvalidProvenance, match="reference_or_jd"):
            repo.create_resume("alice", request)
        assert repo.list_resumes("alice") == []


def test_offsets_are_canonical_unicode_characters(repo):
    record = repo.add_source("alice", SourceCreate(kind="user_statement", label="合成", text="e\u0301\r\n演示同学😀"))
    assert record.text == "é\n演示同学😀"
    f = fact(record, "name", "演示同学😀")
    assert f.source.start == 2
    version = repo.create_resume("alice", ResumeCreate(
        title="合成", document=ResumeDocument(personal=PersonalInfo(name=f))))
    assert version.document.personal.name.text == "演示同学😀"


@pytest.mark.parametrize("mutation,reason", [
    ("hash", "source_hash_mismatch"), ("text", "fact_quote_mismatch"),
    ("offset", "fact_quote_mismatch"), ("overflow", "fact_quote_mismatch"),
])
def test_forged_facts_fail_without_leaving_partial_resume(repo, mutation, reason):
    doc = document(source(repo))
    target = doc.skills[0]
    if mutation == "hash":
        target.source.content_hash = "0" * 64
    elif mutation == "text":
        target.text = "精通 Kubernetes，性能提升 80%"
    elif mutation == "offset":
        target.source.start += 1
    else:
        target.source.end += 100_000
    with pytest.raises(InvalidProvenance, match=reason):
        repo.create_resume("alice", ResumeCreate(title="合成", document=doc))
    assert repo.list_resumes("alice") == []
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT COUNT(*) FROM rw_versions").fetchone()[0] == 0


def test_foreign_source_cannot_be_cited(repo):
    doc = document(source(repo, owner="bob"))
    with pytest.raises(WorkspaceNotFound):
        repo.create_resume("alice", ResumeCreate(title="合成", document=doc))


@pytest.mark.parametrize("field", ["fact_id", "entry_id"])
def test_duplicate_identifiers_are_rejected(repo, field):
    record = source(repo)
    doc = document(record).model_dump()
    if field == "fact_id":
        doc["skills"].append(doc["skills"][0])
    else:
        doc["projects"] = [
            Project(entry_id="p", name=fact(record, "p1", "Python")).model_dump(),
            Project(entry_id="p", name=fact(record, "p2", "FastAPI")).model_dump(),
        ]
    with pytest.raises(ValidationError, match=f"duplicate_{field}"):
        ResumeDocument.model_validate(doc)


@pytest.mark.parametrize("payload", [
    {"kind": "generated_resume", "label": "合成", "text": "x"},
    {"kind": "original_resume", "label": "合成", "text": "   "},
    {"kind": "original_resume", "label": "合成", "text": "x", "evidence_level": "C3"},
])
def test_source_contract_does_not_accept_generated_material_or_level_override(payload):
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(payload)


def test_edit_is_immutable_and_new_confirmation_is_required(repo):
    first = create(repo)
    confirmed = repo.confirm_version("alice", first.resume_id, first.version_id,
                                     expected_content_hash=first.content_hash)
    second = revise(repo, first)
    assert second.sequence == 2
    assert second.parent_version_id == first.version_id
    assert second.document.skills[0].text == "FastAPI"
    assert second.confirmed_at is None
    old = repo.get_version("alice", first.resume_id, first.version_id)
    assert old.document.skills[0].text == "Python"
    assert old.confirmed_at == confirmed.confirmed_at
    assert old.confirmation_scope == "user_attested_only"


def test_model_copy_cannot_skip_duplicate_validation_at_write_boundary(repo):
    first = create(repo)
    unsafe = first.document.model_copy(update={"skills": [first.document.skills[0], first.document.skills[0]]})
    with pytest.raises(ValidationError, match="duplicate_fact_id"):
        repo.save_version("alice", first.resume_id, VersionCreate(
            expected_parent_version_id=first.version_id, document=unsafe))
    assert len(repo.list_versions("alice", first.resume_id)) == 1


def test_stale_edit_is_a_conflict(repo):
    first = create(repo)
    second = revise(repo, first)
    with pytest.raises(WorkspaceConflict, match="resume_head_changed"):
        revise(repo, first)
    assert [v.version_id for v in repo.list_versions("alice", first.resume_id)] == [second.version_id, first.version_id]


def test_simultaneous_edits_have_one_winner(repo):
    first = create(repo)

    def attempt(_):
        try:
            revise(repo, first)
            return "saved"
        except WorkspaceConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["conflict", "saved"]
    assert len(repo.list_versions("alice", first.resume_id)) == 2


def test_confirmation_binds_hash_and_current_version(repo):
    first = create(repo)
    with pytest.raises(WorkspaceConflict, match="confirmation_content_changed"):
        repo.confirm_version("alice", first.resume_id, first.version_id, expected_content_hash="0" * 64)
    second = revise(repo, first)
    with pytest.raises(WorkspaceConflict, match="only_current"):
        repo.confirm_version("alice", first.resume_id, first.version_id,
                             expected_content_hash=first.content_hash)
    assert repo.get_version("alice", first.resume_id, second.version_id).confirmed_at is None


def test_confirmation_retry_is_idempotent_even_after_edit(repo):
    first = create(repo)
    one = repo.confirm_version("alice", first.resume_id, first.version_id, expected_content_hash=first.content_hash)
    revise(repo, first)
    two = repo.confirm_version("alice", first.resume_id, first.version_id, expected_content_hash=first.content_hash)
    assert one == two


def test_restore_a_b_a_creates_new_draft_and_persists(repo):
    first = create(repo)
    repo.confirm_version("alice", first.resume_id, first.version_id, expected_content_hash=first.content_hash)
    second = revise(repo, first)
    third = repo.restore_version("alice", first.resume_id, first.version_id,
                                 expected_parent_version_id=second.version_id, note="恢复")
    assert third.content_hash == first.content_hash
    assert third.version_id != first.version_id
    assert third.sequence == 3
    assert third.restored_from_version_id == first.version_id
    assert third.parent_version_id == second.version_id
    assert third.confirmed_at is None
    reopened = SqliteResumeRepository(repo.path)
    assert reopened.get_version("alice", first.resume_id, third.version_id) == third
    assert reopened.list_resumes("alice")[0].head_version_id == third.version_id


def test_restore_requires_current_head_and_same_resume(repo):
    first = create(repo)
    second = revise(repo, first)
    foreign = create(repo)
    with pytest.raises(WorkspaceConflict):
        repo.restore_version("alice", first.resume_id, first.version_id,
                             expected_parent_version_id=first.version_id)
    with pytest.raises(WorkspaceNotFound):
        repo.restore_version("alice", first.resume_id, foreign.version_id,
                             expected_parent_version_id=second.version_id)


def test_citations_prevent_source_deletion_until_all_referencing_resumes_removed(repo):
    record = source(repo)
    a = repo.create_resume("alice", ResumeCreate(title="A", document=document(record)))
    b = repo.create_resume("alice", ResumeCreate(title="B", document=document(record)))
    with pytest.raises(WorkspaceConflict, match="source_referenced"):
        repo.delete_source("alice", record.source_id)
    repo.delete_resume("alice", a.resume_id)
    with pytest.raises(WorkspaceConflict):
        repo.delete_source("alice", record.source_id)
    repo.delete_resume("alice", b.resume_id)
    repo.delete_source("alice", record.source_id)
    with pytest.raises(WorkspaceNotFound):
        repo.get_source("alice", record.source_id)
    with sqlite3.connect(repo.path) as db:
        for table in ["rw_resumes", "rw_versions", "rw_version_sources", "rw_confirmations", "rw_sources"]:
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_foreign_resources_are_indistinguishable_from_missing_resources(repo):
    first = create(repo)
    assert repo.list_resumes("bob") == []
    for operation in [
        lambda: repo.get_source("bob", first.document.personal.name.source.source_id),
        lambda: repo.get_version("bob", first.resume_id, first.version_id),
        lambda: repo.list_versions("bob", first.resume_id),
        lambda: repo.delete_resume("bob", first.resume_id),
        lambda: repo.confirm_version("bob", first.resume_id, first.version_id, expected_content_hash=first.content_hash),
        lambda: revise(repo, first, owner="bob"),
    ]:
        with pytest.raises(WorkspaceNotFound):
            operation()


@pytest.mark.parametrize("target", ["source", "version"])
def test_stored_corruption_fails_closed_on_read(repo, target):
    first = create(repo)
    with sqlite3.connect(repo.path) as db:
        if target == "source":
            db.execute("UPDATE rw_sources SET text='篡改内容'")
        else:
            payload = first.document.model_dump(mode="json")
            payload["skills"].reverse()
            db.execute("UPDATE rw_versions SET document_json=?", (json.dumps(payload),))
    with pytest.raises(InvalidProvenance, match="integrity_failed"):
        repo.get_version("alice", first.resume_id, first.version_id)


@pytest.fixture
def client(repo):
    return TestClient(create_resume_app(repo, resolve_identity={"test-alice": "alice", "test-bob": "bob"}.get))


ALICE = {"Authorization": "Bearer test-alice"}
BOB = {"Authorization": "Bearer test-bob"}


def test_api_end_to_end_versions_confirmation_restore_and_delete(client):
    created_source = client.post("/api/v2/sources", headers=ALICE, json={
        "kind": "original_resume", "label": "合成", "text": "演示同学\nPython\nFastAPI"})
    assert created_source.status_code == 201
    from job_agent.resume_workspace.contracts import SourceRecord
    stored = SourceRecord.model_validate(created_source.json())
    payload = {"title": "合成简历", "document": document(stored).model_dump(mode="json")}
    response = client.post("/api/v2/resumes", headers=ALICE, json=payload)
    assert response.status_code == 201
    first = response.json()
    base = f"/api/v2/resumes/{first['resume_id']}"
    v1 = f"{base}/versions/{first['version_id']}"
    assert client.get("/api/v2/resumes", headers=ALICE).json()[0]["version_count"] == 1
    assert client.get(v1, headers=ALICE).json() == first
    confirm = client.post(v1 + "/confirm", headers=ALICE, json={"expected_content_hash": first["content_hash"]})
    assert confirm.status_code == 200 and confirm.json()["confirmed_at"]
    payload["document"]["skills"].reverse()
    edit = {"expected_parent_version_id": first["version_id"], "document": payload["document"]}
    second = client.post(base + "/versions", headers=ALICE, json=edit)
    assert second.status_code == 201 and second.json()["confirmed_at"] is None
    assert client.post(base + "/versions", headers=ALICE, json=edit).status_code == 409
    restored = client.post(v1 + "/restore", headers=ALICE, json={
        "expected_parent_version_id": second.json()["version_id"]})
    assert restored.status_code == 201
    assert restored.json()["content_hash"] == first["content_hash"]
    assert len(client.get(base + "/versions", headers=ALICE).json()) == 3
    source_url = f"/api/v2/sources/{stored.source_id}"
    assert client.delete(source_url, headers=ALICE).status_code == 409
    assert client.delete(base, headers=ALICE).status_code == 204
    assert client.delete(source_url, headers=ALICE).status_code == 204
    assert client.get(source_url, headers=ALICE).status_code == 404


def test_api_does_not_trust_user_header_or_body(client, repo):
    first = create(repo)
    url = f"/api/v2/resumes/{first.resume_id}/versions/{first.version_id}"
    assert client.get(url, headers={"X-User-Id": "alice"}).status_code == 401
    assert client.get(url, headers={**BOB, "X-User-Id": "alice"}).status_code == 404
    assert client.get(url, headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/api/v2/resumes", headers=BOB).json() == []
    assert client.post("/api/v2/sources", headers=ALICE, json={
        "owner_id": "bob", "kind": "user_statement", "text": "private", "label": "合成"}).status_code == 422


def test_validation_response_does_not_echo_private_values(client):
    response = client.post("/api/v2/sources", headers=ALICE, json={
        "kind": "private-test-email@example.invalid", "label": "合成", "text": "private phone"})
    assert response.status_code == 422
    assert "private-test-email" not in response.text
    assert "private phone" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_api_rejects_reference_fact_with_sanitized_error(client, repo):
    doc = document(source(repo, kind="reference"))
    response = client.post("/api/v2/resumes", headers=ALICE, json={"title": "合成", "document": doc.model_dump()})
    assert response.status_code == 422
    assert response.json() == {"detail": "reference_or_jd_is_not_candidate_evidence"}


def test_openapi_is_accessible_without_disclosing_private_records(client):
    assert client.get("/health/live").json()["status"] == "ok"
    schema = client.get("/openapi.json").json()
    assert "/api/v2/resumes" in schema["paths"]
    assert schema["paths"]["/api/v2/resumes"]["get"]["security"] == [{"HTTPBearer": []}]
    assert client.get("/api/v2/resumes").status_code == 401


def test_local_launcher_requires_configured_secret_and_handles_invalid_bearer(monkeypatch, tmp_path):
    from job_agent.resume_workspace.main import create_app
    monkeypatch.delenv("JOB_AGENT_WORKSPACE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="JOB_AGENT_WORKSPACE_API_TOKEN"):
        create_app()
    monkeypatch.setenv("JOB_AGENT_WORKSPACE_API_TOKEN", "synthetic-test-token-" * 3)
    monkeypatch.setenv("JOB_AGENT_WORKSPACE_DB", str(tmp_path / "local.sqlite"))
    local = TestClient(create_app())
    assert local.get("/api/v2/resumes", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert local.get("/api/v2/resumes", headers={"Authorization": "Bearer " + "synthetic-test-token-" * 3}).status_code == 200


def test_synthetic_demo_runs_without_models_or_credentials(tmp_path):
    from scripts.demo_resume_versions import run_demo
    report = run_demo(tmp_path)
    assert all(report["checks"].values())
    assert (tmp_path / "report.json").exists()
