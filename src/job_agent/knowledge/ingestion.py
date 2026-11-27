from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from job_agent.knowledge.contracts import (
    EmbeddingBackend,
    KnowledgeChunk,
    KnowledgeDocument,
    VectorIndex,
)
from job_agent.text_identity import normalize_text, sha256_bytes


_CHUNK_ID_NAMESPACE = "job-agent.knowledge.chunk.v1"


def create_knowledge_document(
    *,
    document_id: str,
    source_type: str,
    text: str,
    version: int,
    title: str | None = None,
    source_uri: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    created_at: datetime | None = None,
) -> KnowledgeDocument:
    canonical_text = normalize_text(text)
    content_hash = sha256_bytes(canonical_text.encode("utf-8"))

    return KnowledgeDocument(
        document_id=document_id,
        source_type=source_type,
        text=canonical_text,
        content_hash=content_hash,
        version=version,
        created_at=created_at or datetime.now(timezone.utc),
        title=title,
        source_uri=source_uri,
        metadata=dict(metadata or {}),
    )


def chunk_knowledge_document(
    document: KnowledgeDocument,
    *,
    max_chars: int = 1200,
) -> list[KnowledgeChunk]:
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")

    chunks: list[KnowledgeChunk] = []
    start_offset = 0

    while start_offset < len(document.text):
        end_offset = _next_chunk_end(
            document.text,
            start_offset=start_offset,
            max_chars=max_chars,
        )
        chunk_text = document.text[start_offset:end_offset]

        chunks.append(
            KnowledgeChunk(
                chunk_id=_make_chunk_id(
                    document_id=document.document_id,
                    document_content_hash=document.content_hash,
                    start_offset=start_offset,
                    end_offset=end_offset,
                ),
                document_id=document.document_id,
                document_version=document.version,
                document_content_hash=document.content_hash,
                text=chunk_text,
                chunk_index=len(chunks),
                start_offset=start_offset,
                end_offset=end_offset,
                section=_section_for_span(
                    document.metadata,
                    start_offset=start_offset,
                    end_offset=end_offset,
                ),
                page=_page_for_span(
                    document.metadata,
                    start_offset=start_offset,
                    end_offset=end_offset,
                ),
                metadata=dict(document.metadata),
            )
        )
        start_offset = end_offset

    return chunks


def ingest_text(
    *,
    document_id: str,
    source_type: str,
    text: str,
    version: int,
    embedding_backend: EmbeddingBackend,
    vector_index: VectorIndex,
    max_chars: int = 1200,
    title: str | None = None,
    source_uri: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    created_at: datetime | None = None,
) -> tuple[KnowledgeDocument, list[KnowledgeChunk]]:
    document = create_knowledge_document(
        document_id=document_id,
        source_type=source_type,
        text=text,
        version=version,
        title=title,
        source_uri=source_uri,
        metadata=metadata,
        created_at=created_at,
    )
    chunks = chunk_knowledge_document(document, max_chars=max_chars)
    vectors = embedding_backend.embed_documents(
        [chunk.text for chunk in chunks]
    )
    vector_index.add(chunks=chunks, vectors=vectors)

    return document, chunks


def _next_chunk_end(
    text: str,
    *,
    start_offset: int,
    max_chars: int,
) -> int:
    hard_end = min(start_offset + max_chars, len(text))

    if hard_end == len(text):
        return hard_end

    newline_offset = text.rfind("\n", start_offset + 1, hard_end)
    if newline_offset != -1:
        return newline_offset + 1

    return hard_end


def _make_chunk_id(
    *,
    document_id: str,
    document_content_hash: str,
    start_offset: int,
    end_offset: int,
) -> str:
    canonical_identity = json.dumps(
        [
            _CHUNK_ID_NAMESPACE,
            document_id,
            document_content_hash,
            start_offset,
            end_offset,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical_identity)


def _page_for_span(
    metadata: Mapping[str, Any],
    *,
    start_offset: int,
    end_offset: int,
) -> int | None:
    provenance = metadata.get("extraction_provenance")
    if not isinstance(provenance, Mapping):
        return None
    page_spans = provenance.get("page_spans")
    if not isinstance(page_spans, list):
        return None
    for item in page_spans:
        if not isinstance(item, Mapping):
            continue
        if (
            item.get("start_offset", -1) <= start_offset
            and end_offset <= item.get("end_offset", -1)
            and isinstance(item.get("page"), int)
        ):
            return int(item["page"])
    return None


def _section_for_span(
    metadata: Mapping[str, Any],
    *,
    start_offset: int,
    end_offset: int,
) -> str | None:
    provenance = metadata.get("extraction_provenance")
    if not isinstance(provenance, Mapping):
        return None
    section_spans = provenance.get("section_spans")
    if not isinstance(section_spans, list):
        return None
    for item in section_spans:
        if not isinstance(item, Mapping):
            continue
        section = item.get("section")
        if (
            item.get("start_offset", -1) <= start_offset
            and end_offset <= item.get("end_offset", -1)
            and isinstance(section, str)
            and section
        ):
            return section
    return None
