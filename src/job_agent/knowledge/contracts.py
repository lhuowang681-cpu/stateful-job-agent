from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, Sequence

from pydantic import ConfigDict, Field, model_validator

from job_agent.schemas import StrictModel
from job_agent.text_identity import sha256_bytes


class KnowledgeDocument(StrictModel):
    model_config = ConfigDict(frozen=True)

    document_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: int = Field(ge=1)
    created_at: datetime
    title: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_content_hash(self) -> "KnowledgeDocument":
        expected_hash = sha256_bytes(self.text.encode("utf-8"))
        if self.content_hash != expected_hash:
            raise ValueError("content_hash must match text")
        return self


class KnowledgeChunk(StrictModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: int = Field(ge=1)
    document_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span(self) -> "KnowledgeChunk":
        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset must be greater than start_offset")
        if len(self.text) != self.end_offset - self.start_offset:
            raise ValueError("text length must match the offset span")
        return self


class RetrievedChunk(StrictModel):
    chunk: KnowledgeChunk
    score: float
    rank: int = Field(ge=1)
    retrieval_method: str = Field(min_length=1)
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddingBackend(Protocol):
    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        ...

    def embed_query(
        self,
        text: str,
    ) -> list[float]:
        ...


class VectorIndex(Protocol):
    def add(
        self,
        *,
        chunks: Sequence[KnowledgeChunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        ...

    def search(
        self,
        *,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[RetrievedChunk]:
        ...
