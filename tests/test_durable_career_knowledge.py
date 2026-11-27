from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

import pytest

from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.evidence.contracts import EvidenceLink
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.career_knowledge_eval import (
    load_durable_career_eval,
    run_durable_career_eval,
)
from job_agent.knowledge.durable import (
    CareerKnowledgeLifecycle,
    EmbeddingIdentity,
    IndexCompatibilityError,
    KnowledgeRepository,
    span_for_chunk,
)


SERVER_SCRIPT = "tests/fixtures/career_knowledge_mcp_server.py"
IDENTITY = EmbeddingIdentity(
    provider="deterministic",
    model="mcp-runtime-fixture-v1",
    dimension=5,
)


class KeywordEmbeddingBackend:
    groups = (
        ("faiss", "dense"),
        ("mcp", "runtime"),
        ("evidence", "provenance"),
        ("research", "lora"),
        ("multimodal", "vision"),
    )

    def __init__(self) -> None:
        self.document_calls = 0

    def _embed(self, text: str) -> list[float]:
        lowered = text.casefold()
        return [float(any(term in lowered for term in group)) for group in self.groups]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FailingEmbeddingBackend(KeywordEmbeddingBackend):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("synthetic embedding failure")


def _lifecycle(
    root: Path,
    *,
    backend=None,
    identity: EmbeddingIdentity = IDENTITY,
    max_chars: int = 48,
) -> CareerKnowledgeLifecycle:
    return CareerKnowledgeLifecycle(
        repository=KnowledgeRepository(root / "knowledge.sqlite"),
        embedding_backend=backend or KeywordEmbeddingBackend(),
        embedding_identity=identity,
        index_path=root / "career.faiss",
        manifest_path=root / "career-index-manifest.json",
        max_chars=max_chars,
    )


def _ingest_project(
    lifecycle: CareerKnowledgeLifecycle,
    *,
    document_id: str = "project-job-agent",
    text: str = "Used FAISS to build dense retrieval.",
):
    return lifecycle.ingest_text(
        document_id=document_id,
        source_type="project",
        text=text,
        title="Job Agent",
        source_uri="docs/job-agent.md",
        metadata={"material_kind": "real_project_material"},
    )


def test_same_content_is_noop_and_version_update_is_durable(tmp_path: Path) -> None:
    backend = KeywordEmbeddingBackend()
    lifecycle = _lifecycle(tmp_path, backend=backend)

    first = _ingest_project(lifecycle)
    calls_after_first = backend.document_calls
    unchanged = _ingest_project(lifecycle)
    updated = _ingest_project(
        lifecycle,
        text=(
            "Used FAISS to build dense retrieval.\n"
            "Connected candidate evidence through MCP and Agent Runtime."
        ),
    )

    assert first.status == "COMMITTED"
    assert unchanged.status == "UNCHANGED"
    assert unchanged.corpus_version == first.corpus_version == 1
    assert backend.document_calls == calls_after_first + 1
    assert updated.document_version == 2
    assert updated.corpus_version == 2
    assert [item.version for item in lifecycle.repository.list_document_versions("project-job-agent")] == [1, 2]
    assert lifecycle.repository.get_active_document("project-job-agent").version == 2


def test_chunk_identity_offsets_and_repository_reload(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    result = _ingest_project(
        lifecycle,
        text="FAISS dense retrieval.\r\nMCP Runtime integration.",
    )
    document = lifecycle.repository.get_document("project-job-agent", 1)
    chunks = lifecycle.repository.get_chunks("project-job-agent", 1)

    reopened = KnowledgeRepository(tmp_path / "knowledge.sqlite")
    reopened_chunks = reopened.get_chunks("project-job-agent", 1)

    assert result.chunk_count == len(chunks)
    assert [item.chunk_id for item in reopened_chunks] == [item.chunk_id for item in chunks]
    assert all(document.text[item.start_offset:item.end_offset] == item.text for item in chunks)


def test_persistent_faiss_reload_without_document_embedding(tmp_path: Path) -> None:
    first_backend = KeywordEmbeddingBackend()
    first = _lifecycle(tmp_path, backend=first_backend)
    _ingest_project(first, text="MCP integration through the governed Agent Runtime.")

    second_backend = KeywordEmbeddingBackend()
    second = _lifecycle(tmp_path, backend=second_backend)
    manifest = second.load_index()
    hits = second.candidate_retriever(load=False).retrieve(
        query="MCP Runtime integration",
        limit=1,
    )

    assert manifest.corpus_version == 1
    assert manifest.document_count == 1
    assert manifest.chunk_count >= 1
    assert second_backend.document_calls == 0
    assert hits[0].chunk.document_id == "project-job-agent"


def test_manifest_rejects_embedding_and_index_incompatibility(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _ingest_project(lifecycle)

    incompatible = _lifecycle(
        tmp_path,
        identity=EmbeddingIdentity(
            provider="deterministic",
            model="different-model",
            dimension=5,
        ),
    )
    with pytest.raises(IndexCompatibilityError, match="embedding identity mismatch"):
        incompatible.load_index()

    (tmp_path / "career.faiss").write_bytes(b"corrupt")
    with pytest.raises(IndexCompatibilityError, match="index checksum mismatch"):
        lifecycle.load_index()


def test_update_delete_preserve_historical_provenance(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _ingest_project(lifecycle)
    old_chunk = lifecycle.repository.get_chunks("project-job-agent", 1)[0]
    old_span = span_for_chunk(lifecycle.repository, old_chunk)

    _ingest_project(
        lifecycle,
        text="FAISS dense retrieval plus MCP Runtime integration.",
    )
    assert lifecycle.candidate_retriever(load=False).retrieve(
        query="MCP Runtime",
        limit=1,
    )[0].chunk.document_version == 2

    lifecycle.delete_document("project-job-agent")
    assert lifecycle.candidate_retriever(load=False).retrieve(
        query="MCP Runtime",
        limit=5,
    ) == []
    resolved_after_delete = span_for_chunk(lifecycle.repository, old_chunk)
    assert resolved_after_delete == old_span
    historical_link = EvidenceLink(
        link_id="link-v1-after-delete",
        atom_id="atom-faiss",
        source_span=resolved_after_delete,
        claim="Built FAISS dense retrieval.",
        support_status="supported",
        level="C2",
        confidence=1.0,
    )
    assert historical_link.source_span == old_span
    assert lifecycle.repository.get_document("project-job-agent", 1).text[
        old_span.start_offset:old_span.end_offset
    ] == old_span.exact_quote


def test_failed_ingestion_is_not_active_and_can_retry(tmp_path: Path) -> None:
    failing = _lifecycle(tmp_path, backend=FailingEmbeddingBackend())
    with pytest.raises(RuntimeError, match="synthetic embedding failure"):
        _ingest_project(failing)

    assert failing.repository.get_active_document("project-job-agent") is None
    assert failing.repository.corpus_version == 0
    assert failing.repository.latest_ingestion("project-job-agent")["status"] == "FAILED"

    recovered = _lifecycle(tmp_path)
    result = _ingest_project(recovered)
    assert result.document_version == 1
    assert recovered.repository.get_active_document("project-job-agent") is not None


def test_rebuild_and_candidate_source_filtering(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _ingest_project(lifecycle)
    lifecycle.ingest_text(
        document_id="jd-agent-engineer",
        source_type="job_description",
        text="The employer asks for Kubernetes and PDF processing.",
        title="Agent Engineer JD",
    )
    assert lifecycle.repository.get_active_document("jd-agent-engineer") is not None
    assert lifecycle.candidate_retriever(load=False).indexed_document_ids == {
        "project-job-agent"
    }

    (tmp_path / "career.faiss").unlink()
    manifest = lifecycle.rebuild_index()
    assert manifest.document_count == 1
    assert lifecycle.load_index().corpus_version == 2
    assert lifecycle.candidate_retriever(load=False).retrieve(
        query="FAISS dense",
        limit=3,
    )[0].chunk.document_id == "project-job-agent"


def test_directory_import_supports_markdown_and_text(tmp_path: Path) -> None:
    source_dir = tmp_path / "career_sources"
    source_dir.mkdir()
    (source_dir / "resume.txt").write_text("FAISS dense retrieval", encoding="utf-8")
    (source_dir / "project.md").write_text("MCP Agent Runtime", encoding="utf-8")
    (source_dir / "manifest.json").write_text(
        """[
          {"path":"resume.txt","document_id":"resume-main","source_type":"resume"},
          {"path":"project.md","document_id":"project-runtime","source_type":"project"}
        ]""",
        encoding="utf-8",
    )
    results = _lifecycle(tmp_path / "state").ingest_directory(source_dir)
    assert [item.status for item in results] == ["COMMITTED", "COMMITTED"]


def test_mcp_query_survives_server_process_restart(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    _ingest_project(
        lifecycle,
        text="Integrated MCP tools with a governed Agent Runtime.",
    )
    server_env = {
        "CAREER_KNOWLEDGE_DB_PATH": str(tmp_path / "knowledge.sqlite"),
        "CAREER_KNOWLEDGE_INDEX_PATH": str(tmp_path / "career.faiss"),
        "CAREER_KNOWLEDGE_MANIFEST_PATH": str(
            tmp_path / "career-index-manifest.json"
        ),
    }

    results = []
    for _ in range(2):
        bridge = StdioMCPClientBridge(SERVER_SCRIPT, server_env=server_env)
        bridge.start()
        try:
            results.append(
                bridge.call_tool_sync(
                    CAREER_QUERY_TOOL,
                    {"query": "MCP Runtime integration", "top_k": 1},
                )
            )
        finally:
            bridge.close()

    assert [item["results"][0]["document_version"] for item in results] == [1, 1]
    assert [item["results"][0]["document_id"] for item in results] == [
        "project-job-agent",
        "project-job-agent",
    ]


def test_real_career_eval_v1_has_frozen_split_and_metrics(tmp_path: Path) -> None:
    dataset = load_durable_career_eval(
        "eval/career_knowledge_v1",
        repository_root=".",
    )
    report = run_durable_career_eval(
        dataset,
        repository_root=".",
        state_root=tmp_path,
        embedding_backend=KeywordEmbeddingBackend(),
        embedding_identity=IDENTITY,
    )

    assert len(dataset.documents) == 10
    assert len(dataset.cases) == 30
    assert {case.split for case in dataset.cases} == {"dev", "frozen"}
    assert report.positive_query_count == 25
    assert report.gap_query_count == 5
    assert 0.0 <= report.metrics.recall_at_1 <= 1.0
    assert 0.0 <= report.metrics.recall_at_5 <= 1.0
    assert report.metrics.active_version_correctness == 1.0
    assert report.performance.document_count == 10
    assert report.performance.chunk_count >= 10


def test_pdf_ingestion_preserves_extraction_page_provenance(tmp_path: Path) -> None:
    pytest.importorskip("pypdf")
    canvas_module = pytest.importorskip("reportlab.pdfgen.canvas")
    source = tmp_path / "resume.pdf"
    canvas = canvas_module.Canvas(str(source))
    canvas.drawString(72, 720, "FAISS dense retrieval")
    canvas.showPage()
    canvas.drawString(72, 720, "MCP Agent Runtime")
    canvas.save()

    lifecycle = _lifecycle(tmp_path / "state", max_chars=24)
    result = lifecycle.ingest_file(
        source,
        document_id="resume-pdf",
        source_type="resume",
    )
    document = lifecycle.repository.get_document("resume-pdf", 1)
    chunks = lifecycle.repository.get_chunks("resume-pdf", 1)
    provenance = document.metadata["extraction_provenance"]

    assert result.status == "COMMITTED"
    assert provenance["parser"] == "pypdf"
    assert provenance["offset_basis"] == "canonical_extracted_text"
    assert provenance["original_character_offsets_reliable"] is False
    assert len(provenance["page_spans"]) == 2
    assert {chunk.page for chunk in chunks if chunk.page is not None} == {1, 2}
    assert all(document.text[item.start_offset:item.end_offset] == item.text for item in chunks)


def test_docx_ingestion_extracts_paragraphs_tables_and_sections(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    source = tmp_path / "research.docx"
    document = docx.Document()
    document.add_heading("Research", level=1)
    document.add_paragraph("Evaluated LoRA against a frozen baseline.")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Metric"
    table.cell(0, 1).text = "MRR"
    document.save(source)

    lifecycle = _lifecycle(tmp_path / "state")
    lifecycle.ingest_file(
        source,
        document_id="research-docx",
        source_type="research",
    )
    stored = lifecycle.repository.get_document("research-docx", 1)
    chunks = lifecycle.repository.get_chunks("research-docx", 1)
    provenance = stored.metadata["extraction_provenance"]

    assert "Evaluated LoRA" in stored.text
    assert "Metric\tMRR" in stored.text
    assert provenance["parser"] == "python-docx"
    assert provenance["page_numbers_reliable"] is False
    assert any(item["section"] == "Research" for item in provenance["section_spans"])
    assert any(chunk.section == "Research" for chunk in chunks)
    assert all(chunk.page is None for chunk in chunks)


def test_private_career_sources_are_gitignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "data/private/resume.pdf",
            "data/career_sources/resume.pdf",
            "data/career_sources/manifest.json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(result.stdout.splitlines()) == {
        "data/private/resume.pdf",
        "data/career_sources/resume.pdf",
        "data/career_sources/manifest.json",
    }
