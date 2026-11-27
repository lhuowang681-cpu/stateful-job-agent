from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from job_agent.schemas import ApplicationStatus, StrictModel


class InterviewRoundType(str, Enum):
    ONLINE_ASSESSMENT = "ONLINE_ASSESSMENT"
    HR = "HR"
    TECHNICAL = "TECHNICAL"
    BEHAVIORAL = "BEHAVIORAL"
    HIRING_MANAGER = "HIRING_MANAGER"
    FINAL = "FINAL"
    OTHER = "OTHER"


class InterviewRoundStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InterviewMode(str, Enum):
    QUICK_PREP = "QUICK_PREP"
    MOCK_INTERVIEW = "MOCK_INTERVIEW"
    PROJECT_DEEP_DIVE = "PROJECT_DEEP_DIVE"
    GAP_REVIEW = "GAP_REVIEW"


class QuestionSourceType(str, Enum):
    JOB_REQUIREMENT = "JOB_REQUIREMENT"
    RESUME_PROJECT = "RESUME_PROJECT"
    CAREER_GAP = "CAREER_GAP"
    TECHNICAL = "TECHNICAL"
    BEHAVIORAL = "BEHAVIORAL"
    FOLLOW_UP = "FOLLOW_UP"


class QuestionDifficulty(str, Enum):
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    CHALLENGE = "CHALLENGE"


class SessionStatus(str, Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class EvaluationLevel(str, Enum):
    GOOD = "GOOD"
    PARTIAL = "PARTIAL"
    WEAK = "WEAK"


class ClaimGrounding(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    TECHNICAL_KNOWLEDGE = "TECHNICAL_KNOWLEDGE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class WeaknessStatus(str, Enum):
    OPEN = "OPEN"
    IMPROVING = "IMPROVING"
    RESOLVED = "RESOLVED"


class WeaknessSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InterviewRound(StrictModel):
    round_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    round_type: InterviewRoundType
    round_number: int = Field(ge=1)
    scheduled_at: datetime | None = None
    status: InterviewRoundStatus = InterviewRoundStatus.PLANNED
    interviewer_role: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    notes: str = ""
    created_by_trace_id: str | None = None


class PrepJobFocus(StrictModel):
    requirements: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class PrepResumeFocus(StrictModel):
    item_id: str
    text: str
    reason: str
    claim_refs: list[str] = Field(default_factory=list)


class PrepTechnicalTopic(StrictModel):
    topic: str
    reason: str
    requirement_refs: list[str] = Field(default_factory=list)


class PrepProjectDeepDive(StrictModel):
    project: str
    prompts: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class PrepGapDefense(StrictModel):
    gap: str
    honest_boundary: str
    transferable_experience: list[str] = Field(default_factory=list)


class InterviewPrepSnapshot(StrictModel):
    prep_version_id: str
    version: int = Field(ge=1)
    application_id: str
    job_id: str
    jd_snapshot_id: str
    jd_version: int = Field(ge=1)
    analysis_snapshot_id: str
    interview_round_id: str
    resume_version_id: str
    mode: InterviewMode
    created_at: datetime
    stale: bool = False
    job_focus: PrepJobFocus
    resume_focus: list[PrepResumeFocus] = Field(default_factory=list)
    technical_review: list[PrepTechnicalTopic] = Field(default_factory=list)
    project_deep_dive: list[PrepProjectDeepDive] = Field(default_factory=list)
    gap_defense: list[PrepGapDefense] = Field(default_factory=list)
    questions_to_ask: list[str] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)


class InterviewQuestion(StrictModel):
    question_id: str
    source_type: QuestionSourceType
    category: str
    difficulty: QuestionDifficulty
    prompt: str = Field(min_length=1)
    why_asked: str = Field(min_length=1)
    job_requirement_refs: list[str] = Field(default_factory=list)
    resume_claim_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    expected_points: list[str] = Field(min_length=1)
    created_at: datetime
    parent_question_id: str | None = None
    missing_points: list[str] = Field(default_factory=list)
    follow_up_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_follow_up(self) -> "InterviewQuestion":
        if self.source_type == QuestionSourceType.FOLLOW_UP:
            if not self.parent_question_id or not self.missing_points or not self.follow_up_reason:
                raise ValueError("follow-up requires parent, missing points, and reason")
        return self


class UnsupportedClaim(StrictModel):
    text: str
    kind: str
    reason: str


class AnswerEvaluation(StrictModel):
    factual_grounding: EvaluationLevel
    relevance: EvaluationLevel
    completeness: EvaluationLevel
    specificity: EvaluationLevel
    structure: EvaluationLevel
    grounding: ClaimGrounding
    covered_points: list[str] = Field(default_factory=list)
    missing_points: list[str] = Field(default_factory=list)
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    feedback: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class InterviewTurnRecord(StrictModel):
    turn_id: str
    session_id: str
    ordinal: int = Field(ge=1)
    question: InterviewQuestion
    user_answer: str = Field(min_length=1)
    evaluation: AnswerEvaluation
    follow_up: InterviewQuestion | None = None
    created_at: datetime
    token_usage: dict[str, int] = Field(default_factory=dict)


class MockInterviewSession(StrictModel):
    session_id: str
    application_id: str
    round_id: str | None = None
    job_id: str
    resume_version_id: str
    prep_version_id: str
    mode: InterviewMode
    status: SessionStatus = SessionStatus.CREATED
    started_at: datetime
    completed_at: datetime | None = None
    question_ids: list[str] = Field(default_factory=list)
    turns: list[InterviewTurnRecord] = Field(default_factory=list)
    summary: str = ""
    token_usage: dict[str, int] = Field(default_factory=dict)


class WeaknessHistoryEvent(StrictModel):
    status: WeaknessStatus
    session_id: str
    occurred_at: datetime
    note: str


class InterviewWeaknessSnapshot(StrictModel):
    weakness_id: str
    category: str
    description: str
    supporting_turns: list[str] = Field(min_length=1)
    job_requirement_refs: list[str] = Field(default_factory=list)
    severity: WeaknessSeverity
    created_at: datetime
    status: WeaknessStatus = WeaknessStatus.OPEN
    history: list[WeaknessHistoryEvent] = Field(min_length=1)
    created_by_trace_id: str | None = None


class InterviewReviewItem(StrictModel):
    priority: int = Field(ge=1)
    topic: str
    reason: str
    related_jobs: list[str] = Field(default_factory=list)
    source_sessions: list[str] = Field(default_factory=list)
    weakness_ids: list[str] = Field(default_factory=list)
    targeted_question_id: str | None = None


class RealInterviewQuestion(StrictModel):
    question: str
    answer_summary: str = ""
    self_assessment: EvaluationLevel | None = None
    requirement_refs: list[str] = Field(default_factory=list)
    notes: str = ""


class RealInterviewRecord(StrictModel):
    record_id: str
    application_id: str
    round_id: str
    job_id: str
    occurred_at: datetime
    questions: list[RealInterviewQuestion] = Field(min_length=1)
    outcome: str | None = None
    notes: str = ""
    created_at: datetime


class ApplicationDashboard(StrictModel):
    total_applications: int
    by_stage: dict[str, int]
    upcoming_interviews: int
    waiting_response: int
    offers: int
    rejections: int
    withdrawn: int
    average_days_in_stage: float | None = None
    by_job_family: dict[str, int] = Field(default_factory=dict)


class InterviewAnalytics(StrictModel):
    mock_sessions: int
    real_interview_records: int
    questions_answered: int
    weakness_categories: dict[str, int]
    repeated_weaknesses: int
    resolved_weaknesses: int


class CopilotHistory(StrictModel):
    application_id: str
    stage: ApplicationStatus
    rounds: list[InterviewRound]
    prep_snapshots: list[InterviewPrepSnapshot]
    mock_sessions: list[MockInterviewSession]
    real_interviews: list[RealInterviewRecord]
    weaknesses: list[InterviewWeaknessSnapshot]
