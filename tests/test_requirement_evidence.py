from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

from job_agent.evidence.contracts import (
    EvidenceMappingCandidate,
    EvidenceV2Error,
    SourceInput,
)
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.knowledge.candidate_evidence import CandidateEvidenceRetriever
from job_agent.knowledge.contracts import KnowledgeChunk
from job_agent.knowledge.ingestion import (
    chunk_knowledge_document,
    create_knowledge_document,
)
from job_agent.knowledge.vector_index import InMemoryVectorIndex
from job_agent.llm.harness import LLMHarness
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.skill_registry import SkillSpec
from job_agent.requirement_evidence import (
    KnowledgeEvidenceProvenanceAdapter,
    RequirementEvidenceService,
)


_CREATED_AT = datetime(2026, 9, 18, tzinfo=timezone.utc)


class KeywordEmbeddingBackend:
    _terms = ("rag", "faiss", "async", "migration", "kubernetes", "pdf")

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


class _Registry:
    def get(self, skill_id: str) -> SkillSpec:
        return SkillSpec(
            skill_id=skill_id,
            version="requirement-evidence-test-v1",
            instructions="Map evidence without fabrication.",
            reference_paths=(Path("skill-references/evidence-contract.md"),),
            output_schema=EvidenceMappingCandidate,
        )


def _document(
    document_id: str,
    *,
    source_type: str = "project",
    text: str = "Implemented Qwen embeddings and FAISS retrieval for RAG.",
    artifact_type: str | None = None,
):
    metadata = {"material_kind": "real_project_material"}
    if artifact_type is not None:
        metadata["artifact_type"] = artifact_type
    return create_knowledge_document(
        document_id=document_id,
        source_type=source_type,
        text=text,
        version=1,
        title=document_id,
        metadata=metadata,
        created_at=_CREATED_AT,
    )


def _adapter(tmp_path: Path, document):
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot(
        "adapter-run",
        [
            SourceInput(
                kind="project_source",
                display_label=document.document_id,
                text=document.text,
            )
        ],
    )
    return (
        KnowledgeEvidenceProvenanceAdapter(
            source_store=store,
            catalog=catalog,
            documents_by_id={document.document_id: document},
            source_ids_by_document_id={
                document.document_id: catalog.documents[0].source_id
            },
        ),
        store,
        catalog,
    )


def _mapping_response(
    *,
    chunk_id: str | None = None,
    quote: str | None = None,
    support_status: str = "supported",
) -> dict:
    return {
        "atom_results": [
            {
                "atom_id": "requirement-atom-1",
                "semantic_support": (
                    support_status if chunk_id is not None else "unsupported"
                ),
                "selected_chunk_id": chunk_id,
                "exact_quote": quote,
            }
        ]
    }


def _service(
    tmp_path: Path,
    documents,
    response: dict,
) -> RequirementEvidenceService:
    backend = KeywordEmbeddingBackend()
    retriever = CandidateEvidenceRetriever.from_documents(
        documents,
        embedding_backend=backend,
        vector_index=InMemoryVectorIndex(),
    )
    return RequirementEvidenceService(
        candidate_retriever=retriever,
        candidate_documents=documents,
        registry=_Registry(),
        harness=LLMHarness(MockLLMProvider([response])),
        session_dir=tmp_path,
    )


def test_chunk_to_source_span_validates_exact_snapshot(tmp_path: Path) -> None:
    document = _document("rag-project")
    chunk = chunk_knowledge_document(document)[0]
    adapter, store, catalog = _adapter(tmp_path, document)

    span = adapter.span_from_chunk(chunk)

    assert span.content_hash == document.content_hash
    assert span.exact_quote == chunk.text
    assert store.read(catalog, span.source_id)[
        span.start_offset:span.end_offset
    ] == chunk.text


def test_chunk_content_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    document = _document("rag-project")
    chunk = chunk_knowledge_document(document)[0].model_copy(
        update={"document_content_hash": "f" * 64}
    )
    adapter, _, _ = _adapter(tmp_path, document)

    with pytest.raises(EvidenceV2Error, match="source_hash_mismatch"):
        adapter.span_from_chunk(chunk)


def test_chunk_offset_and_exact_quote_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    document = _document(
        "rag-project",
        text="prefix evidence suffix",
    )
    wrong_chunk = KnowledgeChunk(
        chunk_id="wrong-offset",
        document_id=document.document_id,
        document_version=document.version,
        document_content_hash=document.content_hash,
        text="evidence",
        chunk_index=0,
        start_offset=0,
        end_offset=len("evidence"),
    )
    adapter, _, _ = _adapter(tmp_path, document)

    with pytest.raises(EvidenceV2Error, match="invalid_source_span"):
        adapter.span_from_chunk(wrong_chunk)


def test_requirement_service_uses_candidate_project_and_never_jd(
    tmp_path: Path,
) -> None:
    jd = _document(
        "job-description",
        source_type="job_description",
        text="岗位要求 RAG experience.",
    )
    project = _document("candidate-rag-project")
    service = _service(
        tmp_path,
        [jd, project],
        _mapping_response(
            chunk_id=chunk_knowledge_document(project)[0].chunk_id,
            quote=project.text,
        ),
    )

    result = service.assess(
        requirement="候选人具备 RAG retrieval 经验",
        run_id="rag-run",
        session_id="test-session",
    )

    assert result.status == "unverified_lead"
    assert [item.document_id for item in result.evidence_items] == [
        "candidate-rag-project"
    ]
    assert all(
        item.document_id != "job-description"
        for item in result.evidence_items
    )
    assert result.evidence_items[0].evidence_link.support_status == "supported"


@pytest.mark.parametrize(
    ("support_status", "expected_status"),
    [("supported", "supported"), ("partial", "partial")],
)
def test_requirement_service_reuses_verified_evidence_status_semantics(
    tmp_path: Path,
    support_status: str,
    expected_status: str,
) -> None:
    project = _document(
        "verified-project",
        artifact_type="design_record",
    )
    service = _service(
        tmp_path,
        [project],
        _mapping_response(
            chunk_id=chunk_knowledge_document(project)[0].chunk_id,
            quote=project.text,
            support_status=support_status,
        ),
    )

    result = service.assess(
        requirement="候选人具备 RAG retrieval 经验",
        run_id=f"verified-{support_status}",
        session_id="test-session",
    )

    assert result.status == expected_status
    assert len(result.evidence_items) == 1


@pytest.mark.parametrize(
    "requirement",
    [
        "候选人有 Kubernetes 生产集群运维经验",
        "候选人实现过 PDF 或 DOCX ingestion",
    ],
)
def test_unrelated_retrieval_is_assessed_as_gap(
    tmp_path: Path,
    requirement: str,
) -> None:
    project = _document("candidate-rag-project")
    service = _service(tmp_path, [project], _mapping_response())

    result = service.assess(
        requirement=requirement,
        run_id=f"gap-{abs(hash(requirement))}",
        session_id="test-session",
    )

    assert result.status == "gap"
    assert result.evidence_items == ()
    assert result.assessment.verified_coverage == 0.0
