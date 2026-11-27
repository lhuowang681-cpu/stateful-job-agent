from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from job_agent.schemas import StrictModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class PrivacyLevel(str, Enum):
    FULL = "FULL"
    REDACTED = "REDACTED"
    METADATA_ONLY = "METADATA_ONLY"


class TraceStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WAITING = "WAITING"
    CANCELLED = "CANCELLED"


class FailureCategory(str, Enum):
    MODEL_SCHEMA = "MODEL_SCHEMA"
    MODEL_SEMANTIC = "MODEL_SEMANTIC"
    CONTEXT = "CONTEXT"
    REFERENT = "REFERENT"
    CAPABILITY_SELECTION = "CAPABILITY_SELECTION"
    ARGUMENT = "ARGUMENT"
    POLICY = "POLICY"
    APPROVAL = "APPROVAL"
    TOOL_INPUT = "TOOL_INPUT"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    TIMEOUT = "TIMEOUT"
    RETRIEVAL = "RETRIEVAL"
    EVIDENCE = "EVIDENCE"
    PROVENANCE = "PROVENANCE"
    STATE = "STATE"
    IDEMPOTENCY = "IDEMPOTENCY"
    STEP_BUDGET = "STEP_BUDGET"
    USER_INPUT = "USER_INPUT"
    EXTERNAL_PROVIDER = "EXTERNAL_PROVIDER"


class DecisionKind(str, Enum):
    ACTION = "Action"
    FINISH = "Finish"
    INPUT_REQUEST = "InputRequest"


class ContextCategory(str, Enum):
    SYSTEM_POLICY = "SYSTEM_POLICY"
    USER_INPUT = "USER_INPUT"
    CONVERSATION = "CONVERSATION"
    DURABLE = "DURABLE"
    MEMORY = "MEMORY"
    ANALYSIS = "ANALYSIS"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    KNOWLEDGE_EVIDENCE = "KNOWLEDGE_EVIDENCE"


class ContentSummary(StrictModel):
    sha256: str = Field(min_length=64, max_length=64)
    chars: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    preview: str | None = None
    redacted: bool = True


class TokenUsage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)

    @property
    def total_tokens(self) -> int | None:
        values = (self.input_tokens, self.output_tokens)
        if all(value is None for value in values):
            return None
        return sum(value or 0 for value in values)


class CostRecord(StrictModel):
    amount: float = Field(ge=0.0)
    currency: str = "USD"
    estimated: bool = False
    source: str = Field(min_length=1)


class TraceVersions(StrictModel):
    code_revision: str = "unknown"
    runtime: str = "unknown"
    prompt: str = "unknown"
    contract: str = "agent-trace-v1"
    schema_version: int = Field(default=1, ge=1)
    provider_config: str = "unknown"


class FailureAttribution(StrictModel):
    category: FailureCategory
    code: str = Field(min_length=1)
    message: str | None = None
    step_index: int | None = Field(default=None, ge=0)
    retryable: bool | None = None


class ContextTrace(StrictModel):
    category: ContextCategory
    included: bool
    reason: str = Field(min_length=1)
    content: ContentSummary


class PolicyTrace(StrictModel):
    allowed: bool
    reason_code: str
    effect: str | None = None


class ApprovalTrace(StrictModel):
    required: bool = False
    request_id: str | None = None
    resolved: bool = False
    approved: bool | None = None


class ToolTrace(StrictModel):
    tool_name: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    arguments: ContentSummary
    validation_status: Literal["not_checked", "valid", "invalid"] = "not_checked"
    policy: PolicyTrace | None = None
    approval: ApprovalTrace = Field(default_factory=ApprovalTrace)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int = Field(default=0, ge=0)
    result_status: str | None = None
    result: ContentSummary | None = None
    idempotency_key: str | None = None
    retry_count: int = Field(default=0, ge=0)
    timeout: bool = False
    error: FailureAttribution | None = None


class StateMutationTrace(StrictModel):
    entity_type: Literal[
        "Job",
        "JD",
        "ResumeVersion",
        "Application",
        "InterviewRound",
        "Weakness",
        "MemoryPreference",
    ]
    entity_id: str = Field(min_length=1)
    operation: Literal["create", "update", "delete"]
    before_ref: str | None = None
    after_ref: str | None = None
    created_by_trace_id: str | None = None


class RetrievalCandidateTrace(StrictModel):
    chunk_id: str
    rank: int = Field(ge=1)
    score: float
    selected: bool = False


class RetrievalTrace(StrictModel):
    query: ContentSummary
    requirement_atom_id: str | None = None
    method: str = Field(min_length=1)
    candidates: list[RetrievalCandidateTrace] = Field(default_factory=list)
    entailment: str | None = None
    selected_evidence_ids: list[str] = Field(default_factory=list)
    source_span_refs: list[str] = Field(default_factory=list)
    aggregation: str | None = None


class AgentTraceStep(StrictModel):
    step_index: int = Field(ge=0)
    decision: DecisionKind
    capability: str = Field(min_length=1)
    arguments: ContentSummary | None = None
    policy: PolicyTrace | None = None
    approval: ApprovalTrace | None = None
    tool: ToolTrace | None = None
    state_mutations: list[StateMutationTrace] = Field(default_factory=list)
    retrievals: list[RetrievalTrace] = Field(default_factory=list)
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int = Field(default=0, ge=0)
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    failure: FailureAttribution | None = None


class AgentTrace(StrictModel):
    trace_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    started_at: datetime
    ended_at: datetime | None = None
    provider: str = "unknown"
    model: str = "unknown"
    status: TraceStatus = TraceStatus.RUNNING
    termination_reason: str | None = None
    input_summary: ContentSummary
    context: list[ContextTrace] = Field(default_factory=list)
    steps: list[AgentTraceStep] = Field(default_factory=list)
    final_result: ContentSummary | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = Field(default=0, ge=0)
    cost: CostRecord | None = None
    versions: TraceVersions = Field(default_factory=TraceVersions)
    failure: FailureAttribution | None = None
    privacy_level: PrivacyLevel = PrivacyLevel.REDACTED
    job_id: str | None = None
    application_id: str | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "AgentTrace":
        if self.status != TraceStatus.RUNNING and self.ended_at is None:
            raise ValueError("finished traces require ended_at")
        return self


class TraceQuery(StrictModel):
    started_after: datetime | None = None
    started_before: datetime | None = None
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    capability: str | None = None
    status: TraceStatus | None = None
    failure: FailureCategory | None = None
    job_id: str | None = None
    application_id: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ReplayMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    LIVE_ISOLATED = "LIVE_ISOLATED"


class ReplayResult(StrictModel):
    replay_id: str
    source_trace_id: str
    mode: ReplayMode
    trace: AgentTrace
    used_recorded_observations: bool
    used_recorded_state: bool
    production_mutation: bool = False


class TrajectoryDiff(StrictModel):
    baseline_trace_id: str
    candidate_trace_id: str
    added_actions: list[str] = Field(default_factory=list)
    removed_actions: list[str] = Field(default_factory=list)
    changed_arguments: list[str] = Field(default_factory=list)
    final_result_changed: bool = False
    mutation_changes: list[str] = Field(default_factory=list)
    step_delta: int = 0
    token_delta: int | None = None


class ProviderComparison(StrictModel):
    providers: list[str]
    correctness: dict[str, bool | None]
    constraint_compliance: dict[str, bool | None]
    steps: dict[str, int]
    tokens: dict[str, int | None]
    latency_ms: dict[str, int]
    tool_calls: dict[str, int]
    failures: dict[str, str | None]
    diffs: list[TrajectoryDiff] = Field(default_factory=list)


class CapabilityMetric(StrictModel):
    capability: str
    count: int
    success_rate: float = Field(ge=0.0, le=1.0)
    latency_p50_ms: float = Field(ge=0.0)
    latency_p95_ms: float = Field(ge=0.0)
    tokens_total: int | None = None
    tool_calls: int = Field(ge=0)
    state_mutations: int = Field(ge=0)


class SessionMetric(StrictModel):
    session_id: str
    traces: int
    completed: int
    failed: int
    tokens_total: int | None = None
    latency_total_ms: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    state_mutations: int = Field(ge=0)


class MetricsSummary(StrictModel):
    traces: int
    completed: int
    failed: int
    tokens_total: int | None = None
    tool_calls: int
    state_mutations: int
    latency_p50_ms: float
    latency_p95_ms: float
    failures: dict[str, int] = Field(default_factory=dict)
    capabilities: list[CapabilityMetric] = Field(default_factory=list)
    sessions: list[SessionMetric] = Field(default_factory=list)


class RetentionPolicy(StrictModel):
    mode: Literal["keep_forever", "delete_after_days", "metadata_only_after_days"] = "keep_forever"
    days: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_days(self) -> "RetentionPolicy":
        if self.mode != "keep_forever" and self.days is None:
            raise ValueError("bounded retention requires days")
        return self
