from __future__ import annotations

from typing import Any, Callable, Mapping

from pydantic import Field

from job_agent.agent_runtime.contracts import ToolContext, ToolEffect
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.career.durable import DurableCareerRepository, DurableJob, JDSnapshot
from job_agent.career.workspace import (
    JobImportRecord,
    JobQuery,
    JobWorkspaceService,
    WorkspaceStatus,
)
from job_agent.schemas import ApplicationStatus, StrictModel
from job_agent.tools.application_tracker import ApplicationTrackerStore


IMPORT_JOB_TOOL = "job.import"
LIST_JOBS_TOOL = "job.list"
GET_JOB_TOOL = "job.get"
UPDATE_JOB_STATUS_TOOL = "job.update_workspace_status"
COMPARE_JOBS_TOOL = "job.compare"
BATCH_ANALYZE_JOBS_TOOL = "job.batch_analyze"
JOB_ANALYSIS_STATUS_TOOL = "job.analysis_status"
APPLICATION_FROM_JOB_TOOL = "application.create_from_job"


class ImportJobInput(JobImportRecord):
    pass


class ImportJobOutput(StrictModel):
    result: dict[str, Any]


class ListJobsInput(JobQuery):
    pass


class ListJobsOutput(StrictModel):
    jobs: list[dict[str, Any]]


class GetJobInput(StrictModel):
    job_id: str = Field(min_length=1)


class GetJobOutput(StrictModel):
    state: dict[str, Any]


class UpdateJobStatusInput(StrictModel):
    job_id: str = Field(min_length=1)
    status: WorkspaceStatus
    action_id: str | None = None


class UpdateJobStatusOutput(StrictModel):
    job: dict[str, Any]


class CompareJobsInput(StrictModel):
    job_ids: list[str] = Field(min_length=2, max_length=5)


class CompareJobsOutput(StrictModel):
    comparison: dict[str, Any]


class BatchAnalyzeJobsInput(StrictModel):
    filters: JobQuery = Field(default_factory=JobQuery)
    max_jobs: int = Field(default=30, ge=1, le=100)
    batch_id: str | None = None
    job_ids: list[str] | None = None


class BatchAnalyzeJobsOutput(StrictModel):
    batch: dict[str, Any]


class JobAnalysisStatusInput(StrictModel):
    job_id: str = Field(min_length=1)


class JobAnalysisStatusOutput(StrictModel):
    job_id: str
    analysis_status: str
    active_jd_version: int | None = None
    active_analysis_jd_version: int | None = None


class ApplicationFromJobInput(StrictModel):
    job_id: str = Field(min_length=1)
    initial_status: ApplicationStatus = ApplicationStatus.TO_APPLY
    notes: str = ""


class ApplicationFromJobOutput(StrictModel):
    handoff: dict[str, Any]


def build_job_workspace_registry(
    repository: DurableCareerRepository,
    tracker_store: ApplicationTrackerStore,
    *,
    user_id: str,
    analyzer: Callable[[DurableJob, JDSnapshot], Mapping[str, Any] | Any] | None = None,
) -> ToolRegistry:
    service = JobWorkspaceService(repository)
    registry = ToolRegistry()

    registry.register(
        name=IMPORT_JOB_TOOL,
        description="Import or update a real job and immutable JD snapshot in the durable job workspace.",
        input_model=ImportJobInput,
        output_model=ImportJobOutput,
        handler=lambda value, _context: ImportJobOutput(
            result=service.import_record(JobImportRecord.model_validate(value.model_dump())).model_dump(mode="json")
        ),
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
        requires_approval=True,
    )

    registry.register(
        name=LIST_JOBS_TOOL,
        description="List and deterministically filter jobs in the durable workspace.",
        input_model=ListJobsInput,
        output_model=ListJobsOutput,
        handler=lambda value, _context: ListJobsOutput(
            jobs=[item.model_dump(mode="json") for item in service.list_jobs(JobQuery.model_validate(value.model_dump()))]
        ),
        effect=ToolEffect.READ_ONLY,
        idempotent=True,
        requires_approval=False,
    )

    def get_job(value: GetJobInput, _context: ToolContext) -> GetJobOutput:
        state = repository.get_state(value.job_id)
        return GetJobOutput(state=state.model_dump(mode="json"))

    registry.register(
        name=GET_JOB_TOOL,
        description="Read one durable job with JD and analysis history.",
        input_model=GetJobInput,
        output_model=GetJobOutput,
        handler=get_job,
        effect=ToolEffect.READ_ONLY,
        idempotent=True,
        requires_approval=False,
    )

    def update_status(value: UpdateJobStatusInput, context: ToolContext) -> UpdateJobStatusOutput:
        job = service.update_workspace_status(
            job_id=value.job_id,
            status=value.status,
            action_id=value.action_id or f"{context.run_id}:{value.job_id}:{value.status.value}",
            source=f"runtime:{context.agent_id}",
        )
        return UpdateJobStatusOutput(job=job.model_dump(mode="json"))

    registry.register(
        name=UPDATE_JOB_STATUS_TOOL,
        description="Explicitly shortlist, unshortlist-equivalent, archive, or restore a workspace job.",
        input_model=UpdateJobStatusInput,
        output_model=UpdateJobStatusOutput,
        handler=update_status,
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
        requires_approval=True,
    )

    registry.register(
        name=COMPARE_JOBS_TOOL,
        description="Compare two to five analyzed jobs without inventing a composite score.",
        input_model=CompareJobsInput,
        output_model=CompareJobsOutput,
        handler=lambda value, _context: CompareJobsOutput(
            comparison=service.compare(value.job_ids).model_dump(mode="json")
        ),
        effect=ToolEffect.READ_ONLY,
        idempotent=True,
        requires_approval=False,
    )

    def batch_analyze(value: BatchAnalyzeJobsInput, _context: ToolContext) -> BatchAnalyzeJobsOutput:
        if analyzer is None:
            raise ValueError("job analysis backend is unavailable")
        batch_id = value.batch_id or service.create_batch(
            filters=value.filters,
            max_jobs=value.max_jobs,
            job_ids=value.job_ids,
        ).batch_id
        result = service.run_batch(batch_id, analyzer)
        return BatchAnalyzeJobsOutput(batch=result.model_dump(mode="json"))

    registry.register(
        name=BATCH_ANALYZE_JOBS_TOOL,
        description="Create or resume a bounded durable job-analysis batch.",
        input_model=BatchAnalyzeJobsInput,
        output_model=BatchAnalyzeJobsOutput,
        handler=batch_analyze,
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        timeout_s=300.0,
        idempotent=True,
        requires_approval=True,
    )

    def analysis_status(value: JobAnalysisStatusInput, _context: ToolContext) -> JobAnalysisStatusOutput:
        state = repository.get_state(value.job_id)
        return JobAnalysisStatusOutput(
            job_id=value.job_id,
            analysis_status=state.job.analysis_status,
            active_jd_version=state.latest_jd.version if state.latest_jd else None,
            active_analysis_jd_version=(state.latest_analysis.jd_snapshot_version if state.latest_analysis else None),
        )

    registry.register(
        name=JOB_ANALYSIS_STATUS_TOOL,
        description="Read whether a job is unanalyzed, current, stale, or failed.",
        input_model=JobAnalysisStatusInput,
        output_model=JobAnalysisStatusOutput,
        handler=analysis_status,
        effect=ToolEffect.READ_ONLY,
        idempotent=True,
        requires_approval=False,
    )

    def application_from_job(value: ApplicationFromJobInput, _context: ToolContext) -> ApplicationFromJobOutput:
        handoff = service.handoff_to_application(
            job_id=value.job_id,
            tracker=tracker_store,
            user_id=user_id,
            initial_status=value.initial_status,
            notes=value.notes,
        )
        return ApplicationFromJobOutput(handoff=handoff.model_dump(mode="json"))

    registry.register(
        name=APPLICATION_FROM_JOB_TOOL,
        description="Create one canonical application from an explicitly selected workspace job.",
        input_model=ApplicationFromJobInput,
        output_model=ApplicationFromJobOutput,
        handler=application_from_job,
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
        requires_approval=True,
    )
    return registry
