from __future__ import annotations

from datetime import UTC, datetime

from job_agent.agent_runtime.checkpoint import JsonCheckpointStore
from job_agent.agent_runtime.contracts import (
    AgentRunStatus,
    ApprovalDecision,
    ToolObservationStatus,
)
from job_agent.agent_runtime.trajectory import InMemoryTrajectory
from job_agent.domain_agents.application_tracking import (
    RECORD_APPLICATION_TOOL,
    ApplicationTrackingRequest,
    GovernedApplicationTrackingFlow,
)
from job_agent.schemas import ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


def _request() -> ApplicationTrackingRequest:
    return ApplicationTrackingRequest(
        job_id="hangzhou-agent-intern",
        title="杭州 Agent 实习岗位",
        company="Example AI",
        city="杭州",
        source="job-analysis",
        jd_reference="career://jd/hangzhou-agent-intern",
        initial_stage=ApplicationStatus.TO_APPLY,
        notes=(
            "Preference fit; Agent/RAG/async evidence; Kubernetes gap."
        ),
    )


def _flow(tmp_path, *, allow_write=True, now=None):
    trajectory = InMemoryTrajectory()
    store = ApplicationTrackerStore(
        tmp_path / "application-tracker.json",
        now=now or (lambda: datetime.now(UTC)),
    )
    flow = GovernedApplicationTrackingFlow(
        tracker_store=store,
        user_id="candidate-1",
        checkpoint_store=JsonCheckpointStore(tmp_path / "checkpoint.json"),
        allow_write=allow_write,
        trajectory=trajectory,
    )
    return flow, store, trajectory


def _approve(waiting) -> ApprovalDecision:
    request = waiting.pending_approval
    assert request is not None
    return ApprovalDecision(
        request_id=request.request_id,
        action_digest=request.action_digest,
        approved=True,
        reason="User asked to record this job.",
        session_id=request.session_id,
        run_id=request.run_id,
    )


def _record(flow, request, tmp_path, *, run_id):
    waiting = flow.start(
        request,
        session_id="application-session",
        run_id=run_id,
        workspace_root=tmp_path,
    )
    assert waiting.state.status == AgentRunStatus.WAITING_FOR_USER
    completed = flow.resume(
        request,
        session_id="application-session",
        run_id=run_id,
        workspace_root=tmp_path,
        approval=_approve(waiting),
    )
    assert completed.state.status == AgentRunStatus.COMPLETED
    return waiting, completed


def test_approved_application_write_and_readback(tmp_path) -> None:
    fixed_now = datetime(2026, 9, 18, 9, 30, tzinfo=UTC)
    flow, store, trajectory = _flow(
        tmp_path,
        now=lambda: fixed_now,
    )
    request = _request()

    waiting = flow.start(
        request,
        session_id="application-session",
        run_id="record-hangzhou-agent",
        workspace_root=tmp_path,
    )

    assert waiting.state.status == AgentRunStatus.WAITING_FOR_USER
    assert waiting.pending_action is not None
    assert waiting.pending_action.tool_name == RECORD_APPLICATION_TOOL
    assert flow.readback(request) is None
    assert not store.canonical_path.exists()

    completed = flow.resume(
        request,
        session_id="application-session",
        run_id="record-hangzhou-agent",
        workspace_root=tmp_path,
        approval=_approve(waiting),
    )

    assert completed.state.status == AgentRunStatus.COMPLETED
    application = flow.readback(request)
    assert application is not None
    assert application.job_id == "hangzhou-agent-intern"
    assert application.title == "杭州 Agent 实习岗位"
    assert application.company == "Example AI"
    assert application.current_state == ApplicationStatus.TO_APPLY
    assert application.source == "job-analysis"
    assert application.url == "career://jd/hangzhou-agent-intern"
    assert application.state_history[0].timestamp == fixed_now.isoformat()
    tracker = store.load(user_id="candidate-1")
    assert tracker.updated == fixed_now.isoformat()
    assert tracker.stats.total == 1

    action_events = [
        event
        for event in trajectory.events
        if event.event_type == "model_decision"
        and event.decision.kind == "action"
    ]
    observed = [
        event.observation
        for event in trajectory.events
        if event.event_type == "tool_observed"
    ]
    assert len(action_events) == 1
    assert action_events[0].decision.tool_name == RECORD_APPLICATION_TOOL
    assert len(observed) == 1
    assert observed[0].status == ToolObservationStatus.OK
    assert observed[0].data["created"] is True
    assert observed[0].data["application"]["id"] == application.id


def test_policy_deny_prevents_application_write(tmp_path) -> None:
    flow, store, trajectory = _flow(tmp_path, allow_write=False)
    request = _request()

    denied = flow.start(
        request,
        session_id="application-session",
        run_id="denied-record",
        workspace_root=tmp_path,
    )

    assert denied.state.status == AgentRunStatus.FAILED
    assert flow.readback(request) is None
    assert not store.canonical_path.exists()
    observations = [
        event.observation
        for event in trajectory.events
        if event.event_type == "tool_observed"
    ]
    assert observations[0].error_code == "runtime_tool_denied"


def test_resume_and_retry_do_not_duplicate_application(tmp_path) -> None:
    flow, store, _ = _flow(tmp_path)
    request = _request()
    waiting, completed = _record(
        flow,
        request,
        tmp_path,
        run_id="first-record",
    )
    assert completed.state.status == AgentRunStatus.COMPLETED
    first_tracker = store.load(user_id="candidate-1")

    replay = flow.resume(
        request,
        session_id="application-session",
        run_id="first-record",
        workspace_root=tmp_path,
        approval=_approve(waiting),
    )
    assert replay.state.status == AgentRunStatus.FAILED
    assert replay.error_code == "checkpoint_not_found"

    retry_flow = GovernedApplicationTrackingFlow(
        tracker_store=store,
        user_id="candidate-1",
        checkpoint_store=JsonCheckpointStore(
            tmp_path / "retry-checkpoint.json"
        ),
    )
    _record(
        retry_flow,
        request,
        tmp_path,
        run_id="retry-record",
    )
    after_retry = store.load(user_id="candidate-1")

    assert len(after_retry.applications) == 1
    assert after_retry.revision == first_tracker.revision
    assert len(after_retry.applications[0].state_history) == 1
