from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from pydantic import Field

from job_agent.knowledge.candidate_evidence import CandidateEvidenceRetriever
from job_agent.knowledge.career_benchmark import CareerBenchmarkDataset
from job_agent.knowledge.contracts import (
    EmbeddingBackend,
    KnowledgeDocument,
    RetrievedChunk,
    VectorIndex,
)
from job_agent.knowledge.ingestion import create_knowledge_document
from job_agent.schemas import StrictModel

if TYPE_CHECKING:
    from job_agent.knowledge.durable import (
        CareerKnowledgeLifecycle,
        EmbeddingIdentity,
    )


class CareerKnowledgeHit(StrictModel):
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version: int = Field(ge=1)
    document_content_hash: str = Field(min_length=64, max_length=64)
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    section: str | None = None
    page: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float
    rank: int = Field(ge=1)
    retrieval_method: str = Field(min_length=1)
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)
    source_uri: str | None = None


class CareerKnowledgeQueryResult(StrictModel):
    query: str = Field(min_length=1)
    top_k: int = Field(ge=1, le=50)
    results: list[CareerKnowledgeHit] = Field(default_factory=list)


class CareerKnowledgeService:
    def __init__(
        self,
        retriever: CandidateEvidenceRetriever,
        *,
        lifecycle: "CareerKnowledgeLifecycle | None" = None,
    ) -> None:
        self.retriever = retriever
        self.lifecycle = lifecycle

    @classmethod
    def from_durable_storage(
        cls,
        *,
        repository_path: str | Path,
        index_path: str | Path,
        manifest_path: str | Path,
        embedding_backend: EmbeddingBackend,
        embedding_identity: "EmbeddingIdentity",
        max_chars: int = 1200,
    ) -> "CareerKnowledgeService":
        from job_agent.knowledge.durable import (
            CareerKnowledgeLifecycle,
            KnowledgeRepository,
        )

        lifecycle = CareerKnowledgeLifecycle(
            repository=KnowledgeRepository(repository_path),
            embedding_backend=embedding_backend,
            embedding_identity=embedding_identity,
            index_path=index_path,
            manifest_path=manifest_path,
            max_chars=max_chars,
        )
        return cls(
            lifecycle.candidate_retriever(),
            lifecycle=lifecycle,
        )

    @classmethod
    def from_documents(
        cls,
        documents: Sequence[KnowledgeDocument],
        *,
        embedding_backend: EmbeddingBackend,
        vector_index: VectorIndex,
        max_chars: int = 1200,
    ) -> "CareerKnowledgeService":
        return cls(
            CandidateEvidenceRetriever.from_documents(
                documents,
                embedding_backend=embedding_backend,
                vector_index=vector_index,
                max_chars=max_chars,
            )
        )

    @classmethod
    def from_career_dataset(
        cls,
        dataset: CareerBenchmarkDataset,
        *,
        embedding_backend: EmbeddingBackend,
        vector_index: VectorIndex,
        max_chars: int = 2000,
    ) -> "CareerKnowledgeService":
        documents = tuple(
            create_knowledge_document(
                document_id=document.document_id,
                source_type=document.source_type,
                text=document.text,
                version=1,
                title=document.title,
                source_uri=document.source_uri,
                metadata={
                    "material_kind": document.material_kind,
                    "fixture_path": document.fixture_path,
                    "source_uri": document.source_uri,
                },
            )
            for document in dataset.documents
        )
        return cls.from_documents(
            documents,
            embedding_backend=embedding_backend,
            vector_index=vector_index,
            max_chars=max_chars,
        )

    def query_candidate_evidence(
        self,
        query: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be between 1 and 50")
        return self.retriever.retrieve(query=query, limit=top_k)

    def query_structured(
        self,
        query: str,
        top_k: int,
    ) -> CareerKnowledgeQueryResult:
        hits = self.query_candidate_evidence(query, top_k)
        return CareerKnowledgeQueryResult(
            query=query,
            top_k=top_k,
            results=[_structured_hit(hit) for hit in hits],
        )


def _structured_hit(hit: RetrievedChunk) -> CareerKnowledgeHit:
    chunk = hit.chunk
    source_uri = chunk.metadata.get("source_uri")
    return CareerKnowledgeHit(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        document_version=chunk.document_version,
        document_content_hash=chunk.document_content_hash,
        text=chunk.text,
        chunk_index=chunk.chunk_index,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        section=chunk.section,
        page=chunk.page,
        metadata=dict(chunk.metadata),
        score=hit.score,
        rank=hit.rank,
        retrieval_method=hit.retrieval_method,
        retrieval_metadata=dict(hit.retrieval_metadata),
        source_uri=source_uri if isinstance(source_uri, str) else None,
    )
