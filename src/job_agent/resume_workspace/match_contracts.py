from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from job_agent.evidence.contracts import EvidenceBundle
from job_agent.resume_workspace.contracts import ResumeFact, VersionRecord
from job_agent.resume_workspace.parsing_contracts import ParseUsage
from job_agent.schemas import StrictModel
from job_agent.text_identity import normalize_text


class MatchError(ValueError):
    pass


class AnalyzeRequest(StrictModel):
    request_key: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,80}$")
    version_id: str = Field(min_length=1, max_length=64)
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: str = Field(min_length=1, max_length=120)
    jd_text: str = Field(min_length=1, max_length=15_000)
    mode: Literal["local_check", "llm"] = "local_check"
    allow_external_processing: bool = False

    @field_validator("jd_text")
    @classmethod
    def canonical_jd(cls, value):
        value = normalize_text(value).strip()
        if not value:
            raise ValueError("empty_jd")
        return value


class OrderProposal(StrictModel):
    proposal_id: str
    section: Literal["projects", "experience", "skills"]
    target_id: str
    title: str
    reason: str
    preview: str


class MatchPayload(StrictModel):
    schema_version: Literal[1] = 1
    match_id: str
    resume_id: str
    version_id: str
    version_hash: str
    title: str
    jd_text: str
    mode: Literal["local_check", "llm"]
    bundle: EvidenceBundle
    proposals: list[OrderProposal]
    usage: ParseUsage
    created_at: datetime


class MatchLinkView(StrictModel):
    path: str
    quote: str
    # Original workspace span, not a path into a temporary artifact folder.
    fact: ResumeFact
    level: Literal["C1"] = "C1"
    support_status: Literal["supported", "partial", "unsupported", "contradictory"]


class MatchRowView(StrictModel):
    atom_id: str
    text: str
    importance: str
    jd_quote: str
    jd_start: int
    jd_end: int
    match_status: str
    has_contradiction: bool
    rationale: str
    links: list[MatchLinkView]


class ProposalView(OrderProposal):
    decision: Literal["pending", "accepted", "rejected"] = "pending"
    accepted_version_id: str | None = None


class MatchView(StrictModel):
    match_id: str
    resume_id: str
    version_id: str
    version_hash: str
    title: str
    jd_text: str
    mode: Literal["local_check", "llm"]
    provider: str
    model: str
    usage: ParseUsage
    created_at: datetime
    expected_head_version_id: str
    can_apply: bool
    rows: list[MatchRowView]
    proposals: list[ProposalView]
    warnings: list[str]


class MatchSummary(StrictModel):
    match_id: str
    title: str
    version_id: str
    status: Literal["running", "complete", "failed"]
    error_code: str | None = None
    created_at: datetime


class DecideProposal(StrictModel):
    action: Literal["accept", "reject"]
    expected_parent_version_id: str
    user_reviewed: Literal[True]


class DecisionResult(StrictModel):
    match: MatchView
    version: VersionRecord | None = None
