"""Typed, bounded collaboration for quoting existing experience into a summary."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from job_agent.resume_workspace.contracts import VersionRecord, ResumeFact
from job_agent.schemas import StrictModel
from job_agent.text_identity import normalize_text


class CollaborationError(ValueError):
    pass


class CollaborationRequest(StrictModel):
    request_key: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,80}$')
    version_id: str = Field(min_length=1,max_length=64)
    expected_content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    jd_text: str = Field(min_length=1,max_length=12000)
    mode: Literal['local_demo','llm'] = 'local_demo'
    allow_external_processing: bool = False

    @field_validator('jd_text')
    @classmethod
    def canonical(cls,v):
        v=normalize_text(v).strip()
        if not v:raise ValueError('empty_jd')
        return v


class SummaryProposal(StrictModel):
    proposal_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    source_path: str = Field(min_length=1,max_length=100)
    text: str = Field(min_length=1,max_length=5000)
    reason: str = Field(min_length=1,max_length=240)


class WriterDraft(StrictModel):
    proposals: list[SummaryProposal] = Field(max_length=3)


class ReviewItem(StrictModel):
    proposal_id: str = Field(min_length=1,max_length=50)
    outcome: Literal['accept','revise','needs_input']
    issue_code: Literal['none','unrelated','ambiguous','missing_context','unsupported_claim','already_present','invalid_source','changed_original','no_capacity']
    constraint: str = Field(min_length=1,max_length=240)


class ReviewerOutput(StrictModel):
    items: list[ReviewItem] = Field(max_length=3)


class ReviewFeedback(ReviewerOutput):
    draft_revision: int
    draft_hash: str


class AgentMessage(StrictModel):
    message_id: str
    correlation_id: str
    sender: Literal['writer','reviewer','supervisor']
    receiver: Literal['writer','reviewer','user']
    kind: Literal['review_request','review_feedback','revision_request','user_approval','blocked']
    draft_revision: int
    artifact_hash: str
    payload: dict[str,Any]


class CollaborationUsage(StrictModel):
    writer_calls: int = 0
    reviewer_calls: int = 0
    provider_calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    active_ms: int = 0
    cost: float | None = None


class DraftRevision(StrictModel):
    revision: int
    draft_hash: str
    draft: WriterDraft
    feedback: ReviewFeedback | None = None


class CollaborationState(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    resume_id: str
    version_id: str
    version_hash: str
    jd_text: str
    mode: Literal['local_demo','llm']
    provider: str
    model: str
    created_at: datetime
    status: Literal['pending','running','awaiting_approval','needs_input','failed'] = 'pending'
    next_node: Literal['writer','reviewer','supervisor','end'] = 'writer'
    revision: int = Field(default=0,ge=0,le=3)
    drafts: list[DraftRevision] = Field(default_factory=list,max_length=3)
    messages: list[AgentMessage] = Field(default_factory=list,max_length=20)
    usage: CollaborationUsage = Field(default_factory=CollaborationUsage)
    model_inflight: bool = False
    error_code: str | None = None


class CollaborationSummary(StrictModel):
    run_id: str
    version_id: str
    status: str
    created_at: datetime


class CollaborationView(StrictModel):
    state: CollaborationState
    checkpoint_revision: int
    expected_head_version_id: str
    can_apply: bool
    decisions: dict[str,str]
    accepted_version_ids: dict[str,str]
    resumable: bool
    source_facts: dict[str,ResumeFact]
    verification: list['ProposalVerification'] = Field(default_factory=list)


class ProposalVerification(StrictModel):
    proposal_id: str
    provenance: Literal['matched','not_matched']
    statement: Literal['exact_copy','changed_or_unknown']
    relevance: Literal['not_reviewed','keyword_lead','model_recommends','revise','needs_input']
    evidence_level: Literal['C1'] = 'C1'
    independent_truth: Literal['not_verified'] = 'not_verified'
    user_decision: Literal['pending','accepted','rejected']
    resume_confirmation: Literal['not_saved','unconfirmed','confirmed']


class CollaborationDecision(StrictModel):
    action: Literal['accept','reject']
    expected_parent_version_id: str
    draft_revision: int = Field(ge=1,le=3)
    draft_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    user_reviewed: Literal[True]


class CollaborationDecisionResult(StrictModel):
    collaboration: CollaborationView
    version: VersionRecord | None = None
