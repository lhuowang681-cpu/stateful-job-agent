from __future__ import annotations

from job_agent.agent_runtime.checkpoint import JsonCheckpointStore
from job_agent.agent_runtime.contracts import (
    AgentRunStatus,
    ApprovalDecision,
    ToolObservationStatus,
)
from job_agent.agent_runtime.trajectory import InMemoryTrajectory
from job_agent.domain_agents.application_lifecycle import (
    APPLY_TRANSITION_TOOL,
    READ_TRACKER_TOOL,
    ApplicationStageUpdate,
    GovernedApplicationLifecycleFlow,
)
from job_agent.domain_agents.application_tracking import (
    ApplicationTrackingRequest,
    GovernedApplicationTrackingFlow,
)
from job_agent.schemas import ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


def _approval(waiting) -> ApprovalDecision:
    request = waiting.pending_approval
    assert request is not None
    return ApprovalDecision(
        request_id=request.request_id,
        action_digest=request.action_digest,
        approved=True,
        reason="User confirmed the application stage change.",
        session_id=request.session_id,
        run_id=request.run_id,
    )


def _seed_application(tmp_path):
    store = ApplicationTrackerStore(tmp_path / "application-tracker.json")
    request = ApplicationTrackingRequest(
        job_id="hangzhou-agent-intern",
        title="杭州 Agent 实习岗位",
        company="Example AI",
        city="杭州",
        source="job-analysis",
        jd_reference="career://jd/hangzhou-agent-intern",
        initial_stage=ApplicationStatus.TO_APPLY,
    )
    tracking = GovernedApplicationTrackingFlow(
        tracker_store=store,
        user_id="candidate-1",
        checkpoint_store=JsonCheckpointStore(
            tmp_path / "record-checkpoint.json"
        ),
    )
    waiting = tracking.start(
        request,
        session_id="application-session",
        run_id="record-application",
        workspace_root=tmp_path,
    )
    completed = tracking.resume(
        request,
        session_id="application-session",
        run_id="record-application",
        workspace_root=tmp_path,
        approval=_approval(waiting),
    )
    assert completed.state.status == AgentRunStatus.COMPLETED
    application = tracking.readback(request)
    assert application is not None
    return store, application.id


def _lifecycle(tmp_path, store, *, allow_write=True):
    trajectory = InMemoryTrajectory()
    flow = GovernedApplicationLifecycleFlow(
        tracker_store=store,
        user_id="candidate-1",
        checkpoint_store=JsonCheckpointStore(
            tmp_path / "lifecycle-checkpoint.json"
        ),
        allow_write=allow_write,
        trajectory=trajectory,
    )
    return flow, trajectory


def _query(flow, application_id, tmp_path, run_id):
    return flow.query(
        application_id,
        session_id="application-session",
        run_id=run_id,
        workspace_root=tmp_path,
    )


def _start_update(flow, update, tmp_path, run_id):
    return flow.start_update(
        update,
        session_id="application-session",
        run_id=run_id,
        workspace_root=tmp_path,
    )


def _resume_update(flow, update, waiting, tmp_path, run_id):
    return flow.resume_update(
        update,
        session_id="application-session",
        run_id=run_id,
        workspace_root=tmp_path,
        approval=_approval(waiting),
    )


def test_governed_application_lifecycle_preserves_history(tmp_path) -> None:
    store, application_id = _seed_application(tmp_path)
    flow, trajectory = _lifecycle(tmp_path, store)

    initial = _query(
        flow,
        application_id,
        tmp_path,
        "query-initial",
    )
    assert initial.application.current_state == ApplicationStatus.TO_APPLY
    assert [
        event.state for event in initial.application.state_history
    ] == [ApplicationStatus.TO_APPLY]

    apply_update = ApplicationStageUpdate(
        application_id=application_id,
        new_status=ApplicationStatus.APPLIED,
        expected_revision=initial.revision,
        notes="User confirmed the application was submitted.",
    )
    waiting = _start_update(
        flow,
        apply_update,
        tmp_path,
        "update-applied",
    )
    assert waiting.state.status == AgentRunStatus.WAITING_FOR_USER
    assert store.load(user_id="candidate-1").applications[
        0
    ].current_state == ApplicationStatus.TO_APPLY
    completed = _resume_update(
        flow,
        apply_update,
        waiting,
        tmp_path,
        "update-applied",
    )
    assert completed.state.status == AgentRunStatus.COMPLETED

    applied = _query(
        flow,
        application_id,
        tmp_path,
        "query-applied",
    )
    assert applied.application.current_state == ApplicationStatus.APPLIED

    screening_update = ApplicationStageUpdate(
        application_id=application_id,
        new_status=ApplicationStatus.RESUME_SCREEN,
        expected_revision=applied.revision,
        notes="Resume screening recorded before the interview stage.",
    )
    screening_waiting = _start_update(
        flow,
        screening_update,
        tmp_path,
        "update-resume-screen",
    )
    screening_completed = _resume_update(
        flow,
        screening_update,
        screening_waiting,
        tmp_path,
        "update-resume-screen",
    )
    assert screening_completed.state.status == AgentRunStatus.COMPLETED
    screened = _query(
        flow,
        application_id,
        tmp_path,
        "query-resume-screen",
    )

    interview_update = ApplicationStageUpdate(
        application_id=application_id,
        new_status=ApplicationStatus.FIRST_INTERVIEW,
        expected_revision=screened.revision,
        notes="First interview invitation received.",
    )
    interview_waiting = _start_update(
        flow,
        interview_update,
        tmp_path,
        "update-first-interview",
    )
    interview_completed = _resume_update(
        flow,
        interview_update,
        interview_waiting,
        tmp_path,
        "update-first-interview",
    )
    assert interview_completed.state.status == AgentRunStatus.COMPLETED

    final = _query(
        flow,
        application_id,
        tmp_path,
        "query-final",
    )
    assert final.application.current_state == ApplicationStatus.FIRST_INTERVIEW
    assert [
        event.state for event in final.application.state_history
    ] == [
        ApplicationStatus.TO_APPLY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.RESUME_SCREEN,
        ApplicationStatus.FIRST_INTERVIEW,
    ]
    assert final.application.company == "Example AI"
    assert final.application.source == "job-analysis"
    assert all(event.timestamp for event in final.application.state_history)

    read_actions = [
        event
        for event in trajectory.events
        if event.event_type == "model_decision"
        and event.decision.kind == "action"
        and event.decision.tool_name == READ_TRACKER_TOOL
    ]
    update_results = [
        event.observation
        for event in trajectory.events
        if event.event_type == "tool_observed"
        and event.observation.tool_name == APPLY_TRANSITION_TOOL
        and event.observation.status == ToolObservationStatus.OK
    ]
    assert len(read_actions) == 4
    assert len(update_results) == 3


def test_policy_deny_and_pending_approval_leave_stage_unchanged(
    tmp_path,
) -> None:
    store, application_id = _seed_application(tmp_path)
    allowed, _ = _lifecycle(tmp_path / "allowed", store)
    initial = _query(
        allowed,
        application_id,
        tmp_path,
        "read-for-pending",
    )
    update = ApplicationStageUpdate(
        application_id=application_id,
        new_status=ApplicationStatus.APPLIED,
        expected_revision=initial.revision,
    )
    waiting = _start_update(
        allowed,
        update,
        tmp_path,
        "pending-update",
    )
    assert waiting.state.status == AgentRunStatus.WAITING_FOR_USER
    assert store.load(user_id="candidate-1").applications[
        0
    ].current_state == ApplicationStatus.TO_APPLY

    denied, trajectory = _lifecycle(
        tmp_path / "denied",
        store,
        allow_write=False,
    )
    denied_result = _start_update(
        denied,
        update,
        tmp_path,
        "denied-update",
    )
    assert denied_result.state.status == AgentRunStatus.FAILED
    assert store.load(user_id="candidate-1").applications[
        0
    ].current_state == ApplicationStatus.TO_APPLY
    observations = [
        event.observation
        for event in trajectory.events
        if event.event_type == "tool_observed"
    ]
    assert observations[0].error_code == "runtime_tool_denied"


def test_duplicate_retry_does_not_append_transition(tmp_path) -> None:
    store, application_id = _seed_application(tmp_path)
    flow, trajectory = _lifecycle(tmp_path, store)
    initial = _query(flow, application_id, tmp_path, "read-for-update")
    update = ApplicationStageUpdate(
        application_id=application_id,
        new_status=ApplicationStatus.APPLIED,
        expected_revision=initial.revision,
    )
    waiting = _start_update(flow, update, tmp_path, "update-once")
    completed = _resume_update(
        flow,
        update,
        waiting,
        tmp_path,
        "update-once",
    )
    assert completed.state.status == AgentRunStatus.COMPLETED
    after_first = _query(flow, application_id, tmp_path, "read-after-first")

    replay = _resume_update(
        flow,
        update,
        waiting,
        tmp_path,
        "update-once",
    )
    assert replay.state.status == AgentRunStatus.FAILED
    assert replay.error_code == "checkpoint_not_found"

    same_stage = ApplicationStageUpdate(
        application_id=application_id,
        new_status=ApplicationStatus.APPLIED,
        expected_revision=after_first.revision,
    )
    same_waiting = _start_update(
        flow,
        same_stage,
        tmp_path,
        "same-stage-update",
    )
    same_completed = _resume_update(
        flow,
        same_stage,
        same_waiting,
        tmp_path,
        "same-stage-update",
    )
    assert same_completed.state.status == AgentRunStatus.COMPLETED
    after_retry = _query(flow, application_id, tmp_path, "read-after-retry")

    assert after_retry.revision == after_first.revision
    assert [
        event.state for event in after_retry.application.state_history
    ] == [ApplicationStatus.TO_APPLY, ApplicationStatus.APPLIED]
    successful_updates = [
        event.observation
        for event in trajectory.events
        if event.event_type == "tool_observed"
        and event.observation.tool_name == APPLY_TRANSITION_TOOL
        and event.observation.status == ToolObservationStatus.OK
    ]
    assert len(successful_updates) == 2


def test_illegal_transition_is_rejected_by_existing_tracker_rules(
    tmp_path,
) -> None:
    store, application_id = _seed_application(tmp_path)
    flow, trajectory = _lifecycle(tmp_path, store)
    initial = _query(flow, application_id, tmp_path, "read-before-illegal")
    update = ApplicationStageUpdate(
        application_id=application_id,
        new_status=ApplicationStatus.OFFER,
        expected_revision=initial.revision,
    )
    waiting = _start_update(flow, update, tmp_path, "illegal-update")
    failed = _resume_update(
        flow,
        update,
        waiting,
        tmp_path,
        "illegal-update",
    )

    assert failed.state.status == AgentRunStatus.FAILED
    current = store.load(user_id="candidate-1").applications[0]
    assert current.current_state == ApplicationStatus.TO_APPLY
    assert [event.state for event in current.state_history] == [
        ApplicationStatus.TO_APPLY
    ]
    observations = [
        event.observation
        for event in trajectory.events
        if event.event_type == "tool_observed"
        and event.observation.tool_name == APPLY_TRANSITION_TOOL
    ]
    assert observations[-1].error_code == "tool_execution_error"
