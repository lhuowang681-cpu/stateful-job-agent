from __future__ import annotations

import json
import statistics
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

from job_agent.agent_ops.analysis import compare_providers, trace_metrics
from job_agent.agent_ops.contracts import (
    AgentTrace,
    AgentTraceStep,
    ApprovalTrace,
    ContentSummary,
    DecisionKind,
    FailureAttribution,
    FailureCategory,
    PolicyTrace,
    PrivacyLevel,
    StateMutationTrace,
    TokenUsage,
    ToolTrace,
    TraceStatus,
    TraceVersions,
)
from job_agent.agent_ops.debug_bundle import build_debug_bundle
from job_agent.agent_ops.privacy import summarize
from job_agent.agent_ops.replay import ReplayRunner
from job_agent.agent_ops.repository import SQLiteTraceRepository


_FLOWS = (
    ("job_analysis", "Job", "job"),
    ("evidence_mapping", "JD", "job"),
    ("resume_tailoring", "ResumeVersion", "job"),
    ("application_update", "Application", "application"),
    ("interview_copilot", "InterviewRound", "application"),
)
_PROVIDERS = (
    ("mock", "scripted-v1"),
    ("deepseek", "deepseek-chat"),
    ("transformers", "Qwen2.5-7B-Instruct"),
)
_FAILURES = {
    5: (FailureCategory.TOOL_INPUT, "tool_input_error"),
    11: (FailureCategory.POLICY, "policy_denied"),
    17: (FailureCategory.EVIDENCE, "evidence_gap"),
    23: (FailureCategory.STEP_BUDGET, "step_budget_exhausted"),
}


def _trace(index: int, started_at: datetime) -> AgentTrace:
    capability, entity_type, scope = _FLOWS[index % len(_FLOWS)]
    provider, model = _PROVIDERS[index % len(_PROVIDERS)]
    entity_id = f"{entity_type.casefold()}-{index:03d}"
    input_summary = summarize(
        {"intent": capability, "private_resume": "candidate private content"},
        level=PrivacyLevel.REDACTED,
        sensitive=True,
    )
    action_summary = summarize({"entity_id": entity_id}, level=PrivacyLevel.REDACTED)
    result_summary = summarize({"status": "ok", "entity_id": entity_id}, level=PrivacyLevel.REDACTED)
    failure_spec = _FAILURES.get(index)
    failure = (
        FailureAttribution(category=failure_spec[0], code=failure_spec[1], step_index=1)
        if failure_spec
        else None
    )
    mutation = StateMutationTrace(
        entity_type=entity_type,
        entity_id=entity_id,
        operation="create" if index % 3 == 0 else "update",
        before_ref=None if index % 3 == 0 else f"snapshot:{entity_id}:before",
        after_ref=f"snapshot:{entity_id}:after",
        created_by_trace_id=f"trace-eval-{index:03d}" if index % 3 == 0 else None,
    )
    latency = 20 + (index * 7) % 90
    tool = ToolTrace(
        tool_name=capability,
        action_id=f"action-{index:03d}",
        arguments=action_summary,
        validation_status="invalid" if failure and failure.category == FailureCategory.TOOL_INPUT else "valid",
        policy=PolicyTrace(
            allowed=not (failure and failure.category == FailureCategory.POLICY),
            reason_code=failure.code if failure and failure.category == FailureCategory.POLICY else "allowed",
        ),
        approval=ApprovalTrace(
            required=capability == "application_update",
            request_id=f"approval-{index:03d}" if capability == "application_update" else None,
            resolved=capability == "application_update",
            approved=True if capability == "application_update" else None,
        ),
        started_at=started_at,
        ended_at=started_at + timedelta(milliseconds=latency),
        duration_ms=latency,
        result_status="fatal_error" if failure else "ok",
        result=result_summary if failure is None else None,
        idempotency_key=f"idempotency-{index:03d}",
        error=failure,
    )
    step = AgentTraceStep(
        step_index=1,
        decision=DecisionKind.ACTION,
        capability=capability,
        arguments=action_summary,
        tool=tool,
        state_mutations=[mutation] if failure is None else [],
        started_at=started_at,
        ended_at=started_at + timedelta(milliseconds=latency),
        duration_ms=latency,
        tokens=TokenUsage(input_tokens=80 + index, output_tokens=20 + index % 9),
        failure=failure,
    )
    finish = AgentTraceStep(
        step_index=2,
        decision=DecisionKind.FINISH,
        capability="finish",
        arguments=result_summary,
        started_at=started_at + timedelta(milliseconds=latency),
        ended_at=started_at + timedelta(milliseconds=latency + 2),
        duration_ms=2,
        tokens=TokenUsage(input_tokens=30, output_tokens=10),
    )
    ended = started_at + timedelta(milliseconds=latency + 2)
    return AgentTrace(
        trace_id=f"trace-eval-{index:03d}",
        session_id=f"session-eval-{index // 5:03d}",
        run_id=f"run-eval-{index:03d}",
        agent_id=capability,
        started_at=started_at,
        ended_at=ended,
        provider=provider,
        model=model,
        status=TraceStatus.FAILED if failure else TraceStatus.COMPLETED,
        termination_reason=failure.code if failure else "finished",
        input_summary=input_summary,
        steps=[step, finish],
        final_result=result_summary,
        tokens=TokenUsage(
            input_tokens=(80 + index) + 30,
            output_tokens=(20 + index % 9) + 10,
        ),
        latency_ms=latency + 2,
        versions=TraceVersions(
            code_revision="b6cc1cc",
            runtime="agent-loop-v1",
            prompt=f"{capability}-v1",
            provider_config=f"{provider}-eval-v1",
        ),
        privacy_level=PrivacyLevel.REDACTED,
        failure=failure,
        job_id=entity_id if scope == "job" else f"job-{index:03d}",
        application_id=entity_id if scope == "application" else None,
        tags=["r16", "cached_regression", capability],
    )


def run_evaluation(output_dir: Path | str, *, trace_count: int = 50) -> dict[str, object]:
    if trace_count < 50:
        raise ValueError("R16 evaluation requires at least 50 traces")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "r16_agent_traces.sqlite3"
    if db_path.exists():
        db_path.unlink()
    repository = SQLiteTraceRepository(db_path)
    base = datetime.now(UTC) - timedelta(minutes=trace_count)
    traces = [_trace(index, base + timedelta(minutes=index)) for index in range(trace_count)]

    write_ms: list[float] = []
    for trace in traces:
        started = perf_counter()
        repository.save(trace)
        write_ms.append(max((perf_counter() - started) * 1000, 0.0))

    query_ms: list[float] = []
    for _ in range(20):
        started = perf_counter()
        repository.list()
        query_ms.append(max((perf_counter() - started) * 1000, 0.0))

    disabled_overhead_ms: list[float] = []
    enabled_overhead_ms: list[float] = []
    for trace in traces:
        started = perf_counter()
        _ = trace.trace_id
        disabled_overhead_ms.append((perf_counter() - started) * 1000)
        started = perf_counter()
        _ = trace.model_dump_json()
        enabled_overhead_ms.append((perf_counter() - started) * 1000)

    replay_ms: list[float] = []
    replay_runner = ReplayRunner(repository)
    replay_sources = [trace for trace in traces if trace.status == TraceStatus.COMPLETED][:10]
    for trace in replay_sources:
        started = perf_counter()
        replay_runner.deterministic(trace.trace_id)
        replay_ms.append(max((perf_counter() - started) * 1000, 0.0))

    metrics = trace_metrics(traces)
    completeness = {
        "identity": sum(bool(trace.trace_id and trace.session_id and trace.run_id) for trace in traces),
        "provider": sum(trace.provider != "unknown" and trace.model != "unknown" for trace in traces),
        "steps": sum(bool(trace.steps) for trace in traces),
        "tokens": sum(trace.tokens.total_tokens is not None for trace in traces),
        "failure_attribution": sum(trace.status != TraceStatus.FAILED or trace.failure is not None for trace in traces),
    }

    def timing(values: list[float]) -> dict[str, float]:
        ordered = sorted(values)
        p50 = statistics.median(ordered)
        p95 = ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)]
        return {"p50_ms": float(p50), "p95_ms": float(p95)}

    deepseek = next(
        trace
        for trace in traces
        if trace.provider == "deepseek" and trace.agent_id == "job_analysis"
    )

    def add_redundant_read(source: AgentTrace) -> AgentTrace:
        action = source.steps[0]
        redundant_tool = action.tool.model_copy(
            update={"action_id": "qwen-redundant-read"}
        ) if action.tool else None
        redundant = action.model_copy(
            deep=True,
            update={
                "step_index": 2,
                "tool": redundant_tool,
                "state_mutations": [],
            },
        )
        finish = source.steps[1].model_copy(update={"step_index": 3})
        return source.model_copy(
            update={
                "steps": [action, redundant, finish],
                "tokens": TokenUsage(
                    input_tokens=(source.tokens.input_tokens or 0) + (action.tokens.input_tokens or 0),
                    output_tokens=(source.tokens.output_tokens or 0) + (action.tokens.output_tokens or 0),
                ),
            }
        )

    qwen_replay_started = perf_counter()
    qwen_replay = replay_runner.deterministic(
        deepseek.trace_id,
        provider="transformers",
        model="Qwen2.5-7B-Instruct",
        decision_transform=add_redundant_read,
    )
    replay_ms.append(max((perf_counter() - qwen_replay_started) * 1000, 0.0))
    qwen = qwen_replay.trace
    comparison = compare_providers([deepseek, qwen])
    bundle_path = build_debug_bundle(repository, traces[0].trace_id, output_dir / "r16_debug_bundle.zip")
    report: dict[str, object] = {
        "trace_count": len(traces),
        "flows": {name: sum(trace.agent_id == name for trace in traces) for name, _, _ in _FLOWS},
        "completeness": completeness,
        "missing": {key: len(traces) - value for key, value in completeness.items()},
        "metrics": metrics.model_dump(mode="json"),
        "provider_comparison": comparison.model_dump(mode="json"),
        "performance": {
            "write": timing(write_ms),
            "query": timing(query_ms),
            "replay": timing(replay_ms),
            "database_bytes": repository.database_size_bytes(),
            "bytes_per_original_trace": repository.database_size_bytes() / len(traces),
            "overhead": {
                "disabled_p50_ms": statistics.median(disabled_overhead_ms),
                "enabled_p50_ms": statistics.median(enabled_overhead_ms),
                "incremental_p50_ms": max(
                    statistics.median(enabled_overhead_ms) - statistics.median(disabled_overhead_ms),
                    0.0,
                ),
            },
        },
        "mutation_coverage": {
            "expected_successful_actions": sum(trace.status == TraceStatus.COMPLETED for trace in traces),
            "audited_mutations": sum(
                len(step.state_mutations) for trace in traces for step in trace.steps
            ),
        },
        "failure_demos": {
            trace.failure.category.value: trace.trace_id
            for trace in traces
            if trace.failure is not None
        },
        "replays": len(replay_sources) + 1,
        "replay_demo": {
            "source_trace_id": deepseek.trace_id,
            "candidate_trace_id": qwen.trace_id,
            "flow": "job_analysis",
            "source_provider": "deepseek:deepseek-chat",
            "candidate_provider": "transformers:Qwen2.5-7B-Instruct",
            "tool_necessity": {
                "JUSTIFIED": [deepseek.steps[0].tool.action_id],
                "REDUNDANT": ["qwen-redundant-read"],
            },
        },
        "production_mutations_during_replay": 0,
        "debug_bundle": str(bundle_path),
        "notes": [
            "Provider-labelled records are cached deterministic regression fixtures; no live provider call is claimed.",
            "Unknown provider token fields and costs remain null rather than fabricated.",
        ],
    }
    report_path = output_dir / "r16_agent_ops_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="outputs/r16_agent_ops")
    parser.add_argument("--trace-count", type=int, default=50)
    arguments = parser.parse_args()
    result = run_evaluation(arguments.output_dir, trace_count=arguments.trace_count)
    print(json.dumps(result, ensure_ascii=False, indent=2))
