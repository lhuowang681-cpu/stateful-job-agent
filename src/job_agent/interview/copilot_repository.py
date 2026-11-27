from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, TypeVar

from pydantic import BaseModel

from job_agent.text_identity import normalize_text

from .copilot_contracts import (
    InterviewPrepSnapshot,
    InterviewQuestion,
    InterviewRound,
    InterviewRoundStatus,
    InterviewWeaknessSnapshot,
    MockInterviewSession,
    RealInterviewRecord,
)


COPILOT_DDL = """
CREATE TABLE IF NOT EXISTS copilot_actions (
 action_id TEXT PRIMARY KEY, action_kind TEXT NOT NULL,
 input_digest TEXT NOT NULL, entity_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_rounds_v1 (
 round_id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
 status TEXT NOT NULL, scheduled_at TEXT, created_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interview_rounds_application
 ON interview_rounds_v1(application_id, created_at);
CREATE TABLE IF NOT EXISTS interview_prep_snapshots_v2 (
 prep_version_id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
 job_id TEXT NOT NULL, version INTEGER NOT NULL,
 jd_snapshot_id TEXT NOT NULL, analysis_snapshot_id TEXT NOT NULL,
 resume_version_id TEXT NOT NULL, interview_round_id TEXT NOT NULL,
 created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 UNIQUE(application_id, version)
);
CREATE INDEX IF NOT EXISTS idx_interview_prep_binding
 ON interview_prep_snapshots_v2(application_id, interview_round_id, version);
CREATE TABLE IF NOT EXISTS interview_questions_v1 (
 question_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
 category TEXT NOT NULL, source_type TEXT NOT NULL,
 created_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_prep_questions_v1 (
 prep_version_id TEXT NOT NULL, question_id TEXT NOT NULL,
 PRIMARY KEY(prep_version_id, question_id)
);
CREATE TABLE IF NOT EXISTS mock_interview_sessions_v1 (
 session_id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
 job_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
 completed_at TEXT, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mock_sessions_application
 ON mock_interview_sessions_v1(application_id, started_at);
CREATE TABLE IF NOT EXISTS interview_weaknesses_v1 (
 weakness_id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
 category TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_weakness_application
 ON interview_weaknesses_v1(application_id, status, category);
CREATE TABLE IF NOT EXISTS real_interview_records_v1 (
 record_id TEXT PRIMARY KEY, application_id TEXT NOT NULL,
 round_id TEXT NOT NULL, job_id TEXT NOT NULL,
 occurred_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_real_interview_application
 ON real_interview_records_v1(application_id, occurred_at);
"""


ModelT = TypeVar("ModelT", bound=BaseModel)


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def stable_id(namespace: str, *parts: object) -> str:
    material = "\0".join(str(part) for part in parts)
    return f"{namespace}-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def question_fingerprint(question: InterviewQuestion) -> str:
    source_refs = sorted(
        {
            *question.job_requirement_refs,
            *question.resume_claim_refs,
            *question.evidence_refs,
        }
    )
    return canonical_digest(
        {
            "prompt": " ".join(normalize_text(question.prompt).casefold().split()),
            "source_refs": source_refs,
            "parent": question.parent_question_id,
        }
    )


class InterviewCopilotRepository:
    """Durable interview state stored beside the existing career/resume SQLite data."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None

    @classmethod
    def open(cls, output_root: Path | str) -> "InterviewCopilotRepository":
        repository = cls(Path(output_root) / "career.sqlite3")
        repository.initialize()
        return repository

    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
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

    def initialize(self) -> None:
        self.connection().executescript(COPILOT_DDL)

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

    def _action(self, action_id: str, kind: str, payload: object) -> str | None:
        row = self.connection().execute(
            "SELECT * FROM copilot_actions WHERE action_id=?", (action_id,)
        ).fetchone()
        if row is None:
            return None
        if row["action_kind"] != kind or row["input_digest"] != canonical_digest(payload):
            raise ValueError("copilot action idempotency conflict")
        return str(row["entity_id"])

    def existing_action(self, action_id: str, kind: str) -> str | None:
        row = self.connection().execute(
            "SELECT action_kind, entity_id FROM copilot_actions WHERE action_id=?",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        if row["action_kind"] != kind:
            raise ValueError("copilot action idempotency conflict")
        return str(row["entity_id"])

    @staticmethod
    def _record_action(connection, action_id: str, kind: str, payload: object, entity_id: str) -> None:
        connection.execute(
            "INSERT INTO copilot_actions VALUES (?,?,?,?)",
            (action_id, kind, canonical_digest(payload), entity_id),
        )

    def create_round(self, value: InterviewRound, *, action_id: str) -> InterviewRound:
        payload = value.model_dump(mode="json")
        existing = self._action(action_id, "create_round", payload)
        if existing is not None:
            return self.get_round(existing)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO interview_rounds_v1 VALUES (?,?,?,?,?,?)",
                (
                    value.round_id,
                    value.application_id,
                    value.status.value,
                    value.scheduled_at.isoformat() if value.scheduled_at else None,
                    value.created_at.isoformat(),
                    value.model_dump_json(),
                ),
            )
            self._record_action(connection, action_id, "create_round", payload, value.round_id)
        return value

    def get_round(self, round_id: str) -> InterviewRound:
        return self._one("interview_rounds_v1", "round_id", round_id, InterviewRound)

    def list_rounds(self, application_id: str) -> list[InterviewRound]:
        return self._many(
            "SELECT payload_json FROM interview_rounds_v1 WHERE application_id=? ORDER BY created_at, round_id",
            (application_id,),
            InterviewRound,
        )

    def update_round(self, value: InterviewRound, *, action_id: str) -> InterviewRound:
        payload = value.model_dump(mode="json")
        existing = self._action(action_id, "update_round", payload)
        if existing is not None:
            return self.get_round(existing)
        self.get_round(value.round_id)
        with self.transaction() as connection:
            connection.execute(
                "UPDATE interview_rounds_v1 SET status=?, scheduled_at=?, payload_json=? WHERE round_id=?",
                (
                    value.status.value,
                    value.scheduled_at.isoformat() if value.scheduled_at else None,
                    value.model_dump_json(),
                    value.round_id,
                ),
            )
            self._record_action(connection, action_id, "update_round", payload, value.round_id)
        return value

    def save_prep(self, value: InterviewPrepSnapshot, *, action_id: str) -> InterviewPrepSnapshot:
        payload = value.model_dump(mode="json")
        existing = self._action(action_id, "create_prep", payload)
        if existing is not None:
            return self.get_prep(existing)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO interview_prep_snapshots_v2 VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    value.prep_version_id,
                    value.application_id,
                    value.job_id,
                    value.version,
                    value.jd_snapshot_id,
                    value.analysis_snapshot_id,
                    value.resume_version_id,
                    value.interview_round_id,
                    value.created_at.isoformat(),
                    value.model_dump_json(),
                ),
            )
            self._record_action(connection, action_id, "create_prep", payload, value.prep_version_id)
        return value

    def next_prep_version(self, application_id: str) -> int:
        row = self.connection().execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM interview_prep_snapshots_v2 WHERE application_id=?",
            (application_id,),
        ).fetchone()
        return int(row[0])

    def get_prep(self, prep_version_id: str) -> InterviewPrepSnapshot:
        return self._one(
            "interview_prep_snapshots_v2", "prep_version_id", prep_version_id, InterviewPrepSnapshot
        )

    def list_preps(self, application_id: str) -> list[InterviewPrepSnapshot]:
        return self._many(
            "SELECT payload_json FROM interview_prep_snapshots_v2 WHERE application_id=? ORDER BY version",
            (application_id,),
            InterviewPrepSnapshot,
        )

    def save_question(self, value: InterviewQuestion) -> InterviewQuestion:
        fingerprint = question_fingerprint(value)
        row = self.connection().execute(
            "SELECT payload_json FROM interview_questions_v1 WHERE fingerprint=?",
            (fingerprint,),
        ).fetchone()
        if row is not None:
            return InterviewQuestion.model_validate_json(row["payload_json"])
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO interview_questions_v1 VALUES (?,?,?,?,?,?)",
                (
                    value.question_id,
                    fingerprint,
                    value.category,
                    value.source_type.value,
                    value.created_at.isoformat(),
                    value.model_dump_json(),
                ),
            )
        return value

    def get_question(self, question_id: str) -> InterviewQuestion:
        return self._one("interview_questions_v1", "question_id", question_id, InterviewQuestion)

    def link_question(self, prep_version_id: str, question_id: str) -> None:
        self.get_prep(prep_version_id)
        self.get_question(question_id)
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO interview_prep_questions_v1 VALUES (?,?)",
                (prep_version_id, question_id),
            )

    def list_questions(self, prep_version_id: str | None = None) -> list[InterviewQuestion]:
        if prep_version_id is None:
            query, params = "SELECT payload_json FROM interview_questions_v1 ORDER BY created_at, question_id", ()
        else:
            query, params = (
                """
                SELECT q.payload_json FROM interview_questions_v1 q
                JOIN interview_prep_questions_v1 l USING(question_id)
                WHERE l.prep_version_id=? ORDER BY q.created_at, q.question_id
                """,
                (prep_version_id,),
            )
        return self._many(query, params, InterviewQuestion)

    def create_session(self, value: MockInterviewSession, *, action_id: str) -> MockInterviewSession:
        payload = value.model_dump(mode="json")
        existing = self._action(action_id, "start_mock", payload)
        if existing is not None:
            return self.get_session(existing)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO mock_interview_sessions_v1 VALUES (?,?,?,?,?,?,?)",
                (
                    value.session_id,
                    value.application_id,
                    value.job_id,
                    value.status.value,
                    value.started_at.isoformat(),
                    None,
                    value.model_dump_json(),
                ),
            )
            self._record_action(connection, action_id, "start_mock", payload, value.session_id)
        return value

    def get_session(self, session_id: str) -> MockInterviewSession:
        return self._one("mock_interview_sessions_v1", "session_id", session_id, MockInterviewSession)

    def list_sessions(self, application_id: str | None = None) -> list[MockInterviewSession]:
        if application_id is None:
            query, params = "SELECT payload_json FROM mock_interview_sessions_v1 ORDER BY started_at", ()
        else:
            query, params = (
                "SELECT payload_json FROM mock_interview_sessions_v1 WHERE application_id=? ORDER BY started_at",
                (application_id,),
            )
        return self._many(query, params, MockInterviewSession)

    def save_session(self, value: MockInterviewSession, *, action_id: str, kind: str) -> MockInterviewSession:
        payload = value.model_dump(mode="json")
        existing = self._action(action_id, kind, payload)
        if existing is not None:
            return self.get_session(existing)
        self.get_session(value.session_id)
        with self.transaction() as connection:
            connection.execute(
                "UPDATE mock_interview_sessions_v1 SET status=?, completed_at=?, payload_json=? WHERE session_id=?",
                (
                    value.status.value,
                    value.completed_at.isoformat() if value.completed_at else None,
                    value.model_dump_json(),
                    value.session_id,
                ),
            )
            self._record_action(connection, action_id, kind, payload, value.session_id)
        return value

    def save_weakness(
        self,
        application_id: str,
        value: InterviewWeaknessSnapshot,
        *,
        action_id: str,
    ) -> InterviewWeaknessSnapshot:
        payload = value.model_dump(mode="json")
        existing = self._action(action_id, "save_weakness", payload)
        if existing is not None:
            return self.get_weakness(existing)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO interview_weaknesses_v1 VALUES (?,?,?,?,?,?)
                ON CONFLICT(weakness_id) DO UPDATE SET
                  status=excluded.status, payload_json=excluded.payload_json
                """,
                (
                    value.weakness_id,
                    application_id,
                    value.category,
                    value.status.value,
                    value.created_at.isoformat(),
                    value.model_dump_json(),
                ),
            )
            self._record_action(connection, action_id, "save_weakness", payload, value.weakness_id)
        return value

    def get_weakness(self, weakness_id: str) -> InterviewWeaknessSnapshot:
        return self._one("interview_weaknesses_v1", "weakness_id", weakness_id, InterviewWeaknessSnapshot)

    def list_weaknesses(self, application_id: str | None = None) -> list[InterviewWeaknessSnapshot]:
        if application_id is None:
            query, params = "SELECT payload_json FROM interview_weaknesses_v1 ORDER BY created_at", ()
        else:
            query, params = (
                "SELECT payload_json FROM interview_weaknesses_v1 WHERE application_id=? ORDER BY created_at",
                (application_id,),
            )
        return self._many(query, params, InterviewWeaknessSnapshot)

    def save_real_interview(self, value: RealInterviewRecord, *, action_id: str) -> RealInterviewRecord:
        payload = value.model_dump(mode="json")
        existing = self._action(action_id, "record_real", payload)
        if existing is not None:
            return self.get_real_interview(existing)
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO real_interview_records_v1 VALUES (?,?,?,?,?,?)",
                (
                    value.record_id,
                    value.application_id,
                    value.round_id,
                    value.job_id,
                    value.occurred_at.isoformat(),
                    value.model_dump_json(),
                ),
            )
            self._record_action(connection, action_id, "record_real", payload, value.record_id)
        return value

    def get_real_interview(self, record_id: str) -> RealInterviewRecord:
        return self._one("real_interview_records_v1", "record_id", record_id, RealInterviewRecord)

    def list_real_interviews(self, application_id: str | None = None) -> list[RealInterviewRecord]:
        if application_id is None:
            query, params = "SELECT payload_json FROM real_interview_records_v1 ORDER BY occurred_at", ()
        else:
            query, params = (
                "SELECT payload_json FROM real_interview_records_v1 WHERE application_id=? ORDER BY occurred_at",
                (application_id,),
            )
        return self._many(query, params, RealInterviewRecord)

    def _one(self, table: str, key: str, value: str, model: type[ModelT]) -> ModelT:
        row = self.connection().execute(
            f"SELECT payload_json FROM {table} WHERE {key}=?", (value,)
        ).fetchone()
        if row is None:
            raise KeyError(value)
        return model.model_validate_json(row["payload_json"])

    def _many(
        self,
        query: str,
        params: tuple,
        model: type[ModelT],
    ) -> list[ModelT]:
        rows = self.connection().execute(query, params).fetchall()
        return [model.model_validate_json(row["payload_json"]) for row in rows]
