from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
import statistics
import uuid
from collections import Counter
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field

from job_agent.career.durable import (
    AnalysisSnapshot,
    DurableCareerRepository,
    DurableJob,
    JDSnapshot,
)
from job_agent.career.store import normalize_company_name
from job_agent.schemas import ApplicationStatus, StrictModel
from job_agent.text_identity import normalize_text, sha256_bytes
from job_agent.tools.application_tracker import ApplicationTrackerStore


class WorkspaceStatus(str, Enum):
    NEW = "NEW"
    ANALYZED = "ANALYZED"
    SHORTLISTED = "SHORTLISTED"
    ARCHIVED = "ARCHIVED"


class AnalysisStatus(str, Enum):
    UNANALYZED = "UNANALYZED"
    CURRENT = "CURRENT"
    STALE = "STALE"
    FAILED = "FAILED"


class ImportStatus(str, Enum):
    IMPORTED = "IMPORTED"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    FAILED = "FAILED"


class BatchItemStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


JOB_FAMILIES = (
    "AGENT",
    "RAG",
    "LLM_APPLICATION",
    "AI_BACKEND",
    "AI_PLATFORM",
    "MULTIMODAL",
    "MODEL_ENGINEERING",
    "AI_INFRA",
    "OTHER",
)


class JobImportRecord(StrictModel):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    jd_text: str = Field(min_length=1)
    location: str = ""
    employment_type: str = ""
    seniority: str = ""
    job_family: str | None = None
    source_type: str = Field(default="manual", min_length=1)
    source_url: str | None = None
    source_identifier: str | None = None
    lineage: str = "manual"
    captured_at: datetime | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ImportResult(StrictModel):
    status: ImportStatus
    job_id: str | None = None
    jd_snapshot_id: str | None = None
    jd_version: int | None = Field(default=None, ge=1)
    matched_by: str | None = None
    possible_duplicate_of: str | None = None
    error: str | None = None


class BulkImportSummary(StrictModel):
    total: int
    imported: int
    updated: int
    unchanged: int
    possible_duplicate: int
    failed: int
    results: list[ImportResult] = Field(default_factory=list)


class JobQuery(StrictModel):
    company: str | None = None
    title_keyword: str | None = None
    location: str | None = None
    employment_type: str | None = None
    job_family: str | None = None
    workspace_status: str | None = None
    analysis_status: str | None = None
    application_present: bool | None = None
    created_after: datetime | None = None
    include_archived: bool = False
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    sort_by: str = "created_at"
    descending: bool = True


class JDDiff(StrictModel):
    job_id: str
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class JobComparison(StrictModel):
    job_ids: list[str]
    common_requirements: list[str]
    common_strengths: list[str]
    common_gaps: list[str]
    job_specific_strengths: dict[str, list[str]]
    job_specific_gaps: dict[str, list[str]]
    preference_differences: dict[str, dict[str, Any]]
    jd_constraints: dict[str, dict[str, str]]


class AggregateItem(StrictModel):
    capability: str
    job_count: int
    example_jobs: list[str]
    evidence_examples: list[str] = Field(default_factory=list)


class BatchRun(StrictModel):
    batch_id: str
    created_at: datetime
    filters: dict[str, Any]
    job_ids: list[str]
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None


class BatchResult(StrictModel):
    batch: BatchRun
    success: int
    failed: int
    skipped: int
    resumed: int


class ApplicationHandoff(StrictModel):
    job_id: str
    application_id: str
    jd_snapshot_id: str
    jd_version: int = Field(ge=1)
    created_at: datetime


class WorkspaceStats(StrictModel):
    total_jobs: int
    active_jobs: int
    new: int
    analyzed: int
    stale: int
    shortlisted: int
    archived: int
    applications_linked: int
    family_distribution: dict[str, int]
    location_distribution: dict[str, int]


class DataQualityReport(StrictModel):
    total_jobs: int
    duplicate_rate: float
    possible_duplicates: int
    missing_company: int
    missing_title: int
    missing_location: int
    missing_employment_type: int
    jd_text_length: dict[str, float]
    source_distribution: dict[str, int]
    family_distribution: dict[str, int]


class JobCorpusManifest(StrictModel):
    corpus_version: int = Field(ge=0)
    job_count: int
    active_job_count: int
    jd_version_count: int
    source_breakdown: dict[str, int]
    created_at: datetime
    content_checksum: str = Field(min_length=64, max_length=64)


def _now() -> datetime:
    return datetime.now(UTC)


def _normalized(value: str) -> str:
    value = normalize_company_name(value)
    return re.sub(r"\s+", " ", value).strip()


def canonicalize_url(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    parts = urlsplit(value.strip())
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"}
    query = urlencode(
        sorted((key, item) for key, item in parse_qsl(parts.query) if key.casefold() not in tracking)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, query, ""))


def classify_job_family(title: str, text: str) -> str:
    value = f"{title}\n{text[:6000]}".casefold()
    rules = (
        ("MULTIMODAL", ("multimodal", "vision language", "vlm")),
        ("RAG", ("retrieval augmented", "retrieval-augmented", " rag ", "vector database")),
        ("AGENT", ("agent runtime", "ai agent", "agentic", "multi-agent", "mcp")),
        ("AI_PLATFORM", ("ai platform", "llm platform", "agent platform")),
        ("MODEL_ENGINEERING", ("model training", "fine-tuning", "post-training", "inference optimization")),
        ("AI_INFRA", ("gpu infrastructure", "ml infrastructure", "kubernetes", "cuda")),
        ("AI_BACKEND", ("backend", "fastapi", "distributed systems")),
        ("LLM_APPLICATION", ("llm application", "generative ai", "large language model")),
    )
    for family, terms in rules:
        if any(term in value for term in terms):
            return family
    return "OTHER"


class JobWorkspaceService:
    """Durable job pool built on the existing durable career repository."""

    def __init__(self, repository: DurableCareerRepository) -> None:
        self.repository = repository

    def import_raw(
        self,
        *,
        company: str,
        title: str,
        jd_text: str,
        **metadata: Any,
    ) -> ImportResult:
        return self.import_record(
            JobImportRecord(company=company, title=title, jd_text=jd_text, **metadata)
        )

    def import_record(self, record: JobImportRecord) -> ImportResult:
        company = record.company.strip()
        title = record.title.strip()
        text = normalize_text(record.jd_text)
        if not company or not title or not text.strip():
            return ImportResult(status=ImportStatus.FAILED, error="company, title, and JD text are required")

        source_url = canonicalize_url(record.source_url)
        content_hash = sha256_bytes(text.encode("utf-8"))
        identities = self._identity_candidates(record, source_url, content_hash)
        strong_identities = [item for item in identities if item[0] in {"source_id", "canonical_url"}]
        weak_identities = [item for item in identities if item[0] in {"metadata", "content_hash"}]
        strong_matches = self._matched_jobs(strong_identities)
        weak_matches = self._matched_jobs(weak_identities)
        if len(strong_matches) > 1 or (strong_matches and weak_matches - strong_matches):
            return ImportResult(
                status=ImportStatus.FAILED,
                error="identity conflict: supplied identifiers resolve to different jobs",
            )
        if strong_matches:
            existing_id = next(iter(strong_matches))
        elif strong_identities:
            existing_id = None
        elif len(weak_matches) == 1:
            existing_id = next(iter(weak_matches))
        elif len(weak_matches) > 1:
            return ImportResult(
                status=ImportStatus.FAILED,
                error="identity conflict: fallback identifiers resolve to different jobs",
            )
        else:
            existing_id = None
        possible = None
        if existing_id is None:
            possible = next(iter(sorted(weak_matches)), None) or self._near_duplicate(record)
            stable = identities[0][1] if identities else content_hash
            job_id = f"job-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:24]}"
            created = True
        else:
            job_id = existing_id
            created = False

        family = record.job_family or classify_job_family(title, text)
        if family not in JOB_FAMILIES:
            family = "OTHER"
        before = None
        if not created:
            before = self.repository.get_state(job_id).latest_jd
        self.repository.save_job(
            job_id=job_id,
            company=company,
            title=title,
            location=record.location,
            employment_type=record.employment_type,
            seniority=record.seniority,
            job_family=family,
            source_type=record.source_type,
            source_uri=source_url,
            source_identifier=record.source_identifier,
            lineage=record.lineage,
            raw_metadata={**record.raw_metadata, "captured_at": str(record.captured_at or _now())},
            possible_duplicate_of=possible,
        )
        snapshot = self.repository.append_jd_snapshot(
            job_id=job_id,
            text=text,
            source_uri=source_url,
            created_by=f"job-import:{record.lineage}",
        )
        self._record_identities(job_id, identities)
        connection = self.repository.connection()
        connection.execute(
            "UPDATE job_workspace SET last_seen_at=? WHERE job_id=?",
            ((record.captured_at or _now()).isoformat(), job_id),
        )

        if created:
            self._bump_corpus()
            status = ImportStatus.POSSIBLE_DUPLICATE if possible else ImportStatus.IMPORTED
        elif before is not None and before.snapshot_id == snapshot.snapshot_id:
            status = ImportStatus.UNCHANGED
        else:
            status = ImportStatus.UPDATED
        return ImportResult(
            status=status,
            job_id=job_id,
            jd_snapshot_id=snapshot.snapshot_id,
            jd_version=snapshot.version,
            matched_by=(self._match_reason(identities, job_id) if not created else None),
            possible_duplicate_of=possible,
        )

    def import_json(self, value: str | bytes | Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> BulkImportSummary:
        payload = json.loads(value) if isinstance(value, (str, bytes)) else value
        rows = [payload] if isinstance(payload, Mapping) else list(payload)
        return self.import_many(rows)

    def import_jsonl(self, value: str | bytes | Path) -> BulkImportSummary:
        if isinstance(value, Path):
            text = value.read_text(encoding="utf-8")
        elif isinstance(value, bytes):
            text = value.decode("utf-8")
        else:
            text = value
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        return self.import_many(rows)

    def import_csv(self, value: str | bytes | Path) -> BulkImportSummary:
        if isinstance(value, Path):
            text = value.read_text(encoding="utf-8-sig")
        elif isinstance(value, bytes):
            text = value.decode("utf-8-sig")
        else:
            text = value
        return self.import_many(csv.DictReader(io.StringIO(text)))

    def import_many(self, rows: Iterable[Mapping[str, Any] | JobImportRecord]) -> BulkImportSummary:
        results: list[ImportResult] = []
        for row in rows:
            try:
                record = row if isinstance(row, JobImportRecord) else JobImportRecord.model_validate(row)
                results.append(self.import_record(record))
            except Exception as exc:
                results.append(ImportResult(status=ImportStatus.FAILED, error=f"{type(exc).__name__}: {exc}"))
        counts = Counter(item.status.value for item in results)
        return BulkImportSummary(
            total=len(results),
            imported=counts[ImportStatus.IMPORTED.value],
            updated=counts[ImportStatus.UPDATED.value],
            unchanged=counts[ImportStatus.UNCHANGED.value],
            possible_duplicate=counts[ImportStatus.POSSIBLE_DUPLICATE.value],
            failed=counts[ImportStatus.FAILED.value],
            results=results,
        )

    def get_job(self, job_id: str) -> DurableJob:
        return self.repository.get_job_record(job_id)

    def list_jobs(self, query: JobQuery | None = None) -> list[DurableJob]:
        query = query or JobQuery()
        jobs = self.repository.list_jobs()
        def keep(job: DurableJob) -> bool:
            if not query.include_archived and job.workspace_status == WorkspaceStatus.ARCHIVED.value:
                return False
            checks = (
                (query.company, job.company),
                (query.title_keyword, job.title),
                (query.location, job.location),
                (query.employment_type, job.employment_type),
            )
            if any(value and _normalized(value) not in _normalized(actual) for value, actual in checks):
                return False
            if query.job_family and job.job_family != query.job_family:
                return False
            if query.workspace_status and job.workspace_status != query.workspace_status:
                return False
            if query.analysis_status and job.analysis_status != query.analysis_status:
                return False
            if query.created_after and job.created_at < query.created_after:
                return False
            if query.application_present is not None:
                linked = self.repository.connection().execute(
                    "SELECT 1 FROM career_application_links WHERE job_id=?", (job.job_id,)
                ).fetchone() is not None
                if linked != query.application_present:
                    return False
            return True
        selected = [job for job in jobs if keep(job)]
        keys: dict[str, Callable[[DurableJob], Any]] = {
            "created_at": lambda item: item.created_at,
            "first_seen_at": lambda item: item.first_seen_at or item.created_at,
            "last_seen_at": lambda item: item.last_seen_at or item.updated_at,
            "company": lambda item: _normalized(item.company),
            "title": lambda item: _normalized(item.title),
        }
        if query.sort_by not in keys:
            raise ValueError("unsupported job sort")
        selected.sort(key=keys[query.sort_by], reverse=query.descending)
        return selected[query.offset : query.offset + query.limit]

    def update_workspace_status(self, *, job_id: str, status: WorkspaceStatus, action_id: str, source: str) -> DurableJob:
        job = self.get_job(job_id)
        existing = self.repository.connection().execute(
            "SELECT job_id FROM job_workspace_events WHERE action_id=?", (action_id,)
        ).fetchone()
        if existing is not None:
            if existing["job_id"] != job_id:
                raise ValueError("workspace action idempotency conflict")
            return self.get_job(job_id)
        if job.workspace_status == status.value:
            return job
        occurred = _now()
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO job_workspace_events VALUES (?,?,?,?,?,?,?)",
                (f"jwe-{uuid.uuid4().hex[:16]}", job_id, job.workspace_status, status.value, action_id, occurred.isoformat(), source),
            )
            connection.execute(
                "UPDATE job_workspace SET workspace_status=?, status_updated_at=?, status_source=? WHERE job_id=?",
                (status.value, occurred.isoformat(), source, job_id),
            )
            self.repository._bump_corpus_version(connection)
        return self.get_job(job_id)

    def shortlist(self, *, job_id: str, action_id: str, source: str = "user") -> DurableJob:
        return self.update_workspace_status(job_id=job_id, status=WorkspaceStatus.SHORTLISTED, action_id=action_id, source=source)

    def unshortlist(self, *, job_id: str, action_id: str, source: str = "user") -> DurableJob:
        job = self.get_job(job_id)
        target = WorkspaceStatus.ANALYZED if job.analysis_status == AnalysisStatus.CURRENT.value else WorkspaceStatus.NEW
        return self.update_workspace_status(job_id=job_id, status=target, action_id=action_id, source=source)

    def archive(self, *, job_id: str, action_id: str, source: str = "user") -> DurableJob:
        return self.update_workspace_status(job_id=job_id, status=WorkspaceStatus.ARCHIVED, action_id=action_id, source=source)

    def unarchive(self, *, job_id: str, action_id: str, source: str = "user") -> DurableJob:
        job = self.get_job(job_id)
        target = WorkspaceStatus.ANALYZED if job.analysis_status == AnalysisStatus.CURRENT.value else WorkspaceStatus.NEW
        return self.update_workspace_status(job_id=job_id, status=target, action_id=action_id, source=source)

    def jd_diff(self, job_id: str, from_version: int, to_version: int) -> JDDiff:
        state = self.repository.get_state(job_id)
        versions = {item.version: item for item in state.jd_snapshots}
        try:
            old, new = versions[from_version], versions[to_version]
        except KeyError as exc:
            raise ValueError("JD version not found") from exc
        old_lines = self._diff_units(old.text)
        new_lines = self._diff_units(new.text)
        delta = list(difflib.ndiff(old_lines, new_lines))
        return JDDiff(
            job_id=job_id,
            from_version=from_version,
            to_version=to_version,
            added=[item[2:] for item in delta if item.startswith("+ ")],
            removed=[item[2:] for item in delta if item.startswith("- ")],
        )

    def compare(self, job_ids: Sequence[str]) -> JobComparison:
        if not 2 <= len(job_ids) <= 5 or len(set(job_ids)) != len(job_ids):
            raise ValueError("compare requires 2 to 5 distinct jobs")
        states = {job_id: self.repository.get_state(job_id) for job_id in job_ids}
        requirements: dict[str, set[str]] = {}
        strengths: dict[str, set[str]] = {}
        gaps: dict[str, set[str]] = {}
        preferences: dict[str, dict[str, Any]] = {}
        constraints: dict[str, dict[str, str]] = {}
        for job_id, state in states.items():
            analysis = state.latest_analysis
            requirements[job_id] = {
                self._capability(item.get("text", ""))
                for item in (analysis.requirement_results if analysis else [])
                if item.get("text")
            }
            strengths[job_id] = {self._capability(item) for item in (analysis.strengths if analysis else [])}
            gaps[job_id] = {self._capability(item) for item in (analysis.gaps if analysis else [])}
            preferences[job_id] = analysis.preference_result if analysis else {}
            constraints[job_id] = {
                "location": state.job.location,
                "employment_type": state.job.employment_type,
                "seniority": state.job.seniority,
            }
        return JobComparison(
            job_ids=list(job_ids),
            common_requirements=sorted(set.intersection(*requirements.values()) if requirements else set()),
            common_strengths=sorted(set.intersection(*strengths.values()) if strengths else set()),
            common_gaps=sorted(set.intersection(*gaps.values()) if gaps else set()),
            job_specific_strengths={key: sorted(value - set.union(*(item for other, item in strengths.items() if other != key)) if len(strengths) > 1 else value) for key, value in strengths.items()},
            job_specific_gaps={key: sorted(value - set.union(*(item for other, item in gaps.items() if other != key)) if len(gaps) > 1 else value) for key, value in gaps.items()},
            preference_differences=preferences,
            jd_constraints=constraints,
        )

    def aggregate_gaps(self, *, status: WorkspaceStatus | None = None) -> list[AggregateItem]:
        return self._aggregate("gaps", status=status)

    def aggregate_strengths(self, *, status: WorkspaceStatus | None = None) -> list[AggregateItem]:
        return self._aggregate("strengths", status=status)

    def create_batch(
        self,
        *,
        filters: JobQuery | None = None,
        max_jobs: int = 50,
        job_ids: Sequence[str] | None = None,
    ) -> BatchRun:
        filters = filters or JobQuery(analysis_status=AnalysisStatus.UNANALYZED.value, limit=min(max_jobs, 500))
        if job_ids is None:
            jobs = self.list_jobs(filters)[:max_jobs]
        else:
            if len(set(job_ids)) != len(job_ids):
                raise ValueError("batch job_ids must be distinct")
            jobs = [self.get_job(job_id) for job_id in job_ids[:max_jobs]]
        batch_id = f"batch-{uuid.uuid4().hex[:16]}"
        created = _now()
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT INTO job_batch_runs VALUES (?,?,?,?,?,?,?,?,?)",
                (batch_id, created.isoformat(), filters.model_dump_json(), json.dumps([job.job_id for job in jobs]), 0, 0, "PENDING", None, None),
            )
            connection.executemany(
                "INSERT INTO job_batch_items(batch_id,job_id,status) VALUES (?,?,?)",
                [(batch_id, job.job_id, BatchItemStatus.PENDING.value) for job in jobs],
            )
        return self.get_batch(batch_id)

    def run_batch(
        self,
        batch_id: str,
        analyzer: Callable[[DurableJob, JDSnapshot], Mapping[str, Any] | Any],
        *,
        max_items: int | None = None,
    ) -> BatchResult:
        batch = self.get_batch(batch_id)
        connection = self.repository.connection()
        pending = connection.execute(
            "SELECT * FROM job_batch_items WHERE batch_id=? AND status IN ('PENDING','FAILED') ORDER BY job_id",
            (batch_id,),
        ).fetchall()
        if max_items is not None:
            pending = pending[:max_items]
        resumed = sum(1 for item in pending if item["status"] == BatchItemStatus.FAILED.value)
        connection.execute(
            "UPDATE job_batch_runs SET status='RUNNING', started_at=COALESCE(started_at,?) WHERE batch_id=?",
            (_now().isoformat(), batch_id),
        )
        skipped = 0
        for item in pending:
            job_id = item["job_id"]
            started = _now().isoformat()
            try:
                state = self.repository.get_state(job_id)
                if state.latest_jd is None:
                    raise ValueError("job has no JD snapshot")
                if state.latest_analysis and state.latest_analysis.jd_snapshot_id == state.latest_jd.snapshot_id:
                    connection.execute(
                        "UPDATE job_batch_items SET status='SKIPPED', started_at=?, finished_at=? WHERE batch_id=? AND job_id=?",
                        (started, _now().isoformat(), batch_id, job_id),
                    )
                    skipped += 1
                    continue
                payload = analyzer(state.job, state.latest_jd)
                analysis = self.repository.append_analysis_snapshot(
                    job_id=job_id,
                    jd_snapshot_id=state.latest_jd.snapshot_id,
                    analysis=payload,
                    producer_run_id=f"{batch_id}:{job_id}:{state.latest_jd.version}",
                    model_metadata={"batch_id": batch_id},
                )
                connection.execute(
                    "UPDATE job_batch_items SET status='SUCCESS', analysis_id=?, error=NULL, started_at=?, finished_at=? WHERE batch_id=? AND job_id=?",
                    (analysis.analysis_id, started, _now().isoformat(), batch_id, job_id),
                )
            except Exception as exc:
                connection.execute(
                    "UPDATE job_batch_items SET status='FAILED', error=?, started_at=?, finished_at=? WHERE batch_id=? AND job_id=?",
                    (f"{type(exc).__name__}: {exc}", started, _now().isoformat(), batch_id, job_id),
                )
                connection.execute(
                    "UPDATE job_workspace SET analysis_status='FAILED' WHERE job_id=?",
                    (job_id,),
                )
        counts = dict(connection.execute(
            "SELECT status, COUNT(*) FROM job_batch_items WHERE batch_id=? GROUP BY status", (batch_id,)
        ).fetchall())
        remaining = counts.get(BatchItemStatus.PENDING.value, 0)
        failed = counts.get(BatchItemStatus.FAILED.value, 0)
        status = "COMPLETED" if remaining == 0 and failed == 0 else ("PARTIAL" if remaining == 0 else "RUNNING")
        connection.execute(
            "UPDATE job_batch_runs SET completed=?, failed=?, status=?, finished_at=? WHERE batch_id=?",
            (counts.get("SUCCESS", 0) + counts.get("SKIPPED", 0), failed, status, _now().isoformat() if status in {"COMPLETED", "PARTIAL"} else None, batch_id),
        )
        return BatchResult(
            batch=self.get_batch(batch_id),
            success=counts.get("SUCCESS", 0),
            failed=failed,
            skipped=counts.get("SKIPPED", 0),
            resumed=resumed,
        )

    def get_batch(self, batch_id: str) -> BatchRun:
        row = self.repository.connection().execute(
            "SELECT * FROM job_batch_runs WHERE batch_id=?", (batch_id,)
        ).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return BatchRun(
            batch_id=row["batch_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            filters=json.loads(row["filters_json"]),
            job_ids=json.loads(row["job_ids_json"]),
            completed=row["completed"],
            failed=row["failed"],
            status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            finished_at=datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None,
        )

    def handoff_to_application(
        self,
        *,
        job_id: str,
        tracker: ApplicationTrackerStore,
        user_id: str,
        initial_status: ApplicationStatus = ApplicationStatus.TO_APPLY,
        notes: str = "",
    ) -> ApplicationHandoff:
        state = self.repository.get_state(job_id)
        if state.latest_jd is None:
            raise ValueError("application handoff requires an active JD")
        existing = self.repository.connection().execute(
            "SELECT * FROM application_handoffs WHERE job_id=?", (job_id,)
        ).fetchone()
        if existing is not None:
            return self._handoff(existing)
        application = tracker.record_application(
            user_id=user_id,
            job_id=job_id,
            company=state.job.company,
            title=state.job.title,
            city=state.job.location,
            source=state.job.source_type,
            url=state.job.source_uri or "",
            initial_status=initial_status,
            notes=notes,
            user_confirmed=True,
        )
        self.repository.link_application(job_id=job_id, application_id=application.id)
        created = _now()
        with self.repository.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO application_handoffs VALUES (?,?,?,?,?)",
                (job_id, application.id, state.latest_jd.snapshot_id, state.latest_jd.version, created.isoformat()),
            )
        return self._handoff(self.repository.connection().execute(
            "SELECT * FROM application_handoffs WHERE job_id=?", (job_id,)
        ).fetchone())

    def stats(self) -> WorkspaceStats:
        jobs = self.repository.list_jobs()
        statuses = Counter(job.workspace_status for job in jobs)
        analyses = Counter(job.analysis_status for job in jobs)
        return WorkspaceStats(
            total_jobs=len(jobs),
            active_jobs=sum(job.workspace_status != WorkspaceStatus.ARCHIVED.value for job in jobs),
            new=statuses[WorkspaceStatus.NEW.value],
            analyzed=sum(job.analysis_status == AnalysisStatus.CURRENT.value for job in jobs),
            stale=analyses[AnalysisStatus.STALE.value],
            shortlisted=statuses[WorkspaceStatus.SHORTLISTED.value],
            archived=statuses[WorkspaceStatus.ARCHIVED.value],
            applications_linked=self.repository.connection().execute("SELECT COUNT(*) FROM career_application_links").fetchone()[0],
            family_distribution=dict(sorted(Counter(job.job_family for job in jobs).items())),
            location_distribution=dict(sorted(Counter(job.location or "UNKNOWN" for job in jobs).items())),
        )

    def data_quality(self) -> DataQualityReport:
        jobs = self.repository.list_jobs()
        lengths = [len(self.repository.get_state(job.job_id).latest_jd.text) for job in jobs if self.repository.get_state(job.job_id).latest_jd]
        latest_hashes = [
            self.repository.get_state(job.job_id).latest_jd.content_hash
            for job in jobs
            if self.repository.get_state(job.job_id).latest_jd is not None
        ]
        duplicate_rate = (
            0.0
            if not latest_hashes
            else 1.0 - len(set(latest_hashes)) / len(latest_hashes)
        )
        return DataQualityReport(
            total_jobs=len(jobs),
            duplicate_rate=round(duplicate_rate, 4),
            possible_duplicates=sum(bool(job.possible_duplicate_of) for job in jobs),
            missing_company=sum(not job.company.strip() for job in jobs),
            missing_title=sum(not job.title.strip() for job in jobs),
            missing_location=sum(not job.location.strip() for job in jobs),
            missing_employment_type=sum(not job.employment_type.strip() for job in jobs),
            jd_text_length={
                "min": float(min(lengths, default=0)),
                "median": float(statistics.median(lengths)) if lengths else 0.0,
                "max": float(max(lengths, default=0)),
                "mean": round(statistics.mean(lengths), 2) if lengths else 0.0,
            },
            source_distribution=dict(sorted(Counter(job.source_type for job in jobs).items())),
            family_distribution=dict(sorted(Counter(job.job_family for job in jobs).items())),
        )

    def manifest(self) -> JobCorpusManifest:
        jobs = self.repository.list_jobs()
        jd_rows = self.repository.connection().execute(
            "SELECT job_id, version, content_hash FROM jd_snapshots ORDER BY job_id, version"
        ).fetchall()
        encoded = json.dumps(
            [(row["job_id"], row["version"], row["content_hash"]) for row in jd_rows],
            separators=(",", ":"),
        ).encode("utf-8")
        version = int(self.repository.connection().execute(
            "SELECT value FROM job_workspace_metadata WHERE key='corpus_version'"
        ).fetchone()[0])
        return JobCorpusManifest(
            corpus_version=version,
            job_count=len(jobs),
            active_job_count=sum(job.workspace_status != WorkspaceStatus.ARCHIVED.value for job in jobs),
            jd_version_count=len(jd_rows),
            source_breakdown=dict(sorted(Counter(job.source_type for job in jobs).items())),
            created_at=_now(),
            content_checksum=sha256_bytes(encoded),
        )

    def _identity_candidates(self, record: JobImportRecord, source_url: str | None, content_hash: str) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if record.source_identifier:
            items.append(("source_id", f"{_normalized(record.source_type)}:{record.source_identifier.strip()}"))
        if source_url:
            items.append(("canonical_url", source_url))
        items.append(("metadata", "\x1f".join((_normalized(record.company), _normalized(record.title), _normalized(record.location)))))
        items.append(("content_hash", content_hash))
        return items

    def _matched_jobs(self, identities: Sequence[tuple[str, str]]) -> set[str]:
        connection = self.repository.connection()
        result = set()
        for identity_type, value in identities:
            row = connection.execute(
                "SELECT job_id FROM job_identities WHERE identity_type=? AND identity_value=?",
                (identity_type, value),
            ).fetchone()
            if row is not None:
                result.add(row["job_id"])
        return result

    def _record_identities(self, job_id: str, identities: Sequence[tuple[str, str]]) -> None:
        with self.repository.transaction() as connection:
            for identity_type, value in identities:
                existing = connection.execute(
                    "SELECT job_id FROM job_identities WHERE identity_type=? AND identity_value=?",
                    (identity_type, value),
                ).fetchone()
                if existing is not None and existing["job_id"] != job_id:
                    if identity_type in {"metadata", "content_hash"}:
                        continue
                    raise ValueError("identity belongs to another job")
                connection.execute(
                    "INSERT OR IGNORE INTO job_identities VALUES (?,?,?,?)",
                    (identity_type, value, job_id, _now().isoformat()),
                )

    def _match_reason(self, identities: Sequence[tuple[str, str]], job_id: str) -> str | None:
        connection = self.repository.connection()
        for identity_type, value in identities:
            row = connection.execute(
                "SELECT job_id FROM job_identities WHERE identity_type=? AND identity_value=?",
                (identity_type, value),
            ).fetchone()
            if row is not None and row["job_id"] == job_id:
                return identity_type
        return None

    def _near_duplicate(self, record: JobImportRecord) -> str | None:
        target_company = _normalized(record.company)
        target_title = _normalized(record.title)
        target_location = _normalized(record.location)
        best: tuple[float, str] | None = None
        for job in self.repository.list_jobs():
            if _normalized(job.company) != target_company:
                continue
            title_score = difflib.SequenceMatcher(None, target_title, _normalized(job.title)).ratio()
            location_score = difflib.SequenceMatcher(None, target_location, _normalized(job.location)).ratio() if target_location and job.location else 0.5
            score = 0.8 * title_score + 0.2 * location_score
            if 0.82 <= score < 0.98 and (best is None or score > best[0]):
                best = (score, job.job_id)
        return best[1] if best else None

    def _bump_corpus(self) -> None:
        with self.repository.transaction() as connection:
            self.repository._bump_corpus_version(connection)

    def _aggregate(self, field: str, *, status: WorkspaceStatus | None) -> list[AggregateItem]:
        values: dict[str, set[str]] = {}
        evidence: dict[str, set[str]] = {}
        jobs = self.repository.list_jobs()
        for job in jobs:
            if status and job.workspace_status != status.value:
                continue
            analysis = self.repository.get_state(job.job_id).latest_analysis
            if analysis is None:
                continue
            for item in getattr(analysis, field):
                capability = self._capability(item)
                values.setdefault(capability, set()).add(job.job_id)
            if field == "strengths":
                for ref in analysis.evidence_refs:
                    for capability in {self._capability(item) for item in analysis.strengths}:
                        evidence.setdefault(capability, set()).add(ref)
        return [
            AggregateItem(
                capability=capability,
                job_count=len(job_ids),
                example_jobs=sorted(job_ids)[:5],
                evidence_examples=sorted(evidence.get(capability, set()))[:5],
            )
            for capability, job_ids in sorted(values.items(), key=lambda item: (-len(item[1]), item[0]))
        ]

    @staticmethod
    def _capability(value: str) -> str:
        return re.sub(r"[^\w+#.-]+", " ", normalize_text(value).casefold()).strip()

    @staticmethod
    def _diff_units(text: str) -> list[str]:
        return [item.strip() for item in re.split(r"(?:\n+|(?<=[.!?。！？]))\s+", text) if item.strip()]

    @staticmethod
    def _handoff(row) -> ApplicationHandoff:
        return ApplicationHandoff(
            job_id=row["job_id"],
            application_id=row["application_id"],
            jd_snapshot_id=row["jd_snapshot_id"],
            jd_version=row["jd_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
