from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .contracts import (
    ApplicationResumeLink,
    CandidateClaim,
    Resume,
    ResumeVersion,
    TailoringDraft,
    TailoringPlan,
)


RESUME_DDL = """
CREATE TABLE IF NOT EXISTS resumes (
 resume_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resume_versions (
 resume_version_id TEXT PRIMARY KEY,
 resume_id TEXT NOT NULL REFERENCES resumes(resume_id),
 version INTEGER NOT NULL,
 parent_version_id TEXT REFERENCES resume_versions(resume_version_id),
 target_job_id TEXT,
 target_jd_snapshot_id TEXT,
 target_jd_version INTEGER,
 content_hash TEXT NOT NULL,
 created_at TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 approval_digest TEXT UNIQUE,
 UNIQUE(resume_id, version),
 UNIQUE(resume_id, content_hash, target_job_id)
);
CREATE INDEX IF NOT EXISTS idx_resume_versions_resume
 ON resume_versions(resume_id, version);
CREATE TABLE IF NOT EXISTS candidate_claims (
 claim_id TEXT PRIMARY KEY,
 resume_version_id TEXT NOT NULL REFERENCES resume_versions(resume_version_id),
 item_id TEXT NOT NULL,
 verification_state TEXT NOT NULL,
 visibility TEXT NOT NULL,
 supersedes_claim_id TEXT,
 superseded_by_claim_id TEXT,
 updated_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_claims_active
 ON candidate_claims(resume_version_id, verification_state, visibility);
CREATE TABLE IF NOT EXISTS tailoring_plans (
 tailoring_plan_id TEXT PRIMARY KEY,
 target_job_id TEXT NOT NULL,
 base_resume_version_id TEXT NOT NULL REFERENCES resume_versions(resume_version_id),
 created_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tailoring_drafts (
 draft_id TEXT PRIMARY KEY,
 plan_id TEXT NOT NULL REFERENCES tailoring_plans(tailoring_plan_id),
 base_resume_version_id TEXT NOT NULL REFERENCES resume_versions(resume_version_id),
 status TEXT NOT NULL,
 created_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resume_application_links (
 application_id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL,
 resume_version_id TEXT NOT NULL REFERENCES resume_versions(resume_version_id),
 linked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resume_application_version
 ON resume_application_links(resume_version_id);
"""


class ResumeRepository:
    """SQLite repository for immutable resume versions and mutable review drafts."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None

    @classmethod
    def open(cls, output_root: Path | str) -> "ResumeRepository":
        repository = cls(Path(output_root) / "career.sqlite3")
        repository.initialize()
        return repository

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection().executescript(RESUME_DDL)

    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                self.db_path,
                timeout=10,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA journal_mode=WAL")
        return self._connection

    @contextmanager
    def transaction(self):
        connection = self.connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def save_resume(self, resume: Resume) -> Resume:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM resumes WHERE resume_id=?", (resume.resume_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO resumes VALUES (?,?,?)",
                    (resume.resume_id, resume.name, resume.created_at.isoformat()),
                )
            elif row["name"] != resume.name:
                raise ValueError("resume id already exists with another name")
        return self.get_resume(resume.resume_id)

    def get_resume(self, resume_id: str) -> Resume:
        row = self.connection().execute(
            "SELECT * FROM resumes WHERE resume_id=?", (resume_id,)
        ).fetchone()
        if row is None:
            raise KeyError(resume_id)
        return Resume(
            resume_id=row["resume_id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_resumes(self) -> list[Resume]:
        rows = self.connection().execute(
            "SELECT * FROM resumes ORDER BY created_at, resume_id"
        ).fetchall()
        return [
            Resume(
                resume_id=row["resume_id"],
                name=row["name"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def save_version(
        self,
        version: ResumeVersion,
        *,
        approval_digest: str | None = None,
    ) -> ResumeVersion:
        if approval_digest:
            row = self.connection().execute(
                "SELECT payload_json FROM resume_versions WHERE approval_digest=?",
                (approval_digest,),
            ).fetchone()
            if row is not None:
                return ResumeVersion.model_validate_json(row["payload_json"])
        existing = self.connection().execute(
            "SELECT payload_json FROM resume_versions WHERE resume_version_id=?",
            (version.resume_version_id,),
        ).fetchone()
        if existing is not None:
            observed = ResumeVersion.model_validate_json(existing["payload_json"])
            if observed != version:
                raise ValueError("resume version idempotency conflict")
            return observed
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO resume_versions(
                    resume_version_id, resume_id, version, parent_version_id,
                    target_job_id, target_jd_snapshot_id, target_jd_version,
                    content_hash, created_at, payload_json, approval_digest
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    version.resume_version_id,
                    version.resume_id,
                    version.version,
                    version.parent_version_id,
                    version.target_job_id,
                    version.target_jd_snapshot_id,
                    version.target_jd_version,
                    version.content_hash,
                    version.created_at.isoformat(),
                    version.model_dump_json(),
                    approval_digest,
                ),
            )
        return version

    def get_version(self, resume_version_id: str) -> ResumeVersion:
        row = self.connection().execute(
            "SELECT payload_json FROM resume_versions WHERE resume_version_id=?",
            (resume_version_id,),
        ).fetchone()
        if row is None:
            raise KeyError(resume_version_id)
        return ResumeVersion.model_validate_json(row["payload_json"])

    def list_versions(self, resume_id: str) -> list[ResumeVersion]:
        rows = self.connection().execute(
            "SELECT payload_json FROM resume_versions WHERE resume_id=? ORDER BY version",
            (resume_id,),
        ).fetchall()
        return [ResumeVersion.model_validate_json(row["payload_json"]) for row in rows]

    def next_version(self, resume_id: str) -> int:
        row = self.connection().execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM resume_versions WHERE resume_id=?",
            (resume_id,),
        ).fetchone()
        return int(row[0])

    def replace_claims(self, resume_version_id: str, claims: Iterable[CandidateClaim]) -> None:
        values = list(claims)
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM candidate_claims WHERE resume_version_id=?",
                (resume_version_id,),
            )
            connection.executemany(
                "INSERT INTO candidate_claims VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        claim.claim_id,
                        claim.resume_version_id,
                        claim.item_id,
                        claim.verification_state.value,
                        claim.visibility.value,
                        claim.supersedes_claim_id,
                        claim.superseded_by_claim_id,
                        claim.updated_at.isoformat(),
                        claim.model_dump_json(),
                    )
                    for claim in values
                ],
            )

    def list_claims(self, resume_version_id: str) -> list[CandidateClaim]:
        rows = self.connection().execute(
            "SELECT payload_json FROM candidate_claims WHERE resume_version_id=? ORDER BY item_id, claim_id",
            (resume_version_id,),
        ).fetchall()
        return [CandidateClaim.model_validate_json(row["payload_json"]) for row in rows]

    def supersede_claim(self, old_claim_id: str, replacement: CandidateClaim) -> CandidateClaim:
        old_row = self.connection().execute(
            "SELECT payload_json FROM candidate_claims WHERE claim_id=?", (old_claim_id,)
        ).fetchone()
        if old_row is None:
            raise KeyError(old_claim_id)
        old = CandidateClaim.model_validate_json(old_row["payload_json"])
        replacement = replacement.model_copy(update={"supersedes_claim_id": old.claim_id})
        old = old.model_copy(update={"superseded_by_claim_id": replacement.claim_id})
        with self.transaction() as connection:
            connection.execute(
                "UPDATE candidate_claims SET superseded_by_claim_id=?, payload_json=? WHERE claim_id=?",
                (replacement.claim_id, old.model_dump_json(), old.claim_id),
            )
            connection.execute(
                "INSERT INTO candidate_claims VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    replacement.claim_id,
                    replacement.resume_version_id,
                    replacement.item_id,
                    replacement.verification_state.value,
                    replacement.visibility.value,
                    replacement.supersedes_claim_id,
                    replacement.superseded_by_claim_id,
                    replacement.updated_at.isoformat(),
                    replacement.model_dump_json(),
                ),
            )
        return replacement

    def save_plan(self, plan: TailoringPlan) -> TailoringPlan:
        row = self.connection().execute(
            "SELECT payload_json FROM tailoring_plans WHERE tailoring_plan_id=?",
            (plan.tailoring_plan_id,),
        ).fetchone()
        if row is not None:
            observed = TailoringPlan.model_validate_json(row["payload_json"])
            if observed != plan:
                raise ValueError("tailoring plan idempotency conflict")
            return observed
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO tailoring_plans VALUES (?,?,?,?,?)",
                (
                    plan.tailoring_plan_id,
                    plan.target_job_id,
                    plan.base_resume_version_id,
                    plan.created_at.isoformat(),
                    plan.model_dump_json(),
                ),
            )
        return plan

    def get_plan(self, plan_id: str) -> TailoringPlan:
        row = self.connection().execute(
            "SELECT payload_json FROM tailoring_plans WHERE tailoring_plan_id=?",
            (plan_id,),
        ).fetchone()
        if row is None:
            raise KeyError(plan_id)
        return TailoringPlan.model_validate_json(row["payload_json"])

    def save_draft(self, draft: TailoringDraft) -> TailoringDraft:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO tailoring_drafts VALUES (?,?,?,?,?,?)
                ON CONFLICT(draft_id) DO UPDATE SET
                  status=excluded.status,
                  payload_json=excluded.payload_json
                """,
                (
                    draft.draft_id,
                    draft.plan_id,
                    draft.base_resume_version_id,
                    draft.status.value,
                    draft.created_at.isoformat(),
                    draft.model_dump_json(),
                ),
            )
        return self.get_draft(draft.draft_id)

    def get_draft(self, draft_id: str) -> TailoringDraft:
        row = self.connection().execute(
            "SELECT payload_json FROM tailoring_drafts WHERE draft_id=?", (draft_id,)
        ).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return TailoringDraft.model_validate_json(row["payload_json"])

    def link_application(self, link: ApplicationResumeLink) -> ApplicationResumeLink:
        row = self.connection().execute(
            "SELECT * FROM resume_application_links WHERE application_id=?",
            (link.application_id,),
        ).fetchone()
        if row is not None:
            observed = self._application_link(row)
            if observed.job_id != link.job_id or observed.resume_version_id != link.resume_version_id:
                raise ValueError("application is already bound to another resume version")
            return observed
        self.get_version(link.resume_version_id)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO resume_application_links VALUES (?,?,?,?)",
                (
                    link.application_id,
                    link.job_id,
                    link.resume_version_id,
                    link.linked_at.isoformat(),
                ),
            )
        return link

    def application_link(self, application_id: str) -> ApplicationResumeLink | None:
        row = self.connection().execute(
            "SELECT * FROM resume_application_links WHERE application_id=?",
            (application_id,),
        ).fetchone()
        return self._application_link(row) if row is not None else None

    def applications_using_version(self, resume_version_id: str) -> list[ApplicationResumeLink]:
        rows = self.connection().execute(
            "SELECT * FROM resume_application_links WHERE resume_version_id=? ORDER BY linked_at",
            (resume_version_id,),
        ).fetchall()
        return [self._application_link(row) for row in rows]

    @staticmethod
    def _application_link(row: sqlite3.Row) -> ApplicationResumeLink:
        return ApplicationResumeLink(
            application_id=row["application_id"],
            job_id=row["job_id"],
            resume_version_id=row["resume_version_id"],
            linked_at=datetime.fromisoformat(row["linked_at"]),
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
