from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from job_agent.agent_runtime import AgentAction, ApprovalDecision, ToolContext
from job_agent.agent_runtime.policy import PolicyContext, PolicyEngine
from job_agent.agent_runtime.tool_executor import ToolExecutor
from job_agent.agent_runtime.contracts import ToolObservationStatus
from job_agent.career.durable import DurableCareerRepository
from job_agent.career.workspace import (
    AnalysisStatus,
    ImportStatus,
    JobImportRecord,
    JobQuery,
    JobWorkspaceService,
    WorkspaceStatus,
)
from job_agent.career.workspace_api import create_job_workspace_app
from job_agent.career.workspace_tools import (
    APPLICATION_FROM_JOB_TOOL,
    COMPARE_JOBS_TOOL,
    GET_JOB_TOOL,
    IMPORT_JOB_TOOL,
    LIST_JOBS_TOOL,
    UPDATE_JOB_STATUS_TOOL,
    ApplicationFromJobInput,
    ImportJobInput,
    UpdateJobStatusInput,
    build_job_workspace_registry,
)
from job_agent.agent_runtime.contracts import ToolEffect
from job_agent.agent_runtime.interaction_context import (
    ConversationState,
    ReferentEntityType,
    ReferentResolutionStatus,
    ReferentResolver,
)
from job_agent.knowledge.durable import KnowledgeRepository
from job_agent.schemas import ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


def _record(
    identifier: str,
    *,
    company: str = "Example AI",
    title: str = "Agent Runtime Engineer",
    location: str = "Shanghai",
    text: str = "Build agent runtime and RAG systems. Kubernetes is required.",
    url: str | None = None,
) -> JobImportRecord:
    return JobImportRecord(
        company=company,
        title=title,
        location=location,
        employment_type="full-time",
        source_type="greenhouse",
        source_identifier=identifier,
        source_url=url or f"https://boards.example.test/jobs/{identifier}?utm_source=test",
        lineage="new-R13",
        jd_text=text,
    )


def _analysis(job, jd):
    return {
        "preference_analysis": {"location": job.location},
        "requirements": [
            {"text": "Agent Runtime", "status": "supported", "evidence": [{"source_id": "src-runtime"}]},
            {"text": "Kubernetes", "status": "gap", "evidence": []},
        ],
        "summary": {
            "evidence_backed_strengths": ["Agent Runtime"],
            "gaps": ["Kubernetes"],
        },
    }


def _service(tmp_path: Path):
    repository = DurableCareerRepository.open(tmp_path)
    return repository, JobWorkspaceService(repository)


def test_import_identity_tiers_versions_staleness_and_diff(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    first = service.import_record(_record("source-1"))
    assert first.status == ImportStatus.IMPORTED
    same_source = service.import_record(_record("source-1"))
    assert same_source.status == ImportStatus.UNCHANGED
    assert same_source.job_id == first.job_id

    same_url = service.import_record(
        _record("different-source", url="https://boards.example.test/jobs/source-1/")
    )
    assert same_url.status == ImportStatus.UNCHANGED
    assert same_url.job_id == first.job_id

    same_hash = service.import_record(
        JobImportRecord(
            company="Other display",
            title="Different title",
            location="Hangzhou",
            source_type="manual",
            lineage="new-R13",
            jd_text="Build agent runtime and RAG systems. Kubernetes is required.",
        )
    )
    assert same_hash.status == ImportStatus.UNCHANGED
    assert same_hash.job_id == first.job_id

    first_state = repository.get_state(first.job_id)
    analysis = repository.append_analysis_snapshot(
        job_id=first.job_id,
        jd_snapshot_id=first.jd_snapshot_id,
        analysis=_analysis(first_state.job, first_state.latest_jd),
        producer_run_id="analysis-v1",
    )
    assert service.get_job(first.job_id).analysis_status == AnalysisStatus.CURRENT.value
    updated = service.import_record(
        _record(
            "source-1",
            text="Build agent runtime and RAG systems. Kubernetes and MCP are required.",
        )
    )
    assert updated.status == ImportStatus.UPDATED
    assert updated.jd_version == 2
    assert service.get_job(first.job_id).analysis_status == AnalysisStatus.STALE.value
    diff = service.jd_diff(first.job_id, 1, 2)
    assert diff.added
    assert diff.removed
    state = repository.get_state(first.job_id)
    assert state.latest_analysis.analysis_id == analysis.analysis_id
    assert state.latest_analysis.jd_snapshot_version == 1
    refreshed = repository.append_analysis_snapshot(
        job_id=first.job_id,
        jd_snapshot_id=updated.jd_snapshot_id,
        analysis=_analysis(state.job, repository.get_state(first.job_id).latest_jd),
        producer_run_id="analysis-v2",
    )
    assert refreshed.jd_snapshot_version == 2
    assert service.get_job(first.job_id).analysis_status == AnalysisStatus.CURRENT.value


def test_near_duplicate_is_flagged_not_merged_and_bulk_failures_are_isolated(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    first = service.import_record(_record("one", title="Senior Agent Platform Engineer"))
    second = service.import_record(
        _record(
            "two",
            title="Sr Agent Platform Engineer",
            text="Own agent platform reliability and distributed runtime services.",
        )
    )
    assert second.status == ImportStatus.POSSIBLE_DUPLICATE
    assert second.possible_duplicate_of == first.job_id
    assert second.job_id != first.job_id

    summary = service.import_many(
        [
            _record("three", company="Another AI", title="RAG Engineer", text="Build retrieval systems."),
            {"company": "missing title", "jd_text": "invalid"},
        ]
    )
    assert summary.total == 2
    assert summary.imported == 1
    assert summary.failed == 1
    assert len(repository.list_jobs()) == 3


def test_status_search_restart_manifest_and_quality(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    shanghai = service.import_record(_record("shanghai"))
    hangzhou = service.import_record(
        _record("hangzhou", company="Acme AI", title="RAG Intern", location="Hangzhou", text="Build RAG pipelines.")
    )
    service.shortlist(job_id=shanghai.job_id, action_id="shortlist-1")
    service.shortlist(job_id=shanghai.job_id, action_id="shortlist-1")
    service.archive(job_id=hangzhou.job_id, action_id="archive-1")
    assert [item.job_id for item in service.list_jobs(JobQuery(location="Shanghai"))] == [shanghai.job_id]
    assert service.list_jobs(JobQuery(location="Hangzhou")) == []
    assert service.list_jobs(JobQuery(location="Hangzhou", include_archived=True))[0].job_id == hangzhou.job_id
    repository.close()

    reopened = DurableCareerRepository.open(tmp_path)
    restored = JobWorkspaceService(reopened)
    assert restored.get_job(shanghai.job_id).workspace_status == WorkspaceStatus.SHORTLISTED.value
    assert restored.get_job(hangzhou.job_id).workspace_status == WorkspaceStatus.ARCHIVED.value
    stats = restored.stats()
    assert stats.total_jobs == 2
    assert stats.shortlisted == 1
    assert stats.archived == 1
    assert restored.manifest().job_count == 2
    assert restored.manifest().jd_version_count == 2
    assert restored.data_quality().source_distribution == {"greenhouse": 2}


def test_batch_resume_compare_and_workspace_aggregation(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    jobs = [
        service.import_record(_record(f"batch-{index}", company=f"Company {index}", title=f"Agent Engineer {index}", text=f"Build Agent Runtime {index}. Kubernetes required."))
        for index in range(3)
    ]
    batch = service.create_batch(max_jobs=3)
    failed_once = {jobs[1].job_id}

    def flaky(job, jd):
        if job.job_id in failed_once:
            failed_once.remove(job.job_id)
            raise RuntimeError("transient provider failure")
        return _analysis(job, jd)

    first = service.run_batch(batch.batch_id, flaky)
    assert first.success == 2
    assert first.failed == 1
    assert first.batch.status == "PARTIAL"
    resumed = service.run_batch(batch.batch_id, flaky)
    assert resumed.success == 3
    assert resumed.failed == 0
    assert resumed.resumed == 1
    assert resumed.batch.status == "COMPLETED"
    assert all(service.get_job(item.job_id).analysis_status == AnalysisStatus.CURRENT.value for item in jobs)

    comparison = service.compare([item.job_id for item in jobs[:2]])
    assert comparison.common_strengths == ["agent runtime"]
    assert comparison.common_gaps == ["kubernetes"]
    assert service.aggregate_gaps()[0].job_count == 3
    assert service.aggregate_strengths()[0].evidence_examples == ["source:src-runtime"]


def test_application_handoff_is_explicit_idempotent_and_persistent(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    imported = service.import_record(_record("handoff"))
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    assert tracker.load(user_id="user-1").applications == []
    first = service.handoff_to_application(
        job_id=imported.job_id,
        tracker=tracker,
        user_id="user-1",
        initial_status=ApplicationStatus.TO_APPLY,
    )
    second = service.handoff_to_application(
        job_id=imported.job_id,
        tracker=tracker,
        user_id="user-1",
        initial_status=ApplicationStatus.TO_APPLY,
    )
    assert second == first
    assert len(tracker.load(user_id="user-1").applications) == 1
    repository.close()
    reopened = JobWorkspaceService(DurableCareerRepository.open(tmp_path))
    assert reopened.repository.get_state(imported.job_id).application_link.application_id == first.application_id


def test_registry_governance_contracts_referent_ambiguity_and_api(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    one = service.import_record(_record("ref-1", company="Anthropic", title="Agent Engineer"))
    two = service.import_record(_record("ref-2", company="Anthropic", title="RAG Engineer", text="Build RAG search."))
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    registry = build_job_workspace_registry(repository, tracker, user_id="user-1", analyzer=_analysis)
    assert set(registry.names()) >= {
        IMPORT_JOB_TOOL,
        LIST_JOBS_TOOL,
        GET_JOB_TOOL,
        UPDATE_JOB_STATUS_TOOL,
        COMPARE_JOBS_TOOL,
        APPLICATION_FROM_JOB_TOOL,
    }
    assert registry.get(LIST_JOBS_TOOL).spec.effect == ToolEffect.READ_ONLY
    assert registry.get(LIST_JOBS_TOOL).spec.requires_approval is False
    assert registry.get(UPDATE_JOB_STATUS_TOOL).spec.effect == ToolEffect.LOCAL_STATE_MUTATION
    assert registry.get(UPDATE_JOB_STATUS_TOOL).spec.requires_approval is True
    context = ToolContext(session_id="s", run_id="r", agent_id="a", workspace_root=str(tmp_path), sandbox_root=str(tmp_path))
    value = registry.get(UPDATE_JOB_STATUS_TOOL).handler(
        UpdateJobStatusInput(job_id=one.job_id, status=WorkspaceStatus.SHORTLISTED), context
    )
    assert value.job["workspace_status"] == "SHORTLISTED"
    handoff = registry.get(APPLICATION_FROM_JOB_TOOL).handler(
        ApplicationFromJobInput(job_id=one.job_id), context
    )
    assert handoff.handoff["job_id"] == one.job_id

    resolver = ReferentResolver(tracker_store=tracker, career_repository=repository)
    resolution = resolver.resolve(
        conversation=ConversationState(session_id="session-b"),
        mention="Anthropic",
        entity_type=ReferentEntityType.JOB,
        source_turn_id="turn-b",
        user_id="user-1",
    )
    assert resolution.status == ReferentResolutionStatus.AMBIGUOUS
    assert {item.entity_id for item in resolution.candidates} == {one.job_id, two.job_id}

    client = TestClient(create_job_workspace_app(service, analyzer=_analysis))
    assert client.get(f"/jobs/{one.job_id}").status_code == 200
    assert client.get("/jobs", params={"company": "Anthropic"}).status_code == 200
    assert client.post("/jobs/compare", json={"job_ids": [one.job_id, two.job_id]}).status_code == 200


def test_runtime_policy_and_approval_govern_workspace_mutation(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    imported = service.import_record(_record("governed"))
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    registry = build_job_workspace_registry(repository, tracker, user_id="user-1", analyzer=_analysis)
    tool = registry.get(UPDATE_JOB_STATUS_TOOL)
    action = AgentAction(
        action_id="shortlist-action",
        tool_name=UPDATE_JOB_STATUS_TOOL,
        tool_arguments={"job_id": imported.job_id, "status": "SHORTLISTED"},
        expected_observation="workspace job is shortlisted",
        progress_claim="shortlist through governed runtime",
    )
    denied_context = PolicyContext(
        skill_allowed_tools=registry.names(),
        agent_allowed_tools=registry.names(),
        runtime_allowed_tools=(),
    )
    denied = PolicyEngine().authorize(action, tool.spec, denied_context, session_id="s", run_id="r")
    assert denied.allowed is False
    assert denied.reason_code == "runtime_tool_denied"
    assert service.get_job(imported.job_id).workspace_status == "NEW"

    allowed_context = denied_context.model_copy(update={"runtime_allowed_tools": registry.names()})
    pending = PolicyEngine().authorize(action, tool.spec, allowed_context, session_id="s", run_id="r")
    assert pending.allowed is False
    assert pending.reason_code == "approval_required"
    assert service.get_job(imported.job_id).workspace_status == "NEW"
    request = pending.approval_request
    approval = ApprovalDecision(
        request_id=request.request_id,
        action_digest=request.action_digest,
        approved=True,
        session_id="s",
        run_id="r",
    )
    authorized = PolicyEngine().authorize(
        action,
        tool.spec,
        allowed_context,
        approval=approval,
        session_id="s",
        run_id="r",
    )
    observation = ToolExecutor(registry).execute(
        action,
        authorized,
        ToolContext(session_id="s", run_id="r", agent_id="workspace-agent", workspace_root=str(tmp_path), sandbox_root=str(tmp_path)),
    )
    assert observation.status == ToolObservationStatus.OK
    assert service.get_job(imported.job_id).workspace_status == "SHORTLISTED"
    assert repository.connection().execute("SELECT COUNT(*) FROM job_workspace_events").fetchone()[0] == 1


def test_100_plus_realistic_repository_load_and_candidate_scope_isolation(tmp_path: Path) -> None:
    repository, service = _service(tmp_path / "workspace")
    rows = [
        _record(
            f"load-{index}",
            company=f"Public Company {index}",
            title=f"AI Engineer {index}",
            location=("Shanghai" if index % 2 else "Hangzhou"),
            text=f"Public job description {index}: build AI backend, agent runtime, and retrieval systems.",
        )
        for index in range(105)
    ]
    summary = service.import_many(rows)
    assert summary.imported == 105
    assert service.stats().total_jobs == 105
    assert len(service.list_jobs(JobQuery(limit=200))) == 105
    repository.close()
    assert len(DurableCareerRepository.open(tmp_path / "workspace").list_jobs()) == 105

    evidence_repository = KnowledgeRepository(tmp_path / "candidate-evidence.sqlite")
    assert evidence_repository.list_active_documents() == []
    assert evidence_repository.list_active_candidate_chunks() == []


def test_existing_durable_job_is_backfilled_into_workspace_schema(tmp_path: Path) -> None:
    path = tmp_path / "career.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE durable_jobs(
            job_id TEXT PRIMARY KEY, company TEXT NOT NULL,
            normalized_company TEXT NOT NULL, title TEXT NOT NULL,
            location TEXT NOT NULL, job_type TEXT NOT NULL,
            source_type TEXT NOT NULL, source_uri TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE jd_snapshots(
            snapshot_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, version INTEGER NOT NULL,
            text TEXT NOT NULL, content_hash TEXT NOT NULL, source_uri TEXT,
            created_at TEXT NOT NULL, created_by TEXT NOT NULL,
            UNIQUE(job_id, version), UNIQUE(job_id, content_hash)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE analysis_snapshots(
            analysis_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, version INTEGER NOT NULL,
            jd_snapshot_id TEXT NOT NULL, producer_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
            UNIQUE(job_id, version), UNIQUE(job_id, producer_run_id)
        )
        """
    )
    connection.execute(
        "INSERT INTO durable_jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "legacy-durable-job",
            "Legacy AI",
            "legacy ai",
            "Agent Engineer",
            "Shanghai",
            "full-time",
            "manual",
            None,
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()

    repository = DurableCareerRepository.open(tmp_path)
    migrated = repository.get_job_record("legacy-durable-job")
    assert migrated.employment_type == "full-time"
    assert migrated.workspace_status == "NEW"
    assert migrated.analysis_status == "UNANALYZED"
    assert migrated.lineage == "manual"
