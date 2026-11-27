from __future__ import annotations

from typing import Any, Callable, Mapping

from fastapi import FastAPI, HTTPException
from pydantic import Field

from job_agent.career.durable import DurableJob, JDSnapshot
from job_agent.career.workspace import JobImportRecord, JobQuery, JobWorkspaceService, WorkspaceStatus
from job_agent.schemas import StrictModel


class StatusRequest(StrictModel):
    action_id: str = Field(min_length=1)


class CompareRequest(StrictModel):
    job_ids: list[str] = Field(min_length=2, max_length=5)


class BatchRequest(StrictModel):
    filters: JobQuery = Field(default_factory=JobQuery)
    max_jobs: int = Field(default=30, ge=1, le=100)
    batch_id: str | None = None


def create_job_workspace_app(
    service: JobWorkspaceService,
    *,
    analyzer: Callable[[DurableJob, JDSnapshot], Mapping[str, Any] | Any] | None = None,
) -> FastAPI:
    """Small HTTP surface over the same workspace service used by Runtime tools."""

    app = FastAPI(title="Job Workspace API", version="1.0")

    @app.post("/jobs/import")
    def import_job(record: JobImportRecord) -> dict[str, Any]:
        return service.import_record(record).model_dump(mode="json")

    @app.get("/jobs")
    def list_jobs(
        company: str | None = None,
        title_keyword: str | None = None,
        location: str | None = None,
        employment_type: str | None = None,
        job_family: str | None = None,
        workspace_status: str | None = None,
        analysis_status: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = JobQuery(
            company=company,
            title_keyword=title_keyword,
            location=location,
            employment_type=employment_type,
            job_family=job_family,
            workspace_status=workspace_status,
            analysis_status=analysis_status,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
        return [item.model_dump(mode="json") for item in service.list_jobs(query)]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            return service.repository.get_state(job_id).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job_not_found") from exc

    def change_status(job_id: str, request: StatusRequest, status: WorkspaceStatus) -> dict[str, Any]:
        try:
            return service.update_workspace_status(
                job_id=job_id,
                status=status,
                action_id=request.action_id,
                source="workspace-api",
            ).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job_not_found") from exc

    @app.post("/jobs/{job_id}/shortlist")
    def shortlist(job_id: str, request: StatusRequest) -> dict[str, Any]:
        return change_status(job_id, request, WorkspaceStatus.SHORTLISTED)

    @app.post("/jobs/{job_id}/archive")
    def archive(job_id: str, request: StatusRequest) -> dict[str, Any]:
        return change_status(job_id, request, WorkspaceStatus.ARCHIVED)

    @app.post("/jobs/compare")
    def compare(request: CompareRequest) -> dict[str, Any]:
        return service.compare(request.job_ids).model_dump(mode="json")

    @app.post("/jobs/batch-analysis")
    def batch_analysis(request: BatchRequest) -> dict[str, Any]:
        if analyzer is None:
            raise HTTPException(status_code=503, detail="analysis_backend_unavailable")
        batch_id = request.batch_id or service.create_batch(filters=request.filters, max_jobs=request.max_jobs).batch_id
        return service.run_batch(batch_id, analyzer).model_dump(mode="json")

    return app
