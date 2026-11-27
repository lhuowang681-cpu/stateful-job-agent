from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from job_agent.knowledge.contracts import (
    KnowledgeChunk,
    KnowledgeDocument,
    RetrievedChunk,
)
from job_agent.text_identity import normalize_text, sha256_bytes


def _document(**overrides: Any) -> KnowledgeDocument:
    text = normalize_text("a\r\nb\rc")
    values: dict[str, Any] = {
        "document_id": "document-1",
        "source_type": "manual",
        "text": text,
        "content_hash": sha256_bytes(text.encode("utf-8")),
        "version": 1,
        "created_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return KnowledgeDocument(**values)


def _chunk(**overrides: Any) -> KnowledgeChunk:
    values: dict[str, Any] = {
        "chunk_id": "chunk-1",
        "document_id": "document-1",
        "document_version": 1,
        "document_content_hash": "0" * 64,
        "text": "agent",
        "chunk_index": 0,
        "start_offset": 10,
        "end_offset": 15,
    }
    values.update(overrides)
    return KnowledgeChunk(**values)


def _retrieved_chunk(**overrides: Any) -> RetrievedChunk:
    values: dict[str, Any] = {
        "chunk": _chunk(),
        "score": 0.75,
        "rank": 1,
        "retrieval_method": "dense",
    }
    values.update(overrides)
    return RetrievedChunk(**values)


def test_knowledge_document_accepts_valid_canonical_text() -> None:
    document = _document(title="Example", source_uri="file:///example.txt")

    assert document.text == "a\nb\nc"
    assert document.content_hash == sha256_bytes(document.text.encode("utf-8"))
    assert document.title == "Example"
    assert document.source_uri == "file:///example.txt"
    assert document.metadata == {}


def test_knowledge_document_rejects_invalid_hash_format() -> None:
    with pytest.raises(ValidationError):
        _document(content_hash="abc")


def test_knowledge_document_rejects_hash_that_does_not_match_text() -> None:
    with pytest.raises(ValidationError):
        _document(content_hash="0" * 64)


def test_knowledge_document_rejects_non_positive_version() -> None:
    with pytest.raises(ValidationError):
        _document(version=0)


def test_knowledge_document_metadata_defaults_are_isolated() -> None:
    first = _document(document_id="document-1")
    second = _document(document_id="document-2")

    first.metadata["owner"] = "first"

    assert first.metadata == {"owner": "first"}
    assert second.metadata == {}


def test_knowledge_chunk_accepts_valid_local_span() -> None:
    chunk = _chunk(section="Experience", page=1)

    assert chunk.document_id == "document-1"
    assert chunk.document_version == 1
    assert chunk.text == "agent"
    assert chunk.end_offset - chunk.start_offset == len(chunk.text)
    assert chunk.section == "Experience"
    assert chunk.page == 1


def test_knowledge_chunk_rejects_invalid_document_hash_format() -> None:
    with pytest.raises(ValidationError):
        _chunk(document_content_hash="abc")


def test_knowledge_chunk_rejects_non_positive_document_version() -> None:
    with pytest.raises(ValidationError):
        _chunk(document_version=0)


def test_knowledge_chunk_rejects_negative_chunk_index() -> None:
    with pytest.raises(ValidationError):
        _chunk(chunk_index=-1)


def test_knowledge_chunk_rejects_non_positive_span() -> None:
    with pytest.raises(ValidationError):
        _chunk(start_offset=10, end_offset=10)


def test_knowledge_chunk_rejects_text_length_mismatch() -> None:
    with pytest.raises(ValidationError):
        _chunk(end_offset=14)


def test_knowledge_chunk_rejects_zero_page() -> None:
    with pytest.raises(ValidationError):
        _chunk(page=0)


def test_knowledge_chunk_metadata_defaults_are_isolated() -> None:
    first = _chunk(chunk_id="chunk-1")
    second = _chunk(chunk_id="chunk-2")

    first.metadata["owner"] = "first"

    assert first.metadata == {"owner": "first"}
    assert second.metadata == {}


def test_retrieved_chunk_accepts_valid_result() -> None:
    result = _retrieved_chunk()

    assert result.chunk.chunk_id == "chunk-1"
    assert result.score == pytest.approx(0.75)
    assert result.rank == 1
    assert result.retrieval_method == "dense"
    assert result.retrieval_metadata == {}


def test_retrieved_chunk_rejects_zero_rank() -> None:
    with pytest.raises(ValidationError):
        _retrieved_chunk(rank=0)


def test_retrieved_chunk_rejects_empty_retrieval_method() -> None:
    with pytest.raises(ValidationError):
        _retrieved_chunk(retrieval_method="")


def test_retrieved_chunk_metadata_defaults_are_isolated() -> None:
    first = _retrieved_chunk()
    second = _retrieved_chunk()

    first.retrieval_metadata["backend"] = "in-memory"

    assert first.retrieval_metadata == {"backend": "in-memory"}
    assert second.retrieval_metadata == {}
