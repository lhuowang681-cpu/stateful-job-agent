from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence

from pydantic import Field

from job_agent.career.store import CareerStore, normalize_company_name
from job_agent.schemas import StrictModel
from job_agent.text_identity import normalize_text, sha256_bytes


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stable_id(namespace: str, *parts: str) -> str:
    encoded = "\x1f".join((namespace, *parts)).encode("utf-8")
    return f"{namespace}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256_bytes(encoded)


class DurableJob(StrictModel):
    job_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str = ""
    job_type: str = ""
    source_type: str = Field(min_length=1)
    source_uri: str | None = None
    created_at: datetime
    updated_at: datetime
    employment_type: str = ""
    seniority: str = ""
    job_family: str = "OTHER"
    source_identifier: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    workspace_status: str = "NEW"
    analysis_status: str = "UNANALYZED"
    lineage: str = "manual"
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    possible_duplicate_of: str | None = None
    created_by_trace_id: str | None = None


class JDSnapshot(StrictModel):
    snapshot_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    text: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    source_uri: str | None = None
    created_at: datetime
    created_by: str = Field(min_length=1)
    created_by_trace_id: str | None = None


class AnalysisSnapshot(StrictModel):
    analysis_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    jd_snapshot_id: str = Field(min_length=1)
    jd_snapshot_version: int = Field(ge=1)
    producer_run_id: str = Field(min_length=1)
    created_at: datetime
    preference_result: dict[str, Any] = Field(default_factory=dict)
    requirement_results: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    provenance_refs: list[str] = Field(default_factory=list)
    input_digest: str = Field(min_length=64, max_length=64)


class ApplicationLink(StrictModel):
    job_id: str = Field(min_length=1)
    application_id: str = Field(min_length=1)
    linked_at: datetime


class InterviewPrepSnapshot(StrictModel):
    prep_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    application_id: str = Field(min_length=1)
    analysis_id: str = Field(min_length=1)
    producer_run_id: str = Field(min_length=1)
    created_at: datetime
    application_stage_at_generation: str = Field(min_length=1)
    evidence_backed_questions: list[dict[str, Any]] = Field(default_factory=list)
    gap_risks: list[dict[str, Any]] = Field(default_factory=list)
    technical_review: list[dict[str, Any]] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    input_digest: str = Field(min_length=64, max_length=64)


class DurableCareerState(StrictModel):
    schema_version: int = Field(default=1, ge=1)
    job: DurableJob
    jd_snapshots: list[JDSnapshot] = Field(default_factory=list)
    analysis_snapshots: list[AnalysisSnapshot] = Field(default_factory=list)
    application_link: ApplicationLink | None = None
    interview_prep_snapshots: list[InterviewPrepSnapshot] = Field(
        default_factory=list
    )

    @property
    def latest_jd(self) -> JDSnapshot | None:
        return self.jd_snapshots[-1] if self.jd_snapshots else None

    @property
    def latest_analysis(self) -> AnalysisSnapshot | None:
        return self.analysis_snapshots[-1] if self.analysis_snapshots else None

    @property
    def latest_interview_prep(self) -> InterviewPrepSnapshot | None:
        return (
            self.interview_prep_snapshots[-1]
            if self.interview_prep_snapshots
            else None
        )


class DurableCareerRepository(CareerStore):
    """SQLite-backed long-horizon career state beside the legacy workbench API."""

    def __init__(
        self,
        db_path,
        *,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        super().__init__(db_path)
        self._now = now

    def save_job(
        self,
        *,
        job_id: str,
        company: str,
        title: str,
        location: str = "",
        job_type: str = "",
        employment_type: str | None = None,
        seniority: str = "",
        job_family: str = "OTHER",
        source_type: str = "manual",
        source_uri: str | None = None,
        source_identifier: str | None = None,
        lineage: str = "manual",
        raw_metadata: Mapping[str, Any] | None = None,
        possible_duplicate_of: str | None = None,
    ) -> DurableJob:
        job_id = job_id.strip()
        company = company.strip()
        title = title.strip()
        if not job_id or not company or not title or not source_type.strip():
            raise ValueError("job identity fields must not be empty")
        now = self._now()
        existing = self._connect().execute(
            "SELECT * FROM durable_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        created_at = (
            datetime.fromisoformat(existing["created_at"])
            if existing is not None
            else now
        )
        employment = (employment_type if employment_type is not None else job_type).strip()
        record = DurableJob(
            job_id=job_id,
            company=company,
            title=title,
            location=location.strip(),
            job_type=employment,
            source_type=source_type.strip(),
            source_uri=source_uri,
            created_at=created_at,
            updated_at=now,
            employment_type=employment,
            seniority=seniority.strip(),
            job_family=job_family.strip() or "OTHER",
            source_identifier=source_identifier,
            first_seen_at=(
                datetime.fromisoformat(existing["created_at"])
                if existing is not None
                else now
            ),
            last_seen_at=now,
            lineage=lineage.strip() or "manual",
            raw_metadata=dict(raw_metadata or {}),
            possible_duplicate_of=possible_duplicate_of,
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO durable_jobs VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET
                    company=excluded.company,
                    normalized_company=excluded.normalized_company,
                    title=excluded.title,
                    location=excluded.location,
                    job_type=excluded.job_type,
                    source_type=excluded.source_type,
                    source_uri=excluded.source_uri,
                    updated_at=excluded.updated_at
                """,
                (
                    record.job_id,
                    record.company,
                    normalize_company_name(record.company),
                    record.title,
                    record.location,
                    record.job_type,
                    record.source_type,
                    record.source_uri,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                ),
            )
            workspace = connection.execute(
                "SELECT * FROM job_workspace WHERE job_id=?", (record.job_id,)
            ).fetchone()
            first_seen = workspace["first_seen_at"] if workspace is not None else now.isoformat()
            workspace_status = workspace["workspace_status"] if workspace is not None else "NEW"
            analysis_status = workspace["analysis_status"] if workspace is not None else "UNANALYZED"
            connection.execute(
                """
                INSERT INTO job_workspace VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET
                    employment_type=excluded.employment_type,
                    seniority=excluded.seniority,
                    job_family=excluded.job_family,
                    source_identifier=COALESCE(excluded.source_identifier, job_workspace.source_identifier),
                    canonical_url=COALESCE(excluded.canonical_url, job_workspace.canonical_url),
                    normalized_title=excluded.normalized_title,
                    normalized_location=excluded.normalized_location,
                    last_seen_at=excluded.last_seen_at,
                    lineage=excluded.lineage,
                    raw_metadata_json=excluded.raw_metadata_json,
                    possible_duplicate_of=COALESCE(excluded.possible_duplicate_of, job_workspace.possible_duplicate_of)
                """,
                (
                    record.job_id,
                    record.employment_type,
                    record.seniority,
                    record.job_family,
                    record.source_identifier,
                    record.source_uri,
                    normalize_company_name(record.title),
                    normalize_company_name(record.location),
                    first_seen,
                    now.isoformat(),
                    workspace_status,
                    analysis_status,
                    record.lineage,
                    json.dumps(record.raw_metadata, ensure_ascii=False, sort_keys=True),
                    record.possible_duplicate_of,
                    now.isoformat(),
                    "import",
                ),
            )
        return self.get_job_record(job_id)

    def get_job_record(self, job_id: str) -> DurableJob:
        row = self._connect().execute(
            "SELECT j.*, w.* FROM durable_jobs j LEFT JOIN job_workspace w USING(job_id) WHERE j.job_id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job(row)

    def list_jobs(self) -> list[DurableJob]:
        rows = self._connect().execute(
            "SELECT j.*, w.* FROM durable_jobs j LEFT JOIN job_workspace w USING(job_id) ORDER BY j.created_at, j.job_id"
        ).fetchall()
        return [self._job(row) for row in rows]

    def find_jobs(self, query: str) -> list[DurableJob]:
        normalized = normalize_company_name(query)
        return [
            job
            for job in self.list_jobs()
            if normalized
            in {
                normalize_company_name(job.job_id),
                normalize_company_name(job.company),
                normalize_company_name(job.title),
                normalize_company_name(f"{job.company} {job.title}"),
                normalize_company_name(f"{job.company} 的 {job.title}"),
            }
        ]

    def append_jd_snapshot(
        self,
        *,
        job_id: str,
        text: str,
        source_uri: str | None = None,
        created_by: str,
    ) -> JDSnapshot:
        self.get_job_record(job_id)
        normalized = normalize_text(text)
        if not normalized.strip():
            raise ValueError("JD text must not be empty")
        content_hash = sha256_bytes(normalized.encode("utf-8"))
        existing = self._connect().execute(
            "SELECT * FROM jd_snapshots WHERE job_id=? AND content_hash=?",
            (job_id, content_hash),
        ).fetchone()
        if existing is not None:
            return self._jd(existing)
        version = self._next_version("jd_snapshots", job_id)
        snapshot = JDSnapshot(
            snapshot_id=_stable_id("jd", job_id, content_hash),
            job_id=job_id,
            version=version,
            text=normalized,
            content_hash=content_hash,
            source_uri=source_uri,
            created_at=self._now(),
            created_by=created_by,
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO jd_snapshots VALUES (?,?,?,?,?,?,?,?)",
                (
                    snapshot.snapshot_id,
                    snapshot.job_id,
                    snapshot.version,
                    snapshot.text,
                    snapshot.content_hash,
                    snapshot.source_uri,
                    snapshot.created_at.isoformat(),
                    snapshot.created_by,
                ),
            )
            prior_analysis = connection.execute(
                "SELECT 1 FROM analysis_snapshots WHERE job_id=? LIMIT 1", (job_id,)
            ).fetchone()
            connection.execute(
                "UPDATE job_workspace SET analysis_status=?, last_seen_at=? WHERE job_id=?",
                ("STALE" if prior_analysis is not None else "UNANALYZED", snapshot.created_at.isoformat(), job_id),
            )
            self._bump_corpus_version(connection)
        return snapshot

    def append_analysis_snapshot(
        self,
        *,
        job_id: str,
        jd_snapshot_id: str,
        analysis: Mapping[str, Any] | Any,
        producer_run_id: str,
        model_metadata: Mapping[str, Any] | None = None,
        provenance_refs: Sequence[str] = (),
    ) -> AnalysisSnapshot:
        self.get_job_record(job_id)
        jd = self._jd_for_job(job_id, jd_snapshot_id)
        analysis_payload = (
            analysis.to_dict() if hasattr(analysis, "to_dict") else dict(analysis)
        )
        summary = dict(analysis_payload.get("summary") or {})
        requirements = list(analysis_payload.get("requirements") or [])
        evidence_refs = sorted(self._analysis_evidence_refs(requirements))
        content = {
            "preference_result": dict(
                analysis_payload.get("preference_analysis") or {}
            ),
            "requirement_results": requirements,
            "evidence_refs": evidence_refs,
            "strengths": list(summary.get("evidence_backed_strengths") or []),
            "gaps": list(summary.get("gaps") or []),
            "model_metadata": dict(model_metadata or {}),
            "provenance_refs": sorted(
                set((f"jd:{jd.snapshot_id}", *provenance_refs, *evidence_refs))
            ),
        }
        input_digest = _canonical_digest(content)
        existing = self._connect().execute(
            "SELECT * FROM analysis_snapshots WHERE job_id=? AND producer_run_id=?",
            (job_id, producer_run_id),
        ).fetchone()
        if existing is not None:
            snapshot = self._analysis(existing)
            if snapshot.input_digest != input_digest:
                raise ValueError("analysis snapshot idempotency conflict")
            return snapshot
        snapshot = AnalysisSnapshot(
            analysis_id=_stable_id("analysis", job_id, producer_run_id),
            job_id=job_id,
            version=self._next_version("analysis_snapshots", job_id),
            jd_snapshot_id=jd.snapshot_id,
            jd_snapshot_version=jd.version,
            producer_run_id=producer_run_id,
            created_at=self._now(),
            input_digest=input_digest,
            **content,
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO analysis_snapshots VALUES (?,?,?,?,?,?,?)",
                (
                    snapshot.analysis_id,
                    snapshot.job_id,
                    snapshot.version,
                    snapshot.jd_snapshot_id,
                    snapshot.producer_run_id,
                    snapshot.created_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )
            connection.execute(
                """
                UPDATE job_workspace
                SET analysis_status='CURRENT',
                    workspace_status=CASE WHEN workspace_status='NEW' THEN 'ANALYZED' ELSE workspace_status END
                WHERE job_id=?
                """,
                (job_id,),
            )
        return snapshot

    def link_application(
        self,
        *,
        job_id: str,
        application_id: str,
    ) -> ApplicationLink:
        self.get_job_record(job_id)
        existing = self._connect().execute(
            "SELECT * FROM career_application_links WHERE job_id=? OR application_id=?",
            (job_id, application_id),
        ).fetchone()
        if existing is not None:
            link = self._application_link(existing)
            if (link.job_id, link.application_id) != (job_id, application_id):
                raise ValueError("application link conflict")
            return link
        link = ApplicationLink(
            job_id=job_id,
            application_id=application_id,
            linked_at=self._now(),
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO career_application_links VALUES (?,?,?)",
                (link.job_id, link.application_id, link.linked_at.isoformat()),
            )
        return link

    def append_interview_prep_snapshot(
        self,
        *,
        job_id: str,
        application_id: str,
        analysis_id: str,
        application_stage_at_generation: str,
        preparation: Mapping[str, Any] | Any,
        producer_run_id: str,
        provenance_refs: Sequence[str] = (),
    ) -> InterviewPrepSnapshot:
        self.get_job_record(job_id)
        link = self._application_link_for_job(job_id)
        if link is None or link.application_id != application_id:
            raise ValueError("interview prep requires the linked application")
        analysis = self.get_analysis_snapshot(analysis_id)
        if analysis.job_id != job_id:
            raise ValueError("interview prep analysis belongs to another job")
        payload = (
            preparation.model_dump(mode="json")
            if hasattr(preparation, "model_dump")
            else dict(preparation)
        )
        content = {
            "application_stage_at_generation": application_stage_at_generation,
            "evidence_backed_questions": list(
                payload.get("evidence_backed_questions") or payload.get("questions") or []
            ),
            "gap_risks": list(payload.get("gap_risks") or payload.get("gaps") or []),
            "technical_review": list(
                payload.get("technical_review_topics")
                or payload.get("technical_review")
                or []
            ),
            "provenance_refs": sorted(
                set((f"analysis:{analysis_id}", *provenance_refs))
            ),
        }
        input_digest = _canonical_digest(content)
        existing = self._connect().execute(
            "SELECT * FROM interview_prep_snapshots WHERE job_id=? AND producer_run_id=?",
            (job_id, producer_run_id),
        ).fetchone()
        if existing is not None:
            snapshot = self._interview_prep(existing)
            if snapshot.input_digest != input_digest:
                raise ValueError("interview prep snapshot idempotency conflict")
            return snapshot
        snapshot = InterviewPrepSnapshot(
            prep_id=_stable_id("prep", job_id, producer_run_id),
            job_id=job_id,
            version=self._next_version("interview_prep_snapshots", job_id),
            application_id=application_id,
            analysis_id=analysis_id,
            producer_run_id=producer_run_id,
            created_at=self._now(),
            input_digest=input_digest,
            **content,
        )
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO interview_prep_snapshots VALUES (?,?,?,?,?,?,?,?)",
                (
                    snapshot.prep_id,
                    snapshot.job_id,
                    snapshot.version,
                    snapshot.application_id,
                    snapshot.analysis_id,
                    snapshot.producer_run_id,
                    snapshot.created_at.isoformat(),
                    snapshot.model_dump_json(),
                ),
            )
        return snapshot

    def get_analysis_snapshot(self, analysis_id: str) -> AnalysisSnapshot:
        row = self._connect().execute(
            "SELECT * FROM analysis_snapshots WHERE analysis_id=?",
            (analysis_id,),
        ).fetchone()
        if row is None:
            raise KeyError(analysis_id)
        return self._analysis(row)

    def get_state(self, job_id: str) -> DurableCareerState:
        job = self.get_job_record(job_id)
        jd_rows = self._connect().execute(
            "SELECT * FROM jd_snapshots WHERE job_id=? ORDER BY version",
            (job_id,),
        ).fetchall()
        analysis_rows = self._connect().execute(
            "SELECT * FROM analysis_snapshots WHERE job_id=? ORDER BY version",
            (job_id,),
        ).fetchall()
        prep_rows = self._connect().execute(
            "SELECT * FROM interview_prep_snapshots WHERE job_id=? ORDER BY version",
            (job_id,),
        ).fetchall()
        jd_snapshots = [self._jd(row) for row in jd_rows]
        analysis_snapshots = [self._analysis(row) for row in analysis_rows]
        application_link = self._application_link_for_job(job_id)
        prep_snapshots = [self._interview_prep(row) for row in prep_rows]
        jd_by_id = {item.snapshot_id: item for item in jd_snapshots}
        analysis_by_id = {item.analysis_id: item for item in analysis_snapshots}
        for analysis in analysis_snapshots:
            jd = jd_by_id.get(analysis.jd_snapshot_id)
            if jd is None or jd.version != analysis.jd_snapshot_version:
                raise ValueError("analysis snapshot has a broken JD reference")
        for prep in prep_snapshots:
            analysis = analysis_by_id.get(prep.analysis_id)
            if analysis is None:
                raise ValueError("interview prep has a broken analysis reference")
            if application_link is None or prep.application_id != application_link.application_id:
                raise ValueError("interview prep has a broken application reference")
        return DurableCareerState(
            job=job,
            jd_snapshots=jd_snapshots,
            analysis_snapshots=analysis_snapshots,
            application_link=application_link,
            interview_prep_snapshots=prep_snapshots,
        )

    def _jd_for_job(self, job_id: str, snapshot_id: str) -> JDSnapshot:
        row = self._connect().execute(
            "SELECT * FROM jd_snapshots WHERE snapshot_id=? AND job_id=?",
            (snapshot_id, job_id),
        ).fetchone()
        if row is None:
            raise ValueError("analysis requires an existing JD snapshot for the job")
        return self._jd(row)

    def _application_link_for_job(self, job_id: str) -> ApplicationLink | None:
        row = self._connect().execute(
            "SELECT * FROM career_application_links WHERE job_id=?",
            (job_id,),
        ).fetchone()
        return self._application_link(row) if row is not None else None

    def _next_version(self, table: str, job_id: str) -> int:
        if table not in {
            "jd_snapshots",
            "analysis_snapshots",
            "interview_prep_snapshots",
        }:
            raise ValueError("unsupported versioned table")
        row = self._connect().execute(
            f"SELECT COALESCE(MAX(version), 0) + 1 FROM {table} WHERE job_id=?",
            (job_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _bump_corpus_version(connection) -> int:
        connection.execute(
            "UPDATE job_workspace_metadata SET value=CAST(value AS INTEGER)+1 WHERE key='corpus_version'"
        )
        row = connection.execute(
            "SELECT value FROM job_workspace_metadata WHERE key='corpus_version'"
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _analysis_evidence_refs(requirements: Sequence[Mapping[str, Any]]) -> set[str]:
        refs: set[str] = set()
        for requirement in requirements:
            for evidence in requirement.get("evidence", []):
                for key, namespace in (
                    ("evidence_link_id", "evidence"),
                    ("document_id", "document"),
                    ("chunk_id", "chunk"),
                    ("source_id", "source"),
                ):
                    value = evidence.get(key)
                    if isinstance(value, str) and value:
                        refs.add(f"{namespace}:{value}")
        return refs

    @staticmethod
    def _job(row) -> DurableJob:
        keys = set(row.keys())
        raw_metadata = (
            json.loads(row["raw_metadata_json"])
            if "raw_metadata_json" in keys and row["raw_metadata_json"]
            else {}
        )
        return DurableJob(
            job_id=row["job_id"],
            company=row["company"],
            title=row["title"],
            location=row["location"],
            job_type=row["job_type"],
            source_type=row["source_type"],
            source_uri=row["source_uri"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            employment_type=(row["employment_type"] if "employment_type" in keys and row["employment_type"] is not None else row["job_type"]),
            seniority=row["seniority"] if "seniority" in keys and row["seniority"] is not None else "",
            job_family=row["job_family"] if "job_family" in keys and row["job_family"] else "OTHER",
            source_identifier=row["source_identifier"] if "source_identifier" in keys else None,
            first_seen_at=(datetime.fromisoformat(row["first_seen_at"]) if "first_seen_at" in keys and row["first_seen_at"] else datetime.fromisoformat(row["created_at"])),
            last_seen_at=(datetime.fromisoformat(row["last_seen_at"]) if "last_seen_at" in keys and row["last_seen_at"] else datetime.fromisoformat(row["updated_at"])),
            workspace_status=row["workspace_status"] if "workspace_status" in keys and row["workspace_status"] else "NEW",
            analysis_status=row["analysis_status"] if "analysis_status" in keys and row["analysis_status"] else "UNANALYZED",
            lineage=row["lineage"] if "lineage" in keys and row["lineage"] else "manual",
            raw_metadata=raw_metadata,
            possible_duplicate_of=row["possible_duplicate_of"] if "possible_duplicate_of" in keys else None,
        )

    @staticmethod
    def _jd(row) -> JDSnapshot:
        return JDSnapshot(
            snapshot_id=row["snapshot_id"],
            job_id=row["job_id"],
            version=row["version"],
            text=row["text"],
            content_hash=row["content_hash"],
            source_uri=row["source_uri"],
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
        )

    @staticmethod
    def _application_link(row) -> ApplicationLink:
        return ApplicationLink(
            job_id=row["job_id"],
            application_id=row["application_id"],
            linked_at=datetime.fromisoformat(row["linked_at"]),
        )

    @staticmethod
    def _analysis(row) -> AnalysisSnapshot:
        snapshot = AnalysisSnapshot.model_validate_json(row["payload_json"])
        expected = (
            row["analysis_id"],
            row["job_id"],
            row["version"],
            row["jd_snapshot_id"],
            row["producer_run_id"],
            row["created_at"],
        )
        actual = (
            snapshot.analysis_id,
            snapshot.job_id,
            snapshot.version,
            snapshot.jd_snapshot_id,
            snapshot.producer_run_id,
            snapshot.created_at.isoformat(),
        )
        if actual != expected:
            raise ValueError("analysis snapshot payload does not match its envelope")
        return snapshot

    @staticmethod
    def _interview_prep(row) -> InterviewPrepSnapshot:
        snapshot = InterviewPrepSnapshot.model_validate_json(row["payload_json"])
        expected = (
            row["prep_id"],
            row["job_id"],
            row["version"],
            row["application_id"],
            row["analysis_id"],
            row["producer_run_id"],
            row["created_at"],
        )
        actual = (
            snapshot.prep_id,
            snapshot.job_id,
            snapshot.version,
            snapshot.application_id,
            snapshot.analysis_id,
            snapshot.producer_run_id,
            snapshot.created_at.isoformat(),
        )
        if actual != expected:
            raise ValueError("interview prep payload does not match its envelope")
        return snapshot
