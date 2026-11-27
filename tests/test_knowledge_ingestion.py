from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from job_agent.knowledge.ingestion import (
    chunk_knowledge_document,
    create_knowledge_document,
    ingest_text,
)
from job_agent.knowledge.vector_index import InMemoryVectorIndex
from job_agent.text_identity import normalize_text, sha256_bytes


_CREATED_AT = datetime(2026, 9, 17, tzinfo=timezone.utc)


class RecordingEmbeddingBackend:
    def __init__(self) -> None:
        self.embedded_documents: list[str] = []

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        self.embedded_documents = list(texts)
        return [[1.0, float(index)] for index, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _document(text: str):
    return create_knowledge_document(
        document_id="project-agent-runtime",
        source_type="project",
        text=text,
        version=1,
        title="Agent Runtime Project",
        created_at=_CREATED_AT,
    )


def test_create_document_normalizes_text_and_hash() -> None:
    raw_text = "Cafe\u0301\r\nAgent Runtime\rMCP"

    document = _document(raw_text)

    assert document.text == "Café\nAgent Runtime\nMCP"
    assert document.text == normalize_text(raw_text)
    assert document.content_hash == sha256_bytes(
        document.text.encode("utf-8")
    )


def test_chunks_cover_canonical_text_with_exact_offsets() -> None:
    document = _document(
        "Summary\r\n\r\nBuilt an Agent Runtime with MCP integration.\r\n"
        "Added policy checks and approval gates."
    )

    chunks = chunk_knowledge_document(document, max_chars=28)

    assert "".join(chunk.text for chunk in chunks) == document.text
    assert all(
        document.text[chunk.start_offset:chunk.end_offset] == chunk.text
        for chunk in chunks
    )
    assert all(len(chunk.text) <= 28 for chunk in chunks)


def test_repeated_document_chunking_has_stable_hash_and_ids() -> None:
    text = "Agent Runtime\nMCP Adapter\nPolicy approval"
    first_document = _document(text)
    second_document = _document(text)

    first_chunks = chunk_knowledge_document(first_document, max_chars=18)
    second_chunks = chunk_knowledge_document(second_document, max_chars=18)

    assert first_document.content_hash == second_document.content_hash
    assert [chunk.chunk_id for chunk in first_chunks] == [
        chunk.chunk_id for chunk in second_chunks
    ]


def test_content_change_changes_document_hash_and_chunk_ids() -> None:
    first_document = _document("Agent Runtime integrates MCP.")
    second_document = _document("Agent Runtime integrates RAG.")

    first_chunks = chunk_knowledge_document(first_document, max_chars=12)
    second_chunks = chunk_knowledge_document(second_document, max_chars=12)

    assert first_document.content_hash != second_document.content_hash
    assert len(first_chunks) == len(second_chunks)
    assert all(
        first.chunk_id != second.chunk_id
        for first, second in zip(first_chunks, second_chunks)
    )


def test_multiple_chunk_indexes_and_offsets_are_ordered() -> None:
    document = _document("Resume\nProject experience\nAgent platform delivery")

    chunks = chunk_knowledge_document(document, max_chars=16)

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].start_offset == 0
    assert chunks[-1].end_offset == len(document.text)
    assert all(
        current.end_offset == following.start_offset
        for current, following in zip(chunks, chunks[1:])
    )


def test_ingest_text_embeds_and_adds_chunks_to_index() -> None:
    backend = RecordingEmbeddingBackend()
    index = InMemoryVectorIndex()

    document, chunks = ingest_text(
        document_id="resume-1",
        source_type="resume",
        text="Built agent systems.\r\nIntegrated tool calling.",
        version=1,
        embedding_backend=backend,
        vector_index=index,
        max_chars=24,
        created_at=_CREATED_AT,
    )

    hits = index.search(query_vector=[1.0, 0.0], limit=len(chunks))

    assert backend.embedded_documents == [chunk.text for chunk in chunks]
    assert {hit.chunk.chunk_id for hit in hits} == {
        chunk.chunk_id for chunk in chunks
    }
    assert all(chunk.document_content_hash == document.content_hash for chunk in chunks)
