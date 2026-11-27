from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from job_agent.knowledge.candidate_evidence import (
    CandidateEvidenceRetriever,
    is_candidate_evidence_document,
)
from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_candidate_evidence_compare import (
    run_candidate_evidence_comparison,
)
from job_agent.knowledge.ingestion import create_knowledge_document
from job_agent.knowledge.vector_index import InMemoryVectorIndex


_CREATED_AT = datetime(2026, 9, 17, tzinfo=timezone.utc)
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"


class KeywordEmbeddingBackend:
    _terms = ("rag", "faiss", "async", "career", "mcp", "evidence")

    def _embed(self, text: str) -> list[float]:
        lowered = text.casefold()
        return [float(lowered.count(term)) for term in self._terms]

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _document(
    document_id: str,
    *,
    source_type: str,
    text: str,
    material_kind: str,
):
    return create_knowledge_document(
        document_id=document_id,
        source_type=source_type,
        text=text,
        version=1,
        metadata={"material_kind": material_kind},
        created_at=_CREATED_AT,
    )


def test_candidate_retrieval_excludes_jd_from_the_index() -> None:
    jd = _document(
        "job-description",
        source_type="job_description",
        text="岗位要求 RAG experience and semantic retrieval.",
        material_kind="synthetic_jd",
    )
    project = _document(
        "candidate-project",
        source_type="project",
        text="Implemented Qwen embedding and FAISS retrieval for RAG.",
        material_kind="real_project_material",
    )
    retriever = CandidateEvidenceRetriever.from_documents(
        [jd, project],
        embedding_backend=KeywordEmbeddingBackend(),
        vector_index=InMemoryVectorIndex(),
    )

    hits = retriever.retrieve(query="RAG experience", limit=10)

    assert retriever.indexed_document_ids == frozenset({"candidate-project"})
    assert {hit.chunk.document_id for hit in hits} == {"candidate-project"}
    assert all(hit.chunk.document_id != "job-description" for hit in hits)


def test_candidate_scope_is_explicit_and_does_not_use_fuzzy_source_names() -> None:
    project_material = _document(
        "technical-project",
        source_type="technical_material",
        text="Backend project details.",
        material_kind="real_project_material",
    )
    external_material = _document(
        "external-reference",
        source_type="technical_material",
        text="Generic external architecture guide.",
        material_kind="external_reference",
    )
    fuzzy_project = _document(
        "fuzzy-project",
        source_type="my_project_notes",
        text="Personal notes.",
        material_kind="real_project_material",
    )

    assert is_candidate_evidence_document(project_material)
    assert not is_candidate_evidence_document(external_material)
    assert not is_candidate_evidence_document(fuzzy_project)


def test_career_comparison_uses_same_cases_with_candidate_scoped_index() -> None:
    report = run_candidate_evidence_comparison(
        load_career_benchmark(FIXTURE_ROOT),
        embedding_backend=KeywordEmbeddingBackend(),
        global_vector_index=InMemoryVectorIndex(),
        candidate_vector_index=InMemoryVectorIndex(),
    )

    cases = {case.case_id: case for case in report.positive_cases}

    assert len(report.positive_cases) == 18
    assert len(report.gap_cases) == 2
    assert "synthetic-jd-agent-engineer" not in report.candidate_document_ids
    assert cases["requirement-synthetic-agent-jd"].candidate_rank is None
    assert 0.0 <= report.global_requirement_metrics.recall_at_5 <= 1.0
    assert 0.0 <= report.candidate_requirement_metrics.recall_at_5 <= 1.0
