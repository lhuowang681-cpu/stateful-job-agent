from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

import pytest

from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.jd_match_demo import (
    knowledge_documents_from_career_dataset,
    run_jd_match_demo,
)
from job_agent.knowledge.vector_index import InMemoryVectorIndex


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"
JD_PATH = Path(__file__).parent / "fixtures" / "jd_match" / "synthetic_jd.md"

EXPECTED_DOCUMENTS = {
    "atom_001": "real-dense-knowledge-retrieval",
    "atom_002": "real-backend-reliability",
    "atom_003": "real-career-store",
}
GAP_ATOMS = {
    "atom_004",
    "atom_005",
}


class SemanticFixtureEmbeddingBackend:
    _groups = (
        ("rag", "语义检索", "qwen", "faiss"),
        ("异步", "async", "lease", "checkpoint"),
        ("迁移", "migration", "legacy", "idempotent"),
        ("kubernetes",),
        ("pdf", "docx"),
    )

    def _embed(self, text: str) -> list[float]:
        lowered = text.casefold()
        return [
            float(any(term in lowered for term in group))
            for group in self._groups
        ]

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _assert_vertical_slice(analysis, dataset) -> None:
    assert len(analysis.requirement_analysis.atoms) == 5
    assert len(analysis.requirements) == 5
    assert analysis.supported == ()
    assert set(analysis.partial_or_unverified) == set(EXPECTED_DOCUMENTS)
    assert set(analysis.gaps) == GAP_ATOMS
    assert analysis.unsupported == ()
    assert analysis.evidence_summary.unverified_lead_count == 3
    assert analysis.evidence_summary.gap_count == 2
    assert analysis.evidence_summary.evidence_link_count == 3

    documents_by_id = {
        document.document_id: document
        for document in knowledge_documents_from_career_dataset(dataset)
    }
    for requirement in analysis.requirements:
        assert requirement.explanation
        if requirement.atom.atom_id in GAP_ATOMS:
            assert requirement.status == "gap"
            assert requirement.evidence_items == ()
            continue

        expected_document_id = EXPECTED_DOCUMENTS[requirement.atom.atom_id]
        assert requirement.status == "unverified_lead"
        assert len(requirement.evidence_items) == 1
        evidence = requirement.evidence_items[0]
        document = documents_by_id[evidence.document_id]
        span = evidence.evidence_link.source_span

        assert evidence.document_id == expected_document_id
        assert evidence.document_version == document.version
        assert evidence.document_content_hash == document.content_hash
        assert evidence.evidence_link.atom_id == requirement.atom.atom_id
        assert evidence.retrieval_method == "dense"
        assert span.source_id != analysis.jd_source_id
        assert span.content_hash == document.content_hash
        assert document.text[span.start_offset:span.end_offset] == span.exact_quote

    assert all(
        evidence.document_id != "synthetic-jd-agent-engineer"
        for requirement in analysis.requirements
        for evidence in requirement.evidence_items
    )


def test_synthetic_jd_match_analysis_is_provenance_safe(tmp_path: Path) -> None:
    dataset = load_career_benchmark(FIXTURE_ROOT)

    analysis = run_jd_match_demo(
        dataset,
        jd_text=JD_PATH.read_text(encoding="utf-8"),
        embedding_backend=SemanticFixtureEmbeddingBackend(),
        vector_index=InMemoryVectorIndex(),
        session_dir=tmp_path,
    )

    _assert_vertical_slice(analysis, dataset)


def test_synthetic_jd_match_analysis_with_real_qwen(tmp_path: Path) -> None:
    model_path = os.environ.get("QWEN_EMBEDDING_MODEL_PATH")
    if not model_path or not Path(model_path).is_dir():
        pytest.skip("QWEN_EMBEDDING_MODEL_PATH is unavailable")
    pytest.importorskip("faiss")
    pytest.importorskip("sentence_transformers")

    from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    dataset = load_career_benchmark(FIXTURE_ROOT)
    analysis = run_jd_match_demo(
        dataset,
        jd_text=JD_PATH.read_text(encoding="utf-8"),
        embedding_backend=QwenEmbeddingBackend(
            model_path=model_path,
            device="cuda",
        ),
        vector_index=FAISSVectorIndex(),
        session_dir=tmp_path,
    )

    _assert_vertical_slice(analysis, dataset)
