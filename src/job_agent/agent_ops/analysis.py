from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from job_agent.agent_ops.contracts import (
    AgentTrace,
    CapabilityMetric,
    CostRecord,
    MetricsSummary,
    ProviderComparison,
    SessionMetric,
    TrajectoryDiff,
)


def percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def diff_trajectories(baseline: AgentTrace, candidate: AgentTrace) -> TrajectoryDiff:
    baseline_actions = [step.capability for step in baseline.steps]
    candidate_actions = [step.capability for step in candidate.steps]
    baseline_counts = Counter(baseline_actions)
    candidate_counts = Counter(candidate_actions)
    added: list[str] = []
    removed: list[str] = []
    for name in sorted(set(baseline_counts) | set(candidate_counts)):
        added.extend([name] * max(candidate_counts[name] - baseline_counts[name], 0))
        removed.extend([name] * max(baseline_counts[name] - candidate_counts[name], 0))
    changed_arguments: list[str] = []
    for left, right in zip(baseline.steps, candidate.steps):
        if left.capability == right.capability:
            left_hash = left.arguments.sha256 if left.arguments else None
            right_hash = right.arguments.sha256 if right.arguments else None
            if left_hash != right_hash:
                changed_arguments.append(left.capability)
    baseline_mutations = {
        (item.entity_type, item.entity_id, item.operation, item.after_ref)
        for step in baseline.steps
        for item in step.state_mutations
    }
    candidate_mutations = {
        (item.entity_type, item.entity_id, item.operation, item.after_ref)
        for step in candidate.steps
        for item in step.state_mutations
    }
    mutation_changes = [
        f"{kind}:{entity}:{operation}:{after or ''}"
        for kind, entity, operation, after in sorted(baseline_mutations ^ candidate_mutations)
    ]
    left_total = baseline.tokens.total_tokens
    right_total = candidate.tokens.total_tokens
    token_delta = None if left_total is None or right_total is None else right_total - left_total
    return TrajectoryDiff(
        baseline_trace_id=baseline.trace_id,
        candidate_trace_id=candidate.trace_id,
        added_actions=added,
        removed_actions=removed,
        changed_arguments=changed_arguments,
        final_result_changed=(
            (baseline.final_result.sha256 if baseline.final_result else None)
            != (candidate.final_result.sha256 if candidate.final_result else None)
        ),
        mutation_changes=mutation_changes,
        step_delta=len(candidate.steps) - len(baseline.steps),
        token_delta=token_delta,
    )


def compare_providers(traces: list[AgentTrace]) -> ProviderComparison:
    providers = [f"{trace.provider}:{trace.model}" for trace in traces]
    return ProviderComparison(
        providers=providers,
        correctness={key: trace.status.value == "COMPLETED" for key, trace in zip(providers, traces)},
        constraint_compliance={
            key: not any(step.failure and step.failure.category.value in {"POLICY", "APPROVAL"} for step in trace.steps)
            for key, trace in zip(providers, traces)
        },
        steps={key: len(trace.steps) for key, trace in zip(providers, traces)},
        tokens={key: trace.tokens.total_tokens for key, trace in zip(providers, traces)},
        latency_ms={key: trace.latency_ms for key, trace in zip(providers, traces)},
        tool_calls={key: sum(step.tool is not None for step in trace.steps) for key, trace in zip(providers, traces)},
        failures={key: trace.failure.category.value if trace.failure else None for key, trace in zip(providers, traces)},
        diffs=[diff_trajectories(traces[0], trace) for trace in traces[1:]] if traces else [],
    )


def trace_metrics(traces: Iterable[AgentTrace]) -> MetricsSummary:
    items = list(traces)
    capabilities: dict[str, list[tuple[AgentTrace, object]]] = defaultdict(list)
    for trace in items:
        for step in trace.steps:
            capabilities[step.capability].append((trace, step))
    capability_metrics: list[CapabilityMetric] = []
    for capability, entries in sorted(capabilities.items()):
        latencies = [entry.duration_ms for _, entry in entries]
        successes = sum(entry.failure is None for _, entry in entries)
        token_values = [entry.tokens.total_tokens for _, entry in entries]
        known_tokens = [value for value in token_values if value is not None]
        capability_metrics.append(
            CapabilityMetric(
                capability=capability,
                count=len(entries),
                success_rate=successes / len(entries),
                latency_p50_ms=percentile(latencies, 0.50),
                latency_p95_ms=percentile(latencies, 0.95),
                tokens_total=sum(known_tokens) if known_tokens else None,
                tool_calls=sum(entry.tool is not None for _, entry in entries),
                state_mutations=sum(len(entry.state_mutations) for _, entry in entries),
            )
        )
    token_values = [trace.tokens.total_tokens for trace in items]
    known_tokens = [value for value in token_values if value is not None]
    failures = Counter(trace.failure.category.value for trace in items if trace.failure)
    latencies = [trace.latency_ms for trace in items]
    session_groups: dict[str, list[AgentTrace]] = defaultdict(list)
    for trace in items:
        session_groups[trace.session_id].append(trace)
    sessions: list[SessionMetric] = []
    for session_id, session_traces in sorted(session_groups.items()):
        session_token_values = [trace.tokens.total_tokens for trace in session_traces]
        known_session_tokens = [value for value in session_token_values if value is not None]
        sessions.append(
            SessionMetric(
                session_id=session_id,
                traces=len(session_traces),
                completed=sum(trace.status.value == "COMPLETED" for trace in session_traces),
                failed=sum(trace.status.value == "FAILED" for trace in session_traces),
                tokens_total=sum(known_session_tokens) if known_session_tokens else None,
                latency_total_ms=sum(trace.latency_ms for trace in session_traces),
                tool_calls=sum(step.tool is not None for trace in session_traces for step in trace.steps),
                state_mutations=sum(len(step.state_mutations) for trace in session_traces for step in trace.steps),
            )
        )
    return MetricsSummary(
        traces=len(items),
        completed=sum(trace.status.value == "COMPLETED" for trace in items),
        failed=sum(trace.status.value == "FAILED" for trace in items),
        tokens_total=sum(known_tokens) if known_tokens else None,
        tool_calls=sum(step.tool is not None for trace in items for step in trace.steps),
        state_mutations=sum(len(step.state_mutations) for trace in items for step in trace.steps),
        latency_p50_ms=percentile(latencies, 0.50),
        latency_p95_ms=percentile(latencies, 0.95),
        failures=dict(failures),
        capabilities=capability_metrics,
        sessions=sessions,
    )


def analyze_tool_necessity(trace: AgentTrace) -> dict[str, list[str]]:
    seen_success: set[tuple[str, str | None]] = set()
    justified: list[str] = []
    redundant: list[str] = []
    for step in trace.steps:
        if step.tool is None:
            continue
        identity = (step.capability, step.arguments.sha256 if step.arguments else None)
        if identity in seen_success:
            redundant.append(step.tool.action_id)
        else:
            justified.append(step.tool.action_id)
        if step.failure is None:
            seen_success.add(identity)
    return {"JUSTIFIED": justified, "REDUNDANT": redundant}


class LocalPriceCatalog:
    """Optional local rates per one million tokens; never fetched or guessed."""

    def __init__(self, rates: dict[str, dict[str, float]]) -> None:
        self.rates = rates

    @classmethod
    def from_path(cls, path: Path | str) -> "LocalPriceCatalog":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def estimate(self, trace: AgentTrace) -> CostRecord | None:
        rates = self.rates.get(f"{trace.provider}:{trace.model}")
        if rates is None or trace.tokens.input_tokens is None or trace.tokens.output_tokens is None:
            return None
        amount = (
            trace.tokens.input_tokens * rates.get("input_per_million", 0.0)
            + trace.tokens.output_tokens * rates.get("output_per_million", 0.0)
        ) / 1_000_000
        return CostRecord(amount=amount, estimated=True, source="local_price_config")
