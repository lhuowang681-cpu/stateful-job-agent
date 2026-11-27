from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from job_agent.evidence.contracts import EvidenceLink
from job_agent.schemas import StrictModel


class SectionKind(str, Enum):
    SUMMARY = "summary"
    EDUCATION = "education"
    RESEARCH = "research"
    PROJECT = "project"
    EXPERIENCE = "experience"
    SKILLS = "skills"
    AWARDS = "awards"
    OTHER = "other"


class ResumeSourceType(str, Enum):
    PLAIN_TEXT = "plain_text"
    MARKDOWN = "markdown"
    STRUCTURED_JSON = "structured_json"


class ResumeVersionStatus(str, Enum):
    BASE = "BASE"
    SAVED = "SAVED"


class ClaimVerification(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICT = "CONFLICT"
    GAP = "GAP"


class DisclosureVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    RESUME_SAFE = "RESUME_SAFE"
    PRIVATE_ONLY = "PRIVATE_ONLY"
    ANONYMIZED_ONLY = "ANONYMIZED_ONLY"


class CoverageStatus(str, Enum):
    ALREADY_COVERED = "ALREADY_COVERED"
    COVERED_BUT_WEAK = "COVERED_BUT_WEAK"
    SUPPORTED_NOT_ON_RESUME = "SUPPORTED_NOT_ON_RESUME"
    GAP = "GAP"


class ChangeType(str, Enum):
    REPHRASE = "REPHRASE"
    REORDER = "REORDER"
    EMPHASIZE = "EMPHASIZE"
    COMPRESS = "COMPRESS"
    EXPAND_WITH_EVIDENCE = "EXPAND_WITH_EVIDENCE"


class DraftStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    SAVED = "SAVED"


class Resume(StrictModel):
    resume_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    created_at: datetime


class ClaimEvidence(StrictModel):
    evidence_link: EvidenceLink
    knowledge_document_id: str = Field(min_length=1)
    knowledge_document_version: int = Field(ge=1)
    knowledge_content_hash: str = Field(min_length=64, max_length=64)
    visibility: DisclosureVisibility = DisclosureVisibility.RESUME_SAFE
    anonymized_text: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_disclosure(self) -> "ClaimEvidence":
        if self.visibility == DisclosureVisibility.ANONYMIZED_ONLY and not self.anonymized_text:
            raise ValueError("anonymized-only evidence requires anonymized_text")
        if self.evidence_link.source_span.content_hash != self.knowledge_content_hash:
            raise ValueError("evidence content hash does not match knowledge document")
        return self


class ResumeItem(StrictModel):
    item_id: str = Field(min_length=1)
    section: SectionKind
    title: str = ""
    original_text: str = Field(min_length=1)
    current_text: str = Field(min_length=1)
    order: int = Field(ge=0)
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeSection(StrictModel):
    section_id: str = Field(min_length=1)
    kind: SectionKind
    title: str = Field(min_length=1)
    order: int = Field(ge=0)
    items: list[ResumeItem] = Field(default_factory=list)


class CandidateClaim(StrictModel):
    claim_id: str = Field(min_length=1)
    canonical_claim: str = Field(min_length=1)
    category: str = Field(min_length=1)
    resume_version_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    verification_state: ClaimVerification
    visibility: DisclosureVisibility = DisclosureVisibility.RESUME_SAFE
    evidence: list[ClaimEvidence] = Field(default_factory=list)
    numeric_values: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    supersedes_claim_id: str | None = None
    superseded_by_claim_id: str | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def supported_claim_has_evidence(self) -> "CandidateClaim":
        if self.verification_state == ClaimVerification.SUPPORTED and not self.evidence:
            raise ValueError("supported claims require evidence")
        return self


class ResumeVersion(StrictModel):
    resume_version_id: str = Field(min_length=1)
    resume_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    parent_version_id: str | None = None
    target_job_id: str | None = None
    target_jd_snapshot_id: str | None = None
    target_jd_version: int | None = Field(default=None, ge=1)
    analysis_snapshot_id: str | None = None
    tailoring_plan_id: str | None = None
    created_at: datetime
    source_type: ResumeSourceType
    status: ResumeVersionStatus
    content_hash: str = Field(min_length=64, max_length=64)
    raw_text: str
    sections: list[ResumeSection]
    claims: list[CandidateClaim] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by_trace_id: str | None = None

    @model_validator(mode="after")
    def validate_version_graph(self) -> "ResumeVersion":
        if self.version == 1 and self.parent_version_id is not None:
            raise ValueError("base resume version cannot have a parent")
        if self.version > 1 and self.parent_version_id is None:
            raise ValueError("derived resume version requires a parent")
        section_ids = [item.section_id for item in self.sections]
        item_ids = [item.item_id for section in self.sections for item in section.items]
        if len(section_ids) != len(set(section_ids)) or len(item_ids) != len(set(item_ids)):
            raise ValueError("resume section and item ids must be unique")
        return self


class ClaimAudit(StrictModel):
    resume_version_id: str
    claims: list[CandidateClaim]
    supported: int
    unverified: int
    conflict: int
    gap: int
    numeric_claims: int
    technology_claims: int


class RequirementFact(StrictModel):
    requirement_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_state: ClaimVerification
    evidence: list[ClaimEvidence] = Field(default_factory=list)
    importance: str = "must"

    @model_validator(mode="after")
    def validate_evidence_state(self) -> "RequirementFact":
        if self.evidence_state == ClaimVerification.SUPPORTED and not self.evidence:
            raise ValueError("supported requirement requires evidence")
        return self


class RequirementCoverage(StrictModel):
    requirement_id: str
    requirement_text: str
    status: CoverageStatus
    item_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


class TailoringPlan(StrictModel):
    tailoring_plan_id: str
    target_job_id: str
    target_jd_snapshot_id: str
    target_jd_version: int = Field(ge=1)
    analysis_snapshot_id: str
    base_resume_version_id: str
    created_at: datetime
    coverage: list[RequirementCoverage]
    highlight_items: list[str] = Field(default_factory=list)
    deemphasize_items: list[str] = Field(default_factory=list)
    rewrite_candidates: list[str] = Field(default_factory=list)
    missing_supported_capabilities: list[str] = Field(default_factory=list)
    true_gaps: list[str] = Field(default_factory=list)
    do_not_claim: list[str] = Field(default_factory=list)


class RewriteProposal(StrictModel):
    item_id: str
    rewritten_text: str = Field(min_length=1)
    used_evidence_ids: list[str] = Field(default_factory=list)
    target_requirement_ids: list[str] = Field(default_factory=list)
    change_type: ChangeType


class TailoringChange(StrictModel):
    change_id: str
    item_id: str
    before: str
    after: str
    reason: str
    requirement_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    change_type: ChangeType
    accepted_by_gate: bool
    rejection_reasons: list[str] = Field(default_factory=list)


class TailoringDraft(StrictModel):
    draft_id: str
    plan_id: str
    base_resume_version_id: str
    created_at: datetime
    status: DraftStatus = DraftStatus.DRAFT
    changes: list[TailoringChange] = Field(default_factory=list)
    allowed_evidence_by_item: dict[str, list[ClaimEvidence]] = Field(default_factory=dict)
    approved_change_ids: list[str] = Field(default_factory=list)
    rejected_change_ids: list[str] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)


class ResumeVersionDiff(StrictModel):
    from_version_id: str
    to_version_id: str
    added: list[dict[str, Any]] = Field(default_factory=list)
    removed: list[dict[str, Any]] = Field(default_factory=list)
    rewritten: list[dict[str, Any]] = Field(default_factory=list)
    moved: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)


class CoverageReport(StrictModel):
    resume_version_id: str
    target_job_id: str
    total_required_atoms: int
    covered_on_resume: int
    supported_not_on_resume: int
    partial: int
    gap: int
    entries: list[RequirementCoverage]


class ApplicationResumeLink(StrictModel):
    application_id: str
    job_id: str
    resume_version_id: str
    linked_at: datetime


class GroundingMetrics(StrictModel):
    unsupported_claim_rate: float = Field(ge=0.0, le=1.0)
    false_skill_additions: int = Field(ge=0)
    false_experience_additions: int = Field(ge=0)
    numeric_fabrication: int = Field(ge=0)
    gap_laundering: int = Field(ge=0)
    coverage_before: float = Field(ge=0.0, le=1.0)
    coverage_after: float = Field(ge=0.0, le=1.0)
