from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from job_agent.agent_ops.contracts import (
    AgentTrace,
    AgentTraceStep,
    ApprovalTrace,
    ContextCategory,
    ContextTrace,
    CostRecord,
    DecisionKind,
    FailureAttribution,
    FailureCategory,
    PrivacyLevel,
    PolicyTrace,
    RetrievalTrace,
    StateMutationTrace,
    ToolTrace,
    TokenUsage,
    TraceStatus,
    TraceVersions,
)
from job_agent.agent_ops.privacy import summarize
from job_agent.agent_ops.repository import SQLiteTraceRepository
from job_agent.agent_runtime.contracts import AgentAction, AgentFinish, AgentInputRequest
from job_agent.agent_runtime.events import (
    AgentEvent,
    ApprovalResolvedEvent,
    ModelDecisionEvent,
    PolicyDecisionEvent,
    RunFinishedEvent,
    RunStartedEvent,
    ToolObservedEvent,
    VerificationEvent,
)


_FAILURE_MAP: tuple[tuple[str, FailureCategory], ...] = (
    ("schema", FailureCategory.MODEL_SCHEMA),
    ("semantic", FailureCategory.MODEL_SEMANTIC),
    ("verifier", FailureCategory.MODEL_SEMANTIC),
    ("context", FailureCategory.CONTEXT),
    ("referent", FailureCategory.REFERENT),
    ("capability", FailureCategory.CAPABILITY_SELECTION),
    ("argument", FailureCategory.ARGUMENT),
    ("policy", FailureCategory.POLICY),
    ("authorization", FailureCategory.POLICY),
    ("approval", FailureCategory.APPROVAL),
    ("tool_input", FailureCategory.TOOL_INPUT),
    ("tool_output", FailureCategory.TOOL_OUTPUT),
    ("tool_execution", FailureCategory.TOOL_EXECUTION),
    ("timeout", FailureCategory.TIMEOUT),
    ("retrieval", FailureCategory.RETRIEVAL),
    ("evidence", FailureCategory.EVIDENCE),
    ("provenance", FailureCategory.PROVENANCE),
    ("state", FailureCategory.STATE),
    ("idempotent", FailureCategory.IDEMPOTENCY),
    ("duplicate", FailureCategory.IDEMPOTENCY),
    ("step_budget", FailureCategory.STEP_BUDGET),
    ("budget", FailureCategory.STEP_BUDGET),
    ("user_input", FailureCategory.USER_INPUT),
    ("provider", FailureCategory.EXTERNAL_PROVIDER),
    ("model_error", FailureCategory.EXTERNAL_PROVIDER),
)


def classify_failure(code: str, *, step_index: int | None = None) -> FailureAttribution:
    lowered = code.casefold()
    category = FailureCategory.TOOL_EXECUTION
    for marker, candidate in _FAILURE_MAP:
        if marker in lowered:
            category = candidate
            break
    return FailureAttribution(category=category, code=code, step_index=step_index)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _action_digest(tool_name: str, arguments: dict[str, Any]) -> str:
    value = json.dumps(
        {"tool_name": tool_name, "tool_arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CompositeTrajectorySink:
    def __init__(self, *sinks: Any) -> None:
        self.sinks = sinks

    def append(self, event: AgentEvent) -> None:
        for sink in self.sinks:
            sink.append(event)


class AgentTraceRecorder:
    """Adapts existing Agent Runtime events into one privacy-safe AgentTrace."""

    def __init__(
        self,
        *,
        repository: SQLiteTraceRepository | None = None,
        privacy_level: PrivacyLevel = PrivacyLevel.REDACTED,
        versions: TraceVersions | None = None,
        trace_id: str | None = None,
        job_id: str | None = None,
        application_id: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self.repository = repository
        self.privacy_level = privacy_level
        self.versions = versions or TraceVersions()
        self.trace_id = trace_id or f"trace-{uuid4().hex}"
        self.job_id = job_id
        self.application_id = application_id
        self.tags = tags or []
        self.trace: AgentTrace | None = None
        self.events: list[AgentEvent] = []

    def append(self, event: AgentEvent) -> None:
        self.events.append(event)
        if isinstance(event, RunStartedEvent):
            self._start(event)
        elif self.trace is None:
            raise ValueError("trace must start with run_started")
        elif isinstance(event, ModelDecisionEvent):
            self._decision(event)
        elif isinstance(event, PolicyDecisionEvent):
            self._policy(event)
        elif isinstance(event, ApprovalResolvedEvent):
            self._approval(event)
        elif isinstance(event, ToolObservedEvent):
            self._observation(event)
        elif isinstance(event, VerificationEvent):
            self._verification(event)
        elif isinstance(event, RunFinishedEvent):
            self._finish(event)

    def _start(self, event: RunStartedEvent) -> None:
        self.trace = AgentTrace(
            trace_id=self.trace_id,
            session_id=event.session_id,
            run_id=event.run_id,
            agent_id=event.agent_id,
            started_at=_timestamp(event.timestamp),
            input_summary=summarize(event.goal, level=self.privacy_level, sensitive=True),
            versions=self.versions,
            privacy_level=self.privacy_level,
            job_id=self.job_id,
            application_id=self.application_id,
            tags=self.tags,
        )

    def _replace_trace(self, **updates: Any) -> None:
        assert self.trace is not None
        self.trace = self.trace.model_copy(update=updates)

    def _replace_step(self, position: int, step: AgentTraceStep) -> None:
        assert self.trace is not None
        steps = list(self.trace.steps)
        steps[position] = step
        self._replace_trace(steps=steps)

    def _decision(self, event: ModelDecisionEvent) -> None:
        assert self.trace is not None
        decision = event.decision
        if isinstance(decision, AgentAction):
            kind = DecisionKind.ACTION
            capability = decision.tool_name
            arguments = summarize(
                decision.tool_arguments,
                level=self.privacy_level,
                sensitive=True,
            )
            tool = ToolTrace(
                tool_name=decision.tool_name,
                action_id=decision.action_id,
                arguments=arguments,
                idempotency_key=_action_digest(decision.tool_name, decision.tool_arguments),
                started_at=_timestamp(event.timestamp),
            )
        elif isinstance(decision, AgentFinish):
            kind = DecisionKind.FINISH
            capability = "finish"
            arguments = summarize(decision.result, level=self.privacy_level, sensitive=True)
            tool = None
        elif isinstance(decision, AgentInputRequest):
            kind = DecisionKind.INPUT_REQUEST
            capability = "request_user_input"
            arguments = summarize(
                decision.request.model_dump(mode="json"),
                level=self.privacy_level,
                sensitive=True,
            )
            tool = None
        else:  # pragma: no cover - discriminated union guard
            raise TypeError(type(decision))
        step = AgentTraceStep(
            step_index=event.step_index,
            decision=kind,
            capability=capability,
            arguments=arguments,
            tool=tool,
            started_at=_timestamp(event.timestamp),
            tokens=TokenUsage(
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cached_tokens=event.cached_tokens,
                reasoning_tokens=event.reasoning_tokens,
            ),
        )
        cost = self.trace.cost
        if event.cost is not None:
            cost = CostRecord(
                amount=(cost.amount if cost else 0.0) + event.cost,
                source="provider_event",
                estimated=False,
            )
        self._replace_trace(
            steps=[*self.trace.steps, step],
            provider=event.provider,
            model=event.model,
            tokens=self._aggregate_tokens([*self.trace.steps, step]),
            cost=cost,
        )

    def _current_action(self, step_index: int) -> tuple[int, AgentTraceStep] | None:
        assert self.trace is not None
        for position in range(len(self.trace.steps) - 1, -1, -1):
            step = self.trace.steps[position]
            if step.step_index == step_index and step.decision == DecisionKind.ACTION:
                return position, step
        return None

    def _policy(self, event: PolicyDecisionEvent) -> None:
        current = self._current_action(event.step_index)
        if current is None:
            return
        position, step = current
        authorization = event.authorization
        policy = PolicyTrace(
            allowed=authorization.allowed,
            reason_code=authorization.reason_code,
            effect=authorization.effect.value,
        )
        approval_request = authorization.approval_request
        approval = ApprovalTrace(
            required=authorization.requires_approval,
            request_id=approval_request.request_id if approval_request else None,
        )
        tool = step.tool.model_copy(update={"policy": policy, "approval": approval}) if step.tool else None
        self._replace_step(
            position,
            step.model_copy(update={"policy": policy, "approval": approval, "tool": tool}),
        )

    def _approval(self, event: ApprovalResolvedEvent) -> None:
        current = self._current_action(event.step_index)
        if current is None:
            return
        position, step = current
        approval = ApprovalTrace(
            required=True,
            request_id=event.approval.request_id,
            resolved=True,
            approved=event.approval.approved,
        )
        tool = step.tool.model_copy(update={"approval": approval}) if step.tool else None
        self._replace_step(position, step.model_copy(update={"approval": approval, "tool": tool}))

    def _observation(self, event: ToolObservedEvent) -> None:
        current = self._current_action(event.step_index)
        if current is None:
            return
        position, step = current
        observation = event.observation
        ended = _timestamp(event.timestamp)
        failure = classify_failure(observation.error_code, step_index=event.step_index) if observation.error_code else None
        validation = "invalid" if observation.error_code == "tool_input_error" else "valid"
        result = summarize(observation.data, level=self.privacy_level, sensitive=True)
        tool = step.tool.model_copy(
            update={
                "validation_status": validation,
                "ended_at": ended,
                "duration_ms": observation.duration_ms,
                "result_status": observation.status.value,
                "result": result,
                "timeout": observation.error_code == "tool_timeout",
                "error": failure,
            }
        ) if step.tool else None
        self._replace_step(
            position,
            step.model_copy(
                update={
                    "tool": tool,
                    "ended_at": ended,
                    "duration_ms": observation.duration_ms,
                    "failure": failure,
                }
            ),
        )

    def _verification(self, event: VerificationEvent) -> None:
        if event.verification.passed or self.trace is None or not self.trace.steps:
            return
        position = len(self.trace.steps) - 1
        step = self.trace.steps[position]
        failure = FailureAttribution(
            category=FailureCategory.MODEL_SEMANTIC,
            code=event.verification.reason_code,
            step_index=step.step_index,
        )
        self._replace_step(position, step.model_copy(update={"failure": failure}))

    def _finish(self, event: RunFinishedEvent) -> None:
        assert self.trace is not None
        ended = _timestamp(event.timestamp)
        status_map = {
            "COMPLETED": TraceStatus.COMPLETED,
            "FAILED": TraceStatus.FAILED,
            "BUDGET_EXCEEDED": TraceStatus.FAILED,
            "WAITING_FOR_USER": TraceStatus.WAITING,
            "CANCELLED": TraceStatus.CANCELLED,
            "RUNNING": TraceStatus.RUNNING,
        }
        status = status_map[event.status.value]
        failure = classify_failure(event.error_code) if event.error_code else None
        self._replace_trace(
            ended_at=ended,
            status=status,
            termination_reason=event.error_code or event.status.value.casefold(),
            final_result=summarize(event.result, level=self.privacy_level, sensitive=True),
            latency_ms=max(int((ended - self.trace.started_at).total_seconds() * 1000), 0),
            failure=failure,
        )
        if self.repository is not None:
            self.repository.save(self.trace)

    def record_context(
        self,
        category: ContextCategory,
        value: Any,
        *,
        included: bool,
        reason: str,
        sensitive: bool | None = None,
    ) -> None:
        if self.trace is None:
            raise ValueError("trace has not started")
        if sensitive is None:
            sensitive = category in {
                ContextCategory.USER_INPUT,
                ContextCategory.CONVERSATION,
                ContextCategory.DURABLE,
                ContextCategory.MEMORY,
                ContextCategory.TOOL_OBSERVATION,
                ContextCategory.KNOWLEDGE_EVIDENCE,
            }
        context = ContextTrace(
            category=category,
            included=included,
            reason=reason,
            content=summarize(value, level=self.privacy_level, sensitive=sensitive),
        )
        self._replace_trace(context=[*self.trace.context, context])

    def record_mutation(self, step_index: int, mutation: StateMutationTrace) -> None:
        if self.trace is None:
            raise ValueError("trace has not started")
        if mutation.operation == "create" and mutation.created_by_trace_id is None:
            mutation = mutation.model_copy(update={"created_by_trace_id": self.trace.trace_id})
        for position, step in enumerate(self.trace.steps):
            if step.step_index == step_index:
                self._replace_step(
                    position,
                    step.model_copy(update={"state_mutations": [*step.state_mutations, mutation]}),
                )
                return
        raise ValueError(f"unknown step_index: {step_index}")

    def record_retrieval(self, step_index: int, retrieval: RetrievalTrace) -> None:
        if self.trace is None:
            raise ValueError("trace has not started")
        for position, step in enumerate(self.trace.steps):
            if step.step_index == step_index:
                self._replace_step(
                    position,
                    step.model_copy(update={"retrievals": [*step.retrievals, retrieval]}),
                )
                return
        raise ValueError(f"unknown step_index: {step_index}")

    def record_provider_usage(
        self,
        *,
        cached_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        cost: float | None = None,
        cost_source: str = "provider",
        estimated: bool = False,
    ) -> None:
        if self.trace is None:
            raise ValueError("trace has not started")
        tokens = self.trace.tokens.model_copy(
            update={"cached_tokens": cached_tokens, "reasoning_tokens": reasoning_tokens}
        )
        cost_record = None
        if cost is not None:
            cost_record = CostRecord(amount=cost, source=cost_source, estimated=estimated)
        self._replace_trace(tokens=tokens, cost=cost_record)

    @staticmethod
    def _aggregate_tokens(steps: list[AgentTraceStep]) -> TokenUsage:
        inputs = [step.tokens.input_tokens for step in steps if step.tokens.input_tokens is not None]
        outputs = [step.tokens.output_tokens for step in steps if step.tokens.output_tokens is not None]
        cached = [step.tokens.cached_tokens for step in steps if step.tokens.cached_tokens is not None]
        reasoning = [step.tokens.reasoning_tokens for step in steps if step.tokens.reasoning_tokens is not None]
        return TokenUsage(
            input_tokens=sum(inputs) if inputs else None,
            output_tokens=sum(outputs) if outputs else None,
            cached_tokens=sum(cached) if cached else None,
            reasoning_tokens=sum(reasoning) if reasoning else None,
        )
