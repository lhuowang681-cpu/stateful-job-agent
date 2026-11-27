import pytest

from job_agent.knowledge.vector_index import cosine_similarity


from job_agent.knowledge.contracts import KnowledgeChunk
from job_agent.knowledge.vector_index import (
    InMemoryVectorIndex,
    cosine_similarity,
)


_SYNTHETIC_DOCUMENT_HASH = "0" * 64


def _chunk(chunk_id: str, text: str, chunk_index: int) -> KnowledgeChunk:
    start_offset = chunk_index * 100
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="synthetic-vector-index-document",
        document_version=1,
        document_content_hash=_SYNTHETIC_DOCUMENT_HASH,
        text=text,
        chunk_index=chunk_index,
        start_offset=start_offset,
        end_offset=start_offset + len(text),
    )


def test_cosine_similarity_orthogonal_is_zero() -> None:
    result = cosine_similarity(
        [1.0, 0.0],
        [0.0, 1.0],
    )

    assert result == pytest.approx(0.0)
def test_cosine_similarity_same_direction_is_one() -> None:
    result = cosine_similarity(
        [1.0, 0.0],
        [1.0, 0.0],
    )

    assert result == pytest.approx(1.0)
    
def test_vector_index_returns_most_similar_chunks_first() -> None:
    index = InMemoryVectorIndex()

    chunks = [
        _chunk("a", "Agent Runtime", 0),
        _chunk("b", "Visual Grounding", 1),
        _chunk("c", "MCP Runtime Integration", 2),
    ]

    vectors = [
        [1.0, 0.0],
        [0.0, 1.0],
        [0.8, 0.2],
    ]

    index.add(
        chunks=chunks,
        vectors=vectors,
    )

    hits = index.search(
        query_vector=[1.0, 0.0],
        limit=2,
    )

    assert len(hits) == 2
    assert hits[0].chunk.chunk_id == "a"
    assert hits[1].chunk.chunk_id == "c"
