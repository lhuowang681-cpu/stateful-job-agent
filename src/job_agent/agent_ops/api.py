from __future__ import annotations

import html
import json
from datetime import datetime

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import Field

from job_agent.agent_ops.analysis import compare_providers, trace_metrics
from job_agent.agent_ops.contracts import (
    AgentTrace,
    FailureCategory,
    MetricsSummary,
    ProviderComparison,
    ReplayResult,
    TraceQuery,
    TraceStatus,
)
from job_agent.agent_ops.replay import IncompleteReplayFixtureError, ReplayRunner
from job_agent.agent_ops.repository import SQLiteTraceRepository, TraceNotFoundError
from job_agent.schemas import StrictModel


class ReplayRequest(StrictModel):
    provider: str | None = None
    model: str | None = None


class CompareRequest(StrictModel):
    trace_ids: list[str] = Field(min_length=2, max_length=10)


def create_trace_router(repository: SQLiteTraceRepository) -> APIRouter:
    router = APIRouter()
    replay = ReplayRunner(repository)

    @router.get("/traces", response_model=list[AgentTrace])
    def list_traces(
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        session_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        capability: str | None = None,
        status: TraceStatus | None = None,
        failure: FailureCategory | None = None,
        job_id: str | None = None,
        application_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[AgentTrace]:
        return repository.list(
            TraceQuery(
                started_after=started_after,
                started_before=started_before,
                session_id=session_id,
                provider=provider,
                model=model,
                capability=capability,
                status=status,
                failure=failure,
                job_id=job_id,
                application_id=application_id,
                limit=limit,
            )
        )

    @router.get("/traces/{trace_id}", response_model=AgentTrace)
    def get_trace(trace_id: str) -> AgentTrace:
        try:
            return repository.get(trace_id)
        except TraceNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "trace_not_found"}) from exc

    @router.get("/traces/{trace_id}/steps")
    def get_steps(trace_id: str):
        return get_trace(trace_id).steps

    @router.post("/traces/{trace_id}/replay", response_model=ReplayResult)
    def replay_trace(trace_id: str, request: ReplayRequest) -> ReplayResult:
        try:
            return replay.deterministic(trace_id, provider=request.provider, model=request.model)
        except TraceNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "trace_not_found"}) from exc
        except IncompleteReplayFixtureError as exc:
            raise HTTPException(status_code=409, detail={"code": "replay_fixture_incomplete"}) from exc

    @router.post("/traces/compare", response_model=ProviderComparison)
    def compare(request: CompareRequest) -> ProviderComparison:
        try:
            traces = [repository.get(trace_id) for trace_id in request.trace_ids]
        except TraceNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"code": "trace_not_found"}) from exc
        return compare_providers(traces)

    @router.get("/traces-metrics/summary", response_model=MetricsSummary)
    @router.get("/traces/metrics/summary", response_model=MetricsSummary)
    def metrics_summary() -> MetricsSummary:
        return trace_metrics(repository.list(TraceQuery(limit=1000)))

    @router.get("/debug/traces/{trace_id}", response_class=HTMLResponse)
    def debug_trace(trace_id: str) -> str:
        trace = get_trace(trace_id)
        payload = html.escape(json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>Agent Trace</title>"
            "<style>body{font-family:system-ui;max-width:1100px;margin:2rem auto}"
            "pre{white-space:pre-wrap;background:#111;color:#eee;padding:1rem;border-radius:8px}</style>"
            f"</head><body><h1>{html.escape(trace.trace_id)}</h1><pre>{payload}</pre></body></html>"
        )

    return router


def create_trace_app(repository: SQLiteTraceRepository) -> FastAPI:
    app = FastAPI(title="Job Agent Trace Workbench", version="1.0")
    app.include_router(create_trace_router(repository))
    return app
