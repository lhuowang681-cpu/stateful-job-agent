"""Synthetic regression cases, not a real-resume accuracy benchmark."""
import hashlib
import io

from fastapi.testclient import TestClient
import pytest

from job_agent.resume_workspace.api import create_resume_app
from job_agent.resume_workspace.contracts import SourceCreate
from job_agent.resume_workspace.ingestion import extract_upload
from job_agent.resume_workspace.parsing import ResumeParser
from job_agent.resume_workspace.repository import SqliteResumeRepository


ORDINARY = """张晓明
13800000000  demo@example.invalid
教育背景
2022.09—2026.06  示例大学  计算机科学与技术  本科
项目经验
求职资料管理平台  后端开发  2025.03—2025.06
项目描述：为合成求职资料提供管理界面。
负责 Python 接口与数据校验。
使用 SQLite 保存版本，未进行生产部署。

课程检索工具  项目负责人  2024.09—2024.12
基于课程样例实现关键词检索。
实习经历
示例科技有限公司  后端开发实习生  2025.07—2025.09
参与内部接口回归测试。
专业技能
Python、SQL、Git
了解 Redis，不熟悉 Kubernetes。
荣誉奖项
合成竞赛一等奖
"""


def parse(tmp_path, text=ORDINARY):
    repo = SqliteResumeRepository(tmp_path / "autofill.sqlite")
    source = repo.add_source("synthetic", SourceCreate(kind="original_resume", label="合成简历", text=text))
    draft = ResumeParser().parse(source)
    for fact in draft.document.facts():
        assert source.text[fact.source.start:fact.source.end] == fact.text
        assert fact.source.content_hash == source.content_hash
    return source, draft


def test_ordinary_unlabeled_resume_extracts_identity_sections_and_plain_bullets(tmp_path):
    _, d = parse(tmp_path)
    doc = d.document
    assert doc.personal.name.text == "张晓明"
    assert doc.personal.phone.text == "13800000000"
    assert doc.personal.email.text == "demo@example.invalid"
    assert doc.personal.location is None
    assert doc.education[0].school.text == "示例大学"
    assert doc.education[0].major.text == "计算机科学与技术"
    assert doc.education[0].degree.text == "本科"
    assert doc.education[0].period.text == "2022.09—2026.06"
    assert len(doc.projects) == 2
    assert doc.projects[0].name.text == "求职资料管理平台"
    assert doc.projects[0].role.text == "后端开发"
    assert len(doc.projects[0].bullets) == 3
    assert "未进行生产部署" in doc.projects[0].bullets[-1].text
    assert doc.projects[1].name.text == "课程检索工具"
    assert doc.experience[0].organization.text == "示例科技有限公司"
    assert doc.experience[0].role.text == "后端开发实习生"
    assert [f.text for f in doc.skills] == ["Python", "SQL", "Git", "了解 Redis，不熟悉 Kubernetes。"]
    assert d.usage.provider_calls == 0 and d.provider == "python"


def test_multiline_entry_metadata_and_dated_description_do_not_create_phantom_projects(tmp_path):
    _, d = parse(tmp_path, "姓名：合成同学\n项目经历\n合成平台\n2025.01 - 2025.06\n项目负责人\n负责 2025.03—2025.04 阶段测试。\n- 2025.04—2025.05 完成测试。\n第二行说明不带项目符号。")
    assert len(d.document.projects) == 1
    p = d.document.projects[0]
    assert p.name.text == "合成平台" and p.role.text == "项目负责人"
    assert p.period.text == "2025.01 - 2025.06"
    assert len(p.bullets) == 3


@pytest.mark.parametrize("heading", ["项目经历", "项目经验", "项 目 经 历", "【项目经历】", "## 项目经历", "Projects"], ids=["cn", "alias", "spaced", "brackets", "markdown", "english"])
def test_heading_variants_preserve_unicode_offsets(tmp_path, heading):
    _, d = parse(tmp_path, f"姓名：合成同学\n{heading}\n示例平台 | 开发 | 2025\n• 处理 😀 示例数据。")
    assert d.document.projects[0].bullets[0].text == "处理 😀 示例数据。"


def test_duplicate_contacts_are_not_arbitrarily_selected(tmp_path):
    _, d = parse(tmp_path, "张晓明\na@example.invalid | b@example.invalid\n13800000000 | 13900000000\n技能\nPython")
    assert d.document.personal.email is None and d.document.personal.phone is None
    assert len(d.warnings) == 3
    assert any("多个候选" in warning for warning in d.warnings)


@pytest.mark.parametrize("intro", ["后端开发工程师", "个人简历", "AI Agent 开发实习生", "Unknown identity"], ids=["job-title", "resume-title", "target-role", "unknown"])
def test_unknown_identity_remains_missing_instead_of_guessing(tmp_path, intro):
    _, d = parse(tmp_path, intro + "\n技能\nPython")
    assert d.document.personal.name is None
    assert any(q.path == "personal.name" and q.required for q in d.questions)


def test_reference_contact_in_project_body_is_not_personal_contact(tmp_path):
    _, d = parse(tmp_path, "张晓明\n项目经历\n合成邮件测试工具\n使用 receiver@example.invalid 验证邮件格式。\n荣誉奖项\n获奖记录\n证书\n不应成为项目或技能")
    assert d.document.personal.email is None
    assert len(d.document.projects) == 1
    assert len(d.document.projects[0].bullets) == 1
    assert d.document.skills == []


def test_missing_title_produces_incomplete_entry_with_original_description(tmp_path):
    _, d = parse(tmp_path, "张晓明\n项目经历\n- 负责接口测试。")
    assert d.document.projects[0].name is None
    assert d.document.projects[0].bullets[0].text == "负责接口测试。"
    assert any(q.path == "projects.0.name" and q.required for q in d.questions)


def test_date_first_pipe_columns_are_not_mistaken_for_school_or_project_name(tmp_path):
    _, d = parse(tmp_path, "张晓明\n教育经历\n2022—2026 | 示例大学 | 本科 | 计算机\n项目经历\n2025.01—至今 | 合成平台 | 开发")
    assert d.document.education[0].school.text == "示例大学"
    assert d.document.education[0].degree.text == "本科"
    assert d.document.education[0].major.text == "计算机"
    assert d.document.projects[0].name.text == "合成平台"
    assert d.document.projects[0].period.text == "2025.01—至今"


def test_project_technology_subheading_does_not_assert_personal_skills(tmp_path):
    _, d = parse(tmp_path, "张晓明\n项目经历\n合成平台 | 开发 | 2025\n技术栈\nPython、Redis\n负责接口测试。")
    assert d.document.skills == []
    assert len(d.document.projects) == 1
    assert [f.text for f in d.document.projects[0].bullets] == ["技术栈", "Python、Redis", "负责接口测试。"]


def test_multiple_identity_labels_on_header_line_and_english_name(tmp_path):
    _, d = parse(tmp_path, "姓名：合成同学 | 邮箱：demo@example.invalid | 电话：13800000000\n技能\nPython")
    assert d.document.personal.name.text == "合成同学"
    assert d.document.personal.email.text == "demo@example.invalid"
    assert d.document.personal.phone.text == "13800000000"
    _, english = parse(tmp_path, "Alice Example\nEducation\nExample College | Bachelor | Computer Science | 2020—2024")
    assert english.document.personal.name.text == "Alice Example"


def synthetic_pdf(text=ORDINARY):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    data = io.BytesIO()
    canvas = Canvas(data, pagesize=(595, 842))
    canvas.setFont("STSong-Light", 11)
    y = 805
    for line in text.splitlines():
        if line == "===PAGE===":
            canvas.showPage(); canvas.setFont("STSong-Light", 11); y = 805
            continue
        canvas.drawString(35, y, line)
        y -= 21
    canvas.save()
    return data.getvalue()


def test_real_pdf_bytes_to_draft_to_saved_version_without_manual_edits(tmp_path):
    raw = synthetic_pdf()
    repo = SqliteResumeRepository(tmp_path / "http.sqlite")
    client = TestClient(create_resume_app(repo, resolve_identity={"a": "synthetic", "b": "other"}.get))
    headers = {"Authorization": "Bearer a"}
    imported = client.post("/api/v2/imports?filename=synthetic-resume.pdf", headers=headers, content=raw)
    assert imported.status_code == 201
    data = imported.json()
    assert data["raw_hash"] == hashlib.sha256(raw).hexdigest()
    source_id = data["source_id"]
    d = client.post(f"/api/v2/sources/{source_id}/parse", headers=headers, json={}).json()
    assert d["document"]["personal"]["name"]["text"] == "张晓明"
    assert len(d["document"]["projects"]) == 2
    saved = client.post(f"/api/v2/drafts/{d['draft_id']}/accept", headers=headers, json={
        "title": "合成 PDF 自动填表", "expected_source_hash": d["source_content_hash"], "user_reviewed": True, "edits": [],
    })
    assert saved.status_code == 201 and saved.json()["confirmed_at"] is None
    assert client.get(f"/api/v2/sources/{source_id}/original", headers=headers).content == raw
    assert client.get(f"/api/v2/sources/{source_id}", headers={"Authorization": "Bearer b"}).status_code == 404
    source = repo.get_source("synthetic", source_id)
    for fact in repo.list_versions("synthetic", saved.json()["resume_id"])[0].document.facts():
        assert fact.text == source.text[fact.source.start:fact.source.end]


def test_multipage_pdf_retains_canonical_citations_and_original_wording(tmp_path):
    raw = synthetic_pdf("张晓明\n教育经历\n示例大学 | 硕士 | 计算机 | 2024—2027\n===PAGE===\n项目经历\n示例平台 | 开发 | 2025\n使用 Python 完成合成演示。")
    extracted = extract_upload("two-pages.pdf", raw)
    assert len(extracted.metadata["page_spans"]) == 2
    _, d = parse(tmp_path, extracted.text)
    assert d.document.projects[0].bullets[0].text == "使用 Python 完成合成演示。"
