from __future__ import annotations

from job_agent.knowledge.contracts import KnowledgeChunk, RetrievedChunk
from job_agent.knowledge.hybrid_retriever import HybridRetriever
from job_agent.knowledge.rrf import reciprocal_rank_fusion


_DOCUMENT_HASH = "0" * 64


def _chunk(chunk_id: str, chunk_index: int) -> KnowledgeChunk:
    text = f"chunk {chunk_id}"
    start_offset = chunk_index * 100
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="rrf-test-document",
        document_version=1,
        document_content_hash=_DOCUMENT_HASH,
        text=text,
        chunk_index=chunk_index,
        start_offset=start_offset,
        end_offset=start_offset + len(text),
    )


def _result(
    chunk: KnowledgeChunk,
    *,
    score: float,
    rank: int,
    method: str,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=chunk,
        score=score,
        rank=rank,
        retrieval_method=method,
    )


def test_rrf_accumulates_shared_chunk_and_deduplicates_by_chunk_id() -> None:
    chunk_a = _chunk("a", 0)
    chunk_b = _chunk("b", 1)
    chunk_c = _chunk("c", 2)

    hits = reciprocal_rank_fusion(
        dense_results=[
            _result(chunk_a, score=0.9, rank=1, method="dense"),
            _result(chunk_b, score=0.8, rank=2, method="dense"),
        ],
        bm25_results=[
            _result(chunk_b, score=4.0, rank=1, method="bm25"),
            _result(chunk_c, score=3.0, rank=2, method="bm25"),
        ],
        limit=3,
    )

    assert [hit.chunk.chunk_id for hit in hits] == ["b", "a", "c"]
    assert len({hit.chunk.chunk_id for hit in hits}) == 3
    assert hits[0].score == 1 / 62 + 1 / 61
    assert hits[0].retrieval_metadata == {
        "dense_rank": 2,
        "dense_score": 0.8,
        "bm25_rank": 1,
        "bm25_score": 4.0,
    }


def test_rrf_filters_zero_score_bm25_candidate() -> None:
    dense_chunk = _chunk("dense", 0)
    zero_score_chunk = _chunk("zero-score", 1)

    hits = reciprocal_rank_fusion(
        dense_results=[
            _result(dense_chunk, score=0.7, rank=1, method="dense"),
        ],
        bm25_results=[
            _result(zero_score_chunk, score=0.0, rank=1, method="bm25"),
        ],
        limit=5,
    )

    assert [hit.chunk.chunk_id for hit in hits] == ["dense"]
    assert "bm25_rank" not in hits[0].retrieval_metadata


def test_rrf_assigns_final_rank_and_retrieval_method() -> None:
    chunks = [_chunk("a", 0), _chunk("b", 1)]

    hits = reciprocal_rank_fusion(
        dense_results=[
            _result(chunks[0], score=0.9, rank=1, method="dense"),
            _result(chunks[1], score=0.8, rank=2, method="dense"),
        ],
        bm25_results=[],
        limit=2,
    )

    assert [hit.rank for hit in hits] == [1, 2]
    assert all(hit.retrieval_method == "rrf" for hit in hits)


class _FakeRetriever:
    def __init__(self, results: list[RetrievedChunk]) -> None:
        self.results = results
        self.requested_limits: list[int] = []

    def retrieve(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        self.requested_limits.append(limit)
        return self.results[:limit]

    def search(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        self.requested_limits.append(limit)
        return self.results[:limit]


def test_hybrid_retriever_uses_fixed_candidate_depth() -> None:
    chunk = _chunk("shared", 0)
    dense = _FakeRetriever(
        [_result(chunk, score=0.9, rank=1, method="dense")]
    )
    sparse = _FakeRetriever(
        [_result(chunk, score=2.0, rank=1, method="bm25")]
    )
    retriever = HybridRetriever(
        dense_retriever=dense,
        sparse_retriever=sparse,
    )

    hits = retriever.retrieve(query="shared", limit=1)

    assert dense.requested_limits == [10]
    assert sparse.requested_limits == [10]
    assert hits[0].retrieval_method == "rrf"
