from __future__ import annotations

from typing import Sequence

from job_agent.knowledge.contracts import (
    EmbeddingBackend,
    KnowledgeDocument,
    RetrievedChunk,
    VectorIndex,
)
from job_agent.knowledge.ingestion import ingest_text
from job_agent.knowledge.retriever import KnowledgeRetriever


CANDIDATE_EVIDENCE_SOURCE_TYPES = frozenset(
    {
        "resume",
        "project",
        "project_material",
        "research",
        "user_verified_artifact",
    }
)
_PROJECT_MATERIAL_SOURCE_TYPE = "technical_material"
_PROJECT_MATERIAL_KIND = "real_project_material"


def is_candidate_evidence_document(document: KnowledgeDocument) -> bool:
    if document.source_type in CANDIDATE_EVIDENCE_SOURCE_TYPES:
        return True
    return (
        document.source_type == _PROJECT_MATERIAL_SOURCE_TYPE
        and document.metadata.get("material_kind") == _PROJECT_MATERIAL_KIND
    )


def select_candidate_evidence_documents(
    documents: Sequence[KnowledgeDocument],
) -> tuple[KnowledgeDocument, ...]:
    return tuple(
        document
        for document in documents
        if is_candidate_evidence_document(document)
    )


class CandidateEvidenceRetriever:
    def __init__(
        self,
        *,
        retriever: KnowledgeRetriever,
        indexed_document_ids: frozenset[str],
    ) -> None:
        self._retriever = retriever
        self.indexed_document_ids = indexed_document_ids

    @classmethod
    def from_documents(
        cls,
        documents: Sequence[KnowledgeDocument],
        *,
        embedding_backend: EmbeddingBackend,
        vector_index: VectorIndex,
        max_chars: int = 1200,
    ) -> "CandidateEvidenceRetriever":
        selected_documents = select_candidate_evidence_documents(documents)

        for document in selected_documents:
            ingest_text(
                document_id=document.document_id,
                source_type=document.source_type,
                text=document.text,
                version=document.version,
                title=document.title,
                source_uri=document.source_uri,
                metadata=document.metadata,
                created_at=document.created_at,
                embedding_backend=embedding_backend,
                vector_index=vector_index,
                max_chars=max_chars,
            )

        return cls(
            retriever=KnowledgeRetriever(
                embedding_backend=embedding_backend,
                vector_index=vector_index,
            ),
            indexed_document_ids=frozenset(
                document.document_id for document in selected_documents
            ),
        )

    def retrieve(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        return self._retriever.retrieve(query=query, limit=limit)
