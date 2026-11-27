from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Sequence

import pytest
from pydantic import Field

from job_agent.agent_runtime import (
    AgentAction,
    AgentFinish,
    AgentInputRequest,
    AgentLoopConfig,
    AgentLoopTerminationReason,
    AgentTurn,
    ApprovalDecision,
    ContextPurpose,
    DeepSeekAPIProvider,
    InMemoryConversationStateStore,
    InMemoryTrajectory,
    JsonCheckpointStore,
    NaturalLanguageAgentLoop,
    ReferentEntityType,
    ReferentRef,
    ReferentResolutionStatus,
    ReferentResolver,
    ScriptedAgentDecisionProvider,
    StructuredAgentDecisionProvider,
    ToolContext,
    ToolEffect,
    UserInputRequest,
)
from job_agent.agent_runtime.events import (
    ModelDecisionEvent,
    PolicyDecisionEvent,
    RunFinishedEvent,
    ToolObservedEvent,
)
from job_agent.agent_runtime.failures import ToolRetryableError
from job_agent.agent_runtime.interaction_context import ContextProjector
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.stateful_evaluation import (
    ContextProjectionMetadata,
    FailureLayer,
    ObservedAction,
    StatefulAgentEvalCase,
    StatefulAgentEvaluator,
    StatefulCaseObservation,
    TurnEvalObservation,
    load_stateful_eval_dataset,
    write_stateful_eval_artifact,
)
from job_agent.agent_runtime.tool_registry import RegisteredTool, ToolRegistry
from job_agent.career.durable import DurableCareerRepository
from job_agent.career.runtime_tools import (
    READ_CAREER_STATE_TOOL,
    build_durable_career_registry,
)
from job_agent.domain_agents.application_ops import (
    APPLY_TRANSITION_TOOL,
    READ_TRACKER_TOOL,
    build_application_ops_registry,
)
from job_agent.domain_agents.application_tracking import (
    RECORD_APPLICATION_TOOL,
    build_application_tracking_registry,
)
from job_agent.llm.harness import NodePolicy
from job_agent.llm.providers.transformers import LocalTransformersProvider
from job_agent.memory.contracts import MemoryRecord, MemorySource, UserState
from job_agent.memory.tools import (
    UPDATE_JOB_LOCATION_PREFERENCE_TOOL,
    build_memory_tool_registry,
)
from job_agent.memory.user_state_store import UserStateStore
from job_agent.schemas import ApplicationStatus, StrictModel
from job_agent.tools.application_tracker import ApplicationTrackerStore


ROOT = Path(__file__).resolve().parents[1]
DEV_DATASET = ROOT / "eval/stateful_agent/dev/cases.json"
FROZEN_DATASET = ROOT / "eval/stateful_agent/test/cases.json"
USER_ID = "eval-user"
ANALYZE_JOB_TOOL = "career.analyze_job"


class AnalyzeJobInput(StrictModel):
    job_id: str = Field(min_length=1)


class AnalyzeJobOutput(StrictModel):
    job_id: str
    preference: dict[str, Any]
    evidence: list[str]
    gaps: list[str]


def _merge(target: ToolRegistry, source: ToolRegistry) -> None:
    for name in source.names():
        target.register_tool(source.get(name))


def _action(action_id: str, tool_name: str, arguments: dict[str, Any]) -> AgentAction:
    return AgentAction(
        action_id=action_id,
        tool_name=tool_name,
        tool_arguments=arguments,
        expected_observation="structured governed state",
        progress_claim=f"use {tool_name} through Runtime",
    )


def _finish(facts: Sequence[str]) -> AgentFinish:
    answer = "; ".join(facts) if facts else "completed"
    return AgentFinish(
        result={"answer": answer},
        completion_evidence=["runtime_observation_or_user_request"],
        confidence=1.0,
    )


class StatefulScenarioEnvironment:
    def __init__(self, root: Path, case: StatefulAgentEvalCase) -> None:
        self.root = root
        self.case = case
        self.repository = DurableCareerRepository.open(root / "career")
        self.tracker = ApplicationTrackerStore(root / "tracker.json")
        self.memory = UserStateStore(root / "memory.json")
        self.conversation = InMemoryConversationStateStore()
        self.trajectory = InMemoryTrajectory()
        self.fail_read_once = case.family == "tool_failure_recovery"
        self._seed()
        if case.process_boundary:
            self.repository.close()
            self.repository = DurableCareerRepository.open(root / "career")
            self.conversation = InMemoryConversationStateStore()
        self.registry = self._registry()

    def _seed(self) -> None:
        memory = self.case.initial.memory
        memories = []
        if memory.preferred_city:
            memories.append(
                MemoryRecord(
                    memory_id="memory-location-v1",
                    user_id=USER_ID,
                    kind="preference",
                    key="job_location",
                    value={
                        "preferred_city": memory.preferred_city,
                        "acceptable_cities": memory.acceptable_cities,
                    },
                    content=f"preferred city: {memory.preferred_city}",
                    source=MemorySource.USER_STATED,
                    confidence=1.0,
                    created_at="2026-09-19T00:00:00+00:00",
                    updated_at="2026-09-19T00:00:00+00:00",
                )
            )
        self.memory.save(
            user_id=USER_ID,
            state=UserState(
                user_id=USER_ID,
                preferences={
                    **(
                        {"preferred_city": memory.preferred_city}
                        if memory.preferred_city
                        else {}
                    ),
                    "acceptable_cities": memory.acceptable_cities,
                },
                memories=memories,
            ),
            expected_version=1,
        )
        for job in self.case.initial.jobs:
            durable = self.repository.save_job(
                job_id=job.job_id,
                company=job.company,
                title=job.title,
                location=job.location,
                job_type=job.job_type,
                source_type="eval_fixture",
            )
            jd = self.repository.append_jd_snapshot(
                job_id=job.job_id,
                text=job.jd_text or f"{job.title}: Agent Runtime role.",
                created_by="stateful_eval_fixture",
            )
            if job.gaps or job.strengths:
                self.repository.append_analysis_snapshot(
                    job_id=job.job_id,
                    jd_snapshot_id=jd.snapshot_id,
                    analysis={
                        "requirements": [
                            {
                                "text": gap,
                                "status": "gap",
                                "evidence": [],
                            }
                            for gap in job.gaps
                        ],
                        "summary": {
                            "evidence_backed_strengths": job.strengths,
                            "gaps": job.gaps,
                        },
                    },
                    producer_run_id=f"seed-analysis-{job.job_id}",
                    model_metadata={"provider": "fixture"},
                )
            if job.application_id:
                application = self.tracker.record_application(
                    user_id=USER_ID,
                    job_id=job.job_id,
                    company=job.company,
                    title=job.title,
                    city=job.location or "unknown",
                    source="eval_fixture",
                    url="",
                    initial_status=ApplicationStatus(job.application_stage),
                    notes="stateful eval fixture",
                    user_confirmed=True,
                )
                assert application.id == job.application_id
                self.repository.link_application(
                    job_id=job.job_id,
                    application_id=application.id,
                )
        for setup in self.case.initial.conversations:
            if setup.current_job_id:
                self.conversation.record_referent(
                    setup.session_id,
                    ReferentRef(
                        entity_type=ReferentEntityType.JOB,
                        entity_id=setup.current_job_id,
                        source_turn_id="fixture",
                    ),
                )
            if setup.current_application_id:
                self.conversation.record_referent(
                    setup.session_id,
                    ReferentRef(
                        entity_type=ReferentEntityType.APPLICATION,
                        entity_id=setup.current_application_id,
                        source_turn_id="fixture",
                    ),
                )

    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        career = build_durable_career_registry(
            self.repository,
            self.tracker,
            user_id=USER_ID,
        )
        if self.fail_read_once:
            original = career.get(READ_CAREER_STATE_TOOL)
            calls = {"count": 0}

            def flaky_read(value, context):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise ToolRetryableError("synthetic recoverable read failure")
                return original.handler(value, context)

            registry.register_tool(
                RegisteredTool(
                    spec=original.spec,
                    input_model=original.input_model,
                    output_model=original.output_model,
                    handler=flaky_read,
                )
            )
        else:
            _merge(registry, career)
        _merge(registry, build_memory_tool_registry(self.memory, user_id=USER_ID))
        _merge(
            registry,
            build_application_tracking_registry(self.tracker, user_id=USER_ID),
        )
        _merge(registry, build_application_ops_registry(self.tracker, user_id=USER_ID))

        def analyze(value: AnalyzeJobInput, context: ToolContext) -> AnalyzeJobOutput:
            state = self.repository.get_state(value.job_id)
            memory = self.memory.load(user_id=USER_ID)
            acceptable = memory.preferences.get("acceptable_cities", [])
            city = state.job.location
            preferred = memory.preferences.get("preferred_city")
            fit = city == preferred or city in acceptable
            gaps = (
                state.latest_analysis.gaps
                if state.latest_analysis is not None
                else ["Kubernetes production experience"]
            )
            return AnalyzeJobOutput(
                job_id=value.job_id,
                preference={
                    "city": city,
                    "fit": fit,
                    "reason": "acceptable" if city in acceptable else "preferred",
                },
                evidence=["Agent Runtime evidence"],
                gaps=gaps,
            )

        registry.register(
            name=ANALYZE_JOB_TOOL,
            description="Evaluate the selected job with preference, evidence, and gap facts.",
            input_model=AnalyzeJobInput,
            output_model=AnalyzeJobOutput,
            handler=analyze,
            effect=ToolEffect.READ_ONLY,
        )
        return registry

    def snapshot(self) -> dict[str, Any]:
        tracker = self.tracker.load(user_id=USER_ID)
        applications = {
            item.id: {
                "stage": item.current_state.value,
                "job_id": item.job_id,
                "history_count": len(item.state_history),
            }
            for item in tracker.applications
        }
        first = tracker.applications[0] if tracker.applications else None
        memory = self.memory.load(user_id=USER_ID)
        return {
            "application": (
                {
                    "application_id": first.id,
                    "stage": first.current_state.value,
                    "job_id": first.job_id,
                    "history_count": len(first.state_history),
                }
                if first
                else None
            ),
            "applications": applications,
            "memory": {
                "preferred_city": memory.preferences.get("preferred_city"),
                "acceptable_cities": memory.preferences.get(
                    "acceptable_cities", []
                ),
                "history_count": len(memory.memories),
            },
        }

    def scripted_decisions(self, expectation, turn_index: int):
        decisions = []
        action_index = 0
        for kind in expectation.required_kinds:
            if kind == "finish":
                decisions.append(_finish(self.case.expected.final_answer_facts))
                continue
            if kind == "input_request":
                if self.case.family in {"ambiguous_referent", "clarification_resume"}:
                    decisions.append(
                        _action(
                            f"unsafe-{turn_index}",
                            APPLY_TRANSITION_TOOL,
                            {
                                "application_id": "app-001",
                                "new_status": "first_interview",
                                "expected_revision": self.tracker.load(
                                    user_id=USER_ID
                                ).revision,
                            },
                        )
                    )
                else:
                    decisions.append(
                        AgentInputRequest(
                            request=UserInputRequest(
                                request_id=f"clarify-{turn_index}",
                                prompt="请确认目标岗位。",
                                reason="missing_referent",
                                required_fields=["job_id"],
                            ),
                            progress_claim="clarify target",
                        )
                    )
                continue
            tool = self._tool_for_action(expectation, action_index)
            arguments = self._arguments(tool, expectation, action_index)
            decisions.append(_action(f"action-{turn_index}-{action_index}", tool, arguments))
            action_index += 1
        return decisions

    def _tool_for_action(self, expectation, action_index: int) -> str:
        tools = expectation.required_tools
        if (
            self.case.family == "stage_update"
            and len(expectation.required_kinds) == 4
        ):
            return [READ_TRACKER_TOOL, APPLY_TRANSITION_TOOL, APPLY_TRANSITION_TOOL][
                action_index
            ]
        if self.case.family == "tool_failure_recovery":
            return READ_CAREER_STATE_TOOL
        if self.case.family == "step_budget":
            return ANALYZE_JOB_TOOL
        return tools[min(action_index, len(tools) - 1)]

    def _arguments(self, tool: str, expectation, action_index: int) -> dict[str, Any]:
        explicit = dict(expectation.expected_arguments.get(tool, {}))
        job = self.case.initial.jobs[0] if self.case.initial.jobs else None
        tracker = self.tracker.load(user_id=USER_ID)
        application = tracker.applications[0] if tracker.applications else None
        if tool in {ANALYZE_JOB_TOOL, READ_CAREER_STATE_TOOL}:
            return {"job_id": explicit.get("job_id", job.job_id if job else "job-agent")}
        if tool == RECORD_APPLICATION_TOOL:
            return {
                "job_id": job.job_id,
                "title": job.title,
                "company": job.company,
                "city": job.location or "unknown",
                "source": "stateful_eval",
            }
        if tool == READ_TRACKER_TOOL:
            return {"application_id": application.id}
        if tool == APPLY_TRANSITION_TOOL:
            new_status = explicit.get("new_status")
            revision = tracker.revision
            if (
                self.case.family == "stage_update"
                and len(expectation.required_kinds) == 4
            ):
                if action_index == 1:
                    new_status = "resume_screen"
                elif action_index == 2:
                    new_status = "first_interview"
                    revision += 1
            return {
                "application_id": explicit.get("application_id", application.id),
                "new_status": new_status or "applied",
                "expected_revision": revision,
                "notes": "stateful eval user-confirmed transition",
            }
        if tool == UPDATE_JOB_LOCATION_PREFERENCE_TOOL:
            return {
                "add_acceptable_cities": explicit.get("add_acceptable_cities", []),
                "replace_preferred_city": explicit.get("replace_preferred_city"),
                "statement": self.case.turns[0].text,
                "idempotency_key": self.case.turns[0].turn_id,
            }
        return explicit


ProviderFactory = Callable[[Sequence[Any], str, str], Any]


def _scripted_provider(decisions, session_id: str, run_id: str):
    return ScriptedAgentDecisionProvider(decisions)


def _run_case(
    tmp_path: Path,
    case: StatefulAgentEvalCase,
    *,
    provider_factory: ProviderFactory = _scripted_provider,
) -> StatefulCaseObservation:
    environment = StatefulScenarioEnvironment(tmp_path / case.case_id, case)
    before = environment.snapshot()
    turn_observations = []
    approval_requested = False
    approval_resolved = False
    policy_denied = False
    total_steps = 0
    total_tools = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_model_calls = 0
    schema_valid = True
    provider_name = "scripted"
    model_name = "scripted"

    for turn_index, (turn, expectation) in enumerate(
        zip(case.turns, case.expected.decisions), start=1
    ):
        scripted = environment.scripted_decisions(expectation, turn_index)
        provider = provider_factory(scripted, turn.session_id, f"{case.case_id}-{turn.turn_id}")
        allowed = environment.registry.names()
        runtime_allowed = allowed
        if case.family == "policy_deny":
            runtime_allowed = tuple(name for name in allowed if name != APPLY_TRANSITION_TOOL)
        projector = ContextProjector(tracker_store=environment.tracker)
        resolver = ReferentResolver(
            tracker_store=environment.tracker,
            career_repository=environment.repository,
        )
        agent_turn = AgentTurn(
            turn_id=turn.turn_id,
            session_id=turn.session_id,
            user_input=turn.text,
        )
        pre_conversation = environment.conversation.load(turn.session_id)
        projected_referents = resolver.resolve_turn(
            conversation=pre_conversation,
            turn=agent_turn,
            user_id=USER_ID,
        )
        projected_context = projector.project(
            purpose=ContextPurpose.AGENT_DECISION,
            conversation=pre_conversation,
            current_turn=agent_turn,
            user_id=USER_ID,
            user_state=environment.memory.load(user_id=USER_ID),
            policy_summary="Use only registered capabilities and obey approval.",
            remaining_steps=case.expected.max_agent_steps,
        )
        loop = NaturalLanguageAgentLoop(
            provider=provider,
            registry=environment.registry,
            policy_context=PolicyContext(
                skill_allowed_tools=allowed,
                agent_allowed_tools=allowed,
                runtime_allowed_tools=runtime_allowed,
                target_summary="stateful career evaluation",
                arguments_preview_keys=(
                    "job_id",
                    "application_id",
                    "new_status",
                    "add_acceptable_cities",
                    "replace_preferred_city",
                ),
            ),
            conversation_store=environment.conversation,
            context_projector=projector,
            referent_resolver=resolver,
            checkpoint_store=JsonCheckpointStore(
                environment.root / f"{turn.turn_id}.checkpoint.json"
            ),
            trajectory=environment.trajectory,
            config=AgentLoopConfig(max_steps=case.expected.max_agent_steps),
        )
        run_id = f"{case.case_id}-{turn.turn_id}"
        event_start = len(environment.trajectory.events)

        def invoke(*, approvals=None, resume=False):
            return loop.run_turn(
                turn=agent_turn,
                run_id=run_id,
                user_id=USER_ID,
                user_state=environment.memory.load(user_id=USER_ID),
                tool_context=ToolContext(
                    session_id=turn.session_id,
                    run_id=run_id,
                    agent_id="stateful-eval-agent",
                    workspace_root=str(environment.root),
                    sandbox_root=str(environment.root / "sandbox"),
                ),
                policy_summary="Use only registered capabilities and obey approval.",
                approvals=approvals,
                resume=resume,
            )

        try:
            result = invoke()
            last_approval = None
            while result.runtime_result.pending_approval is not None:
                approval_requested = True
                if turn.approval != "approve":
                    break
                request = result.runtime_result.pending_approval
                last_approval = {
                    request.action_digest: ApprovalDecision(
                        request_id=request.request_id,
                        action_digest=request.action_digest,
                        approved=True,
                        session_id=request.session_id,
                        run_id=request.run_id,
                    )
                }
                result = invoke(approvals=last_approval, resume=True)
                approval_resolved = True
            if case.family == "approval_retry" and last_approval is not None:
                history_before = environment.snapshot()["application"]["history_count"]
                duplicate = invoke(approvals=last_approval, resume=True)
                history_after = environment.snapshot()["application"]["history_count"]
                assert duplicate.termination_reason == AgentLoopTerminationReason.FATAL_ERROR
                assert history_before == history_after
        except Exception:
            schema_valid = False
            raise

        events = environment.trajectory.events[event_start:]
        decisions = [
            event.decision.kind
            for event in events
            if isinstance(event, ModelDecisionEvent)
        ]
        if not decisions and result.termination_reason == AgentLoopTerminationReason.FATAL_ERROR:
            schema_valid = False
        actions = []
        for event in events:
            if not isinstance(event, ModelDecisionEvent) or not isinstance(
                event.decision, AgentAction
            ):
                continue
            observed = next(
                (
                    item.observation
                    for item in events
                    if isinstance(item, ToolObservedEvent)
                    and item.observation.action_id == event.decision.action_id
                ),
                None,
            )
            denied = next(
                (
                    item.authorization
                    for item in events
                    if isinstance(item, PolicyDecisionEvent)
                    and item.authorization.action_id == event.decision.action_id
                    and not item.authorization.allowed
                    and not item.authorization.requires_approval
                ),
                None,
            )
            if denied is not None:
                outcome = "denied"
                policy_denied = True
            elif observed is not None:
                outcome = observed.status.value
            elif result.runtime_result.error_code == "tool_registry_error":
                outcome = "unknown_tool"
            else:
                outcome = "not_executed"
            actions.append(
                ObservedAction(
                    tool_name=event.decision.tool_name,
                    arguments=event.decision.tool_arguments,
                    outcome=outcome,
                )
            )
        referent_ids = [
            item.resolution.referent.entity_id
            for item in projected_referents
            if item.resolution.status == ReferentResolutionStatus.RESOLVED
            and item.resolution.referent is not None
        ]
        expected_ref = expectation.expected_referent_id
        referent_id = (
            expected_ref if expected_ref in referent_ids else (referent_ids[0] if referent_ids else None)
        )
        contexts = [projected_context]
        sections = [section for context in contexts for section in context.sections]
        final_event = next(
            (
                event
                for event in reversed(events)
                if isinstance(event, RunFinishedEvent)
            ),
            None,
        )
        final_answer = ""
        if final_event is not None:
            final_answer = str(final_event.result.get("answer", final_event.result))
        terminal = result.termination_reason.value
        turn_observations.append(
            TurnEvalObservation(
                turn_id=turn.turn_id,
                decisions=decisions,
                actions=actions,
                referent_id=referent_id,
                clarification_requested=(
                    result.runtime_result.pending_user_input is not None
                    or "input_request" in decisions
                ),
                final_answer=final_answer,
                termination_reason=terminal,
                context=ContextProjectionMetadata(
                    included_sections=[section.name for section in sections],
                    excluded_sections=sorted(
                        {name for context in contexts for name in context.unavailable}
                    ),
                    sources=[section.source for section in sections],
                    inclusion_reasons=[section.inclusion_reason for section in sections],
                    char_count=sum(section.char_count for section in sections),
                ),
            )
        )
        total_steps += len(decisions)
        total_tools += len(actions)
        traces = getattr(provider, "traces", [])
        total_model_calls += len(traces)
        if traces:
            provider_name = traces[-1].provider
            model_name = traces[-1].model
            total_input_tokens += sum(trace.input_tokens or 0 for trace in traces)
            total_output_tokens += sum(trace.output_tokens or 0 for trace in traces)
            schema_valid = schema_valid and bool(traces[-1].schema_valid)
        else:
            total_input_tokens += result.input_tokens
            total_output_tokens += result.output_tokens

    after = environment.snapshot()
    expected_history = case.expected.final_state.get("application", {}).get(
        "history_count"
    )
    duplicate_mutations = 0
    if expected_history is not None and after.get("application"):
        duplicate_mutations = max(
            after["application"]["history_count"] - expected_history,
            0,
        )
    environment.repository.close()
    return StatefulCaseObservation(
        case_id=case.case_id,
        provider=provider_name,
        model=model_name,
        schema_valid=schema_valid,
        turns=turn_observations,
        state_before=before,
        state_after=after,
        approval_requested=approval_requested,
        approval_resolved=approval_resolved,
        policy_denied=policy_denied,
        direct_state_bypass=False,
        durable_reloaded=case.process_boundary,
        duplicate_mutations=duplicate_mutations,
        agent_steps=total_steps,
        tool_calls=total_tools,
        clarification_turns=sum(item.clarification_requested for item in turn_observations),
        model_calls=total_model_calls,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )


def test_stateful_eval_datasets_are_structured_and_frozen() -> None:
    dev = load_stateful_eval_dataset(DEV_DATASET)
    frozen = load_stateful_eval_dataset(FROZEN_DATASET)
    assert len(dev.cases) == 12
    assert len(frozen.cases) == 18
    assert frozen.frozen is True
    assert {case.family for case in frozen.cases} == {
        "direct_response",
        "job_analysis",
        "contextual_track",
        "cross_session_read",
        "ambiguous_referent",
        "clarification_resume",
        "stage_update",
        "policy_deny",
        "approval_retry",
        "memory_update",
        "memory_strong_override",
        "durable_analysis_reuse",
        "gap_grounding",
        "tool_failure_recovery",
        "unknown_capability",
        "step_budget",
        "stale_context_authority",
        "preference_vs_gap",
    }


def test_failure_attribution_reports_first_layer(tmp_path) -> None:
    case = load_stateful_eval_dataset(FROZEN_DATASET).cases[3]
    observation = StatefulCaseObservation(
        case_id=case.case_id,
        provider="fixture",
        model="fixture",
        turns=[
            TurnEvalObservation(
                turn_id="t1",
                decisions=["finish"],
                referent_id="wrong-job",
                final_answer="unknown",
                context=ContextProjectionMetadata(
                    included_sections=["current_turn"],
                    sources=["AgentTurn"],
                    inclusion_reasons=["current request"],
                    char_count=10,
                ),
            )
        ],
        state_before={"application": {"stage": "applied"}},
        state_after={"application": {"stage": "applied"}},
        durable_reloaded=True,
        agent_steps=1,
    )
    report = StatefulAgentEvaluator().evaluate(case, observation)
    assert report.passed is False
    assert report.primary_failure_layer == FailureLayer.REFERENT_RESOLUTION
    assert FailureLayer.AGENT_DECISION in report.secondary_failure_layers


def test_frozen_stateful_agent_deterministic_eval(tmp_path) -> None:
    dataset = load_stateful_eval_dataset(FROZEN_DATASET)
    observations = [_run_case(tmp_path, case) for case in dataset.cases]
    artifact = StatefulAgentEvaluator().artifact(
        run_id="deterministic-stateful-v1",
        dataset=dataset,
        observations=observations,
        git_commit="working-tree",
        provider_role="deterministic_regression",
    )
    output = write_stateful_eval_artifact(
        artifact,
        tmp_path / "artifacts/eval/stateful_agent/deterministic.json",
    )
    assert output.exists()
    assert artifact.metrics.task_success_rate == 1.0
    assert artifact.metrics.required_tool_recall == 1.0
    assert artifact.metrics.forbidden_tool_rate == 0.0
    assert artifact.metrics.constraint_compliance == 1.0
    assert artifact.metrics.unnecessary_tool_rate > 0.0
    assert artifact.metrics.trajectory_efficiency < 1.0
    assert artifact.metrics.governance_compliance == 1.0
    assert artifact.metrics.cross_session_recovery == 1.0
    assert artifact.metrics.grounding_accuracy == 1.0


def test_redundant_safe_read_degrades_efficiency_not_task_success(tmp_path) -> None:
    case = next(
        item
        for item in load_stateful_eval_dataset(FROZEN_DATASET).cases
        if item.case_id == "frozen-b-job-analysis"
    )
    observation = _run_case(tmp_path, case)
    turn = observation.turns[0].model_copy(
        update={
            "decisions": ["action", "action", "finish"],
            "actions": [
                ObservedAction(
                    tool_name=READ_CAREER_STATE_TOOL,
                    arguments={"job_id": "job-agent"},
                ),
                *observation.turns[0].actions,
            ],
        }
    )
    observation = observation.model_copy(
        update={
            "turns": [turn],
            "agent_steps": observation.agent_steps + 1,
            "tool_calls": observation.tool_calls + 1,
        }
    )
    report = StatefulAgentEvaluator().evaluate(case, observation)
    assert report.task_success is True
    assert report.constraint_compliant is True
    assert report.efficiency_passed is False
    assert any(
        item.kind == "redundant_read" for item in report.efficiency_findings
    )


def test_optional_read_must_respect_ordering_constraint(tmp_path) -> None:
    case = next(
        item
        for item in load_stateful_eval_dataset(FROZEN_DATASET).cases
        if item.case_id == "frozen-c-contextual-track"
    )
    observation = _run_case(tmp_path, case)
    second = observation.turns[1]
    read = ObservedAction(
        tool_name=READ_CAREER_STATE_TOOL,
        arguments={"job_id": "job-agent"},
    )
    ordered = second.model_copy(
        update={
            "decisions": ["action", "action", "finish"],
            "actions": [read, *second.actions],
        }
    )
    ordered_observation = observation.model_copy(
        update={
            "turns": [observation.turns[0], ordered],
            "agent_steps": observation.agent_steps + 1,
            "tool_calls": observation.tool_calls + 1,
        }
    )
    ordered_report = StatefulAgentEvaluator().evaluate(case, ordered_observation)
    assert ordered_report.task_success is True
    assert ordered_report.constraint_compliant is True
    assert ordered_report.efficiency_passed is True
    assert any(
        item.kind == "justified_read"
        for item in ordered_report.efficiency_findings
    )

    reversed_turn = ordered.model_copy(
        update={"actions": [*second.actions, read]}
    )
    reversed_observation = ordered_observation.model_copy(
        update={"turns": [observation.turns[0], reversed_turn]}
    )
    reversed_report = StatefulAgentEvaluator().evaluate(
        case,
        reversed_observation,
    )
    assert reversed_report.task_success is False
    assert reversed_report.constraint_compliant is False
    assert reversed_report.primary_failure_layer == FailureLayer.AGENT_DECISION


def test_grounding_accepts_explicit_chinese_equivalents(tmp_path) -> None:
    case = next(
        item
        for item in load_stateful_eval_dataset(FROZEN_DATASET).cases
        if item.case_id == "frozen-b-job-analysis"
    )
    observation = _run_case(tmp_path, case)
    turn = observation.turns[0].model_copy(
        update={
            "final_answer": "岗位在杭州；已有证据；Kubernetes 是待补短板。"
        }
    )
    observation = observation.model_copy(update={"turns": [turn]})
    report = StatefulAgentEvaluator().evaluate(case, observation)
    grounding = next(item for item in report.metrics if item.name == "grounding")
    assert grounding.passed is True


class _LocalChatRunner:
    def __init__(self, model_path: str, *, max_new_tokens: int = 1200) -> None:
        self.model_path = model_path
        self.max_new_tokens = max_new_tokens
        self._tokenizer = None
        self._model = None

    def _load(self):
        if self._tokenizer is not None:
            return self._tokenizer, self._model
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            trust_remote_code=True,
            local_files_only=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            trust_remote_code=True,
            local_files_only=True,
        )
        if torch.cuda.is_available():
            model = model.to("cuda")
        model.eval()
        self._tokenizer = tokenizer
        self._model = model
        return tokenizer, model

    def generate(self, prompt: str) -> str:
        tokenizer, model = self._load()
        text = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(text, return_tensors="pt")
        device = next(model.parameters()).device
        inputs = {name: value.to(device) for name, value in inputs.items()}
        output_ids = model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
        )
        generated = output_ids[0][inputs["input_ids"].shape[-1] :]
        raw_output = tokenizer.decode(generated, skip_special_tokens=True).strip()
        if os.getenv("DEBUG_STATEFUL_RAW_MODEL") == "1":
            print("LOCAL_QWEN_RAW_OUTPUT=" + raw_output[:2000])
        return raw_output


def _real_case_ids() -> set[str]:
    return {
        "frozen-a-direct-response",
        "frozen-b-job-analysis",
        "frozen-c-contextual-track",
        "frozen-d-cross-session-read",
        "frozen-e-ambiguous-referent",
        "frozen-f-clarification-resume",
        "frozen-g-stage-update",
        "frozen-h-policy-deny",
        "frozen-j-memory-update",
        "frozen-l-durable-analysis-reuse",
        "frozen-m-gap-grounding",
    }


def _run_real_subset(tmp_path, provider_factory, *, provider_label: str):
    dataset = load_stateful_eval_dataset(FROZEN_DATASET)
    selected = [case for case in dataset.cases if case.case_id in _real_case_ids()]
    subset = dataset.model_copy(update={"cases": selected})
    observations = []
    failures = []
    for case in selected:
        try:
            observations.append(
                _run_case(tmp_path / provider_label, case, provider_factory=provider_factory)
            )
        except Exception as exc:
            failures.append((case.case_id, type(exc).__name__, str(exc)))
    if failures:
        pytest.fail("real stateful eval execution failures: " + repr(failures))
    artifact = StatefulAgentEvaluator().artifact(
        run_id=f"{provider_label}-stateful-v1",
        dataset=subset,
        observations=observations,
        git_commit="working-tree",
        provider_role=(
            "production_acceptance"
            if provider_label == "deepseek"
            else "development_smoke"
        ),
    )
    write_stateful_eval_artifact(
        artifact,
        tmp_path / "artifacts/eval/stateful_agent" / f"{provider_label}.json",
    )
    print(
        f"{provider_label.upper()}_STATEFUL_EVAL="
        + json.dumps(artifact.metrics.model_dump(mode="json"), sort_keys=True)
    )
    print(
        f"{provider_label.upper()}_STATEFUL_FAILURES="
        + json.dumps(artifact.failures, ensure_ascii=False, sort_keys=True)
    )
    return artifact


@pytest.mark.skipif(
    os.getenv("RUN_DEEPSEEK_STATEFUL_EVAL") != "1" or not os.getenv("API_KEY"),
    reason="explicit DeepSeek stateful eval opt-in and API_KEY are required",
)
def test_deepseek_stateful_frozen_acceptance(tmp_path) -> None:
    def factory(decisions, session_id, run_id):
        return DeepSeekAPIProvider.from_env(
            session_id=session_id,
            run_id=run_id,
            policy=NodePolicy(
                timeout_s=60,
                max_retries=0,
                max_schema_repairs=1,
                temperature=0.0,
                max_output_tokens=1200,
                allow_rule_fallback=False,
            ),
        )

    artifact = _run_real_subset(tmp_path, factory, provider_label="deepseek")
    assert artifact.metrics.case_count == 11
    assert artifact.metrics.task_success_rate == 1.0
    assert artifact.metrics.constraint_compliance == 1.0
    assert artifact.metrics.capability_selection_accuracy == 1.0
    assert artifact.metrics.argument_correctness == 1.0
    assert artifact.metrics.referent_accuracy == 1.0
    assert artifact.metrics.clarification_accuracy == 1.0
    assert artifact.metrics.governance_compliance == 1.0
    assert artifact.metrics.state_mutation_accuracy == 1.0
    assert artifact.metrics.cross_session_recovery == 1.0
    assert artifact.metrics.grounding_accuracy == 1.0


@pytest.mark.skipif(
    os.getenv("RUN_LOCAL_STATEFUL_EVAL") != "1"
    or not os.getenv("QWEN2_5_MODEL_PATH"),
    reason="explicit local stateful eval opt-in and model path are required",
)
def test_local_qwen_stateful_eval(tmp_path) -> None:
    runner = _LocalChatRunner(os.environ["QWEN2_5_MODEL_PATH"])

    def factory(decisions, session_id, run_id):
        return StructuredAgentDecisionProvider.from_local_transformers(
            provider=LocalTransformersProvider(
                runner=runner,
                model="Qwen2.5-7B-Instruct",
            ),
            session_id=session_id,
            run_id=run_id,
            policy=NodePolicy(
                timeout_s=240,
                max_retries=0,
                max_schema_repairs=1,
                temperature=0.0,
                max_output_tokens=1200,
                allow_rule_fallback=False,
            ),
        )

    artifact = _run_real_subset(tmp_path, factory, provider_label="local_qwen")
    assert artifact.metrics.case_count == 11
    assert artifact.metrics.idempotency_safety == 1.0
    for observation in artifact.observations:
        if observation.schema_valid:
            continue
        assert observation.tool_calls == 0
        assert observation.state_after == observation.state_before
        assert all(
            turn.termination_reason == AgentLoopTerminationReason.FATAL_ERROR.value
            for turn in observation.turns
        )
