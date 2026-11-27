from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from pydantic import Field

from job_agent.agent_runtime.budgets import (
    AgentBudget,
    BudgetManager,
    BudgetProfile,
)
from job_agent.agent_runtime.checkpoint import CheckpointStore
from job_agent.agent_runtime.contracts import (
    AgentAction,
    AgentFinish,
    AgentRunResult,
    AgentRunStatus,
    AgentStepRecord,
    ApprovalDecision,
    ToolContext,
    ToolObservation,
    ToolObservationStatus,
    VerificationResult,
)
from job_agent.agent_runtime.loop import AgentLoop, ScriptedAgentModel
from job_agent.agent_runtime.policy import (
    PolicyContext,
    PolicyEngine,
    compute_action_digest,
)
from job_agent.agent_runtime.trajectory import InMemoryTrajectory
from job_agent.domain_agents.application_ops import (
    APPLY_TRANSITION_TOOL,
    READ_TRACKER_TOOL,
    ApplyTransitionInput,
    ReadTrackerInput,
    ReadTrackerOutput,
    build_application_ops_registry,
)
from job_agent.schemas import ApplicationStatus, StrictModel
from job_agent.tools.application_tracker import ApplicationTrackerStore


class ApplicationStageUpdate(StrictModel):
    application_id: str = Field(min_length=1)
    new_status: ApplicationStatus
    expected_revision: int = Field(ge=0)
    notes: str = ""


class _ObservedToolVerifier:
    def __init__(self, expected_tool: str) -> None:
        self.expected_tool = expected_tool

    def verify(
        self,
        finish: AgentFinish,
        *,
        goal: dict,
        steps: Sequence[AgentStepRecord],
    ) -> VerificationResult:
        observed = any(
            step.action.tool_name == self.expected_tool
            and step.observation.status == ToolObservationStatus.OK
            for step in steps
        )
        return VerificationResult(
            passed=observed,
            reason_code=(
                "application_lifecycle_complete"
                if observed
                else "application_lifecycle_not_observed"
            ),
            feedback=(
                "Application lifecycle result is grounded in the tool output."
                if observed
                else "Use the governed application lifecycle tool first."
            ),
        )


class GovernedApplicationLifecycleFlow:
    def __init__(
        self,
        *,
        tracker_store: ApplicationTrackerStore,
        user_id: str,
        checkpoint_store: CheckpointStore,
        allow_write: bool = True,
        trajectory: InMemoryTrajectory | None = None,
    ) -> None:
        self.registry = build_application_ops_registry(
            tracker_store,
            user_id=user_id,
        )
        self.checkpoint_store = checkpoint_store
        self.trajectory = trajectory or InMemoryTrajectory()
        runtime_tools = (
            (READ_TRACKER_TOOL, APPLY_TRANSITION_TOOL)
            if allow_write
            else (READ_TRACKER_TOOL,)
        )
        self.policy_context = PolicyContext(
            skill_allowed_tools=(
                READ_TRACKER_TOOL,
                APPLY_TRANSITION_TOOL,
            ),
            agent_allowed_tools=(
                READ_TRACKER_TOOL,
                APPLY_TRANSITION_TOOL,
            ),
            runtime_allowed_tools=runtime_tools,
            target_summary="canonical local application tracker stage",
            arguments_preview_keys=(
                "application_id",
                "new_status",
                "expected_revision",
            ),
        )

    def query(
        self,
        application_id: str,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
    ) -> ReadTrackerOutput:
        tool_input = ReadTrackerInput(application_id=application_id)
        action = _action(
            prefix="read-application",
            tool_name=READ_TRACKER_TOOL,
            arguments=tool_input.model_dump(mode="json"),
            expected_observation="application stage and transition history",
            progress_claim="read the tracked application lifecycle",
        )
        event_start = len(self.trajectory.events)
        result = self._run(
            goal=tool_input.model_dump(mode="json"),
            model=ScriptedAgentModel([action, _finish("application_read")]),
            expected_tool=READ_TRACKER_TOOL,
            session_id=session_id,
            run_id=run_id,
            workspace_root=workspace_root,
        )
        observation = self._latest_observation(event_start, READ_TRACKER_TOOL)
        if (
            result.state.status != AgentRunStatus.COMPLETED
            or observation is None
            or observation.status != ToolObservationStatus.OK
        ):
            error = observation.error_code if observation is not None else None
            raise RuntimeError(
                f"application lifecycle query failed: "
                f"{error or result.error_code or result.state.status.value}"
            )
        return ReadTrackerOutput.model_validate(observation.data)

    def start_update(
        self,
        update: ApplicationStageUpdate,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
    ) -> AgentRunResult:
        action = self.action_for_update(update)
        return self._run(
            goal=update.model_dump(mode="json"),
            model=ScriptedAgentModel([action, _finish("application_updated")]),
            expected_tool=APPLY_TRANSITION_TOOL,
            session_id=session_id,
            run_id=run_id,
            workspace_root=workspace_root,
        )

    def resume_update(
        self,
        update: ApplicationStageUpdate,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
        approval: ApprovalDecision,
    ) -> AgentRunResult:
        action = self.action_for_update(update)
        return self._run(
            goal=update.model_dump(mode="json"),
            model=ScriptedAgentModel([_finish("application_updated")]),
            expected_tool=APPLY_TRANSITION_TOOL,
            session_id=session_id,
            run_id=run_id,
            workspace_root=workspace_root,
            approvals={compute_action_digest(action): approval},
            resume=True,
        )

    @staticmethod
    def action_for_update(update: ApplicationStageUpdate) -> AgentAction:
        tool_input = ApplyTransitionInput(
            application_id=update.application_id,
            new_status=update.new_status,
            expected_revision=update.expected_revision,
            notes=update.notes,
        )
        return _action(
            prefix="update-application-stage",
            tool_name=APPLY_TRANSITION_TOOL,
            arguments=tool_input.model_dump(mode="json"),
            expected_observation="updated application stage and tracker revision",
            progress_claim="apply the approved application stage transition",
        )

    def _run(
        self,
        *,
        goal: dict,
        model: ScriptedAgentModel,
        expected_tool: str,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
        approvals: Mapping[str, ApprovalDecision] | None = None,
        resume: bool = False,
    ) -> AgentRunResult:
        return AgentLoop(
            agent_id="application-lifecycle",
            model=model,
            registry=self.registry,
            policy=PolicyEngine(),
            policy_context=self.policy_context,
            budget=BudgetManager(
                AgentBudget.for_profile(BudgetProfile.QUICK)
            ),
            verifier=_ObservedToolVerifier(expected_tool),
            trajectory=self.trajectory,
            checkpoint_store=self.checkpoint_store,
            skill_version="application-lifecycle-v1",
            prompt_version="application-lifecycle-controller-v1",
        ).run(
            session_id=session_id,
            run_id=run_id,
            goal=goal,
            tool_context=ToolContext(
                session_id=session_id,
                run_id=run_id,
                agent_id="application-lifecycle",
                workspace_root=str(Path(workspace_root).resolve()),
            ),
            approvals=approvals,
            resume=resume,
        )

    def _latest_observation(
        self,
        event_start: int,
        tool_name: str,
    ) -> ToolObservation | None:
        return next(
            (
                event.observation
                for event in reversed(self.trajectory.events[event_start:])
                if event.event_type == "tool_observed"
                and event.observation.tool_name == tool_name
            ),
            None,
        )


def _action(
    *,
    prefix: str,
    tool_name: str,
    arguments: dict,
    expected_observation: str,
    progress_claim: str,
) -> AgentAction:
    encoded = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return AgentAction(
        action_id=f"{prefix}-{digest[:16]}",
        tool_name=tool_name,
        tool_arguments=arguments,
        expected_observation=expected_observation,
        progress_claim=progress_claim,
    )


def _finish(result_key: str) -> AgentFinish:
    return AgentFinish(
        result={result_key: True},
        completion_evidence=["governed application lifecycle tool observation"],
        confidence=1.0,
    )
