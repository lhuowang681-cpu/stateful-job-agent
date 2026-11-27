from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from job_agent.agent_runtime import (
    AgentAction,
    AgentContextProjection,
    AgentDecisionContext,
    AgentFinish,
    AgentInputRequest,
    AgentLoopTerminationReason,
    AgentTurn,
    ApprovalDecision,
    CapabilityCatalogEntry,
    ContextProjector,
    ContextPurpose,
    DeepSeekAPIProvider,
    InMemoryConversationStateStore,
    JsonCheckpointStore,
    NaturalLanguageAgentLoop,
    ReferentEntityType,
    ReferentResolutionStatus,
    ReferentResolver,
    ScriptedAgentDecisionProvider,
    ToolContext,
)
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.career.durable import DurableCareerRepository
from job_agent.career.runtime_tools import (
    READ_CAREER_STATE_TOOL,
    ReadCareerStateInput,
    build_durable_career_registry,
)
from job_agent.jd_match_analysis import JobBasicInfo
from job_agent.memory.contracts import MemoryRecord, MemorySource, UserState
from job_agent.memory.tools import (
    UPDATE_JOB_LOCATION_PREFERENCE_TOOL,
    UpdateJobLocationPreferenceInput,
    build_memory_tool_registry,
)
from job_agent.memory.user_state_store import UserStateStore
from job_agent.memory_aware_job_analysis import _preference_analysis
from job_agent.schemas import ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


USER_ID = "user-1"


def _analysis_payload() -> dict:
    return {
        "preference_analysis": {"city": {"fit": True, "actual": "杭州"}},
        "requirements": [
            {
                "text": "Kubernetes production experience",
                "status": "gap",
                "evidence": [],
            },
            {
                "text": "Agent Runtime and MCP integration",
                "status": "supported",
                "evidence": [
                    {
                        "document_id": "doc-runtime",
                        "chunk_id": "chunk-runtime",
                    }
                ],
            },
        ],
        "summary": {
            "evidence_backed_strengths": ["Agent Runtime and MCP integration"],
            "gaps": ["Kubernetes production experience"],
        },
    }


def _finish(answer: str = "done") -> AgentFinish:
    return AgentFinish(
        result={"answer": answer},
        completion_evidence=["governed-runtime-observation"],
        confidence=1.0,
    )


def _action(action_id: str, tool_name: str, arguments: dict) -> AgentAction:
    return AgentAction(
        action_id=action_id,
        tool_name=tool_name,
        tool_arguments=arguments,
        expected_observation="structured durable state",
        progress_claim=f"use {tool_name} through Runtime",
    )


def _loop(
    tmp_path: Path,
    *,
    decisions,
    registry: ToolRegistry,
    tracker: ApplicationTrackerStore,
    resolver: ReferentResolver,
    checkpoint_name: str,
    runtime_allowed: tuple[str, ...] | None = None,
) -> tuple[NaturalLanguageAgentLoop, ScriptedAgentDecisionProvider]:
    provider = ScriptedAgentDecisionProvider(decisions)
    allowed = registry.names()
    loop = NaturalLanguageAgentLoop(
        provider=provider,
        registry=registry,
        policy_context=PolicyContext(
            skill_allowed_tools=allowed,
            agent_allowed_tools=allowed,
            runtime_allowed_tools=(
                allowed if runtime_allowed is None else runtime_allowed
            ),
            target_summary="durable career and user preference state",
            arguments_preview_keys=("job_id", "add_acceptable_cities"),
        ),
        conversation_store=InMemoryConversationStateStore(),
        context_projector=ContextProjector(tracker_store=tracker),
        referent_resolver=resolver,
        checkpoint_store=JsonCheckpointStore(tmp_path / checkpoint_name),
    )
    return loop, provider


def _run(
    loop: NaturalLanguageAgentLoop,
    *,
    tmp_path: Path,
    turn: AgentTurn,
    run_id: str,
    state: UserState,
    approvals=None,
    resume: bool = False,
):
    return loop.run_turn(
        turn=turn,
        run_id=run_id,
        user_id=USER_ID,
        user_state=state,
        tool_context=ToolContext(
            session_id=turn.session_id,
            run_id=run_id,
            agent_id="durable-career-agent",
            workspace_root=str(tmp_path),
            sandbox_root=str(tmp_path / "sandbox"),
        ),
        policy_summary="Read through tools; approve all durable writes.",
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


def _seed_process_a(root: Path):
    repository = DurableCareerRepository.open(root)
    tracker = ApplicationTrackerStore(root / "tracker.json")
    job = repository.save_job(
        job_id="job-example-agent",
        company="Example AI",
        title="Agent Intern",
        location="杭州",
        job_type="internship",
        source_type="manual",
        source_uri="https://example.test/jobs/agent",
    )
    jd_v1 = repository.append_jd_snapshot(
        job_id=job.job_id,
        text="Build Agent Runtime.\r\nKubernetes experience required.",
        source_uri=job.source_uri,
        created_by="user",
    )
    jd_v2 = repository.append_jd_snapshot(
        job_id=job.job_id,
        text="Build Agent Runtime and MCP.\nKubernetes production experience required.",
        source_uri=job.source_uri,
        created_by="jd-refresh",
    )
    analysis = repository.append_analysis_snapshot(
        job_id=job.job_id,
        jd_snapshot_id=jd_v2.snapshot_id,
        analysis=_analysis_payload(),
        producer_run_id="analysis-run-1",
        model_metadata={"provider": "deterministic", "model": "fixture"},
        provenance_refs=["source:jd-example"],
    )
    application = tracker.record_application(
        user_id=USER_ID,
        job_id=job.job_id,
        company=job.company,
        title=job.title,
        city=job.location,
        source="fixture",
        url=job.source_uri or "",
        initial_status=ApplicationStatus.TO_APPLY,
        notes="saved after analysis",
        user_confirmed=True,
    )
    repository.link_application(
        job_id=job.job_id,
        application_id=application.id,
    )
    tracker.update_status(
        user_id=USER_ID,
        application_id=application.id,
        new_status=ApplicationStatus.APPLIED,
        notes="submitted",
        user_confirmed=True,
    )
    assert repository.append_jd_snapshot(
        job_id=job.job_id,
        text=jd_v1.text,
        source_uri=job.source_uri,
        created_by="duplicate-import",
    ).snapshot_id == jd_v1.snapshot_id
    repository.close()
    return job, jd_v1, jd_v2, analysis, application


def test_cross_process_long_horizon_scenario_and_agent_read(tmp_path) -> None:
    job, jd_v1, jd_v2, analysis, application = _seed_process_a(tmp_path)

    repository = DurableCareerRepository.open(tmp_path)
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    state = repository.get_state(job.job_id)
    assert [item.version for item in state.jd_snapshots] == [1, 2]
    assert state.latest_jd.snapshot_id == jd_v2.snapshot_id
    assert state.latest_analysis.analysis_id == analysis.analysis_id
    assert state.latest_analysis.jd_snapshot_version == 2
    assert "Kubernetes production experience" in state.latest_analysis.gaps
    assert state.application_link.application_id == application.id

    registry = build_durable_career_registry(
        repository,
        tracker,
        user_id=USER_ID,
    )
    turn = AgentTurn(
        turn_id="turn-process-b-read",
        session_id="new-session-b",
        user_input="Example AI 那个岗位现在什么情况？当时 Kubernetes 是不是我的 gap？",
    )
    loop, provider = _loop(
        tmp_path,
        decisions=[
            _action(
                "read-career",
                READ_CAREER_STATE_TOOL,
                {"job_id": job.job_id},
            ),
            _finish("applied; Kubernetes was a recorded gap"),
        ],
        registry=registry,
        tracker=tracker,
        resolver=ReferentResolver(
            tracker_store=tracker,
            career_repository=repository,
        ),
        checkpoint_name="read.checkpoint.json",
    )
    result = _run(
        loop,
        tmp_path=tmp_path,
        turn=turn,
        run_id="process-b-read",
        state=UserState(user_id=USER_ID),
    )
    assert result.termination_reason == AgentLoopTerminationReason.FINISHED
    resolution = provider.calls[0].referents[0].resolution
    assert resolution.status == ReferentResolutionStatus.RESOLVED
    assert resolution.referent.entity_id == job.job_id
    observed = provider.calls[1].observations[0].result["data"]
    assert observed["application"]["current_stage"] == "applied"
    assert "Kubernetes production experience" in observed["latest_analysis"]["gaps"]

    tracker.update_status(
        user_id=USER_ID,
        application_id=application.id,
        new_status=ApplicationStatus.RESUME_SCREEN,
        notes="resume passed",
        user_confirmed=True,
    )
    tracker.update_status(
        user_id=USER_ID,
        application_id=application.id,
        new_status=ApplicationStatus.FIRST_INTERVIEW,
        notes="interview scheduled",
        user_confirmed=True,
    )
    prep = repository.append_interview_prep_snapshot(
        job_id=job.job_id,
        application_id=application.id,
        analysis_id=analysis.analysis_id,
        application_stage_at_generation="first_interview",
        preparation={
            "questions": [{"question": "How does your MCP runtime enforce policy?"}],
            "gaps": [{"topic": "Kubernetes", "risk": "production depth"}],
            "technical_review": [{"topic": "Agent Runtime"}],
        },
        producer_run_id="prep-run-1",
        provenance_refs=["application:app-001"],
    )
    repository.close()

    process_c = DurableCareerRepository.open(tmp_path)
    recovered = process_c.get_state(job.job_id)
    assert recovered.latest_interview_prep.prep_id == prep.prep_id
    assert recovered.latest_interview_prep.analysis_id == analysis.analysis_id
    assert recovered.latest_interview_prep.application_stage_at_generation == "first_interview"
    live_tracker = ApplicationTrackerStore(tmp_path / "tracker.json").load(
        user_id=USER_ID
    )
    assert live_tracker.applications[0].current_state == ApplicationStatus.FIRST_INTERVIEW
    assert [item.state.value for item in live_tracker.applications[0].state_history] == [
        "to_apply",
        "applied",
        "resume_screen",
        "first_interview",
    ]
    process_c.close()


def test_broken_references_and_corrupt_snapshot_fail_closed(tmp_path) -> None:
    repository = DurableCareerRepository.open(tmp_path)
    repository.save_job(
        job_id="job-1",
        company="Example AI",
        title="Agent Intern",
    )
    with pytest.raises(ValueError, match="existing JD snapshot"):
        repository.append_analysis_snapshot(
            job_id="job-1",
            jd_snapshot_id="missing-jd",
            analysis=_analysis_payload(),
            producer_run_id="broken-analysis",
        )
    with pytest.raises(KeyError):
        repository.append_analysis_snapshot(
            job_id="missing-job",
            jd_snapshot_id="missing-jd",
            analysis=_analysis_payload(),
            producer_run_id="missing-job-analysis",
        )

    jd = repository.append_jd_snapshot(
        job_id="job-1",
        text="Kubernetes required",
        created_by="user",
    )
    snapshot = repository.append_analysis_snapshot(
        job_id="job-1",
        jd_snapshot_id=jd.snapshot_id,
        analysis=_analysis_payload(),
        producer_run_id="valid-analysis",
    )
    repository._connect().execute(
        "UPDATE analysis_snapshots SET payload_json=? WHERE analysis_id=?",
        ("{not-json", snapshot.analysis_id),
    )
    repository.close()

    reopened = DurableCareerRepository.open(tmp_path)
    with pytest.raises(ValueError):
        reopened.get_state("job-1")
    assert reopened.list_jobs()[0].job_id == "job-1"
    reopened.close()


def test_cross_session_same_company_is_ambiguous(tmp_path) -> None:
    repository = DurableCareerRepository.open(tmp_path)
    for job_id, title in (("job-agent", "Agent Intern"), ("job-infra", "AI Infra Intern")):
        repository.save_job(job_id=job_id, company="Example AI", title=title)
    resolver = ReferentResolver(career_repository=repository)
    conversation = InMemoryConversationStateStore().load("brand-new-session")

    result = resolver.resolve(
        conversation=conversation,
        mention="Example AI 那个岗位",
        entity_type=ReferentEntityType.JOB,
        source_turn_id="turn-ambiguous",
        user_id=USER_ID,
    )

    assert result.status == ReferentResolutionStatus.AMBIGUOUS
    assert [item.entity_id for item in result.candidates] == ["job-infra", "job-agent"]
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    loop, _ = _loop(
        tmp_path,
        decisions=[
            _action(
                "unsafe-read",
                READ_CAREER_STATE_TOOL,
                {"job_id": "job-agent"},
            )
        ],
        registry=build_durable_career_registry(
            repository,
            tracker,
            user_id=USER_ID,
        ),
        tracker=tracker,
        resolver=resolver,
        checkpoint_name="ambiguous.checkpoint.json",
    )
    agent_result = _run(
        loop,
        tmp_path=tmp_path,
        turn=AgentTurn(
            turn_id="turn-agent-ambiguous",
            session_id="another-new-session",
            user_input="Example AI 那个岗位现在什么情况？",
        ),
        run_id="ambiguous-run",
        state=UserState(user_id=USER_ID),
    )
    assert agent_result.termination_reason == AgentLoopTerminationReason.WAITING_FOR_USER
    assert agent_result.runtime_result.pending_user_input.reason == "ambiguous_referent"
    repository.close()


def test_memory_update_requires_approval_and_preserves_supersession(tmp_path) -> None:
    memory_store = UserStateStore(tmp_path / "memory.json")
    old = MemoryRecord(
        memory_id="memory-old",
        user_id=USER_ID,
        kind="preference",
        key="job_location",
        value={"preferred_city": "杭州", "acceptable_cities": []},
        content="优先考虑杭州。",
        source=MemorySource.USER_STATED,
        confidence=1.0,
        created_at="2026-09-18T00:00:00+00:00",
        updated_at="2026-09-18T00:00:00+00:00",
    )
    memory_store.save(
        user_id=USER_ID,
        state=UserState(
            user_id=USER_ID,
            preferences={"preferred_city": "杭州", "acceptable_cities": []},
            memories=[old],
        ),
        expected_version=1,
    )
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    registry = build_memory_tool_registry(memory_store, user_id=USER_ID)
    action = _action(
        "accept-shanghai",
        UPDATE_JOB_LOCATION_PREFERENCE_TOOL,
        {
            "add_acceptable_cities": ["上海"],
            "statement": "以后上海的岗位我也可以考虑。",
            "idempotency_key": "turn-location-1",
        },
    )
    turn = AgentTurn(
        turn_id="turn-location-1",
        session_id="memory-session-a",
        user_input="以后上海的岗位我也可以考虑。",
    )
    loop, provider = _loop(
        tmp_path,
        decisions=[action, _finish("preference updated")],
        registry=registry,
        tracker=tracker,
        resolver=ReferentResolver(tracker_store=tracker),
        checkpoint_name="memory.checkpoint.json",
    )

    pending = _run(
        loop,
        tmp_path=tmp_path,
        turn=turn,
        run_id="memory-run",
        state=memory_store.load(user_id=USER_ID),
    )
    assert pending.termination_reason == AgentLoopTerminationReason.WAITING_FOR_APPROVAL
    assert memory_store.load(user_id=USER_ID).preferences["acceptable_cities"] == []

    completed = _run(
        loop,
        tmp_path=tmp_path,
        turn=turn,
        run_id="memory-run",
        state=memory_store.load(user_id=USER_ID),
        approvals=_approval(pending),
        resume=True,
    )
    assert completed.termination_reason == AgentLoopTerminationReason.FINISHED
    current = memory_store.load(user_id=USER_ID)
    assert current.preferences == {
        "preferred_city": "杭州",
        "acceptable_cities": ["上海"],
    }
    assert len(current.memories) == 2
    assert current.memories[0].superseded_by_memory_id == current.memories[1].memory_id
    assert current.memories[1].supersedes_memory_id == "memory-old"
    assert current.memories[1].source == MemorySource.USER_STATED

    replay = memory_store.update_job_location_preference(
        user_id=USER_ID,
        add_acceptable_cities=["上海"],
        statement="以后上海的岗位我也可以考虑。",
        idempotency_key="turn-location-1",
    )
    assert replay.changed is False
    assert len(replay.state.memories) == 2
    assert len(provider.calls) == 2


def test_policy_deny_memory_write_leaves_state_unchanged(tmp_path) -> None:
    memory_store = UserStateStore(tmp_path / "memory.json")
    memory_store.save(
        user_id=USER_ID,
        state=UserState(user_id=USER_ID, preferences={"preferred_city": "杭州"}),
        expected_version=1,
    )
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    registry = build_memory_tool_registry(memory_store, user_id=USER_ID)
    loop, provider = _loop(
        tmp_path,
        decisions=[
            _action(
                "denied-memory",
                UPDATE_JOB_LOCATION_PREFERENCE_TOOL,
                {
                    "add_acceptable_cities": ["上海"],
                    "statement": "以后上海也可以考虑。",
                    "idempotency_key": "denied-turn",
                },
            ),
            _finish("write denied"),
        ],
        registry=registry,
        tracker=tracker,
        resolver=ReferentResolver(tracker_store=tracker),
        checkpoint_name="denied.checkpoint.json",
        runtime_allowed=(),
    )
    result = _run(
        loop,
        tmp_path=tmp_path,
        turn=AgentTurn(
            turn_id="denied-turn",
            session_id="memory-denied",
            user_input="以后上海也可以考虑。",
        ),
        run_id="denied-run",
        state=memory_store.load(user_id=USER_ID),
    )
    assert result.termination_reason == AgentLoopTerminationReason.FINISHED
    assert provider.calls[1].observations[0].error_summary == "runtime_tool_denied"
    current = memory_store.load(user_id=USER_ID)
    assert current.preferences == {"preferred_city": "杭州"}
    assert current.memories == []


def test_persisted_acceptable_city_is_used_by_later_analysis(tmp_path) -> None:
    first_process = UserStateStore(tmp_path / "memory.json")
    first_process.save(
        user_id=USER_ID,
        state=UserState(user_id=USER_ID, preferences={"preferred_city": "杭州"}),
        expected_version=1,
    )
    first_process.update_job_location_preference(
        user_id=USER_ID,
        add_acceptable_cities=["上海"],
        statement="以后上海也可以考虑。",
        idempotency_key="location-cross-session",
    )

    second_process = UserStateStore(tmp_path / "memory.json")
    state = second_process.load(user_id=USER_ID)
    result = _preference_analysis(
        state,
        JobBasicInfo(
            title="Agent Intern",
            city="上海",
            role_direction="Agent",
            job_type="internship",
            text="Build agent systems.",
        ),
    )
    assert state.preferences["preferred_city"] == "杭州"
    assert result.city.fit is True
    assert "acceptable alternative" in result.city.explanation


@pytest.mark.skipif(
    os.getenv("RUN_DEEPSEEK_DURABLE_EVAL") != "1" or not os.getenv("API_KEY"),
    reason="explicit DeepSeek durable-state acceptance opt-in required",
)
@pytest.mark.parametrize(
    ("text", "expected_kind", "expected_tool"),
    [
        ("Example AI 那个岗位现在什么情况？", "action", READ_CAREER_STATE_TOOL),
        ("当时 Kubernetes 是不是我的 gap？", "action", READ_CAREER_STATE_TOOL),
        (
            "以后上海的岗位我也可以考虑。",
            "action",
            UPDATE_JOB_LOCATION_PREFERENCE_TOOL,
        ),
        ("Example AI 那个岗位", "input_request", None),
    ],
)
def test_deepseek_long_horizon_decisions(text, expected_kind, expected_tool) -> None:
    capabilities = [
        CapabilityCatalogEntry(
            name=READ_CAREER_STATE_TOOL,
            description="Read durable career state for one resolved job.",
            input_schema=ReadCareerStateInput.model_json_schema(),
            effect="read_only",
            requires_approval=False,
            idempotent=True,
        ),
        CapabilityCatalogEntry(
            name=UPDATE_JOB_LOCATION_PREFERENCE_TOOL,
            description="Persist an explicit user-stated location preference.",
            input_schema=UpdateJobLocationPreferenceInput.model_json_schema(),
            effect="local_state_mutation",
            requires_approval=True,
            idempotent=True,
        ),
    ]
    turn = AgentTurn(turn_id="deepseek-turn", session_id="deepseek-session", user_input=text)
    context = AgentDecisionContext(
        turn=turn,
        context=AgentContextProjection(
            purpose=ContextPurpose.AGENT_DECISION,
            session_id=turn.session_id,
            sections=[],
        ),
        capabilities=capabilities,
        referents=(
            (
                []
                if expected_tool == UPDATE_JOB_LOCATION_PREFERENCE_TOOL
                else [
                    {
                        "mention": "Example AI",
                        "entity_type": "job",
                        "resolution": {
                            "status": "resolved",
                            "referent": {
                                "entity_type": "job",
                                "entity_id": "job-agent",
                                "source_turn_id": "deepseek-turn",
                                "display_hint": "Example AI — Agent Intern",
                            },
                            "matched_by": "explicit_identity",
                        },
                    }
                ]
            )
            if expected_kind != "input_request"
            else [
                {
                    "mention": "Example AI",
                    "entity_type": "job",
                    "resolution": {
                        "status": "ambiguous",
                        "candidates": [
                            {
                                "entity_type": "job",
                                "entity_id": "job-agent",
                                "source_turn_id": "deepseek-turn",
                                "display_hint": "Example AI — Agent Intern",
                            },
                            {
                                "entity_type": "job",
                                "entity_id": "job-infra",
                                "source_turn_id": "deepseek-turn",
                                "display_hint": "Example AI — AI Infra Intern",
                            },
                        ],
                        "matched_by": "explicit_identity",
                    },
                }
            ]
        ),
        observations=[],
        step_index=0,
        remaining_steps=4,
        context_char_count=len(json.dumps({"text": text}, ensure_ascii=False)),
    )
    decision = DeepSeekAPIProvider.from_env(
        session_id="deepseek-session",
        run_id=f"deepseek-{expected_kind}-{expected_tool or 'clarify'}",
    ).decide(context).decision
    assert decision.kind == expected_kind
    if expected_tool is not None:
        assert isinstance(decision, AgentAction)
        assert decision.tool_name == expected_tool
    else:
        assert isinstance(decision, AgentInputRequest)
