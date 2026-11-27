from __future__ import annotations

from pathlib import Path
from typing import Sequence

from job_agent.knowledge.bm25_index import BM25Index, tokenize_for_bm25
from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_benchmark_compare import (
    run_dense_bm25_comparison,
)
from job_agent.knowledge.contracts import KnowledgeChunk
from job_agent.knowledge.vector_index import InMemoryVectorIndex


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"
_DOCUMENT_HASH = "0" * 64


def _chunk(chunk_id: str, text: str, chunk_index: int) -> KnowledgeChunk:
    start_offset = chunk_index * 100
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="bm25-test-document",
        document_version=1,
        document_content_hash=_DOCUMENT_HASH,
        text=text,
        chunk_index=chunk_index,
        start_offset=start_offset,
        end_offset=start_offset + len(text),
    )


class KeywordEmbeddingBackend:
    _terms = ("mcp", "outbox", "evidence", "career", "faiss", "tool")

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


def test_tokenizer_splits_camel_case_and_preserves_technical_terms() -> None:
    tokens = tokenize_for_bm25(
        "CareerContextAdapter MCP FAISS Runtime RAG FastAPI"
    )

    assert tokens == [
        "career",
        "context",
        "adapter",
        "mcp",
        "faiss",
        "runtime",
        "rag",
        "fast",
        "api",
    ]


def test_bm25_ranks_exact_component_match_first() -> None:
    index = BM25Index()
    index.add(
        [
            _chunk("career", "CareerContextAdapter reads snapshots.", 0),
            _chunk("mcp", "MCPToolAdapter registers tools.", 1),
            _chunk("other", "Adaptive interview questions.", 2),
        ]
    )

    hits = index.search(query="Career Context Adapter", limit=3)

    assert hits[0].chunk.chunk_id == "career"
    assert hits[0].score > hits[1].score
    assert [hit.rank for hit in hits] == [1, 2, 3]
    assert all(hit.retrieval_method == "bm25" for hit in hits)


def test_bm25_returns_shared_chunk_ids_and_zero_limit_is_empty() -> None:
    chunk = _chunk("shared-id", "FAISS retrieval baseline", 0)
    index = BM25Index()
    index.add([chunk])

    hits = index.search(query="FAISS", limit=1)

    assert hits[0].chunk is chunk
    assert hits[0].chunk.chunk_id == "shared-id"
    assert hits[0].score > 0.0
    assert index.search(query="FAISS", limit=0) == []


def test_comparison_uses_same_positive_cases_and_reports_both_methods() -> None:
    report = run_dense_bm25_comparison(
        load_career_benchmark(FIXTURE_ROOT),
        dense_embedding_backend=KeywordEmbeddingBackend(),
        dense_vector_index=InMemoryVectorIndex(),
    )

    assert len(report.positive_cases) == 18
    assert len(report.gap_cases) == 2
    assert report.decision in {
        "KEEP HYBRID",
        "DO NOT KEEP HYBRID",
    }
    assert 0.0 <= report.dense_metrics.recall_at_5 <= 1.0
    assert 0.0 <= report.bm25_metrics.recall_at_5 <= 1.0
    assert 0.0 <= report.rrf_metrics.recall_at_5 <= 1.0
