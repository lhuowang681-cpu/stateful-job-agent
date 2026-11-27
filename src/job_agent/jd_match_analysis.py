from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from job_agent.evidence.contracts import (
    AtomMatchStatus,
    RequirementAnalysis,
    RequirementAtom,
    SourceInput,
)
from job_agent.evidence.requirements import RequirementAnalyzer
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.knowledge.candidate_evidence import CandidateEvidenceRetriever
from job_agent.knowledge.contracts import KnowledgeDocument
from job_agent.llm.harness import LLMHarness
from job_agent.requirement_evidence import (
    RequirementEvidenceItem,
    RequirementEvidenceService,
)


@dataclass(frozen=True)
class JobMatchRequirement:
    atom: RequirementAtom
    status: AtomMatchStatus
    evidence_items: tuple[RequirementEvidenceItem, ...]
    explanation: str
    semantic_support: str | None = None


@dataclass(frozen=True)
class JobMatchEvidenceSummary:
    total_requirements: int
    supported_count: int
    partial_count: int
    unverified_lead_count: int
    unsupported_count: int
    gap_count: int
    evidence_link_count: int


@dataclass(frozen=True)
class JobBasicInfo:
    title: str
    city: str
    role_direction: str
    job_type: str
    text: str


@dataclass(frozen=True)
class PreferenceDimensionAnalysis:
    dimension: str
    preferred: str | None
    actual: str | None
    fit: bool | None
    explanation: str
    source: str = "UserState.preferences"


@dataclass(frozen=True)
class PreferenceAnalysis:
    city: PreferenceDimensionAnalysis
    role: PreferenceDimensionAnalysis
    job_type: PreferenceDimensionAnalysis

    @property
    def conflicts(self) -> tuple[str, ...]:
        return tuple(
            item.dimension
            for item in (self.city, self.role, self.job_type)
            if item.fit is False
        )


@dataclass(frozen=True)
class JobAnalysisSummary:
    evidence_backed_strengths: tuple[str, ...]
    gaps: tuple[str, ...]
    preference_conflicts: tuple[str, ...]


@dataclass(frozen=True)
class JobMatchAnalysis:
    requirement_analysis: RequirementAnalysis
    requirements: tuple[JobMatchRequirement, ...]
    supported: tuple[str, ...]
    partial_or_unverified: tuple[str, ...]
    gaps: tuple[str, ...]
    unsupported: tuple[str, ...]
    evidence_summary: JobMatchEvidenceSummary
    jd_source_id: str
    jd_basic_info: JobBasicInfo | None = None
    preference_analysis: PreferenceAnalysis | None = None
    summary: JobAnalysisSummary | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "requirements": [
                {
                    "atom_id": item.atom.atom_id,
                    "parent_requirement_id": item.atom.parent_requirement_id,
                    "text": item.atom.text,
                    "status": item.status,
                    "semantic_support": item.semantic_support,
                    "explanation": item.explanation,
                    "requirement_source": {
                        "source_id": item.atom.source_span.source_id,
                        "content_hash": item.atom.source_span.content_hash,
                        "start_offset": item.atom.source_span.start_offset,
                        "end_offset": item.atom.source_span.end_offset,
                    },
                    "evidence": [
                        {
                            "evidence_link_id": evidence.evidence_link.link_id,
                            "document_id": evidence.document_id,
                            "document_version": evidence.document_version,
                            "document_content_hash": (
                                evidence.document_content_hash
                            ),
                            "chunk_id": evidence.chunk_id,
                            "retrieval_rank": evidence.retrieval_rank,
                            "retrieval_score": evidence.retrieval_score,
                            "retrieval_method": evidence.retrieval_method,
                            "retrieval_metadata": dict(
                                evidence.retrieval_metadata
                            ),
                            "support_status": (
                                evidence.evidence_link.support_status
                            ),
                            "evidence_level": evidence.evidence_link.level.value,
                            "source_id": evidence.evidence_link.source_span.source_id,
                            "source_content_hash": (
                                evidence.evidence_link.source_span.content_hash
                            ),
                            "start_offset": (
                                evidence.evidence_link.source_span.start_offset
                            ),
                            "end_offset": (
                                evidence.evidence_link.source_span.end_offset
                            ),
                        }
                        for evidence in item.evidence_items
                    ],
                }
                for item in self.requirements
            ],
            "supported": list(self.supported),
            "partial_or_unverified": list(self.partial_or_unverified),
            "gaps": list(self.gaps),
            "unsupported": list(self.unsupported),
            "evidence_summary": {
                "total_requirements": self.evidence_summary.total_requirements,
                "supported_count": self.evidence_summary.supported_count,
                "partial_count": self.evidence_summary.partial_count,
                "unverified_lead_count": (
                    self.evidence_summary.unverified_lead_count
                ),
                "unsupported_count": self.evidence_summary.unsupported_count,
                "gap_count": self.evidence_summary.gap_count,
                "evidence_link_count": (
                    self.evidence_summary.evidence_link_count
                ),
            },
            "jd_source_id": self.jd_source_id,
        }
        if self.jd_basic_info is not None:
            result["jd_basic_info"] = {
                "title": self.jd_basic_info.title,
                "city": self.jd_basic_info.city,
                "role_direction": self.jd_basic_info.role_direction,
                "job_type": self.jd_basic_info.job_type,
            }
        if self.preference_analysis is not None:
            result["preference_analysis"] = {
                item.dimension: {
                    "preferred": item.preferred,
                    "actual": item.actual,
                    "fit": item.fit,
                    "explanation": item.explanation,
                    "source": item.source,
                }
                for item in (
                    self.preference_analysis.city,
                    self.preference_analysis.role,
                    self.preference_analysis.job_type,
                )
            }
        if self.summary is not None:
            result["summary"] = {
                "evidence_backed_strengths": list(
                    self.summary.evidence_backed_strengths
                ),
                "gaps": list(self.summary.gaps),
                "preference_conflicts": list(
                    self.summary.preference_conflicts
                ),
            }
        return result


class JDMatchAnalysisService:
    def __init__(
        self,
        *,
        candidate_retriever: CandidateEvidenceRetriever,
        candidate_documents: Sequence[KnowledgeDocument],
        registry,
        harness: LLMHarness,
        session_dir: Path,
    ) -> None:
        self.registry = registry
        self.harness = harness
        self.session_dir = Path(session_dir)
        self.requirement_evidence = RequirementEvidenceService(
            candidate_retriever=candidate_retriever,
            candidate_documents=candidate_documents,
            registry=registry,
            harness=harness,
            session_dir=self.session_dir,
        )

    def analyze(
        self,
        *,
        jd_text: str,
        run_id: str,
        session_id: str,
        limit: int = 5,
    ) -> JobMatchAnalysis:
        if not jd_text.strip():
            raise ValueError("jd_text must not be empty")

        source_store = EvidenceSourceStore(self.session_dir)
        catalog = source_store.snapshot(
            f"{run_id}-requirements",
            [
                SourceInput(
                    kind="raw_jd",
                    display_label="Job description",
                    text=jd_text,
                )
            ],
        )
        jd_source = catalog.documents[0]
        requirement_analysis = RequirementAnalyzer(
            registry=self.registry,
            harness=self.harness,
            source_store=source_store,
        ).analyze(
            jd_source,
            catalog=catalog,
            session_id=session_id,
            run_id=f"{run_id}-requirements",
        )

        requirements = tuple(
            self._assess_atom(
                atom,
                run_id=f"{run_id}-evidence-{index:03d}",
                session_id=session_id,
                limit=limit,
            )
            for index, atom in enumerate(requirement_analysis.atoms, start=1)
        )
        return build_job_match_analysis(
            requirement_analysis=requirement_analysis,
            requirements=requirements,
            jd_source_id=jd_source.source_id,
        )

    def _assess_atom(
        self,
        atom: RequirementAtom,
        *,
        run_id: str,
        session_id: str,
        limit: int,
    ) -> JobMatchRequirement:
        result = self.requirement_evidence.assess_atom(
            atom,
            run_id=run_id,
            session_id=session_id,
            limit=limit,
        )
        return JobMatchRequirement(
            atom=atom,
            status=result.status,
            evidence_items=result.evidence_items,
            explanation=result.explanation,
            semantic_support=result.semantic_support,
        )


def build_job_match_analysis(
    *,
    requirement_analysis: RequirementAnalysis,
    requirements: Sequence[JobMatchRequirement],
    jd_source_id: str,
    jd_basic_info: JobBasicInfo | None = None,
    preference_analysis: PreferenceAnalysis | None = None,
) -> JobMatchAnalysis:
    requirement_items = tuple(requirements)
    statuses = [item.status for item in requirement_items]
    strengths = tuple(
        item.atom.text
        for item in requirement_items
        if item.evidence_items
        and item.status in {"supported", "partial", "unverified_lead"}
    )
    gaps = tuple(
        item.atom.text
        for item in requirement_items
        if item.status in {"gap", "unsupported"}
    )
    summary = JobAnalysisSummary(
        evidence_backed_strengths=strengths,
        gaps=gaps,
        preference_conflicts=(
            preference_analysis.conflicts
            if preference_analysis is not None
            else ()
        ),
    )
    return JobMatchAnalysis(
        requirement_analysis=requirement_analysis,
        requirements=requirement_items,
        supported=tuple(
            item.atom.atom_id
            for item in requirement_items
            if item.status == "supported"
        ),
        partial_or_unverified=tuple(
            item.atom.atom_id
            for item in requirement_items
            if item.status in {"partial", "unverified_lead"}
        ),
        gaps=tuple(
            item.atom.atom_id
            for item in requirement_items
            if item.status == "gap"
        ),
        unsupported=tuple(
            item.atom.atom_id
            for item in requirement_items
            if item.status == "unsupported"
        ),
        evidence_summary=JobMatchEvidenceSummary(
            total_requirements=len(requirement_items),
            supported_count=statuses.count("supported"),
            partial_count=statuses.count("partial"),
            unverified_lead_count=statuses.count("unverified_lead"),
            unsupported_count=statuses.count("unsupported"),
            gap_count=statuses.count("gap"),
            evidence_link_count=sum(
                len(item.evidence_items) for item in requirement_items
            ),
        ),
        jd_source_id=jd_source_id,
        jd_basic_info=jd_basic_info,
        preference_analysis=preference_analysis,
        summary=summary,
    )
