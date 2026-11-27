from __future__ import annotations

import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from job_agent.llm.provider import ProviderTimeoutError
from job_agent.llm.providers.mock import result_from_raw_output
from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.contracts import ResumeDocument, SourceCreate
from job_agent.resume_workspace.ingestion import MAX_UPLOAD_BYTES, extract_upload
from job_agent.resume_workspace.parsing import ResumeParser, materialize
from job_agent.resume_workspace.parsing_contracts import (
    AcceptDraft, EditVersion, FieldCandidate, FieldEdit, ImportErrorCode, ParseCandidate, ParseError,
)
from job_agent.resume_workspace.repository import SqliteResumeRepository, WorkspaceConflict, WorkspaceNotFound


TEXT = "姓名：合成同学\n邮箱：demo@example.invalid\n教育经历\n示例大学 | 硕士 | 计算机 | 2024—2027\n项目经历\n示例工具 | 开发 | 2025\n- 用 Python 编写接口。\n技能\nPython、SQL\n"
A = {"Authorization": "Bearer test-alice"}
B = {"Authorization": "Bearer test-bob"}


@pytest.fixture
def repo(tmp_path):
    return SqliteResumeRepository(tmp_path / "m2.sqlite")


def source(repo, text=TEXT):
    return repo.add_source("alice", SourceCreate(kind="original_resume", label="合成", text=text))


def draft(repo, text=TEXT):
    return repo.save_draft("alice", ResumeParser().parse(source(repo, text)))


def accept_request(d, **kwargs):
    return AcceptDraft(title="合成简历", expected_source_hash=d.source_content_hash, user_reviewed=True, **kwargs)


class FixtureProvider:
    provider_name = "test-only"
    model = "fixture-not-real-model"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return result_from_raw_output(provider=self.provider_name, model=self.model,
                                      raw_output=json.dumps(output), output_schema=kwargs["output_schema"],
                                      trace=kwargs["trace"], latency_ms=1, input_tokens=10, output_tokens=5)


def test_rules_parse_exact_fields_without_model_or_fabricated_missing_phone(repo):
    record = source(repo)
    result = ResumeParser().parse(record)
    assert result.usage.provider_calls == 0 and result.usage.cost is None
    assert result.document.personal.name.text == "合成同学"
    assert result.document.personal.phone is None
    assert any(q.path == "personal.phone" for q in result.questions)
    assert result.document.education[0].major.text == "计算机"
    assert result.document.projects[0].bullets[0].text == "用 Python 编写接口。"
    assert [f.text for f in result.document.skills] == ["Python", "SQL"]
    for fact in result.document.facts():
        assert record.text[fact.source.start:fact.source.end] == fact.text


def test_missing_name_yields_partial_draft_instead_of_hallucination(repo):
    d = draft(repo, "技能\nPython、SQL")
    assert d.document.personal.name is None
    assert any(q.path == "personal.name" and q.required for q in d.questions)
    with pytest.raises(ParseError, match="required_fields_missing"):
        repo.accept_draft("alice", d.draft_id, accept_request(d))
    saved = repo.accept_draft("alice", d.draft_id, accept_request(d, edits=[FieldEdit(path="personal.name", value="用户补充姓名")]))
    f = saved.document.personal.name
    assert repo.get_source("alice", f.source.source_id).kind == "user_statement"
    assert saved.confirmed_at is None


@pytest.mark.parametrize("path", ["__proto__.polluted", "schema_version", "education.99.school", "skills.-1", "skills.01", "projects.0.evidence_level"])
def test_parser_cannot_write_outside_allowlisted_fields(repo, path):
    with pytest.raises(ParseError, match="invalid_field_path"):
        materialize(source(repo), ParseCandidate(fields=[FieldCandidate(path=path, exact_quote="Python")]))


def test_ambiguous_quote_needs_valid_offsets(repo):
    record = source(repo, "姓名：合成同学\nPython\nPython")
    with pytest.raises(ParseError, match="ambiguous_quote"):
        materialize(record, ParseCandidate(fields=[FieldCandidate(path="skills.0", exact_quote="Python")]))
    start = record.text.rindex("Python")
    doc = materialize(record, ParseCandidate(fields=[FieldCandidate(path="skills.0", exact_quote="Python", start=start, end=start+6)]))
    assert doc.skills[0].source.start == start


@pytest.mark.parametrize("fields,code", [
    ([{"path":"skills.0", "exact_quote":"Kubernetes"}], "quote_not_found"),
    ([{"path":"skills.1", "exact_quote":"SQL"}], "sparse_field_indexes"),
    ([{"path":"skills.0", "exact_quote":"SQL"}, {"path":"skills.0", "exact_quote":"SQL"}], "duplicate_field_path"),
])
def test_invalid_model_fields_are_rejected(repo, fields, code):
    with pytest.raises(ParseError, match=code):
        materialize(source(repo), ParseCandidate.model_validate({"fields":fields}))


def test_model_semantic_guard_repairs_once_and_reports_all_usage(repo):
    provider = FixtureProvider([
        {"fields":[{"path":"skills.0","exact_quote":"Kubernetes"}]},
        {"fields":[{"path":"personal.name","exact_quote":"合成同学"}]},
    ])
    d = ResumeParser(provider).parse(source(repo), mode="llm")
    assert len(provider.calls) == 2
    assert d.usage.provider_calls == 2 and d.usage.input_tokens == 20 and d.usage.output_tokens == 10
    assert all(not call["tools"] for call in provider.calls)
    assert "untrusted" in provider.calls[0]["system_prompt"].lower()


def test_two_bad_model_results_fail_without_rule_fallback(repo):
    provider = FixtureProvider([{"fields":[{"path":"skills.0","exact_quote":"invented"}]}] * 2)
    with pytest.raises(ParseError, match="model_parse_failed"):
        ResumeParser(provider).parse(source(repo), mode="llm")
    assert len(provider.calls) == 2 and repo.list_drafts("alice") == []


def test_model_transport_timeout_does_not_retry_potentially_billable_call(repo):
    provider = FixtureProvider([ProviderTimeoutError("private-error-not-returned")])
    with pytest.raises(ParseError, match="model_request_failed"):
        ResumeParser(provider).parse(source(repo), mode="llm")
    assert len(provider.calls) == 1


def test_model_input_limit_and_reference_kind_reject_before_call(repo):
    provider = FixtureProvider([])
    with pytest.raises(ParseError, match="model_input_too_large"):
        ResumeParser(provider).parse(source(repo, "x" * 30_001), mode="llm")
    foreign = repo.add_source("alice", SourceCreate(kind="reference", label="参考", text="Python"))
    with pytest.raises(ParseError, match="parser_requires_original_resume"):
        ResumeParser(provider).parse(foreign)
    assert provider.calls == []


def test_accept_is_idempotent_and_conflicting_retry_is_rejected(repo):
    d = draft(repo)
    first = repo.accept_draft("alice", d.draft_id, accept_request(d))
    assert repo.accept_draft("alice", d.draft_id, accept_request(d)) == first
    changed = accept_request(d, edits=[FieldEdit(path="personal.name", value="另一姓名")])
    with pytest.raises(WorkspaceConflict, match="draft_already_accepted"):
        repo.accept_draft("alice", d.draft_id, changed)
    assert len(repo.list_resumes("alice")) == 1
    assert repo.list_drafts("alice") == []


def test_simultaneous_accept_creates_one_resume(repo):
    d = draft(repo)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.accept_draft("alice", d.draft_id, accept_request(d)), range(2)))
    assert results[0].version_id == results[1].version_id
    assert len(repo.list_resumes("alice")) == 1


def test_review_edits_preserve_original_and_create_new_self_attestation(repo):
    d = draft(repo)
    first = repo.accept_draft("alice", d.draft_id, accept_request(d))
    repo.confirm_version("alice", first.resume_id, first.version_id, expected_content_hash=first.content_hash)
    second = repo.edit_version("alice", first.resume_id, first.version_id, EditVersion(edits=[
        FieldEdit(path="projects.0.bullets.0", value="我补充的实际项目说明"), FieldEdit(path="skills.1", value=""),
    ]))
    assert second.confirmed_at is None
    assert len(second.document.skills) == 1
    f = second.document.projects[0].bullets[0]
    assert repo.get_source("alice", f.source.source_id).kind == "user_statement"
    assert repo.get_source("alice", d.source_id).text == TEXT
    assert repo.get_version("alice", first.resume_id, first.version_id).document.projects[0].bullets[0].text == "用 Python 编写接口。"
    with pytest.raises(WorkspaceConflict, match="resume_head_changed"):
        repo.edit_version("alice", first.resume_id, first.version_id, EditVersion(edits=[]))


def test_failed_edit_transaction_does_not_leave_orphan_statement(repo):
    d = draft(repo)
    first = repo.accept_draft("alice", d.draft_id, accept_request(d))
    with sqlite3.connect(repo.path) as db:
        before = db.execute("SELECT COUNT(*) FROM rw_sources").fetchone()[0]
    with pytest.raises(ParseError):
        repo.edit_version("alice", first.resume_id, first.version_id, EditVersion(edits=[
            FieldEdit(path="skills.2", value="新补充"), FieldEdit(path="personal.name", value="")]))
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT COUNT(*) FROM rw_sources").fetchone()[0] == before
    assert len(repo.list_versions("alice", first.resume_id)) == 1


def test_drafts_are_private_and_persist_across_repository_reopen(repo):
    d = draft(repo)
    assert SqliteResumeRepository(repo.path).get_draft("alice", d.draft_id) == d
    assert repo.list_drafts("bob") == []
    with pytest.raises(WorkspaceNotFound):
        repo.accept_draft("bob", d.draft_id, accept_request(d))
    with pytest.raises(WorkspaceConflict, match="source_referenced_by_draft"):
        repo.delete_source("alice", d.source_id)
    repo.delete_draft("alice", d.draft_id)
    repo.delete_source("alice", d.source_id)


@pytest.mark.parametrize("filename,data,code", [
    ("x.exe", b"x", "unsupported_file_type"), ("x.txt", b"", "empty_upload"),
    ("x.pdf", b"not-pdf", "invalid_pdf"), ("x.docx", b"not-a-zip", "invalid_docx"),
    ("x.txt", b"x" * (MAX_UPLOAD_BYTES+1), "upload_too_large"),
    ("x.txt", b"\xff\xfe", "document_extraction_failed"),
], ids=["unsupported", "empty", "invalid-pdf", "invalid-docx", "oversize", "invalid-utf8"])
def test_bad_uploads_fail_with_sanitized_codes(filename, data, code):
    with pytest.raises(ImportErrorCode, match=code):
        extract_upload(filename, data)


def test_text_pdf_docx_extraction_and_scan_detection(repo):
    from docx import Document
    from pypdf import PdfWriter
    from reportlab.pdfgen.canvas import Canvas
    pdf = io.BytesIO()
    canvas = Canvas(pdf); canvas.drawString(30, 700, "Name: Synthetic Student"); canvas.save()
    extracted = extract_upload("resume.pdf", pdf.getvalue())
    assert "Synthetic Student" in extracted.text
    docx = io.BytesIO(); doc = Document(); doc.add_paragraph("姓名：合成同学"); doc.save(docx)
    assert "合成同学" in extract_upload("resume.docx", docx.getvalue()).text
    blank = io.BytesIO(); writer = PdfWriter(); writer.add_blank_page(100, 100); writer.write(blank)
    with pytest.raises(ImportErrorCode, match="needs_ocr"):
        extract_upload("scan.pdf", blank.getvalue())


@pytest.fixture
def client(repo):
    return TestClient(create_resume_app(repo, resolve_identity={"test-alice":"alice", "test-bob":"bob"}.get))


def test_http_import_parse_review_edit_confirm_and_delete(client, repo):
    raw = TEXT.encode()
    response = client.post("/api/v2/imports?filename=../../resume.md", headers=A, content=raw)
    assert response.status_code == 201
    imported = response.json()
    assert imported["filename"] == "resume.md" and imported["original_preserved"]
    sid = imported["source_id"]
    assert client.get(f"/api/v2/sources/{sid}/original", headers=A).content == raw
    assert client.get(f"/api/v2/sources/{sid}/original", headers=B).status_code == 404
    parsed = client.post(f"/api/v2/sources/{sid}/parse", headers=A, json={"mode":"local_rules"})
    assert parsed.status_code == 201
    d = parsed.json()
    url = f"/api/v2/drafts/{d['draft_id']}"
    assert client.get(url, headers=B).status_code == 404
    assert client.get("/api/v2/drafts", headers=A).json()[0]["draft_id"] == d["draft_id"]
    req = {"title":"HTTP 合成简历", "expected_source_hash":d["source_content_hash"], "user_reviewed":True,
           "edits":[{"path":"personal.phone", "value":"000-TEST-ONLY"}]}
    first = client.post(url+"/accept", headers=A, json=req)
    assert first.status_code == 201 and first.json()["confirmed_at"] is None
    assert client.post(url+"/accept", headers=A, json=req).json() == first.json()
    assert client.get("/api/v2/drafts", headers=A).json() == []
    version = first.json(); rid = version["resume_id"]
    assert client.delete(f"/api/v2/resumes/{rid}", headers=A).status_code == 204
    assert client.get(url, headers=A).status_code == 404
    assert client.delete(f"/api/v2/sources/{sid}", headers=A).status_code == 204
    assert client.get(f"/api/v2/sources/{sid}/original", headers=A).status_code == 404


def test_model_consent_and_configuration_fail_closed(client, repo):
    record = source(repo)
    path = f"/api/v2/sources/{record.source_id}/parse"
    assert client.post(path, headers=A, json={"mode":"llm"}).json()["detail"] == "external_processing_consent_required"
    assert client.post(path, headers=A, json={"mode":"llm", "allow_external_processing":True}).status_code == 503
    assert not client.get("/api/v2/capabilities", headers=A).json()["llm"]
    assert client.get("/api/v2/drafts", headers=A).json() == []


def test_stream_upload_limit_and_auth_check_before_ingestion(client):
    assert client.post("/api/v2/imports?filename=x.txt", content=b"x").status_code == 401
    assert client.post("/api/v2/imports?filename=x.txt", headers=A, content=b"x"*(MAX_UPLOAD_BYTES+1)).status_code == 413


def test_api_missing_required_field_is_safe_and_draft_remains(client, repo):
    d = draft(repo, "技能\nSQL")
    req = {"title":"合成", "user_reviewed":True, "expected_source_hash":d.source_content_hash}
    response = client.post(f"/api/v2/drafts/{d.draft_id}/accept", headers=A, json=req)
    assert response.status_code == 422 and response.json()["detail"] == "required_fields_missing"
    assert len(client.get("/api/v2/drafts", headers=A).json()) == 1


def test_source_manager_scopes_and_original_attachment_deletion(client, repo):
    imported = client.post("/api/v2/imports?filename=合成.md", headers=A, content=TEXT.encode()).json()
    items = client.get("/api/v2/sources", headers=A).json()
    assert items[0]["has_original"] and not items[0]["referenced"]
    assert "text" not in items[0]
    assert client.get("/api/v2/sources", headers=B).json() == []
    sid = imported["source_id"]
    assert client.delete(f"/api/v2/sources/{sid}", headers=A).status_code == 204
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT COUNT(*) FROM rw_uploads").fetchone()[0] == 0


def test_oversized_user_edit_and_duplicate_paths_do_not_leave_sources(repo):
    d = draft(repo)
    with pytest.raises(ParseError, match="user_edits_too_large"):
        repo.accept_draft("alice", d.draft_id, accept_request(d, edits=[
            FieldEdit(path=f"skills.{i}", value="x"*5000) for i in range(21)]))
    with pytest.raises(ParseError, match="duplicate_field_path"):
        repo.accept_draft("alice", d.draft_id, accept_request(d, edits=[
            FieldEdit(path="personal.name", value="a"), FieldEdit(path="personal.name", value="b")]))
    assert len(repo.list_sources("alice")) == 1 and repo.list_resumes("alice") == []


def test_schema_repair_is_bounded_and_not_silently_replaced_by_rules(repo):
    provider = FixtureProvider([{"fields":"invalid"}, {"fields":[]}])
    result = ResumeParser(provider).parse(source(repo), mode="llm")
    assert result.document.personal.name is None
    assert result.usage.provider_calls == 2 and len(provider.calls) == 2


def test_review_requires_expected_source_and_explicit_user_action(client, repo):
    d = draft(repo)
    base = {"title":"合成", "expected_source_hash":d.source_content_hash}
    assert client.post(f"/api/v2/drafts/{d.draft_id}/accept", headers=A, json=base).status_code == 422
    base.update(user_reviewed=True, expected_source_hash="0"*64)
    assert client.post(f"/api/v2/drafts/{d.draft_id}/accept", headers=A, json=base).status_code == 409
    assert repo.list_resumes("alice") == []


def test_encrypted_pdf_and_oversized_docx_expansion_are_rejected():
    from pypdf import PdfWriter
    import zipfile
    output = io.BytesIO(); writer = PdfWriter(); writer.add_blank_page(100,100); writer.encrypt("synthetic"); writer.write(output)
    with pytest.raises(ImportErrorCode, match="encrypted_pdf"):
        extract_upload("x.pdf", output.getvalue())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x"*(31*1024*1024))
    with pytest.raises(ImportErrorCode, match="expanded_document_too_large"):
        extract_upload("x.docx", output.getvalue())


def test_synthetic_demo_is_isolated_and_never_reads_live_model_configuration(monkeypatch, tmp_path):
    from scripts.demo_resume_workbench import DEMO_CODE, build_demo_app
    monkeypatch.setenv("JOB_AGENT_WORKSPACE_ENABLE_LLM", "1")
    monkeypatch.setenv("JOB_AGENT_WORKSPACE_DB", str(tmp_path / "must-not-use.sqlite"))
    # A tiny static test build avoids requiring Node to run the Python tests.
    import scripts.demo_resume_workbench as demo_module
    fake_repo = tmp_path / "repo"
    (fake_repo / "frontend/dist").mkdir(parents=True)
    (fake_repo / "frontend/dist/index.html").write_text("synthetic-test", encoding="utf-8")
    monkeypatch.setattr(demo_module, "REPO", fake_repo)
    client = TestClient(build_demo_app(tmp_path / "demo.sqlite"))
    cap = client.get("/api/v2/capabilities", headers={"Authorization":"Bearer "+DEMO_CODE}).json()
    assert cap["demo_only"] and not cap["llm"]
    assert not (tmp_path / "must-not-use.sqlite").exists()
