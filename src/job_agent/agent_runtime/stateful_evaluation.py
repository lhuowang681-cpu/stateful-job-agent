from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import AliasChoices, Field, model_validator

from job_agent.schemas import StrictModel


STATEFUL_EVALUATOR_VERSION = "stateful-agent-evaluator-v2"


class FailureLayer(str, Enum):
    CONTEXT_SELECTION = "CONTEXT_SELECTION"
    REFERENT_RESOLUTION = "REFERENT_RESOLUTION"
    AGENT_DECISION = "AGENT_DECISION"
    CAPABILITY_SELECTION = "CAPABILITY_SELECTION"
    ARGUMENT_GENERATION = "ARGUMENT_GENERATION"
    RUNTIME_POLICY = "RUNTIME_POLICY"
    APPROVAL_RESUME = "APPROVAL_RESUME"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    STATE_MUTATION = "STATE_MUTATION"
    DURABLE_RECOVERY = "DURABLE_RECOVERY"
    MEMORY_UPDATE = "MEMORY_UPDATE"
    KNOWLEDGE_RETRIEVAL = "KNOWLEDGE_RETRIEVAL"
    EVIDENCE_MAPPING = "EVIDENCE_MAPPING"
    FINAL_RESPONSE = "FINAL_RESPONSE"
    STEP_BUDGET = "STEP_BUDGET"
    TRAJECTORY_EFFICIENCY = "TRAJECTORY_EFFICIENCY"


class InitialJobState(StrictModel):
    job_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str = ""
    job_type: str = ""
    jd_text: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    application_id: str | None = None
    application_stage: str | None = None


class InitialMemoryState(StrictModel):
    preferred_city: str | None = None
    acceptable_cities: list[str] = Field(default_factory=list)


class InitialConversationState(StrictModel):
    session_id: str = Field(min_length=1)
    current_job_id: str | None = None
    current_application_id: str | None = None
    stale_facts: dict[str, Any] = Field(default_factory=dict)


class StatefulInitialState(StrictModel):
    jobs: list[InitialJobState] = Field(default_factory=list)
    memory: InitialMemoryState = Field(default_factory=InitialMemoryState)
    conversations: list[InitialConversationState] = Field(default_factory=list)


class EvalUserTurn(StrictModel):
    turn_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    starts_new_process: bool = False
    approval: Literal["none", "approve", "deny"] = "none"
    clarification_response: dict[str, Any] | None = None


class ToolOrderingConstraint(StrictModel):
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)
    if_before_present: bool = True


class ExpectedDecision(StrictModel):
    turn_id: str = Field(min_length=1)
    required_kinds: list[Literal["finish", "input_request", "action"]] = Field(
        min_length=1,
        validation_alias=AliasChoices("required_kinds", "kinds"),
    )
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    ordering_constraints: list[ToolOrderingConstraint] = Field(default_factory=list)
    max_reasonable_tool_calls: int | None = Field(default=None, ge=0)
    expected_arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    expected_referent_id: str | None = None
    expected_clarification: bool = False


class GovernanceExpectation(StrictModel):
    approval_required: bool = False
    approval_resumed: bool = False
    policy_denied: bool = False
    exactly_once_mutation: bool = False
    direct_state_bypass_forbidden: bool = True


class StatefulExpectedBehavior(StrictModel):
    decisions: list[ExpectedDecision] = Field(min_length=1)
    final_state: dict[str, Any] = Field(default_factory=dict)
    forbidden_mutation_paths: list[str] = Field(default_factory=list)
    final_answer_facts: list[str] = Field(default_factory=list)
    forbidden_answer_facts: list[str] = Field(default_factory=list)
    governance: GovernanceExpectation = Field(default_factory=GovernanceExpectation)
    allowed_tool_outcomes: list[str] = Field(default_factory=lambda: ["ok", "empty"])
    termination_reason: str = "finished"
    max_agent_steps: int = Field(default=8, gt=0)
    max_tool_calls: int = Field(default=4, ge=0)


class StatefulAgentEvalCase(StrictModel):
    case_id: str = Field(min_length=1)
    split: Literal["dev", "test"]
    family: str = Field(min_length=1)
    initial: StatefulInitialState = Field(default_factory=StatefulInitialState)
    turns: list[EvalUserTurn] = Field(min_length=1)
    expected: StatefulExpectedBehavior
    cross_session: bool = False
    process_boundary: bool = False
    provider_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_turn_expectations(self):
        turn_ids = {turn.turn_id for turn in self.turns}
        expected_ids = {item.turn_id for item in self.expected.decisions}
        if not expected_ids.issubset(turn_ids):
            raise ValueError("decision expectations must reference declared turns")
        if self.process_boundary and not self.cross_session:
            raise ValueError("process boundary cases must also be cross-session")
        return self


class StatefulEvalDataset(StrictModel):
    dataset_version: str = Field(min_length=1)
    split: Literal["dev", "test"]
    frozen: bool
    cases: list[StatefulAgentEvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_split(self):
        if any(case.split != self.split for case in self.cases):
            raise ValueError("all cases must match the dataset split")
        if self.split == "test" and not self.frozen:
            raise ValueError("test dataset must be frozen")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("case_id values must be unique")
        return self


class ObservedAction(StrictModel):
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    outcome: str = "ok"


class ContextProjectionMetadata(StrictModel):
    included_sections: list[str] = Field(default_factory=list)
    excluded_sections: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    inclusion_reasons: list[str] = Field(default_factory=list)
    char_count: int = Field(default=0, ge=0)


class TurnEvalObservation(StrictModel):
    turn_id: str = Field(min_length=1)
    decisions: list[str] = Field(default_factory=list)
    actions: list[ObservedAction] = Field(default_factory=list)
    referent_id: str | None = None
    clarification_requested: bool = False
    final_answer: str = ""
    termination_reason: str = "finished"
    context: ContextProjectionMetadata = Field(
        default_factory=ContextProjectionMetadata
    )


class StatefulCaseObservation(StrictModel):
    case_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    schema_valid: bool = True
    turns: list[TurnEvalObservation] = Field(min_length=1)
    state_before: dict[str, Any] = Field(default_factory=dict)
    state_after: dict[str, Any] = Field(default_factory=dict)
    approval_requested: bool = False
    approval_resolved: bool = False
    policy_denied: bool = False
    direct_state_bypass: bool = False
    durable_reloaded: bool = False
    duplicate_mutations: int = Field(default=0, ge=0)
    agent_steps: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    clarification_turns: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class StatefulMetricResult(StrictModel):
    name: str = Field(min_length=1)
    passed: bool
    value: Any = None
    failure_layer: FailureLayer | None = None
    detail: str = ""


class TrajectoryEfficiencyFinding(StrictModel):
    turn_id: str = Field(min_length=1)
    kind: Literal[
        "justified_read",
        "redundant_read",
        "duplicate_read",
        "redundant_clarification",
        "redundant_tool_call",
        "tool_call_budget",
    ]
    tool_name: str | None = None
    count: int = Field(default=1, ge=1)
    detail: str = Field(min_length=1)


class StatefulCaseReport(StrictModel):
    case_id: str
    passed: bool
    task_success: bool
    constraint_compliant: bool
    efficiency_passed: bool
    metrics: list[StatefulMetricResult]
    efficiency_findings: list[TrajectoryEfficiencyFinding] = Field(
        default_factory=list
    )
    primary_failure_layer: FailureLayer | None = None
    secondary_failure_layers: list[FailureLayer] = Field(default_factory=list)
    agent_steps: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class StatefulAggregateMetrics(StrictModel):
    case_count: int = Field(ge=1)
    task_success_rate: float = Field(ge=0, le=1)
    constraint_compliance: float = Field(ge=0, le=1)
    trajectory_efficiency: float = Field(ge=0, le=1)
    decision_correctness: float = Field(ge=0, le=1)
    capability_selection_accuracy: float = Field(ge=0, le=1)
    required_tool_recall: float = Field(ge=0, le=1)
    forbidden_tool_rate: float = Field(ge=0, le=1)
    unnecessary_tool_rate: float = Field(ge=0, le=1)
    argument_correctness: float = Field(ge=0, le=1)
    referent_accuracy: float = Field(ge=0, le=1)
    clarification_accuracy: float = Field(ge=0, le=1)
    governance_compliance: float = Field(ge=0, le=1)
    state_mutation_accuracy: float = Field(ge=0, le=1)
    cross_session_recovery: float = Field(ge=0, le=1)
    idempotency_safety: float = Field(ge=0, le=1)
    grounding_accuracy: float = Field(ge=0, le=1)
    step_budget_compliance: float = Field(ge=0, le=1)
    schema_validity: float = Field(ge=0, le=1)
    average_agent_steps: float = Field(ge=0)
    average_tool_calls: float = Field(ge=0)
    average_clarification_turns: float = Field(ge=0)
    average_context_chars_per_turn: float = Field(ge=0)
    input_tokens_per_case: float = Field(ge=0)
    input_tokens_per_successful_task: float = Field(ge=0)
    model_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class StatefulEvalArtifact(StrictModel):
    run_id: str
    provider: str
    model: str
    provider_role: Literal[
        "production_acceptance",
        "development_smoke",
        "deterministic_regression",
    ]
    dataset_version: str
    evaluator_version: str = STATEFUL_EVALUATOR_VERSION
    timestamp: str
    git_commit: str
    metrics: StatefulAggregateMetrics
    cases: list[StatefulCaseReport]
    observations: list[StatefulCaseObservation]
    failures: list[dict[str, Any]] = Field(default_factory=list)
    efficiency_findings: list[dict[str, Any]] = Field(default_factory=list)


_METRIC_LAYERS = {
    "context_selection": FailureLayer.CONTEXT_SELECTION,
    "referent_accuracy": FailureLayer.REFERENT_RESOLUTION,
    "decision_correctness": FailureLayer.AGENT_DECISION,
    "capability_selection": FailureLayer.CAPABILITY_SELECTION,
    "required_tool_recall": FailureLayer.CAPABILITY_SELECTION,
    "forbidden_tool_compliance": FailureLayer.CAPABILITY_SELECTION,
    "trajectory_constraint_compliance": FailureLayer.AGENT_DECISION,
    "trajectory_efficiency": FailureLayer.TRAJECTORY_EFFICIENCY,
    "argument_correctness": FailureLayer.ARGUMENT_GENERATION,
    "governance_compliance": FailureLayer.RUNTIME_POLICY,
    "approval_resume": FailureLayer.APPROVAL_RESUME,
    "tool_execution": FailureLayer.TOOL_EXECUTION,
    "state_mutation": FailureLayer.STATE_MUTATION,
    "durable_recovery": FailureLayer.DURABLE_RECOVERY,
    "idempotency_safety": FailureLayer.STATE_MUTATION,
    "memory_update": FailureLayer.MEMORY_UPDATE,
    "grounding": FailureLayer.FINAL_RESPONSE,
    "step_budget": FailureLayer.STEP_BUDGET,
}


_TASK_CORRECTNESS_METRICS = {
    "referent_accuracy",
    "capability_selection",
    "required_tool_recall",
    "forbidden_tool_compliance",
    "argument_correctness",
    "clarification_accuracy",
    "governance_compliance",
    "approval_resume",
    "tool_execution",
    "state_mutation",
    "durable_recovery",
    "idempotency_safety",
    "memory_update",
    "grounding",
    "step_budget",
    "schema_validity",
    "trajectory_constraint_compliance",
}


_GROUNDING_EQUIVALENTS = {
    "acceptable": ("acceptable", "可接受", "可以考虑", "可考虑"),
    "applied": ("applied", "已投", "已申请", "已投递"),
    "evidence": ("evidence", "证据"),
    "gap": ("gap", "gaps", "差距", "缺口", "短板", "待补"),
}


def _answer_contains_fact(answer: str, fact: str) -> bool:
    normalized_answer = answer.casefold()
    normalized_fact = fact.casefold()
    if normalized_fact in normalized_answer:
        return True
    equivalents = _GROUNDING_EQUIVALENTS.get(normalized_fact)
    return bool(equivalents) and any(
        candidate.casefold() in normalized_answer for candidate in equivalents
    )


def _is_subsequence(required: Sequence[str], actual: Sequence[str]) -> bool:
    iterator = iter(actual)
    return all(any(candidate == item for candidate in iterator) for item in required)


def _ordering_constraints_pass(
    actions: Sequence[ObservedAction],
    constraints: Sequence[ToolOrderingConstraint],
) -> bool:
    names = [item.tool_name for item in actions]
    for constraint in constraints:
        if constraint.before not in names:
            if constraint.if_before_present:
                continue
            return False
        if constraint.after not in names:
            return False
        if names.index(constraint.before) >= names.index(constraint.after):
            return False
    return True


def _looks_like_read(tool_name: str) -> bool:
    terminal = tool_name.rsplit(".", 1)[-1]
    return terminal.startswith(("read", "get", "list", "query", "search"))


class StatefulAgentEvaluator:
    def evaluate(
        self,
        case: StatefulAgentEvalCase,
        observation: StatefulCaseObservation,
    ) -> StatefulCaseReport:
        if case.case_id != observation.case_id:
            raise ValueError("case and observation identity mismatch")
        metrics: list[StatefulMetricResult] = []
        observed_by_turn = {item.turn_id: item for item in observation.turns}
        expected_tools: list[str] = []
        forbidden_tools: list[str] = []
        argument_checks: list[bool] = []
        decision_checks: list[bool] = []
        referent_checks: list[bool] = []
        clarification_checks: list[bool] = []
        all_actions: list[ObservedAction] = []
        context_checks: list[bool] = []
        ordering_checks: list[bool] = []
        efficiency_findings: list[TrajectoryEfficiencyFinding] = []
        unnecessary_actions = 0

        for expected in case.expected.decisions:
            observed = observed_by_turn.get(expected.turn_id)
            if observed is None:
                decision_checks.append(False)
                referent_checks.append(expected.expected_referent_id is None)
                clarification_checks.append(not expected.expected_clarification)
                context_checks.append(False)
                ordering_checks.append(False)
                continue
            decision_checks.append(
                _is_subsequence(expected.required_kinds, observed.decisions)
            )
            expected_tools.extend(expected.required_tools)
            forbidden_tools.extend(expected.forbidden_tools)
            all_actions.extend(observed.actions)
            ordering_checks.append(
                _ordering_constraints_pass(
                    observed.actions,
                    expected.ordering_constraints,
                )
            )
            seen_reads: dict[tuple[str, str], str] = {}
            seen_actions: set[tuple[str, str]] = set()
            for action in observed.actions:
                read_key = (
                    action.tool_name,
                    json.dumps(action.arguments, sort_keys=True),
                )
                if _looks_like_read(action.tool_name) and read_key in seen_reads:
                    previous_outcome = seen_reads[read_key]
                    seen_reads[read_key] = action.outcome
                    if previous_outcome not in {"ok", "empty"}:
                        efficiency_findings.append(
                            TrajectoryEfficiencyFinding(
                                turn_id=expected.turn_id,
                                kind="justified_read",
                                tool_name=action.tool_name,
                                detail="read retried after a failed observation",
                            )
                        )
                    else:
                        unnecessary_actions += 1
                        efficiency_findings.append(
                            TrajectoryEfficiencyFinding(
                                turn_id=expected.turn_id,
                                kind="duplicate_read",
                                tool_name=action.tool_name,
                                detail=(
                                    "identical successful read repeated without "
                                    "a state-changing action"
                                ),
                            )
                        )
                    continue
                if _looks_like_read(action.tool_name):
                    seen_reads[read_key] = action.outcome
                elif read_key in seen_actions:
                    unnecessary_actions += 1
                    efficiency_findings.append(
                        TrajectoryEfficiencyFinding(
                            turn_id=expected.turn_id,
                            kind="redundant_tool_call",
                            tool_name=action.tool_name,
                            detail="identical non-read action was repeated",
                        )
                    )
                    continue
                else:
                    seen_actions.add(read_key)
                if action.tool_name in expected.optional_tools:
                    if _looks_like_read(action.tool_name):
                        efficiency_findings.append(
                            TrajectoryEfficiencyFinding(
                                turn_id=expected.turn_id,
                                kind="justified_read",
                                tool_name=action.tool_name,
                                detail="optional canonical-state read allowed by the case",
                            )
                        )
                elif action.tool_name not in expected.required_tools:
                    unnecessary_actions += 1
                    kind = (
                        "redundant_read"
                        if _looks_like_read(action.tool_name)
                        else "redundant_tool_call"
                    )
                    efficiency_findings.append(
                        TrajectoryEfficiencyFinding(
                            turn_id=expected.turn_id,
                            kind=kind,
                            tool_name=action.tool_name,
                            detail="tool is neither required nor optional for this turn",
                        )
                    )
            if (
                expected.max_reasonable_tool_calls is not None
                and len(observed.actions) > expected.max_reasonable_tool_calls
            ):
                efficiency_findings.append(
                    TrajectoryEfficiencyFinding(
                        turn_id=expected.turn_id,
                        kind="tool_call_budget",
                        count=(
                            len(observed.actions)
                            - expected.max_reasonable_tool_calls
                        ),
                        detail="tool calls exceeded the case's reasonable efficiency budget",
                    )
                )
            referent_checks.append(
                expected.expected_referent_id is None
                or observed.referent_id == expected.expected_referent_id
            )
            clarification_checks.append(
                observed.clarification_requested
                == expected.expected_clarification
            )
            if observed.clarification_requested and not expected.expected_clarification:
                efficiency_findings.append(
                    TrajectoryEfficiencyFinding(
                        turn_id=expected.turn_id,
                        kind="redundant_clarification",
                        detail="clarification was requested for an unambiguous turn",
                    )
                )
            context_checks.append(
                bool(observed.context.included_sections)
                and observed.context.char_count >= 0
            )
            for tool_name, arguments in expected.expected_arguments.items():
                argument_checks.append(
                    any(
                        action.tool_name == tool_name
                        and _contains(action.arguments, arguments)
                        for action in observed.actions
                    )
                )

        actual_tools = [item.tool_name for item in all_actions]
        required_recall = all(tool in actual_tools for tool in expected_tools)
        forbidden_used = [tool for tool in actual_tools if tool in forbidden_tools]
        tool_execution = all(
            item.outcome in set(case.expected.allowed_tool_outcomes)
            for item in all_actions
        )
        expected_termination = case.expected.termination_reason
        actual_termination = observation.turns[-1].termination_reason
        governance = case.expected.governance
        governance_ok = not observation.direct_state_bypass
        if governance.approval_required:
            governance_ok = governance_ok and observation.approval_requested
        if governance.approval_resumed:
            governance_ok = governance_ok and observation.approval_resolved
        if governance.policy_denied:
            governance_ok = governance_ok and observation.policy_denied
        if governance.exactly_once_mutation:
            governance_ok = governance_ok and observation.duplicate_mutations == 0

        state_checks = [
            _get_path(observation.state_after, path) == expected
            for path, expected in _flatten(case.expected.final_state).items()
        ]
        state_checks.extend(
            _get_path(observation.state_before, path)
            == _get_path(observation.state_after, path)
            for path in case.expected.forbidden_mutation_paths
        )
        idempotency_ok = observation.duplicate_mutations == 0
        answers = "\n".join(item.final_answer for item in observation.turns).casefold()
        grounding_ok = all(
            _answer_contains_fact(answers, fact)
            for fact in case.expected.final_answer_facts
        ) and all(
            not _answer_contains_fact(answers, fact)
            for fact in case.expected.forbidden_answer_facts
        )
        state_ok = all(state_checks) if state_checks else True
        arguments_ok = all(argument_checks) if argument_checks else True
        clarification_ok = all(clarification_checks)
        ordering_ok = all(ordering_checks)
        approval_ok = (
            not governance.approval_resumed or observation.approval_resolved
        )
        step_budget_ok = (
            observation.agent_steps <= case.expected.max_agent_steps
            and observation.tool_calls <= case.expected.max_tool_calls
            and actual_termination == expected_termination
        )
        constraint_ok = all(
            (
                required_recall,
                not forbidden_used,
                ordering_ok,
                arguments_ok,
                clarification_ok,
                governance_ok,
                approval_ok,
                tool_execution,
                state_ok,
                idempotency_ok,
            )
        )
        degraded_kinds = {
            "redundant_read",
            "duplicate_read",
            "redundant_clarification",
            "redundant_tool_call",
            "tool_call_budget",
        }
        efficiency_ok = not any(
            item.kind in degraded_kinds for item in efficiency_findings
        )

        checks = [
            ("context_selection", all(context_checks), context_checks),
            ("referent_accuracy", all(referent_checks), referent_checks),
            ("decision_correctness", all(decision_checks), decision_checks),
            (
                "capability_selection",
                required_recall and not forbidden_used,
                actual_tools,
            ),
            ("required_tool_recall", required_recall, actual_tools),
            ("forbidden_tool_compliance", not forbidden_used, forbidden_used),
            (
                "unnecessary_tool_compliance",
                unnecessary_actions == 0,
                unnecessary_actions,
            ),
            (
                "trajectory_constraint_compliance",
                constraint_ok,
                ordering_checks,
            ),
            (
                "trajectory_efficiency",
                efficiency_ok,
                [item.model_dump(mode="json") for item in efficiency_findings],
            ),
            (
                "argument_correctness",
                arguments_ok,
                argument_checks,
            ),
            (
                "clarification_accuracy",
                clarification_ok,
                clarification_checks,
            ),
            ("governance_compliance", governance_ok, None),
            (
                "approval_resume",
                approval_ok,
                observation.approval_resolved,
            ),
            ("tool_execution", tool_execution, [item.outcome for item in all_actions]),
            (
                "state_mutation",
                state_ok,
                state_checks,
            ),
            (
                "durable_recovery",
                not case.process_boundary or observation.durable_reloaded,
                observation.durable_reloaded,
            ),
            (
                "idempotency_safety",
                idempotency_ok,
                observation.duplicate_mutations,
            ),
            (
                "memory_update",
                case.family not in {"memory_update", "memory_strong_override"}
                or (all(state_checks) if state_checks else True),
                state_checks,
            ),
            ("grounding", grounding_ok, answers),
            (
                "step_budget",
                step_budget_ok,
                {
                    "steps": observation.agent_steps,
                    "tools": observation.tool_calls,
                    "termination": actual_termination,
                },
            ),
            ("schema_validity", observation.schema_valid, observation.schema_valid),
        ]
        for name, passed, value in checks:
            metrics.append(
                StatefulMetricResult(
                    name=name,
                    passed=passed,
                    value=value,
                    failure_layer=(None if passed else _METRIC_LAYERS.get(name)),
                    detail="passed" if passed else f"{name} failed",
                )
            )
        task_success = all(
            item.passed
            for item in metrics
            if item.name in _TASK_CORRECTNESS_METRICS
        )
        failures = [
            item.failure_layer
            for item in metrics
            if (
                item.name in _TASK_CORRECTNESS_METRICS
                and not item.passed
                and item.failure_layer is not None
            )
        ]
        return StatefulCaseReport(
            case_id=case.case_id,
            passed=task_success,
            task_success=task_success,
            constraint_compliant=constraint_ok,
            efficiency_passed=efficiency_ok,
            metrics=metrics,
            efficiency_findings=efficiency_findings,
            primary_failure_layer=failures[0] if failures else None,
            secondary_failure_layers=list(dict.fromkeys(failures[1:])),
            agent_steps=observation.agent_steps,
            tool_calls=observation.tool_calls,
            input_tokens=observation.input_tokens,
            output_tokens=observation.output_tokens,
        )

    def artifact(
        self,
        *,
        run_id: str,
        dataset: StatefulEvalDataset,
        observations: Sequence[StatefulCaseObservation],
        git_commit: str,
        provider_role: Literal[
            "production_acceptance",
            "development_smoke",
            "deterministic_regression",
        ],
    ) -> StatefulEvalArtifact:
        by_id = {item.case_id: item for item in observations}
        reports = [self.evaluate(case, by_id[case.case_id]) for case in dataset.cases]
        metrics = aggregate_metrics(reports, observations)
        failures = [
            {
                "case_id": report.case_id,
                "primary_failure_layer": report.primary_failure_layer,
                "secondary_failure_layers": report.secondary_failure_layers,
                "failed_metrics": [
                    {
                        "name": metric.name,
                        "value": metric.value,
                        "detail": metric.detail,
                    }
                    for metric in report.metrics
                    if (
                        metric.name in _TASK_CORRECTNESS_METRICS
                        and not metric.passed
                    )
                ],
            }
            for report in reports
            if not report.passed
        ]
        efficiency_findings = [
            {
                "case_id": report.case_id,
                "efficiency_passed": report.efficiency_passed,
                "findings": [
                    item.model_dump(mode="json")
                    for item in report.efficiency_findings
                ],
            }
            for report in reports
            if report.efficiency_findings
        ]
        first = observations[0]
        return StatefulEvalArtifact(
            run_id=run_id,
            provider=first.provider,
            model=first.model,
            provider_role=provider_role,
            dataset_version=dataset.dataset_version,
            timestamp=datetime.now(UTC).isoformat(),
            git_commit=git_commit,
            metrics=metrics,
            cases=reports,
            observations=list(observations),
            failures=failures,
            efficiency_findings=efficiency_findings,
        )


def load_stateful_eval_dataset(path: Path | str) -> StatefulEvalDataset:
    return StatefulEvalDataset.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def write_stateful_eval_artifact(
    artifact: StatefulEvalArtifact,
    path: Path | str,
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    StatefulEvalArtifact.model_validate_json(destination.read_text(encoding="utf-8"))
    return destination


def aggregate_metrics(
    reports: Sequence[StatefulCaseReport],
    observations: Sequence[StatefulCaseObservation],
) -> StatefulAggregateMetrics:
    if not reports or len(reports) != len(observations):
        raise ValueError("reports and observations must be non-empty and aligned")
    names = {
        "constraint_compliance": "trajectory_constraint_compliance",
        "trajectory_efficiency": "trajectory_efficiency",
        "decision_correctness": "decision_correctness",
        "capability_selection_accuracy": "capability_selection",
        "required_tool_recall": "required_tool_recall",
        "argument_correctness": "argument_correctness",
        "referent_accuracy": "referent_accuracy",
        "clarification_accuracy": "clarification_accuracy",
        "governance_compliance": "governance_compliance",
        "state_mutation_accuracy": "state_mutation",
        "cross_session_recovery": "durable_recovery",
        "idempotency_safety": "idempotency_safety",
        "grounding_accuracy": "grounding",
        "step_budget_compliance": "step_budget",
        "schema_validity": "schema_validity",
    }

    def rate(metric_name: str) -> float:
        values = [
            next(item.passed for item in report.metrics if item.name == metric_name)
            for report in reports
        ]
        return sum(values) / len(values)

    total_actions = sum(observation.tool_calls for observation in observations)
    forbidden_actions = sum(
        len(
            next(
                item.value
                for item in report.metrics
                if item.name == "forbidden_tool_compliance"
            )
        )
        for report in reports
    )
    unnecessary_actions = sum(
        next(
            item.value
            for item in report.metrics
            if item.name == "unnecessary_tool_compliance"
        )
        for report in reports
    )
    values = {field: rate(metric) for field, metric in names.items()}
    count = len(reports)
    successful_tasks = sum(report.task_success for report in reports)
    input_tokens = sum(item.input_tokens for item in observations)
    context_chars = [
        turn.context.char_count
        for observation in observations
        for turn in observation.turns
    ]
    return StatefulAggregateMetrics(
        case_count=count,
        task_success_rate=successful_tasks / count,
        forbidden_tool_rate=(
            forbidden_actions / total_actions if total_actions else 0.0
        ),
        unnecessary_tool_rate=(
            unnecessary_actions / total_actions if total_actions else 0.0
        ),
        average_agent_steps=sum(item.agent_steps for item in observations) / count,
        average_tool_calls=sum(item.tool_calls for item in observations) / count,
        average_clarification_turns=(
            sum(item.clarification_turns for item in observations) / count
        ),
        average_context_chars_per_turn=(
            sum(context_chars) / len(context_chars) if context_chars else 0.0
        ),
        input_tokens_per_case=input_tokens / count,
        input_tokens_per_successful_task=(
            input_tokens / successful_tasks if successful_tasks else 0.0
        ),
        model_calls=sum(item.model_calls for item in observations),
        input_tokens=input_tokens,
        output_tokens=sum(item.output_tokens for item in observations),
        **values,
    )


def _contains(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(key in actual and actual[key] == value for key, value in expected.items())


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, Mapping):
            flattened.update(_flatten(item, path))
        else:
            flattened[path] = item
    return flattened


def _get_path(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current
