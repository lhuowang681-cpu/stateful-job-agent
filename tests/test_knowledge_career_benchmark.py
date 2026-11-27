from __future__ import annotations

from pathlib import Path
from typing import Sequence

from job_agent.knowledge.career_benchmark import (
    ingest_benchmark_documents,
    load_career_benchmark,
    resolve_relevant_chunk_ids,
    run_career_dense_benchmark,
)
from job_agent.knowledge.vector_index import InMemoryVectorIndex


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"


class KeywordEmbeddingBackend:
    _terms = (
        "mcp",
        "outbox",
        "evidence",
        "careerstore",
        "interview",
        "faiss",
        "tool",
        "uncertain",
    )

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


def test_fixture_loads_real_material_synthetic_jd_and_query_categories() -> None:
    dataset = load_career_benchmark(FIXTURE_ROOT)

    assert len(dataset.documents) == 8
    assert len(dataset.cases) == 20
    assert sum(
        document.material_kind == "real_project_material"
        for document in dataset.documents
    ) == 7
    assert sum(
        document.material_kind == "synthetic_jd"
        for document in dataset.documents
    ) == 1
    assert {case.category for case in dataset.cases} == {
        "semantic",
        "exact_term",
        "requirement",
        "negative_gap",
        "ambiguous",
        "exact_entity",
    }


def test_document_gold_resolves_to_explicit_chunk_ids() -> None:
    dataset = load_career_benchmark(FIXTURE_ROOT)
    backend = KeywordEmbeddingBackend()
    chunks_by_document = ingest_benchmark_documents(
        dataset,
        embedding_backend=backend,
        vector_index=InMemoryVectorIndex(),
    )

    positive_cases = [
        case for case in dataset.cases if case.expected_document_ids
    ]
    negative_cases = [
        case for case in dataset.cases if not case.expected_document_ids
    ]

    assert all(
        resolve_relevant_chunk_ids(case, chunks_by_document)
        for case in positive_cases
    )
    assert all(
        not resolve_relevant_chunk_ids(case, chunks_by_document)
        for case in negative_cases
    )


def test_runner_reports_metrics_and_gap_bad_cases() -> None:
    dataset = load_career_benchmark(FIXTURE_ROOT)
    report = run_career_dense_benchmark(
        dataset,
        embedding_backend=KeywordEmbeddingBackend(),
        vector_index=InMemoryVectorIndex(),
    )

    assert report.query_count == 20
    assert report.evaluated_positive_query_count == 18
    assert 0.0 <= report.metrics.recall_at_1 <= 1.0
    assert 0.0 <= report.metrics.recall_at_3 <= 1.0
    assert 0.0 <= report.metrics.recall_at_5 <= 1.0
    assert 0.0 <= report.metrics.mrr <= 1.0

    gap_cases = {
        case.case_id: case
        for case in report.bad_cases
        if case.failure_category == "corpus missing evidence"
    }
    assert set(gap_cases) == {"gap-kubernetes", "gap-pdf-docx"}
    assert all(case.actual_top_results for case in gap_cases.values())
