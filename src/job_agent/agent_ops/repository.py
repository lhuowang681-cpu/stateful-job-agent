from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from job_agent.agent_ops.contracts import (
    AgentTrace,
    PrivacyLevel,
    RetentionPolicy,
    TraceQuery,
)


class TraceNotFoundError(LookupError):
    pass


class SQLiteTraceRepository:
    """Queryable local trace store. Payloads are already privacy-filtered."""

    def __init__(self, path: Path | str, *, retention: RetentionPolicy | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention = retention or RetentionPolicy()
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_traces (
                    trace_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    failure_category TEXT,
                    job_id TEXT,
                    application_id TEXT,
                    privacy_level TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_traces_started ON agent_traces(started_at);
                CREATE INDEX IF NOT EXISTS idx_traces_session ON agent_traces(session_id);
                CREATE INDEX IF NOT EXISTS idx_traces_provider_model ON agent_traces(provider, model);
                CREATE INDEX IF NOT EXISTS idx_traces_status_failure ON agent_traces(status, failure_category);
                CREATE INDEX IF NOT EXISTS idx_traces_job ON agent_traces(job_id);
                CREATE INDEX IF NOT EXISTS idx_traces_application ON agent_traces(application_id);
                CREATE TABLE IF NOT EXISTS trace_capabilities (
                    trace_id TEXT NOT NULL REFERENCES agent_traces(trace_id) ON DELETE CASCADE,
                    capability TEXT NOT NULL,
                    PRIMARY KEY(trace_id, capability)
                );
                CREATE INDEX IF NOT EXISTS idx_trace_capability ON trace_capabilities(capability);
                """
            )

    def save(self, trace: AgentTrace) -> None:
        payload = trace.model_dump_json()
        capabilities = sorted({step.capability for step in trace.steps})
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_traces(
                    trace_id, session_id, run_id, started_at, ended_at, provider,
                    model, status, failure_category, job_id, application_id,
                    privacy_level, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    session_id=excluded.session_id, run_id=excluded.run_id,
                    started_at=excluded.started_at, ended_at=excluded.ended_at,
                    provider=excluded.provider, model=excluded.model,
                    status=excluded.status, failure_category=excluded.failure_category,
                    job_id=excluded.job_id, application_id=excluded.application_id,
                    privacy_level=excluded.privacy_level, payload=excluded.payload
                """,
                (
                    trace.trace_id,
                    trace.session_id,
                    trace.run_id,
                    trace.started_at.isoformat(),
                    trace.ended_at.isoformat() if trace.ended_at else None,
                    trace.provider,
                    trace.model,
                    trace.status.value,
                    trace.failure.category.value if trace.failure else None,
                    trace.job_id,
                    trace.application_id,
                    trace.privacy_level.value,
                    payload,
                ),
            )
            connection.execute("DELETE FROM trace_capabilities WHERE trace_id = ?", (trace.trace_id,))
            connection.executemany(
                "INSERT INTO trace_capabilities(trace_id, capability) VALUES (?, ?)",
                [(trace.trace_id, capability) for capability in capabilities],
            )

    def get(self, trace_id: str) -> AgentTrace:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM agent_traces WHERE trace_id = ?", (trace_id,)
            ).fetchone()
        if row is None:
            raise TraceNotFoundError(trace_id)
        return AgentTrace.model_validate_json(row["payload"])

    def list(self, query: TraceQuery | None = None) -> list[AgentTrace]:
        query = query or TraceQuery()
        clauses: list[str] = []
        parameters: list[object] = []
        fields = {
            "session_id": query.session_id,
            "provider": query.provider,
            "model": query.model,
            "status": query.status.value if query.status else None,
            "failure_category": query.failure.value if query.failure else None,
            "job_id": query.job_id,
            "application_id": query.application_id,
        }
        for field, value in fields.items():
            if value is not None:
                clauses.append(f"t.{field} = ?")
                parameters.append(value)
        if query.started_after is not None:
            clauses.append("t.started_at >= ?")
            parameters.append(query.started_after.isoformat())
        if query.started_before is not None:
            clauses.append("t.started_at <= ?")
            parameters.append(query.started_before.isoformat())
        if query.capability is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM trace_capabilities c WHERE c.trace_id=t.trace_id AND c.capability=?)"
            )
            parameters.append(query.capability)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(query.limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT t.payload FROM agent_traces t {where} ORDER BY t.started_at DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [AgentTrace.model_validate_json(row["payload"]) for row in rows]

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM agent_traces").fetchone()[0])

    def database_size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0

    def apply_retention(self, *, now: datetime | None = None) -> int:
        if self.retention.mode == "keep_forever":
            return 0
        now = now or datetime.now(UTC)
        cutoff = now - timedelta(days=self.retention.days or 0)
        old = self.list(TraceQuery(started_before=cutoff, limit=1000))
        with self._lock, self._connect() as connection:
            if self.retention.mode == "delete_after_days":
                connection.executemany(
                    "DELETE FROM agent_traces WHERE trace_id = ?",
                    [(trace.trace_id,) for trace in old],
                )
            else:
                for trace in old:
                    metadata = trace.model_copy(
                        update={
                            "privacy_level": PrivacyLevel.METADATA_ONLY,
                            "context": [],
                            "steps": [],
                            "final_result": None,
                        }
                    )
                    connection.execute(
                        "UPDATE agent_traces SET privacy_level=?, payload=? WHERE trace_id=?",
                        (PrivacyLevel.METADATA_ONLY.value, metadata.model_dump_json(), trace.trace_id),
                    )
                    connection.execute("DELETE FROM trace_capabilities WHERE trace_id=?", (trace.trace_id,))
        return len(old)
