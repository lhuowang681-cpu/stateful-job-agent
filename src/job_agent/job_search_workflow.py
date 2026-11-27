from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from job_agent.agent_runtime.contracts import (
    AgentRunResult,
    AgentRunStatus,
    ApprovalDecision,
    ApprovalRequest,
)
from job_agent.domain_agents.application_lifecycle import (
    APPLY_TRANSITION_TOOL,
    READ_TRACKER_TOOL,
    ApplicationStageUpdate,
    GovernedApplicationLifecycleFlow,
)
from job_agent.domain_agents.application_tracking import (
    RECORD_APPLICATION_TOOL,
    ApplicationTrackingRequest,
    GovernedApplicationTrackingFlow,
)
from job_agent.career.durable import DurableCareerRepository
from job_agent.interview.contracts import JobSpecificInterviewPreparation
from job_agent.interview.preparation import (
    JobSpecificInterviewPreparationService,
)
from job_agent.jd_match_analysis import JobBasicInfo, JobMatchAnalysis
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.memory_aware_job_analysis import MemoryAwareJobAnalysisService
from job_agent.schemas import ApplicationRecord, ApplicationStatus, StrictModel
from job_agent.tools.application_tracker import ApplicationTrackerStore


class JobSearchWorkflowRequest(StrictModel):
    job_id: str
    company: str
    jd: JobBasicInfo
    source: str = "synthetic-jd"
    jd_reference: str = ""


class ApprovalResolver(Protocol):
    def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        ...


class WorkflowRuntimeSummary(StrictModel):
    analysis_mcp_actions: int
    tracking_write_actions: int
    lifecycle_read_actions: int
    lifecycle_write_actions: int
    interview_prep_mcp_actions: int


@dataclass(frozen=True)
class JobSearchWorkflowResult:
    request: JobSearchWorkflowRequest
    analysis: JobMatchAnalysis
    application: ApplicationRecord
    interview_preparation: JobSpecificInterviewPreparation
    runtime: WorkflowRuntimeSummary

    def demo_artifact(self) -> dict:
        preference = self.analysis.preference_analysis
        evidence_requirements = [
            item.atom.text
            for item in self.analysis.requirements
            if item.evidence_items
        ]
        gap_requirements = [
            item.atom.text
            for item in self.analysis.requirements
            if not item.evidence_items
        ]
        history = [
            event.state.value for event in self.application.state_history
        ]
        questions = self.interview_preparation.evidence_backed_questions
        document_ids = list(
            dict.fromkeys(
                question.provenance.document_id for question in questions
            )
        )
        return {
            "user_profile": {
                "preferred_city": (
                    preference.city.preferred if preference else None
                ),
                "target_role": (
                    preference.role.preferred if preference else None
                ),
                "job_type": (
                    preference.job_type.preferred if preference else None
                ),
            },
            "job": {
                "job_id": self.request.job_id,
                "company": self.request.company,
                "title": self.request.jd.title,
                "source": self.request.source,
            },
            "analysis": {
                "preference_fit": {
                    "city": preference.city.fit if preference else None,
                    "role": preference.role.fit if preference else None,
                    "job_type": preference.job_type.fit if preference else None,
                },
                "evidence_backed_requirements": evidence_requirements,
                "gaps": gap_requirements,
            },
            "application": {
                "current_stage": self.application.current_state.value,
                "history": history,
            },
            "interview_prep": {
                "evidence_backed_questions": [
                    question.topic for question in questions
                ],
                "risks": [
                    risk.requirement_text
                    for risk in self.interview_preparation.gap_risks
                ],
                "technical_review": [
                    topic.topic
                    for topic in (
                        self.interview_preparation.technical_review_topics
                    )
                ],
            },
            "provenance": {
                "question_count": len(questions),
                "document_ids": document_ids,
                "source_spans_valid": all(
                    question.provenance.end_offset
                    > question.provenance.start_offset
                    and bool(question.provenance.exact_quote)
                    for question in questions
                ),
            },
            "runtime": {
                "analysis_mcp": {
                    "tool": CAREER_QUERY_TOOL,
                    "actions": self.runtime.analysis_mcp_actions,
                    "outcome": "ok",
                },
                "tracking_write": {
                    "tool": RECORD_APPLICATION_TOOL,
                    "actions": self.runtime.tracking_write_actions,
                    "outcome": "ok",
                },
                "lifecycle_read": {
                    "tool": READ_TRACKER_TOOL,
                    "actions": self.runtime.lifecycle_read_actions,
                    "outcome": "ok",
                },
                "lifecycle_write": {
                    "tool": APPLY_TRANSITION_TOOL,
                    "actions": self.runtime.lifecycle_write_actions,
                    "outcome": "ok",
                },
                "interview_prep_mcp": {
                    "tool": CAREER_QUERY_TOOL,
                    "actions": self.runtime.interview_prep_mcp_actions,
                    "outcome": "ok",
                },
            },
        }


class JobSearchWorkflowError(RuntimeError):
    pass


class JobSearchWorkflow:
    def __init__(
        self,
        *,
        analysis_service: MemoryAwareJobAnalysisService,
        tracking_flow: GovernedApplicationTrackingFlow,
        lifecycle_flow: GovernedApplicationLifecycleFlow,
        tracker_store: ApplicationTrackerStore,
        user_id: str,
        approval_resolver: ApprovalResolver,
        career_repository: DurableCareerRepository | None = None,
    ) -> None:
        self.analysis_service = analysis_service
        self.tracking_flow = tracking_flow
        self.lifecycle_flow = lifecycle_flow
        self.tracker_store = tracker_store
        self.user_id = user_id
        self.approval_resolver = approval_resolver
        self.career_repository = career_repository

    def run(
        self,
        request: JobSearchWorkflowRequest,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
    ) -> JobSearchWorkflowResult:
        durable_jd = None
        if self.career_repository is not None:
            self.career_repository.save_job(
                job_id=request.job_id,
                company=request.company,
                title=request.jd.title,
                location=request.jd.city,
                job_type=request.jd.job_type,
                source_type=request.source,
                source_uri=request.jd_reference or None,
            )
            durable_jd = self.career_repository.append_jd_snapshot(
                job_id=request.job_id,
                text=request.jd.text,
                source_uri=request.jd_reference or None,
                created_by="job_search_workflow",
            )
        knowledge_events = self.analysis_service.career_runtime.trajectory.events
        analysis_start = len(knowledge_events)
        analysis = self.analysis_service.analyze(
            jd=request.jd,
            session_id=session_id,
            run_id=f"{run_id}-analysis",
        )
        analysis_actions = _action_count(
            knowledge_events[analysis_start:],
            CAREER_QUERY_TOOL,
        )
        durable_analysis = None
        if self.career_repository is not None:
            if durable_jd is None:
                raise JobSearchWorkflowError("durable_jd_snapshot_missing")
            durable_analysis = self.career_repository.append_analysis_snapshot(
                job_id=request.job_id,
                jd_snapshot_id=durable_jd.snapshot_id,
                analysis=analysis,
                producer_run_id=f"{run_id}-analysis",
                model_metadata={"producer": "MemoryAwareJobAnalysisService"},
                provenance_refs=[f"source:{analysis.jd_source_id}"],
            )

        tracking_events = self.tracking_flow.trajectory.events
        tracking_start = len(tracking_events)
        tracking_request = ApplicationTrackingRequest(
            job_id=request.job_id,
            title=request.jd.title,
            company=request.company,
            city=request.jd.city,
            source=request.source,
            jd_reference=request.jd_reference,
            initial_stage=ApplicationStatus.TO_APPLY,
            notes="Recorded from governed JobMatchAnalysis workflow.",
        )
        waiting = self.tracking_flow.start(
            tracking_request,
            session_id=session_id,
            run_id=f"{run_id}-track",
            workspace_root=workspace_root,
        )
        completed = self._approve_tracking(
            tracking_request,
            waiting,
            session_id=session_id,
            run_id=f"{run_id}-track",
            workspace_root=workspace_root,
        )
        _require_completed(completed, "application_tracking_failed")
        application = self.tracking_flow.readback(tracking_request)
        if application is None:
            raise JobSearchWorkflowError("application_tracking_readback_missing")
        if self.career_repository is not None:
            self.career_repository.link_application(
                job_id=request.job_id,
                application_id=application.id,
            )
        tracking_actions = _action_count(
            tracking_events[tracking_start:],
            RECORD_APPLICATION_TOOL,
        )

        lifecycle_events = self.lifecycle_flow.trajectory.events
        lifecycle_start = len(lifecycle_events)
        for index, stage in enumerate(
            (
                ApplicationStatus.APPLIED,
                ApplicationStatus.RESUME_SCREEN,
                ApplicationStatus.FIRST_INTERVIEW,
            ),
            start=1,
        ):
            current = self.lifecycle_flow.query(
                application.id,
                session_id=session_id,
                run_id=f"{run_id}-stage-read-{index}",
                workspace_root=workspace_root,
            )
            update = ApplicationStageUpdate(
                application_id=application.id,
                new_status=stage,
                expected_revision=current.revision,
                notes=f"Workflow transition to {stage.value}.",
            )
            waiting = self.lifecycle_flow.start_update(
                update,
                session_id=session_id,
                run_id=f"{run_id}-stage-{index}",
                workspace_root=workspace_root,
            )
            completed = self._approve_lifecycle(
                update,
                waiting,
                session_id=session_id,
                run_id=f"{run_id}-stage-{index}",
                workspace_root=workspace_root,
            )
            _require_completed(completed, "application_lifecycle_failed")

        final_application = self.lifecycle_flow.query(
            application.id,
            session_id=session_id,
            run_id=f"{run_id}-stage-read-final",
            workspace_root=workspace_root,
        ).application
        lifecycle_slice = lifecycle_events[lifecycle_start:]

        prep_start = len(knowledge_events)
        interview_preparation = JobSpecificInterviewPreparationService(
            tracker_store=self.tracker_store,
            user_id=self.user_id,
            analyses_by_job_id={request.job_id: analysis},
            career_runtime=self.analysis_service.career_runtime,
        ).prepare(
            final_application.id,
            session_id=session_id,
            run_id=f"{run_id}-prep",
        )
        prep_actions = _action_count(
            knowledge_events[prep_start:],
            CAREER_QUERY_TOOL,
        )
        if self.career_repository is not None:
            if durable_analysis is None:
                raise JobSearchWorkflowError("durable_analysis_snapshot_missing")
            self.career_repository.append_interview_prep_snapshot(
                job_id=request.job_id,
                application_id=final_application.id,
                analysis_id=durable_analysis.analysis_id,
                application_stage_at_generation=final_application.current_state.value,
                preparation=interview_preparation,
                producer_run_id=f"{run_id}-prep",
                provenance_refs=[f"source:{analysis.jd_source_id}"],
            )

        return JobSearchWorkflowResult(
            request=request,
            analysis=analysis,
            application=final_application,
            interview_preparation=interview_preparation,
            runtime=WorkflowRuntimeSummary(
                analysis_mcp_actions=analysis_actions,
                tracking_write_actions=tracking_actions,
                lifecycle_read_actions=_action_count(
                    lifecycle_slice,
                    READ_TRACKER_TOOL,
                ),
                lifecycle_write_actions=_action_count(
                    lifecycle_slice,
                    APPLY_TRANSITION_TOOL,
                ),
                interview_prep_mcp_actions=prep_actions,
            ),
        )

    def _approve_tracking(
        self,
        request: ApplicationTrackingRequest,
        waiting: AgentRunResult,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
    ) -> AgentRunResult:
        approval = self._approval(waiting, "application_tracking_failed")
        return self.tracking_flow.resume(
            request,
            session_id=session_id,
            run_id=run_id,
            workspace_root=workspace_root,
            approval=approval,
        )

    def _approve_lifecycle(
        self,
        update: ApplicationStageUpdate,
        waiting: AgentRunResult,
        *,
        session_id: str,
        run_id: str,
        workspace_root: Path | str,
    ) -> AgentRunResult:
        approval = self._approval(waiting, "application_lifecycle_failed")
        return self.lifecycle_flow.resume_update(
            update,
            session_id=session_id,
            run_id=run_id,
            workspace_root=workspace_root,
            approval=approval,
        )

    def _approval(
        self,
        waiting: AgentRunResult,
        failure_prefix: str,
    ) -> ApprovalDecision:
        if waiting.state.status != AgentRunStatus.WAITING_FOR_USER:
            detail = waiting.error_code or waiting.state.status.value
            raise JobSearchWorkflowError(f"{failure_prefix}:{detail}")
        if waiting.pending_approval is None:
            raise JobSearchWorkflowError(f"{failure_prefix}:approval_missing")
        return self.approval_resolver(waiting.pending_approval)


def _require_completed(result: AgentRunResult, prefix: str) -> None:
    if result.state.status != AgentRunStatus.COMPLETED:
        detail = result.error_code or result.state.status.value
        raise JobSearchWorkflowError(f"{prefix}:{detail}")


def _action_count(events: Sequence, tool_name: str) -> int:
    return sum(
        event.event_type == "model_decision"
        and event.decision.kind == "action"
        and event.decision.tool_name == tool_name
        for event in events
    )
