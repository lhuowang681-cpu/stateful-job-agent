from __future__ import annotations

from typing import Any, Mapping, Sequence

from pydantic import Field

from job_agent.agent_runtime.contracts import ToolContext, ToolEffect
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.schemas import StrictModel
from job_agent.tools.application_tracker import ApplicationTrackerStore

from .contracts import (
    ClaimEvidence,
    DisclosureVisibility,
    RequirementFact,
    ResumeSourceType,
    RewriteProposal,
)
from .service import GroundedResumeService


IMPORT_RESUME_TOOL = "resume.import"
AUDIT_RESUME_TOOL = "resume.audit_claims"
PLAN_TAILORING_TOOL = "resume.plan_tailoring"
GENERATE_DRAFT_TOOL = "resume.generate_draft"
REVIEW_DRAFT_TOOL = "resume.review_draft"
SAVE_VERSION_TOOL = "resume.save_version"
COMPARE_RESUME_TOOL = "resume.compare"
COVERAGE_TOOL = "resume.coverage"
APPLICATION_RESUME_TOOL = "application.use_resume_version"


class ImportResumeInput(StrictModel):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_type: ResumeSourceType = ResumeSourceType.PLAIN_TEXT
    resume_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResumeVersionOutput(StrictModel):
    version: dict[str, Any]


class AuditResumeInput(StrictModel):
    resume_version_id: str = Field(min_length=1)
    evidence_by_text: dict[str, list[ClaimEvidence]] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    visibility_by_text: dict[str, DisclosureVisibility] = Field(default_factory=dict)


class AuditResumeOutput(StrictModel):
    audit: dict[str, Any]


class PlanTailoringInput(StrictModel):
    target_job_id: str = Field(min_length=1)
    target_jd_snapshot_id: str = Field(min_length=1)
    target_jd_version: int = Field(ge=1)
    analysis_snapshot_id: str = Field(min_length=1)
    base_resume_version_id: str = Field(min_length=1)
    requirements: list[RequirementFact]


class PlanTailoringOutput(StrictModel):
    plan: dict[str, Any]


class GenerateDraftInput(StrictModel):
    plan_id: str = Field(min_length=1)
    proposals: list[RewriteProposal]
    allowed_evidence_by_item: dict[str, list[ClaimEvidence]] = Field(default_factory=dict)
    token_usage: dict[str, int] = Field(default_factory=dict)


class GenerateDraftOutput(StrictModel):
    draft: dict[str, Any]


class ReviewDraftInput(StrictModel):
    draft_id: str = Field(min_length=1)
    approved_change_ids: list[str] = Field(default_factory=list)


class ReviewDraftOutput(StrictModel):
    draft: dict[str, Any]


class SaveVersionInput(StrictModel):
    draft_id: str = Field(min_length=1)
    approval_action_id: str | None = None


class CompareResumeInput(StrictModel):
    from_version_id: str = Field(min_length=1)
    to_version_id: str = Field(min_length=1)


class CompareResumeOutput(StrictModel):
    comparison: dict[str, Any]


class CoverageInput(StrictModel):
    resume_version_id: str = Field(min_length=1)
    target_job_id: str = Field(min_length=1)
    requirements: list[RequirementFact]


class CoverageOutput(StrictModel):
    coverage: dict[str, Any]


class ApplicationResumeInput(StrictModel):
    application_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    resume_version_id: str = Field(min_length=1)


class ApplicationResumeOutput(StrictModel):
    link: dict[str, Any]


def build_resume_registry(
    service: GroundedResumeService,
    tracker: ApplicationTrackerStore,
    *,
    user_id: str,
) -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        name=IMPORT_RESUME_TOOL,
        description="Import a structured, durable base resume without treating it as one knowledge blob.",
        input_model=ImportResumeInput,
        output_model=ResumeVersionOutput,
        handler=lambda value, _context: ResumeVersionOutput(
            version=service.import_text(
                name=value.name,
                text=value.text,
                source_type=value.source_type,
                resume_id=value.resume_id,
                metadata=value.metadata,
            ).model_dump(mode="json")
        ),
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
        requires_approval=True,
    )

    registry.register(
        name=AUDIT_RESUME_TOOL,
        description="Audit resume claims and bind only explicit candidate evidence.",
        input_model=AuditResumeInput,
        output_model=AuditResumeOutput,
        handler=lambda value, _context: AuditResumeOutput(
            audit=service.audit_claims(
                value.resume_version_id,
                evidence_by_text=value.evidence_by_text,
                conflicts=value.conflicts,
                gaps=value.gaps,
                visibility_by_text=value.visibility_by_text,
            ).model_dump(mode="json")
        ),
        effect=ToolEffect.LOCAL_DRAFT_WRITE,
        idempotent=True,
        requires_approval=False,
    )

    registry.register(
        name=PLAN_TAILORING_TOOL,
        description="Build an evidence-aware plan before changing resume wording.",
        input_model=PlanTailoringInput,
        output_model=PlanTailoringOutput,
        handler=lambda value, _context: PlanTailoringOutput(
            plan=service.plan_tailoring(**value.model_dump()).model_dump(mode="json")
        ),
        effect=ToolEffect.LOCAL_DRAFT_WRITE,
        idempotent=True,
        requires_approval=False,
    )

    registry.register(
        name=GENERATE_DRAFT_TOOL,
        description="Generate a draft and reject unsupported, private, numeric, technology, or responsibility claims.",
        input_model=GenerateDraftInput,
        output_model=GenerateDraftOutput,
        handler=lambda value, _context: GenerateDraftOutput(
            draft=service.generate_draft(**value.model_dump()).model_dump(mode="json")
        ),
        effect=ToolEffect.LOCAL_DRAFT_WRITE,
        idempotent=True,
        requires_approval=False,
    )

    registry.register(
        name=REVIEW_DRAFT_TOOL,
        description="Record explicit partial acceptance or rejection of grounded draft changes.",
        input_model=ReviewDraftInput,
        output_model=ReviewDraftOutput,
        handler=lambda value, _context: ReviewDraftOutput(
            draft=service.review_draft(
                value.draft_id,
                approved_change_ids=value.approved_change_ids,
            ).model_dump(mode="json")
        ),
        effect=ToolEffect.LOCAL_DRAFT_WRITE,
        idempotent=True,
        requires_approval=False,
    )

    def save_version(value: SaveVersionInput, context: ToolContext) -> ResumeVersionOutput:
        return ResumeVersionOutput(
            version=service.save_approved_version(
                value.draft_id,
                approval_action_id=value.approval_action_id or f"{context.run_id}:{value.draft_id}",
            ).model_dump(mode="json")
        )

    registry.register(
        name=SAVE_VERSION_TOOL,
        description="Persist only explicitly approved changes as a new immutable resume version.",
        input_model=SaveVersionInput,
        output_model=ResumeVersionOutput,
        handler=save_version,
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
        requires_approval=True,
    )

    registry.register(
        name=COMPARE_RESUME_TOOL,
        description="Compare resume versions by sections, bullets, skills, rewrites, and moves.",
        input_model=CompareResumeInput,
        output_model=CompareResumeOutput,
        handler=lambda value, _context: CompareResumeOutput(
            comparison=service.compare_versions(
                value.from_version_id, value.to_version_id
            ).model_dump(mode="json")
        ),
        effect=ToolEffect.READ_ONLY,
        idempotent=True,
        requires_approval=False,
    )

    registry.register(
        name=COVERAGE_TOOL,
        description="Report resume representation coverage separately from job fit.",
        input_model=CoverageInput,
        output_model=CoverageOutput,
        handler=lambda value, _context: CoverageOutput(
            coverage=service.coverage(**value.model_dump()).model_dump(mode="json")
        ),
        effect=ToolEffect.READ_ONLY,
        idempotent=True,
        requires_approval=False,
    )

    registry.register(
        name=APPLICATION_RESUME_TOOL,
        description="Bind an existing application to one exact immutable resume version.",
        input_model=ApplicationResumeInput,
        output_model=ApplicationResumeOutput,
        handler=lambda value, _context: ApplicationResumeOutput(
            link=service.link_to_application(
                tracker=tracker,
                user_id=user_id,
                **value.model_dump(),
            ).model_dump(mode="json")
        ),
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
        requires_approval=True,
    )
    return registry
