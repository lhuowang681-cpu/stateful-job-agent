from __future__ import annotations

from datetime import datetime, timezone

import pytest

from job_agent.agent_runtime import AgentObservation, AgentObservationOutcome, AgentTurn
from job_agent.agent_runtime.interaction_context import (
    AssistantResultMetadata,
    ContextAuthority,
    ContextProjector,
    ContextPurpose,
    InMemoryConversationStateStore,
    ReferentEntityType,
    ReferentRef,
    ReferentResolutionStatus,
    ReferentResolver,
)
from job_agent.evidence.contracts import RequirementAnalysis
from job_agent.jd_match_analysis import (
    JobAnalysisSummary,
    JobMatchAnalysis,
    JobMatchEvidenceSummary,
)
from job_agent.memory.contracts import UserState
from job_agent.schemas import ApplicationStatus, RawJob
from job_agent.tools.application_tracker import ApplicationTrackerStore


NOW = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)
USER_ID = "user-1"


def _turn(turn_id: str, text: str) -> AgentTurn:
    return AgentTurn(
        turn_id=turn_id,
        session_id="session-1",
        user_input=text,
        created_at=NOW,
    )


def _job(job_id: str, company: str, title: str, *, marker: str = "") -> RawJob:
    return RawJob(
        job_id=job_id,
        company=company,
        title=title,
        desc=f"Build governed Agent systems. {marker}",
        url=f"https://example.test/{job_id}",
        location="杭州",
        source="fixture",
        job_type="internship",
        fetched_at=NOW.isoformat(),
    )


@pytest.fixture
def jobs() -> tuple[RawJob, ...]:
    return (
        _job("job-agent", "Example AI", "Agent Intern"),
        _job("job-infra", "Example AI", "AI Infra Intern"),
        _job("job-other", "Other Corp", "Backend Intern", marker="UNRELATED_JD"),
    )


@pytest.fixture
def tracker_store(tmp_path) -> ApplicationTrackerStore:
    store = ApplicationTrackerStore(tmp_path / "tracker.json", now=lambda: NOW)
    for job_id, company, title in (
        ("job-agent", "Example AI", "Agent Intern"),
        ("job-infra", "Example AI", "AI Infra Intern"),
        ("job-other", "Other Corp", "Backend Intern"),
    ):
        store.record_application(
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
    return store


def _job_ref(job_id: str, turn_id: str, title: str) -> ReferentRef:
    return ReferentRef(
        entity_type=ReferentEntityType.JOB,
        entity_id=job_id,
        source_turn_id=turn_id,
        updated_at=NOW,
        display_hint=title,
    )


def _application_ref(application_id: str, turn_id: str, title: str) -> ReferentRef:
    return ReferentRef(
        entity_type=ReferentEntityType.APPLICATION,
        entity_id=application_id,
        source_turn_id=turn_id,
        updated_at=NOW,
        display_hint=title,
    )


def test_current_referent_resolves_without_guessing(jobs) -> None:
    store = InMemoryConversationStateStore()
    store.append_turn(_turn("turn-1", "看看 Example AI 的 Agent Intern。"))
    store.record_referent(
        "session-1",
        _job_ref("job-agent", "turn-1", "Example AI — Agent Intern"),
    )

    resolution = ReferentResolver(jobs=jobs, now=lambda: NOW).resolve(
        conversation=store.load("session-1"),
        mention="这个岗位",
        entity_type=ReferentEntityType.JOB,
        source_turn_id="turn-2",
    )

    assert resolution.status == ReferentResolutionStatus.RESOLVED
    assert resolution.referent.entity_id == "job-agent"
    assert resolution.matched_by == "current_referent"


def test_previous_referent_resolves_to_the_prior_distinct_job(jobs) -> None:
    store = InMemoryConversationStateStore()
    store.append_turn(_turn("turn-1", "先看 Job A。"))
    store.record_referent("session-1", _job_ref("job-agent", "turn-1", "Job A"))
    store.append_turn(_turn("turn-2", "再看 Job B。"))
    store.record_referent("session-1", _job_ref("job-infra", "turn-2", "Job B"))

    resolution = ReferentResolver(jobs=jobs, now=lambda: NOW).resolve(
        conversation=store.load("session-1"),
        mention="上次那个岗位",
        entity_type=ReferentEntityType.JOB,
        source_turn_id="turn-3",
    )

    assert resolution.status == ReferentResolutionStatus.RESOLVED
    assert resolution.referent.entity_id == "job-agent"
    assert resolution.matched_by == "previous_referent"


def test_explicit_title_resolves_against_real_application_tracker(
    tracker_store,
) -> None:
    resolution = ReferentResolver(
        tracker_store=tracker_store,
        now=lambda: NOW,
    ).resolve(
        conversation=InMemoryConversationStateStore().load("session-1"),
        mention="Agent Intern",
        entity_type=ReferentEntityType.APPLICATION,
        source_turn_id="turn-1",
        user_id=USER_ID,
    )

    assert resolution.status == ReferentResolutionStatus.RESOLVED
    assert resolution.referent.display_hint == "Example AI — Agent Intern"


def test_explicit_company_is_ambiguous_in_real_application_tracker(
    tracker_store,
) -> None:
    resolver = ReferentResolver(tracker_store=tracker_store, now=lambda: NOW)
    resolution = resolver.resolve(
        conversation=InMemoryConversationStateStore().load("session-1"),
        mention="Example AI 那个",
        entity_type=ReferentEntityType.APPLICATION,
        source_turn_id="turn-1",
        user_id=USER_ID,
    )

    assert resolution.status == ReferentResolutionStatus.AMBIGUOUS
    assert resolution.referent is None
    assert {item.display_hint for item in resolution.candidates} == {
        "Example AI — Agent Intern",
        "Example AI — AI Infra Intern",
    }


def test_ambiguous_resolution_never_defaults_to_latest_or_first(
    tracker_store,
) -> None:
    resolution = ReferentResolver(
        tracker_store=tracker_store,
        now=lambda: NOW,
    ).resolve(
        conversation=InMemoryConversationStateStore().load("session-1"),
        mention="Example AI",
        entity_type=ReferentEntityType.APPLICATION,
        source_turn_id="turn-1",
        user_id=USER_ID,
    )

    assert resolution.status == ReferentResolutionStatus.AMBIGUOUS
    assert resolution.referent is None
    assert len(resolution.candidates) == 2


def test_referent_not_found_is_explicit(tracker_store) -> None:
    resolution = ReferentResolver(
        tracker_store=tracker_store,
        now=lambda: NOW,
    ).resolve(
        conversation=InMemoryConversationStateStore().load("session-1"),
        mention="Missing Company",
        entity_type=ReferentEntityType.APPLICATION,
        source_turn_id="turn-1",
        user_id=USER_ID,
    )

    assert resolution.status == ReferentResolutionStatus.NOT_FOUND
    assert resolution.referent is None
    assert resolution.candidates == []


def test_same_session_continuity_tracks_current_then_previous(jobs) -> None:
    store = InMemoryConversationStateStore()
    first = _turn("turn-1", "看看 Example AI 的 Agent Intern。")
    store.append_turn(
        first,
        assistant_result=AssistantResultMetadata(refs=["job:job-agent"]),
    )
    store.record_referent(
        first.session_id,
        _job_ref("job-agent", first.turn_id, "Example AI — Agent Intern"),
    )
    second = _turn("turn-2", "这个还行，记一下。")
    store.append_turn(second)
    resolver = ReferentResolver(jobs=jobs, now=lambda: NOW)

    current = resolver.resolve(
        conversation=store.load("session-1"),
        mention="这个",
        entity_type=ReferentEntityType.JOB,
        source_turn_id=second.turn_id,
    )
    assert current.referent.entity_id == "job-agent"

    store.record_referent(
        "session-1",
        _job_ref("job-infra", "turn-2", "Example AI — AI Infra Intern"),
    )
    third = _turn("turn-3", "上次那个岗位呢？")
    store.append_turn(third)
    previous = resolver.resolve(
        conversation=store.load("session-1"),
        mention="上次那个岗位",
        entity_type=ReferentEntityType.JOB,
        source_turn_id=third.turn_id,
    )

    assert previous.status == ReferentResolutionStatus.RESOLVED
    assert previous.referent.entity_id == "job-agent"


def _conversation(tracker_store) -> tuple[InMemoryConversationStateStore, str]:
    application = tracker_store.find_application(
        user_id=USER_ID,
        job_id="job-agent",
        company="Example AI",
        title="Agent Intern",
    )
    store = InMemoryConversationStateStore()
    store.append_turn(_turn("turn-1", "看看 Example AI 的 Agent Intern。"))
    store.record_referent(
        "session-1",
        _job_ref("job-agent", "turn-1", "Example AI — Agent Intern"),
    )
    store.record_referent(
        "session-1",
        _application_ref(
            application.id,
            "turn-1",
            "Example AI — Agent Intern",
        ),
    )
    return store, application.id


def _user_state() -> UserState:
    return UserState(
        user_id=USER_ID,
        preferences={
            "preferred_city": "杭州",
            "target_role": "Agent / 大模型应用",
            "job_type": "internship",
            "unrelated_preference": "DO_NOT_PROJECT",
        },
        user={"private_blob": "DO_NOT_DUMP_USER_STATE"},
        current_hunt={"all_jobs": "DO_NOT_DUMP_HUNT"},
        meta={"updated_at": NOW.isoformat()},
    )


def _analysis() -> JobMatchAnalysis:
    return JobMatchAnalysis(
        requirement_analysis=RequirementAnalysis(),
        requirements=(),
        supported=("MCP and governed Runtime integration",),
        partial_or_unverified=(),
        gaps=("Kubernetes",),
        unsupported=(),
        evidence_summary=JobMatchEvidenceSummary(
            total_requirements=2,
            supported_count=1,
            partial_count=0,
            unverified_lead_count=0,
            unsupported_count=0,
            gap_count=1,
            evidence_link_count=1,
        ),
        jd_source_id="jd:job-agent:v1",
        summary=JobAnalysisSummary(
            evidence_backed_strengths=("MCP and governed Runtime integration",),
            gaps=("Kubernetes",),
            preference_conflicts=(),
        ),
    )


def test_job_analysis_projection_selects_job_and_relevant_preferences(
    tracker_store,
    jobs,
) -> None:
    store, _ = _conversation(tracker_store)
    projector = ContextProjector(tracker_store=tracker_store)
    observation = AgentObservation(
        action_id="action-1",
        tool_name="career.read_job",
        outcome=AgentObservationOutcome.SUCCEEDED,
        result={"job_id": "job-agent"},
    )

    projection = projector.project(
        purpose=ContextPurpose.JOB_ANALYSIS,
        conversation=store.load("session-1"),
        current_turn=_turn("turn-2", "这个岗位怎么样？"),
        user_id=USER_ID,
        user_state=_user_state(),
        policy_summary="Use governed Runtime actions only.",
        remaining_steps=7,
        jobs=jobs,
        tool_observations=[observation],
    )

    names = {section.name for section in projection.sections}
    assert "target_job" in names
    assert "user_preferences" in names
    assert "target_application" not in names
    assert "application_history" not in names
    assert projection.section("target_job").content["job_id"] == "job-agent"
    assert projection.section("user_preferences").content == {
        "preferred_city": "杭州",
        "target_role": "Agent / 大模型应用",
        "job_type": "internship",
    }
    serialized = projection.model_dump_json()
    assert "UNRELATED_JD" not in serialized
    assert "DO_NOT_DUMP_USER_STATE" not in serialized
    assert "DO_NOT_DUMP_HUNT" not in serialized
    assert projection.section("tool_observation:action-1").authority == (
        ContextAuthority.TOOL_OBSERVATION
    )


def test_application_update_projection_selects_only_target_business_state(
    tracker_store,
    jobs,
) -> None:
    store, application_id = _conversation(tracker_store)
    projection = ContextProjector(tracker_store=tracker_store).project(
        purpose=ContextPurpose.APPLICATION_UPDATE,
        conversation=store.load("session-1"),
        current_turn=_turn("turn-2", "我已经投了。"),
        user_id=USER_ID,
        user_state=_user_state(),
        policy_summary="Writes require governed Runtime approval.",
        target_ref=_application_ref(
            application_id,
            "turn-2",
            "Example AI — Agent Intern",
        ),
        jobs=jobs,
    )

    names = {section.name for section in projection.sections}
    application = projection.section("target_application")
    assert application.content["application_id"] == application_id
    assert application.content["current_stage"] == "to_apply"
    assert application.authority == ContextAuthority.BUSINESS_STATE
    assert "target_job" not in names
    assert "job_analysis" not in names
    assert "career_knowledge" not in names
    assert "Other Corp" not in projection.model_dump_json()


def test_interview_prep_projection_uses_target_job_application_and_analysis(
    tracker_store,
    jobs,
) -> None:
    store, application_id = _conversation(tracker_store)
    projection = ContextProjector(tracker_store=tracker_store).project(
        purpose=ContextPurpose.INTERVIEW_PREP,
        conversation=store.load("session-1"),
        current_turn=_turn("turn-2", "帮我准备这个岗位的面试。"),
        user_id=USER_ID,
        user_state=_user_state(),
        policy_summary="Use verified evidence and business state.",
        target_ref=_application_ref(
            application_id,
            "turn-2",
            "Example AI — Agent Intern",
        ),
        jobs=jobs,
        analyses_by_job_id={"job-agent": _analysis()},
    )

    names = {section.name for section in projection.sections}
    assert {"target_application", "target_job", "job_analysis"} <= names
    assert projection.section("job_analysis").content == {
        "job_id": "job-agent",
        "analysis_ref": "jd:job-agent:v1",
        "strengths": ["MCP and governed Runtime integration"],
        "gaps": ["Kubernetes"],
    }
    assert "Other Corp" not in projection.model_dump_json()
    assert projection.unavailable == []


def test_context_sections_keep_provenance_and_authority_metadata(
    tracker_store,
    jobs,
) -> None:
    store, _ = _conversation(tracker_store)
    projection = ContextProjector(tracker_store=tracker_store).project(
        purpose=ContextPurpose.JOB_ANALYSIS,
        conversation=store.load("session-1"),
        current_turn=_turn("turn-2", "分析一下。"),
        user_id=USER_ID,
        user_state=_user_state(),
        policy_summary="Use governed Runtime actions only.",
        jobs=jobs,
    )

    for section in projection.sections:
        assert section.source
        assert section.inclusion_reason
        assert section.char_count > 0
        assert section.authority in ContextAuthority
    assert projection.section("current_turn").authority == ContextAuthority.USER_INPUT
    assert projection.section("user_preferences").authority == ContextAuthority.USER_STATE
    assert projection.section("target_job").authority == ContextAuthority.BUSINESS_STATE
