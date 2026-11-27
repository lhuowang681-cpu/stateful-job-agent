from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from job_agent.evidence.assessment import (
    FitAssessmentPolicy,
    initial_fit_policy_v2,
)
from job_agent.evidence.contracts import (
    AtomMatchStatus,
    EvidenceAssessment,
    EvidenceLink,
    EvidenceV2Error,
    ParentRequirement,
    RequirementAnalysis,
    RequirementAtom,
    SourceCatalog,
    SourceDocumentRef,
    SourceInput,
    SourceSpan,
)
from job_agent.evidence.retrieved_mapping import RetrievedEvidenceMappingService
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.knowledge.candidate_evidence import (
    CandidateEvidenceRetriever,
    is_candidate_evidence_document,
)
from job_agent.knowledge.contracts import (
    KnowledgeChunk,
    KnowledgeDocument,
    RetrievedChunk,
)
from job_agent.llm.harness import LLMHarness


@dataclass(frozen=True)
class RequirementEvidenceItem:
    document_id: str
    document_version: int
    document_content_hash: str
    chunk_id: str
    retrieval_rank: int
    retrieval_score: float
    retrieval_method: str
    retrieval_metadata: Mapping[str, Any]
    evidence_link: EvidenceLink


@dataclass(frozen=True)
class RequirementEvidenceResult:
    atom_id: str
    requirement: str
    status: AtomMatchStatus
    semantic_support: str
    evidence_items: tuple[RequirementEvidenceItem, ...]
    explanation: str
    assessment: EvidenceAssessment


class KnowledgeEvidenceProvenanceAdapter:
    def __init__(
        self,
        *,
        source_store: EvidenceSourceStore,
        catalog: SourceCatalog,
        documents_by_id: Mapping[str, KnowledgeDocument],
        source_ids_by_document_id: Mapping[str, str],
    ) -> None:
        self.source_store = source_store
        self.catalog = catalog
        self.documents_by_id = dict(documents_by_id)
        self.source_ids_by_document_id = dict(source_ids_by_document_id)
        self.document_ids_by_source_id = {
            source_id: document_id
            for document_id, source_id in source_ids_by_document_id.items()
        }

    def span_from_chunk(self, chunk: KnowledgeChunk) -> SourceSpan:
        document, source = self._document_and_source(chunk.document_id)
        if (
            chunk.document_version != document.version
            or chunk.document_content_hash != document.content_hash
            or chunk.document_content_hash != source.content_hash
        ):
            raise EvidenceV2Error("source_hash_mismatch")

        span = SourceSpan(
            source_id=source.source_id,
            content_hash=chunk.document_content_hash,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            exact_quote=chunk.text,
        )
        self.source_store.validate_span(self.catalog, span)
        return span

    def evidence_item(
        self,
        *,
        link: EvidenceLink,
        retrieved_chunks: Sequence[RetrievedChunk],
    ) -> RequirementEvidenceItem:
        self.source_store.validate_span(self.catalog, link.source_span)
        document_id = self.document_ids_by_source_id.get(
            link.source_span.source_id
        )
        if document_id is None:
            raise EvidenceV2Error("unknown_source")

        for hit in retrieved_chunks:
            chunk = hit.chunk
            if (
                chunk.document_id == document_id
                and chunk.start_offset <= link.source_span.start_offset
                and link.source_span.end_offset <= chunk.end_offset
            ):
                self.span_from_chunk(chunk)
                return RequirementEvidenceItem(
                    document_id=document_id,
                    document_version=chunk.document_version,
                    document_content_hash=chunk.document_content_hash,
                    chunk_id=chunk.chunk_id,
                    retrieval_rank=hit.rank,
                    retrieval_score=hit.score,
                    retrieval_method=hit.retrieval_method,
                    retrieval_metadata=dict(hit.retrieval_metadata),
                    evidence_link=link,
                )
        raise EvidenceV2Error("evidence_span_outside_retrieved_chunks")

    def _document_and_source(
        self,
        document_id: str,
    ) -> tuple[KnowledgeDocument, SourceDocumentRef]:
        document = self.documents_by_id.get(document_id)
        source_id = self.source_ids_by_document_id.get(document_id)
        if document is None or source_id is None:
            raise EvidenceV2Error("unknown_source")
        source = next(
            (
                item
                for item in self.catalog.documents
                if item.source_id == source_id
            ),
            None,
        )
        if source is None:
            raise EvidenceV2Error("unknown_source")
        return document, source


class RequirementEvidenceService:
    def __init__(
        self,
        *,
        candidate_retriever: CandidateEvidenceRetriever | None,
        candidate_documents: Sequence[KnowledgeDocument],
        registry,
        harness: LLMHarness,
        session_dir: Path,
    ) -> None:
        self.candidate_retriever = candidate_retriever
        self.documents_by_id = {
            document.document_id: document for document in candidate_documents
        }
        self.registry = registry
        self.harness = harness
        self.session_dir = Path(session_dir)

    def assess(
        self,
        *,
        requirement: str,
        run_id: str,
        session_id: str,
        limit: int = 5,
        atom_id: str = "requirement-atom-1",
        parent_requirement_id: str = "requirement-1",
    ) -> RequirementEvidenceResult:
        if not requirement.strip():
            raise ValueError("requirement must not be empty")
        if self.candidate_retriever is None:
            raise RuntimeError("candidate retriever is not configured")

        hits = self.candidate_retriever.retrieve(
            query=requirement,
            limit=limit,
        )
        return self.assess_retrieved(
            requirement=requirement,
            retrieved_chunks=hits,
            run_id=run_id,
            session_id=session_id,
            atom_id=atom_id,
            parent_requirement_id=parent_requirement_id,
        )

    def assess_retrieved(
        self,
        *,
        requirement: str,
        retrieved_chunks: Sequence[RetrievedChunk],
        run_id: str,
        session_id: str,
        atom_id: str = "requirement-atom-1",
        parent_requirement_id: str = "requirement-1",
    ) -> RequirementEvidenceResult:
        if not requirement.strip():
            raise ValueError("requirement must not be empty")

        hits = list(retrieved_chunks)
        retrieved_documents = self._retrieved_documents(hits)
        source_store = EvidenceSourceStore(self.session_dir)
        catalog = source_store.snapshot(
            run_id,
            [
                SourceInput(
                    kind="raw_jd",
                    display_label="岗位 requirement",
                    text=requirement,
                ),
                *[
                    _source_input(document)
                    for document in retrieved_documents
                ],
            ],
        )
        requirement_text = source_store.read(
            catalog,
            catalog.documents[0].source_id,
        )
        requirement_span = source_store.make_span(
            catalog,
            catalog.documents[0].source_id,
            0,
            len(requirement_text),
        )
        analysis = _single_requirement_analysis(
            requirement_text,
            requirement_span,
            atom_id=atom_id,
            parent_requirement_id=parent_requirement_id,
        )
        source_ids_by_document_id = {
            document.document_id: source.source_id
            for document, source in zip(
                retrieved_documents,
                catalog.documents[1:],
            )
        }
        adapter = KnowledgeEvidenceProvenanceAdapter(
            source_store=source_store,
            catalog=catalog,
            documents_by_id=self.documents_by_id,
            source_ids_by_document_id=source_ids_by_document_id,
        )
        for hit in hits:
            adapter.span_from_chunk(hit.chunk)

        mapping = RetrievedEvidenceMappingService(
            registry=self.registry,
            harness=self.harness,
            source_store=source_store,
            documents_by_id=self.documents_by_id,
            source_ids_by_document_id=source_ids_by_document_id,
        ).map(
            analysis,
            retrieved_chunks=hits,
            catalog=catalog,
            session_id=session_id,
            run_id=run_id,
        )
        atom_result = mapping.atom_results[0]
        evidence_items = tuple(
            adapter.evidence_item(link=link, retrieved_chunks=hits)
            for link in atom_result.links
        )
        assessment = FitAssessmentPolicy().assess(
            analysis,
            mapping,
            config=initial_fit_policy_v2(),
        )
        return RequirementEvidenceResult(
            atom_id=atom_id,
            requirement=requirement_text,
            status=atom_result.match_status,
            semantic_support=atom_result.semantic_support or "unsupported",
            evidence_items=evidence_items,
            explanation=atom_result.rationale,
            assessment=assessment,
        )

    def assess_atom(
        self,
        atom: RequirementAtom,
        *,
        run_id: str,
        session_id: str,
        limit: int = 5,
    ) -> RequirementEvidenceResult:
        return self.assess(
            requirement=atom.text,
            run_id=run_id,
            session_id=session_id,
            limit=limit,
            atom_id=atom.atom_id,
            parent_requirement_id=atom.parent_requirement_id,
        )

    def assess_atom_retrieved(
        self,
        atom: RequirementAtom,
        *,
        retrieved_chunks: Sequence[RetrievedChunk],
        run_id: str,
        session_id: str,
    ) -> RequirementEvidenceResult:
        return self.assess_retrieved(
            requirement=atom.text,
            retrieved_chunks=retrieved_chunks,
            run_id=run_id,
            session_id=session_id,
            atom_id=atom.atom_id,
            parent_requirement_id=atom.parent_requirement_id,
        )

    def _retrieved_documents(
        self,
        hits: Sequence[RetrievedChunk],
    ) -> tuple[KnowledgeDocument, ...]:
        documents: list[KnowledgeDocument] = []
        seen_ids: set[str] = set()
        for hit in hits:
            document_id = hit.chunk.document_id
            if document_id in seen_ids:
                continue
            document = self.documents_by_id.get(document_id)
            if document is None:
                raise EvidenceV2Error("unknown_knowledge_document")
            if not is_candidate_evidence_document(document):
                raise EvidenceV2Error("forbidden_evidence_source")
            documents.append(document)
            seen_ids.add(document_id)
        return tuple(documents)


def _source_input(document: KnowledgeDocument) -> SourceInput:
    artifact_type = document.metadata.get("artifact_type")
    if not isinstance(artifact_type, str):
        material_kind = document.metadata.get("material_kind")
        artifact_type = material_kind if isinstance(material_kind, str) else None
    return SourceInput(
        kind=(
            "original_resume"
            if document.source_type == "resume"
            else "project_source"
            if document.source_type
            in {"project", "project_material", "technical_material", "research"}
            else "user_artifact"
        ),
        display_label=document.title or document.document_id,
        text=document.text,
        artifact_type=artifact_type,
    )


def _single_requirement_analysis(
    requirement: str,
    source_span: SourceSpan,
    *,
    atom_id: str = "requirement-atom-1",
    parent_requirement_id: str = "requirement-1",
) -> RequirementAnalysis:
    return RequirementAnalysis(
        parents=[
            ParentRequirement(
                requirement_id=parent_requirement_id,
                text=requirement,
                importance="must",
                source_span=source_span,
                atom_ids=[atom_id],
            )
        ],
        atoms=[
            RequirementAtom(
                atom_id=atom_id,
                parent_requirement_id=parent_requirement_id,
                text=requirement,
                source_span=source_span,
            )
        ],
    )
