import pytest

from job_agent.knowledge.contracts import KnowledgeChunk, RetrievedChunk
from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
from job_agent.knowledge.vector_index import InMemoryVectorIndex


_SYNTHETIC_DOCUMENT_HASH = "0" * 64


def _chunk(chunk_id: str) -> KnowledgeChunk:
    chunk_index = {"A": 0, "B": 1, "C": 2}[chunk_id]
    start_offset = chunk_index * 100
    text = f"chunk {chunk_id}"
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id="synthetic-faiss-document",
        document_version=1,
        document_content_hash=_SYNTHETIC_DOCUMENT_HASH,
        text=text,
        chunk_index=chunk_index,
        start_offset=start_offset,
        end_offset=start_offset + len(text),
    )


def _chunks() -> list[KnowledgeChunk]:
    return [
        _chunk("A"),
        _chunk("B"),
        _chunk("C"),
    ]


def _vectors() -> list[list[float]]:
    return [
        [1.0, 0.0],
        [0.8, 0.2],
        [0.0, 1.0],
    ]


def _ids(hits: list[RetrievedChunk]) -> list[str]:
    return [hit.chunk.chunk_id for hit in hits]


def _indexes() -> tuple[InMemoryVectorIndex, FAISSVectorIndex]:
    return InMemoryVectorIndex(), FAISSVectorIndex()


def test_ranking_parity_between_inmemory_and_faiss() -> None:
    rankings: list[list[str]] = []

    for index in _indexes():
        index.add(
            chunks=_chunks(),
            vectors=_vectors(),
        )
        rankings.append(
            _ids(
                index.search(
                    query_vector=[1.0, 0.0],
                    limit=3,
                )
            )
        )

    assert rankings[0] == ["A", "B", "C"]
    assert rankings[1] == rankings[0]


def test_top_k_parity_between_inmemory_and_faiss() -> None:
    rankings: list[list[str]] = []

    for index in _indexes():
        index.add(
            chunks=_chunks(),
            vectors=_vectors(),
        )

        hits = index.search(
            query_vector=[1.0, 0.0],
            limit=2,
        )
        assert len(hits) == 2
        rankings.append(_ids(hits))

    assert rankings[0] == ["A", "B"]
    assert rankings[1] == rankings[0]


def test_repeated_add_appends_for_both_indexes() -> None:
    rankings: list[list[str]] = []

    for index in _indexes():
        index.add(
            chunks=[_chunk("A"), _chunk("B")],
            vectors=[[1.0, 0.0], [0.0, 1.0]],
        )
        index.add(
            chunks=[_chunk("C")],
            vectors=[[0.8, 0.2]],
        )

        ids = _ids(
            index.search(
                query_vector=[1.0, 0.0],
                limit=3,
            )
        )
        assert len(ids) == 3
        assert set(ids) == {"A", "B", "C"}
        rankings.append(ids)

    assert rankings[0] == ["A", "C", "B"]
    assert rankings[1] == rankings[0]


def test_faiss_rejects_dimension_mismatch() -> None:
    index = FAISSVectorIndex()
    index.add(
        chunks=[_chunk("A")],
        vectors=[[1.0, 0.0]],
    )

    with pytest.raises(ValueError):
        index.add(
            chunks=[_chunk("B")],
            vectors=[[1.0, 0.0, 0.0]],
        )

    with pytest.raises(ValueError):
        index.search(
            query_vector=[1.0, 0.0, 0.0],
            limit=1,
        )
