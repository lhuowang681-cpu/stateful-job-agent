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
    AgentStepRecord,
    ApprovalDecision,
    ToolContext,
    ToolEffect,
    ToolObservationStatus,
    VerificationResult,
)
from job_agent.agent_runtime.loop import AgentLoop, ScriptedAgentModel
from job_agent.agent_runtime.policy import (
    PolicyContext,
    PolicyEngine,
    compute_action_digest,
)
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.agent_runtime.trajectory import (
    InMemoryTrajectory,
    TrajectorySink,
)
from job_agent.schemas import (
    ApplicationRecord,
    ApplicationStatus,
    StrictModel,
)
from job_agent.tools.application_tracker import ApplicationTrackerStore


RECORD_APPLICATION_TOOL = "application.record"


class ApplicationTrackingRequest(StrictModel):
    job_id: str | None = None
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    city: str = "unknown"
    source: str = "manual"
    jd_reference: str = ""
    initial_stage: ApplicationStatus = ApplicationStatus.TO_APPLY
    notes: str = ""


class RecordApplicationOutput(StrictModel):
    application: ApplicationRecord
    tracker_revision: int = Field(ge=0)
    tracker_updated: str
    created: bool


def build_application_tracking_registry(
    tracker_store: ApplicationTrackerStore,
    *,
    user_id: str,
) -> ToolRegistry:
    registry = ToolRegistry()

    def record_application(
        value: ApplicationTrackingRequest,
        context: ToolContext,
    ) -> RecordApplicationOutput:
        before = tracker_store.load(user_id=user_id)
        existing = tracker_store.find_application(
            user_id=user_id,
            job_id=value.job_id,
            company=value.company,
            title=value.title,
        )
        application = tracker_store.record_application(
            user_id=user_id,
            job_id=value.job_id,
            company=value.company,
            title=value.title,
            city=value.city,
            source=value.source,
            url=value.jd_reference,
            initial_status=value.initial_stage,
            notes=value.notes,
            user_confirmed=True,
        )
        after = tracker_store.load(user_id=user_id)
        return RecordApplicationOutput(
            application=application,
            tracker_revision=after.revision,
            tracker_updated=after.updated,
            created=existing is None and after.revision > before.revision,
        )

    registry.register(
        name=RECORD_APPLICATION_TOOL,
        description=(
            "Record one approved job in the canonical local application tracker."
        ),
        input_model=ApplicationTrackingRequest,
        output_model=RecordApplicationOutput,
        handler=record_application,
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
    )
    return registry


class _ApplicationTrackingVerifier:
    def verify(
        self,
        finish: AgentFinish,
        *,
        goal: dict,
        steps: Sequence[AgentStepRecord],
    ) -> VerificationResult:
        expected = ApplicationTrackingRequest.model_validate(goal)
        outputs = [
            RecordApplicationOutput.model_validate(step.observation.data)
            for step in steps
            if step.action.tool_name == RECORD_APPLICATION_TOOL
            and step.observation.status == ToolObservationStatus.OK
        ]
        if not outputs:
            return VerificationResult(
                passed=False,
                reason_code="application_record_not_observed",
                feedback="Record the application through the governed tool.",
            )
        application = outputs[-1].application
        if (
            application.job_id != expected.job_id
            or application.title != expected.title.strip()
            or application.company != expected.company.strip()
        ):
            return VerificationResult(
                passed=False,
                reason_code="application_record_mismatch",
                feedback="Use the application returned by the record tool.",
            )
        return VerificationResult(
            passed=True,
            reason_code="application_recorded",
            feedback="The application write is grounded in the tool observation.",
            evidence_refs=[f"application:{application.id}"],
        )


class GovernedApplicationTrackingFlow:
    def __init__(
        self,
        *,
        tracker_store: ApplicationTrackerStore,
        user_id: str,
        checkpoint_store: CheckpointStore,
        allow_write: bool = True,
        trajectory: TrajectorySink | None = None,
    ) -> None:
        self.tracker_store = tracker_store
        self.user_id = user_id
        self.checkpoint_store = checkpoint_store
        self.registry = build_application_tracking_registry(
            tracker_store,
            user_id=user_id,
        )
        self.trajectory = trajectory or InMemoryTrajectory()
        allowed = (RECORD_APPLICATION_TOOL,) if allow_write else ()
        self.policy_context = PolicyContext(
            skill_allowed_tools=(RECORD_APPLICATION_TOOL,),
            agent_allowed_tools=(RECORD_APPLICATION_TOOL,),
            runtime_allowed_tools=allowed,
            target_summary="canonical local application tracker",
            arguments_preview_keys=(
                "job_id",
                "title",
                "company",
                "initial_stage",
            ),
        )

    def start(
        self,
        request: ApplicationTrackingRequest,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
    ) -> AgentRunResult:
        action = self.action_for(request)
        return self._run(
            request=request,
            model=ScriptedAgentModel([action, _finish()]),
            session_id=session_id,
            run_id=run_id,
            workspace_root=workspace_root,
        )

    def resume(
        self,
        request: ApplicationTrackingRequest,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
        approval: ApprovalDecision,
    ) -> AgentRunResult:
        action = self.action_for(request)
        return self._run(
            request=request,
            model=ScriptedAgentModel([_finish()]),
            session_id=session_id,
            run_id=run_id,
            workspace_root=workspace_root,
            approvals={compute_action_digest(action): approval},
            resume=True,
        )

    def readback(
        self,
        request: ApplicationTrackingRequest,
    ) -> ApplicationRecord | None:
        return self.tracker_store.find_application(
            user_id=self.user_id,
            job_id=request.job_id,
            company=request.company,
            title=request.title,
        )

    @staticmethod
    def action_for(request: ApplicationTrackingRequest) -> AgentAction:
        arguments = request.model_dump(mode="json")
        encoded = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return AgentAction(
            action_id=f"record-application-{digest[:16]}",
            tool_name=RECORD_APPLICATION_TOOL,
            tool_arguments=arguments,
            expected_observation="persisted application record and tracker revision",
            progress_claim="record the user-approved job in application state",
        )

    def _run(
        self,
        *,
        request: ApplicationTrackingRequest,
        model: ScriptedAgentModel,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
        approvals: Mapping[str, ApprovalDecision] | None = None,
        resume: bool = False,
    ) -> AgentRunResult:
        loop = AgentLoop(
            agent_id="application-tracking",
            model=model,
            registry=self.registry,
            policy=PolicyEngine(),
            policy_context=self.policy_context,
            budget=BudgetManager(
                AgentBudget.for_profile(BudgetProfile.QUICK)
            ),
            verifier=_ApplicationTrackingVerifier(),
            trajectory=self.trajectory,
            checkpoint_store=self.checkpoint_store,
            skill_version="application-tracking-v1",
            prompt_version="application-tracking-controller-v1",
        )
        return loop.run(
            session_id=session_id,
            run_id=run_id,
            goal=request.model_dump(mode="json"),
            tool_context=ToolContext(
                session_id=session_id,
                run_id=run_id,
                agent_id="application-tracking",
                workspace_root=str(Path(workspace_root).resolve()),
            ),
            approvals=approvals,
            resume=resume,
        )
def _finish() -> AgentFinish:
    return AgentFinish(
        result={"application_recorded": True},
        completion_evidence=["application.record tool observation"],
        confidence=1.0,
    )
