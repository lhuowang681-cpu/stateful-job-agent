from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable
from uuid import uuid4

from job_agent.agent_ops.contracts import (
    AgentTrace,
    ReplayMode,
    ReplayResult,
)
from job_agent.agent_ops.repository import SQLiteTraceRepository


class UnsafeReplayError(RuntimeError):
    pass


class IncompleteReplayFixtureError(RuntimeError):
    pass


class ReplayRunner:
    def __init__(self, repository: SQLiteTraceRepository) -> None:
        self.repository = repository

    def deterministic(
        self,
        trace_id: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        decision_transform: Callable[[AgentTrace], AgentTrace] | None = None,
    ) -> ReplayResult:
        source = self.repository.get(trace_id)
        missing = [
            step.tool.action_id
            for step in source.steps
            if step.tool is not None and step.tool.result is None
        ]
        if missing:
            raise IncompleteReplayFixtureError(
                f"recorded observations missing for: {', '.join(missing)}"
            )
        replayed = source.model_copy(deep=True)
        if decision_transform is not None:
            replayed = decision_transform(replayed)
        now = datetime.now(UTC)
        replayed = replayed.model_copy(
            update={
                "trace_id": f"trace-replay-{uuid4().hex}",
                "run_id": f"replay-{uuid4().hex}",
                "started_at": now,
                "ended_at": now,
                "provider": provider or replayed.provider,
                "model": model or replayed.model,
                "status": replayed.status,
                "termination_reason": f"deterministic_replay:{source.termination_reason or 'unknown'}",
                "latency_ms": 0,
                "tags": [*replayed.tags, "replay", f"source:{source.trace_id}"],
            }
        )
        self.repository.save(replayed)
        return ReplayResult(
            replay_id=replayed.run_id,
            source_trace_id=source.trace_id,
            mode=ReplayMode.DETERMINISTIC,
            trace=replayed,
            used_recorded_observations=True,
            used_recorded_state=True,
            production_mutation=False,
        )

    def live_isolated(
        self,
        trace_id: str,
        *,
        execute: Callable[[AgentTrace], AgentTrace],
        isolated_sandbox: bool,
        read_only_capabilities: set[str] | None = None,
    ) -> ReplayResult:
        source = self.repository.get(trace_id)
        read_only_capabilities = read_only_capabilities or set()
        is_read_only = all(
            step.tool is None or step.capability in read_only_capabilities
            for step in source.steps
        )
        if not isolated_sandbox and not is_read_only:
            raise UnsafeReplayError("live replay with writes requires an isolated sandbox")
        candidate = execute(source.model_copy(deep=True))
        candidate = candidate.model_copy(
            update={
                "trace_id": f"trace-live-replay-{uuid4().hex}",
                "run_id": f"live-replay-{uuid4().hex}",
                "tags": [*candidate.tags, "live_replay", f"source:{source.trace_id}"],
            }
        )
        self.repository.save(candidate)
        return ReplayResult(
            replay_id=candidate.run_id,
            source_trace_id=source.trace_id,
            mode=ReplayMode.LIVE_ISOLATED,
            trace=candidate,
            used_recorded_observations=False,
            used_recorded_state=True,
            production_mutation=False,
        )
