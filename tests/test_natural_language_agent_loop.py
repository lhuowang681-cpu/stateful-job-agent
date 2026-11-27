from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import Field

from job_agent.agent_runtime import (
    AgentAction,
    AgentContextProjection,
    AgentDecisionContext,
    AgentFinish,
    AgentInputRequest,
    AgentLoopConfig,
    AgentLoopTerminationReason,
    AgentObservation,
    AgentObservationOutcome,
    AgentTurn,
    ApprovalDecision,
    CapabilityCatalogEntry,
    ContextPurpose,
    DeepSeekAPIProvider,
    InMemoryConversationStateStore,
    JsonCheckpointStore,
    NaturalLanguageAgentLoop,
    ReferentEntityType,
    ReferentRef,
    ReferentResolution,
    ReferentResolutionStatus,
    ReferentResolver,
    ScriptedAgentDecisionProvider,
    StructuredAgentDecisionProvider,
    ToolContext,
    ToolEffect,
    TurnReferentResolution,
)
from job_agent.agent_runtime.interaction_context import ContextProjector
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.domain_agents.application_ops import (
    APPLY_TRANSITION_TOOL,
    READ_TRACKER_TOOL,
    build_application_ops_registry,
)
from job_agent.domain_agents.application_tracking import (
    RECORD_APPLICATION_TOOL,
    build_application_tracking_registry,
)
from job_agent.llm.harness import LLMInvocationError, NodePolicy
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.providers.transformers import LocalTransformersProvider
from job_agent.memory.contracts import UserState
from job_agent.schemas import ApplicationStatus, RawJob, StrictModel
from job_agent.tools.application_tracker import ApplicationTrackerStore


USER_ID = "user-1"
SESSION_ID = "session-1"
ANALYZE_JOB_TOOL = "career.analyze_job"
INTERVIEW_PREP_TOOL = "interview.prepare"


class AnalyzeJobInput(StrictModel):
    job_id: str = Field(min_length=1)


class AnalyzeJobOutput(StrictModel):
    job_id: str
    summary: str


class InterviewPrepInput(StrictModel):
    application_id: str = Field(min_length=1)


class InterviewPrepOutput(StrictModel):
    application_id: str
    focus: list[str]


def _job(job_id: str, title: str, company: str = "Example AI") -> RawJob:
    return RawJob(
        job_id=job_id,
        company=company,
        title=title,
        desc="Build governed Agent Runtime and MCP retrieval systems.",
        url=f"https://example.test/{job_id}",
        location="杭州",
        source="fixture",
        job_type="internship",
        fetched_at="2026-09-19T10:00:00+00:00",
    )


def _finish(answer: str = "done") -> AgentFinish:
    return AgentFinish(
        result={"answer": answer},
        completion_evidence=["structured-runtime-observation"],
        confidence=0.9,
    )


def _action(
    action_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> AgentAction:
    return AgentAction(
        action_id=action_id,
        tool_name=tool_name,
        tool_arguments=arguments,
        expected_observation="structured governed result",
        progress_claim=f"use {tool_name} through the governed runtime",
    )


def _merge_tool(registry: ToolRegistry, source: ToolRegistry, name: str) -> None:
    registry.register_tool(source.get(name))


def _registry(
    tracker: ApplicationTrackerStore,
    calls: dict[str, int],
) -> ToolRegistry:
    registry = ToolRegistry()
    tracking = build_application_tracking_registry(tracker, user_id=USER_ID)
    ops = build_application_ops_registry(tracker, user_id=USER_ID)
    _merge_tool(registry, tracking, RECORD_APPLICATION_TOOL)
    _merge_tool(registry, ops, READ_TRACKER_TOOL)
    _merge_tool(registry, ops, APPLY_TRANSITION_TOOL)

    def analyze(value: AnalyzeJobInput, context: ToolContext) -> AnalyzeJobOutput:
        calls[ANALYZE_JOB_TOOL] += 1
        return AnalyzeJobOutput(
            job_id=value.job_id,
            summary="The role matches governed Agent Runtime and MCP work.",
        )

    def prepare(
        value: InterviewPrepInput,
        context: ToolContext,
    ) -> InterviewPrepOutput:
        calls[INTERVIEW_PREP_TOOL] += 1
        return InterviewPrepOutput(
            application_id=value.application_id,
            focus=["Agent Runtime", "MCP", "retrieval provenance"],
        )

    registry.register(
        name=ANALYZE_JOB_TOOL,
        description="Analyze one selected job through the existing evidence workflow facade.",
        input_model=AnalyzeJobInput,
        output_model=AnalyzeJobOutput,
        handler=analyze,
        effect=ToolEffect.READ_ONLY,
    )
    registry.register(
        name=INTERVIEW_PREP_TOOL,
        description="Build interview preparation for one tracked application.",
        input_model=InterviewPrepInput,
        output_model=InterviewPrepOutput,
        handler=prepare,
        effect=ToolEffect.READ_ONLY,
    )
    return registry


def _record_application(
    tracker: ApplicationTrackerStore,
    *,
    job_id: str,
    title: str,
    company: str = "Example AI",
):
    return tracker.record_application(
        user_id=USER_ID,
        job_id=job_id,
        company=company,
        title=title,
        city="杭州",
        source="fixture",
        url=f"https://example.test/{job_id}",
        initial_status=ApplicationStatus.TO_APPLY,
        notes="",
        user_confirmed=True,
    )


def _build_loop(
    tmp_path: Path,
    decisions,
    *,
    tracker: ApplicationTrackerStore | None = None,
    conversation: InMemoryConversationStateStore | None = None,
    jobs: tuple[RawJob, ...] | None = None,
    runtime_allowed: tuple[str, ...] | None = None,
    config: AgentLoopConfig | None = None,
):
    tracker = tracker or ApplicationTrackerStore(tmp_path / "tracker.json")
    conversation = conversation or InMemoryConversationStateStore()
    jobs = jobs or (
        _job("job-agent", "Agent Intern"),
        _job("job-infra", "AI Infra Intern"),
    )
    calls = {ANALYZE_JOB_TOOL: 0, INTERVIEW_PREP_TOOL: 0}
    registry = _registry(tracker, calls)
    allowed = registry.names()
    provider = ScriptedAgentDecisionProvider(decisions)
    loop = NaturalLanguageAgentLoop(
        provider=provider,
        registry=registry,
        policy_context=PolicyContext(
            skill_allowed_tools=allowed,
            agent_allowed_tools=allowed,
            runtime_allowed_tools=allowed if runtime_allowed is None else runtime_allowed,
            target_summary="career agent core capabilities",
            arguments_preview_keys=(
                "job_id",
                "application_id",
                "company",
                "title",
                "new_status",
            ),
        ),
        conversation_store=conversation,
        context_projector=ContextProjector(tracker_store=tracker),
        referent_resolver=ReferentResolver(
            tracker_store=tracker,
            jobs=jobs,
        ),
        checkpoint_store=JsonCheckpointStore(tmp_path / "agent.checkpoint"),
        config=config,
    )
    return loop, provider, tracker, conversation, jobs, calls


def _run(
    loop: NaturalLanguageAgentLoop,
    turn: AgentTurn,
    tmp_path: Path,
    *,
    run_id: str = "run-1",
    resume: bool = False,
    approvals=None,
):
    return loop.run_turn(
        turn=turn,
        run_id=run_id,
        user_id=USER_ID,
        user_state=UserState(
            user_id=USER_ID,
            preferences={"preferred_city": "杭州", "target_role": "Agent"},
        ),
        tool_context=ToolContext(
            session_id=turn.session_id,
            run_id=run_id,
            agent_id="natural-language-agent",
            workspace_root=str(tmp_path),
            sandbox_root=str(tmp_path / "sandbox"),
        ),
        policy_summary="All actions must use registered tools and Runtime policy.",
        approvals=approvals,
        resume=resume,
    )


def _approval(result) -> dict[str, ApprovalDecision]:
    request = result.runtime_result.pending_approval
    assert request is not None
    return {
        request.action_digest: ApprovalDecision(
            request_id=request.request_id,
            action_digest=request.action_digest,
            approved=True,
            session_id=request.session_id,
            run_id=request.run_id,
        )
    }


def test_job_analysis_runs_as_governed_action_then_finish(tmp_path) -> None:
    turn = AgentTurn(
        turn_id="turn-analysis",
        session_id=SESSION_ID,
        user_input="帮我看看这个杭州 Agent 实习岗位。",
    )
    loop, provider, _, conversation, _, calls = _build_loop(
        tmp_path,
        [
            _action("analyze-1", ANALYZE_JOB_TOOL, {"job_id": "job-agent"}),
            _finish("analysis complete"),
        ],
    )
    conversation.record_referent(
        SESSION_ID,
        ReferentRef(
            entity_type=ReferentEntityType.JOB,
            entity_id="job-agent",
            source_turn_id="turn-selection",
            display_hint="Example AI — Agent Intern",
        ),
    )

    result = _run(loop, turn, tmp_path)

    assert result.termination_reason == AgentLoopTerminationReason.FINISHED
    assert calls[ANALYZE_JOB_TOOL] == 1
    assert provider.calls[0].capabilities
    analyze_capability = next(
        item for item in provider.calls[0].capabilities if item.name == ANALYZE_JOB_TOOL
    )
    assert analyze_capability.effect == ToolEffect.READ_ONLY.value
    assert "job_id" in analyze_capability.input_schema["properties"]
    assert provider.calls[1].observations[0].outcome == AgentObservationOutcome.SUCCEEDED
    assert result.context_char_counts and max(result.context_char_counts) < 50_000


def test_contextual_tracking_waits_for_approval_and_resume_writes_once(tmp_path) -> None:
    turn = AgentTurn(
        turn_id="turn-track",
        session_id=SESSION_ID,
        user_input="这个还行，记一下。",
    )
    loop, _, tracker, conversation, _, _ = _build_loop(
        tmp_path,
        [
            _action(
                "track-1",
                RECORD_APPLICATION_TOOL,
                {
                    "job_id": "job-agent",
                    "title": "Agent Intern",
                    "company": "Example AI",
                    "city": "杭州",
                    "source": "fixture",
                    "jd_reference": "https://example.test/job-agent",
                },
            ),
            _finish("application recorded"),
        ],
    )
    conversation.record_referent(
        SESSION_ID,
        ReferentRef(
            entity_type=ReferentEntityType.JOB,
            entity_id="job-agent",
            source_turn_id="turn-analysis",
            display_hint="Example AI — Agent Intern",
        ),
    )

    pending = _run(loop, turn, tmp_path)
    assert pending.termination_reason == AgentLoopTerminationReason.WAITING_FOR_APPROVAL
    assert (
        pending.terminal_observation.outcome
        == AgentObservationOutcome.WAITING_FOR_APPROVAL
    )
    assert tracker.load(user_id=USER_ID).applications == []

    completed = _run(
        loop,
        turn,
        tmp_path,
        resume=True,
        approvals=_approval(pending),
    )
    assert completed.termination_reason == AgentLoopTerminationReason.FINISHED
    assert len(tracker.load(user_id=USER_ID).applications) == 1

    duplicate = _run(
        loop,
        turn,
        tmp_path,
        resume=True,
        approvals=_approval(pending),
    )
    assert duplicate.termination_reason == AgentLoopTerminationReason.FATAL_ERROR
    assert duplicate.runtime_result.error_code == "checkpoint_not_found"
    assert len(tracker.load(user_id=USER_ID).applications) == 1


def test_application_update_is_resolved_then_approved(tmp_path) -> None:
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    application = _record_application(
        tracker,
        job_id="job-agent",
        title="Agent Intern",
    )
    revision = tracker.load(user_id=USER_ID).revision
    turn = AgentTurn(
        turn_id="turn-update",
        session_id=SESSION_ID,
        user_input="Example AI 的 Agent Intern 我已经投了。",
    )
    loop, provider, _, _, _, _ = _build_loop(
        tmp_path,
        [
            _action(
                "update-1",
                APPLY_TRANSITION_TOOL,
                {
                    "application_id": application.id,
                    "new_status": ApplicationStatus.APPLIED.value,
                    "expected_revision": revision,
                    "notes": "user confirmed application submitted",
                },
            ),
            _finish("stage updated"),
        ],
        tracker=tracker,
    )

    pending = _run(loop, turn, tmp_path)
    assert pending.termination_reason == AgentLoopTerminationReason.WAITING_FOR_APPROVAL
    completed = _run(
        loop,
        turn,
        tmp_path,
        resume=True,
        approvals=_approval(pending),
    )

    assert completed.termination_reason == AgentLoopTerminationReason.FINISHED
    updated = tracker.load(user_id=USER_ID).applications[0]
    assert updated.current_state == ApplicationStatus.APPLIED
    assert provider.calls[0].referents[0].resolution.status == ReferentResolutionStatus.RESOLVED


def test_ambiguous_application_referent_forces_input_request(tmp_path) -> None:
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    first = _record_application(tracker, job_id="job-agent", title="Agent Intern")
    _record_application(tracker, job_id="job-infra", title="AI Infra Intern")
    revision = tracker.load(user_id=USER_ID).revision
    turn = AgentTurn(
        turn_id="turn-ambiguous",
        session_id=SESSION_ID,
        user_input="Example AI 那个进一面了。",
    )
    loop, _, _, _, _, _ = _build_loop(
        tmp_path,
        [
            _action(
                "unsafe-update",
                APPLY_TRANSITION_TOOL,
                {
                    "application_id": first.id,
                    "new_status": ApplicationStatus.FIRST_INTERVIEW.value,
                    "expected_revision": revision,
                },
            )
        ],
        tracker=tracker,
    )

    result = _run(loop, turn, tmp_path)

    assert result.termination_reason == AgentLoopTerminationReason.WAITING_FOR_USER
    assert result.terminal_observation.outcome == AgentObservationOutcome.WAITING_FOR_USER
    request = result.runtime_result.pending_user_input
    assert request is not None
    assert request.reason == "ambiguous_referent"
    assert request.choices == [
        "Example AI — AI Infra Intern",
        "Example AI — Agent Intern",
    ]
    assert all(
        item.current_state == ApplicationStatus.TO_APPLY
        for item in tracker.load(user_id=USER_ID).applications
    )


def test_direct_finish_uses_zero_tool_calls(tmp_path) -> None:
    loop, provider, _, _, _, calls = _build_loop(tmp_path, [_finish("you are welcome")])
    turn = AgentTurn(
        turn_id="turn-thanks",
        session_id=SESSION_ID,
        user_input="谢谢，先这样。",
    )

    result = _run(loop, turn, tmp_path)

    assert result.termination_reason == AgentLoopTerminationReason.FINISHED
    assert len(provider.calls) == 1
    assert sum(calls.values()) == 0
    assert result.runtime_result.state.step_index == 1


def test_policy_deny_becomes_failed_observation_without_bypass(tmp_path) -> None:
    action = _action(
        "denied-track",
        RECORD_APPLICATION_TOOL,
        {
            "job_id": "job-agent",
            "title": "Agent Intern",
            "company": "Example AI",
        },
    )
    loop, provider, tracker, _, _, _ = _build_loop(
        tmp_path,
        [action, _finish("write denied")],
        runtime_allowed=(ANALYZE_JOB_TOOL,),
    )
    turn = AgentTurn(
        turn_id="turn-denied",
        session_id=SESSION_ID,
        user_input="记录 Example AI Agent Intern。",
    )

    result = _run(loop, turn, tmp_path)

    assert result.termination_reason == AgentLoopTerminationReason.FINISHED
    assert tracker.load(user_id=USER_ID).applications == []
    denied = provider.calls[1].observations[0]
    assert denied.outcome == AgentObservationOutcome.FAILED
    assert denied.error_summary == "runtime_tool_denied"


def test_invalid_arguments_fail_closed_before_handler(tmp_path) -> None:
    loop, provider, tracker, _, _, calls = _build_loop(
        tmp_path,
        [
            _action("invalid-analysis", ANALYZE_JOB_TOOL, {}),
            _finish("invalid input reported"),
        ],
    )
    turn = AgentTurn(
        turn_id="turn-invalid",
        session_id=SESSION_ID,
        user_input="记录这个岗位。",
    )

    result = _run(loop, turn, tmp_path)

    assert result.termination_reason == AgentLoopTerminationReason.FINISHED
    assert tracker.load(user_id=USER_ID).applications == []
    assert calls[ANALYZE_JOB_TOOL] == 0
    assert provider.calls[1].observations[0].error_summary == "tool_input_error"


def test_step_budget_stops_repeated_actions(tmp_path) -> None:
    loop, provider, _, _, _, calls = _build_loop(
        tmp_path,
        [
            _action("analyze-1", ANALYZE_JOB_TOOL, {"job_id": "job-agent"}),
            _action("analyze-2", ANALYZE_JOB_TOOL, {"job_id": "job-agent"}),
            _finish("must not be reached"),
        ],
        config=AgentLoopConfig(max_steps=2),
    )
    turn = AgentTurn(
        turn_id="turn-loop",
        session_id=SESSION_ID,
        user_input="不断重复分析。",
    )

    result = _run(loop, turn, tmp_path)

    assert result.termination_reason == AgentLoopTerminationReason.STEP_BUDGET_EXHAUSTED
    assert result.terminal_observation.outcome == AgentObservationOutcome.FAILED
    assert result.runtime_result.error_code == "step_budget_exhausted"
    assert calls[ANALYZE_JOB_TOOL] == 2
    assert len(provider.calls) == 2


def _decision_context(
    text: str,
    capabilities: list[CapabilityCatalogEntry],
    *,
    referents: list[TurnReferentResolution] | None = None,
    observations: list[AgentObservation] | None = None,
    turn_id: str = "eval-turn",
) -> AgentDecisionContext:
    turn = AgentTurn(
        turn_id=turn_id,
        session_id="eval-session",
        user_input=text,
    )
    projection = AgentContextProjection(
        purpose=ContextPurpose.AGENT_DECISION,
        session_id=turn.session_id,
        sections=[],
    )
    payload = {
        "turn": turn.model_dump(mode="json"),
        "capabilities": [item.model_dump(mode="json") for item in capabilities],
        "referents": [item.model_dump(mode="json") for item in referents or []],
        "observations": [item.model_dump(mode="json") for item in observations or []],
    }
    return AgentDecisionContext(
        turn=turn,
        context=projection,
        capabilities=capabilities,
        referents=referents or [],
        observations=observations or [],
        step_index=0,
        remaining_steps=8,
        context_char_count=len(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
    )


def _eval_capabilities() -> list[CapabilityCatalogEntry]:
    schemas = {
        ANALYZE_JOB_TOOL: AnalyzeJobInput.model_json_schema(),
        READ_TRACKER_TOOL: {
            "type": "object",
            "properties": {"application_id": {"type": "string"}},
            "required": ["application_id"],
        },
        RECORD_APPLICATION_TOOL: {
            "type": "object",
            "properties": {
                "job_id": {"type": ["string", "null"]},
                "title": {"type": "string"},
                "company": {"type": "string"},
            },
            "required": ["title", "company"],
        },
        APPLY_TRANSITION_TOOL: {
            "type": "object",
            "properties": {
                "application_id": {"type": "string"},
                "new_status": {"type": "string"},
                "expected_revision": {"type": "integer"},
            },
            "required": ["application_id", "new_status", "expected_revision"],
        },
        INTERVIEW_PREP_TOOL: InterviewPrepInput.model_json_schema(),
    }
    effects = {
        ANALYZE_JOB_TOOL: ToolEffect.READ_ONLY,
        READ_TRACKER_TOOL: ToolEffect.READ_ONLY,
        RECORD_APPLICATION_TOOL: ToolEffect.LOCAL_STATE_MUTATION,
        APPLY_TRANSITION_TOOL: ToolEffect.LOCAL_STATE_MUTATION,
        INTERVIEW_PREP_TOOL: ToolEffect.READ_ONLY,
    }
    descriptions = {
        ANALYZE_JOB_TOOL: "Analyze a selected job_id.",
        READ_TRACKER_TOOL: "Read an application by application_id.",
        RECORD_APPLICATION_TOOL: "Create a tracked application.",
        APPLY_TRANSITION_TOOL: "Update application stage with current revision.",
        INTERVIEW_PREP_TOOL: "Prepare interview topics for an application.",
    }
    return [
        CapabilityCatalogEntry(
            name=name,
            description=descriptions[name],
            input_schema=schemas[name],
            effect=effects[name].value,
            requires_approval=effects[name] == ToolEffect.LOCAL_STATE_MUTATION,
            idempotent=True,
        )
        for name in schemas
    ]


def test_structured_provider_repairs_once_and_never_uses_native_dispatch() -> None:
    valid = {
        "decision": {
            "kind": "finish",
            "result": {"answer": "done"},
            "completion_evidence": ["user_request"],
            "unresolved_items": [],
            "confidence": 0.9,
        }
    }
    raw = MockLLMProvider(["not-json", valid])
    provider = StructuredAgentDecisionProvider(
        provider=raw,
        session_id="eval-session",
        run_id="eval-run",
        policy=NodePolicy(max_retries=0, max_schema_repairs=1),
    )

    result = provider.decide(_decision_context("谢谢", _eval_capabilities()))

    assert isinstance(result.decision, AgentFinish)
    assert len(raw.calls) == 2
    assert all(call["tools"] == () for call in raw.calls)


def test_structured_provider_fails_after_one_repair() -> None:
    raw = MockLLMProvider(["not-json", "still-not-json"])
    provider = StructuredAgentDecisionProvider(
        provider=raw,
        session_id="eval-session",
        run_id="eval-run",
        policy=NodePolicy(max_retries=0, max_schema_repairs=1),
    )

    with pytest.raises(LLMInvocationError, match="invalid_json"):
        provider.decide(_decision_context("分析岗位", _eval_capabilities()))
    assert len(raw.calls) == 2


def _real_eval_cases():
    ambiguous = TurnReferentResolution(
        mention="Example AI",
        entity_type=ReferentEntityType.APPLICATION,
        resolution=ReferentResolution(
            status=ReferentResolutionStatus.AMBIGUOUS,
            matched_by="explicit_identity",
            candidates=[
                ReferentRef(
                    entity_type=ReferentEntityType.APPLICATION,
                    entity_id="app-001",
                    source_turn_id="eval",
                    display_hint="Example AI — Agent Intern",
                ),
                ReferentRef(
                    entity_type=ReferentEntityType.APPLICATION,
                    entity_id="app-002",
                    source_turn_id="eval",
                    display_hint="Example AI — AI Infra Intern",
                ),
            ],
        ),
    )
    denied = AgentObservation(
        action_id="denied-1",
        tool_name=RECORD_APPLICATION_TOOL,
        outcome=AgentObservationOutcome.FAILED,
        error_summary="runtime_tool_denied",
    )
    return [
        ("direct-finish", "谢谢，先这样。", "finish", None, [], []),
        (
            "clarification",
            "帮我处理一下那个岗位，但我没有说是哪一个。",
            "input_request",
            None,
            [],
            [],
        ),
        (
            "job-analysis",
            "分析 job_id=job-agent 的岗位。",
            "action",
            ANALYZE_JOB_TOOL,
            [],
            [],
        ),
        (
            "application-read",
            "查询 application_id=app-001 的当前状态。",
            "action",
            READ_TRACKER_TOOL,
            [],
            [],
        ),
        (
            "application-write",
            "记录岗位：job_id=job-agent，title=Agent Intern，company=Example AI。",
            "action",
            RECORD_APPLICATION_TOOL,
            [],
            [],
        ),
        (
            "stage-update",
            "把 application_id=app-001 更新为 applied，expected_revision=2。",
            "action",
            APPLY_TRANSITION_TOOL,
            [],
            [],
        ),
        (
            "ambiguity",
            "Example AI 那个进一面了。",
            "input_request",
            None,
            [ambiguous],
            [],
        ),
        (
            "policy-deny",
            "刚才写入被策略拒绝，请说明结果，不要绕过策略。",
            "finish",
            None,
            [],
            [denied],
        ),
        (
            "interview-prep",
            "为 application_id=app-001 准备面试。",
            "action",
            INTERVIEW_PREP_TOOL,
            [],
            [],
        ),
    ]


def _run_decision_eval(provider, cases):
    capabilities = _eval_capabilities()
    allowed = {item.name for item in capabilities}
    outcomes = []
    for index, (case_id, text, expected_kind, expected_tool, refs, observations) in enumerate(cases):
        trace_start = len(getattr(provider, "traces", []))
        response = provider.decide(
            _decision_context(
                text,
                capabilities,
                referents=refs,
                observations=observations,
                turn_id=f"eval-{index}",
            )
        )
        decision = response.decision
        case_traces = getattr(provider, "traces", [])[trace_start:]
        actual_tool = decision.tool_name if isinstance(decision, AgentAction) else None
        outcomes.append(
            {
                "case_id": case_id,
                "schema_valid": True,
                "first_attempt_schema_valid": (
                    case_traces[0].schema_valid if case_traces else True
                ),
                "attempts": len(case_traces) or 1,
                "kind_correct": decision.kind == expected_kind,
                "tool_correct": expected_tool is None or actual_tool == expected_tool,
                "unknown_tool": actual_tool is not None and actual_tool not in allowed,
                "unnecessary_tool": expected_kind != "action" and actual_tool is not None,
            }
        )
    return outcomes


@pytest.mark.skipif(
    os.environ.get("RUN_DEEPSEEK_AGENT_EVAL") != "1" or not os.environ.get("API_KEY"),
    reason="explicit DeepSeek agent eval opt-in and API_KEY are required",
)
def test_deepseek_agent_decision_acceptance() -> None:
    provider = DeepSeekAPIProvider.from_env(
        session_id="deepseek-eval",
        run_id="deepseek-eval-run",
        policy=NodePolicy(
            timeout_s=60,
            max_retries=0,
            max_schema_repairs=1,
            temperature=0.0,
            max_output_tokens=1200,
            allow_rule_fallback=False,
        ),
    )
    cases = _real_eval_cases()
    outcomes = _run_decision_eval(provider, cases)
    traces = provider.traces
    metrics = {
        "cases": len(cases),
        "schema_validity": sum(item["schema_valid"] for item in outcomes) / len(cases),
        "first_attempt_schema_validity": sum(
            item["first_attempt_schema_valid"] for item in outcomes
        )
        / len(cases),
        "capability_selection": sum(
            item["kind_correct"] and item["tool_correct"] for item in outcomes
        )
        / len(cases),
        "clarification": next(
            item["kind_correct"] for item in outcomes if item["case_id"] == "ambiguity"
        ),
        "unknown_tool_rate": sum(item["unknown_tool"] for item in outcomes) / len(cases),
        "unnecessary_tool_rate": sum(item["unnecessary_tool"] for item in outcomes)
        / len(cases),
        "average_steps": 1.0,
        "api_calls": len(traces),
        "repair_rate": sum(item["attempts"] > 1 for item in outcomes) / len(cases),
        "input_tokens": sum(item.input_tokens or 0 for item in traces),
        "output_tokens": sum(item.output_tokens or 0 for item in traces),
    }
    print("DEEPSEEK_AGENT_EVAL=" + json.dumps(metrics, sort_keys=True))
    assert metrics["schema_validity"] == 1.0
    assert metrics["capability_selection"] >= 8 / 9
    assert metrics["clarification"] is True
    assert metrics["unknown_tool_rate"] == 0.0
    assert metrics["unnecessary_tool_rate"] == 0.0


class _LocalChatRunner:
    def __init__(self, model_path: str, *, max_new_tokens: int = 1400) -> None:
        self.model_path = model_path
        self.max_new_tokens = max_new_tokens
        self._tokenizer = None
        self._model = None

    def _load(self):
        if self._tokenizer is not None and self._model is not None:
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
        return tokenizer.decode(generated, skip_special_tokens=True).strip()


@pytest.mark.skipif(
    os.environ.get("RUN_LOCAL_AGENT_EVAL") != "1"
    or not os.environ.get("QWEN2_5_MODEL_PATH"),
    reason="explicit local model opt-in and QWEN2_5_MODEL_PATH are required",
)
def test_local_qwen_agent_decision_smoke() -> None:
    model_path = os.environ["QWEN2_5_MODEL_PATH"]
    provider = StructuredAgentDecisionProvider.from_local_transformers(
        provider=LocalTransformersProvider(
            runner=_LocalChatRunner(model_path),
            model="Qwen2.5-7B-Instruct",
        ),
        session_id="local-eval",
        run_id="local-eval-run",
        policy=NodePolicy(
            timeout_s=180,
            max_retries=0,
            max_schema_repairs=1,
            temperature=0.0,
            max_output_tokens=1400,
            allow_rule_fallback=False,
        ),
    )
    cases = [
        item
        for item in _real_eval_cases()
        if item[0] in {"direct-finish", "job-analysis", "ambiguity"}
    ]
    outcomes = _run_decision_eval(provider, cases)
    metrics = {
        "cases": len(cases),
        "schema_validity": 1.0,
        "behavior_correct": sum(
            item["kind_correct"] and item["tool_correct"] for item in outcomes
        )
        / len(cases),
        "unknown_tool_rate": sum(item["unknown_tool"] for item in outcomes) / len(cases),
    }
    print("LOCAL_QWEN_AGENT_EVAL=" + json.dumps(metrics, sort_keys=True))
    assert metrics["behavior_correct"] >= 2 / 3
    assert metrics["unknown_tool_rate"] == 0.0
