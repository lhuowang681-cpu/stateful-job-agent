from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import Field

from job_agent.agent_ops.analysis import (
    LocalPriceCatalog,
    analyze_tool_necessity,
    compare_providers,
    diff_trajectories,
    trace_metrics,
)
from job_agent.agent_ops.api import create_trace_app
from job_agent.agent_ops.contracts import (
    ContextCategory,
    FailureCategory,
    PrivacyLevel,
    RetentionPolicy,
    RetrievalCandidateTrace,
    RetrievalTrace,
    StateMutationTrace,
    TokenUsage,
    TraceQuery,
    TraceVersions,
)
from job_agent.agent_ops.debug_bundle import build_debug_bundle
from job_agent.agent_ops.evaluation import run_evaluation
from job_agent.agent_ops.privacy import summarize
from job_agent.agent_ops.recorder import AgentTraceRecorder, classify_failure
from job_agent.agent_ops.replay import ReplayRunner, UnsafeReplayError
from job_agent.agent_ops.repository import SQLiteTraceRepository
from job_agent.agent_runtime.budgets import AgentBudget, BudgetManager, BudgetProfile
from job_agent.agent_runtime.contracts import (
    AgentAction,
    AgentFinish,
    AgentModelResponse,
    ApprovalDecision,
    ToolContext,
    ToolEffect,
    VerificationResult,
)
from job_agent.agent_runtime.loop import AgentLoop, ScriptedAgentModel
from job_agent.agent_runtime.policy import PolicyContext, PolicyEngine, compute_action_digest
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.career.durable import DurableJob, JDSnapshot
from job_agent.career.models import Job
from job_agent.interview.copilot_contracts import InterviewRound, InterviewWeaknessSnapshot
from job_agent.memory.contracts import MemoryRecord
from job_agent.resume.contracts import ResumeVersion
from job_agent.schemas import ApplicationRecord
from job_agent.schemas import StrictModel


class EchoInput(StrictModel):
    query: str = Field(min_length=1)


class EchoOutput(StrictModel):
    result: str


class PassVerifier:
    def verify(self, finish, *, goal, steps):
        return VerificationResult(
            passed=True,
            reason_code="complete",
            feedback="complete",
        )


def _run_trace(
    tmp_path,
    *,
    run_id="run-1",
    query="agent runtime",
    with_usage=False,
    tool_name="career.query",
    agent_id="job-analysis",
    effect=ToolEffect.READ_ONLY,
):
    repository = SQLiteTraceRepository(tmp_path / "traces.sqlite3")
    recorder = AgentTraceRecorder(
        repository=repository,
        job_id="job-1",
        versions=TraceVersions(
            runtime="agent-loop-v1",
            prompt="job-analysis-v3",
            provider_config="scripted-test-v1",
        ),
    )
    registry = ToolRegistry()
    registry.register(
        name=tool_name,
        description="Read career evidence",
        input_model=EchoInput,
        output_model=EchoOutput,
        handler=lambda value, context: EchoOutput(result=f"found:{value.query}"),
        effect=effect,
    )
    action = AgentAction(
                action_id=f"action-{run_id}",
                tool_name=tool_name,
                tool_arguments={"query": query},
                expected_observation="career result",
                progress_claim="read evidence",
            )
    finish = AgentFinish(
                result={"answer": "grounded"},
                completion_evidence=["career.query"],
                confidence=0.9,
            )
    responses = [action, finish]
    if with_usage:
        responses = [
            AgentModelResponse(
                decision=action,
                provider="deepseek",
                model="deepseek-chat",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=10,
                cost=0.001,
            ),
            AgentModelResponse(
                decision=finish,
                provider="deepseek",
                model="deepseek-chat",
                input_tokens=30,
                output_tokens=10,
                reasoning_tokens=5,
                cost=0.002,
            ),
        ]
    model = ScriptedAgentModel(responses)
    policy = PolicyEngine()
    policy_context = PolicyContext(
        skill_allowed_tools=(tool_name,),
        agent_allowed_tools=(tool_name,),
        runtime_allowed_tools=(tool_name,),
    )
    approvals = {}
    if effect == ToolEffect.LOCAL_STATE_MUTATION:
        pending = policy.authorize(
            action,
            registry.get(tool_name).spec,
            policy_context,
            session_id="session-1",
            run_id=run_id,
        )
        request = pending.approval_request
        approvals[compute_action_digest(action)] = ApprovalDecision(
            request_id=request.request_id,
            action_digest=request.action_digest,
            approved=True,
            session_id="session-1",
            run_id=run_id,
        )
    loop = AgentLoop(
        agent_id=agent_id,
        model=model,
        registry=registry,
        policy=policy,
        policy_context=policy_context,
        budget=BudgetManager(
            AgentBudget.for_profile(
                BudgetProfile.EVAL,
                max_model_calls=5,
                max_tool_calls=5,
                max_active_seconds=30,
            )
        ),
        verifier=PassVerifier(),
        trajectory=recorder,
    )
    loop.run(
        session_id="session-1",
        run_id=run_id,
        goal={"request": "analyze", "resume_text": "SECRET RESUME"},
        tool_context=ToolContext(
            session_id="session-1",
            run_id=run_id,
            agent_id=agent_id,
            workspace_root="fixtures",
        ),
        approvals=approvals,
    )
    return repository, recorder.trace


def test_runtime_events_form_complete_privacy_safe_trace(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    assert trace is not None
    persisted = repository.get(trace.trace_id)
    assert persisted.status.value == "COMPLETED"
    assert persisted.provider == "scripted"
    assert [step.capability for step in persisted.steps] == ["career.query", "finish"]
    assert persisted.steps[0].tool.result_status == "ok"
    assert persisted.steps[0].tool.validation_status == "valid"
    assert persisted.versions.prompt == "job-analysis-v3"
    assert "SECRET RESUME" not in (tmp_path / "traces.sqlite3").read_bytes().decode("utf-8", errors="ignore")


def test_new_durable_entities_accept_optional_creation_trace_link() -> None:
    assert "created_by_trace_id" in Job.__dataclass_fields__
    for model in (
        DurableJob,
        JDSnapshot,
        ResumeVersion,
        ApplicationRecord,
        InterviewRound,
        InterviewWeaknessSnapshot,
        MemoryRecord,
    ):
        assert model.model_fields["created_by_trace_id"].default is None


@pytest.mark.parametrize(
    ("agent_id", "tool_name", "entity_type"),
    [
        ("job-analysis", "career.query", "Job"),
        ("resume-tailoring", "resume.version.save", "ResumeVersion"),
        ("application-lifecycle", "application.stage.update", "Application"),
        ("interview-copilot", "interview.round.save", "InterviewRound"),
    ],
)
def test_end_to_end_business_flow_trace_includes_governed_mutation(
    tmp_path, agent_id, tool_name, entity_type
) -> None:
    repository, trace = _run_trace(
        tmp_path / agent_id,
        run_id=f"run-{agent_id}",
        agent_id=agent_id,
        tool_name=tool_name,
        effect=ToolEffect.LOCAL_STATE_MUTATION,
    )
    recorder = AgentTraceRecorder(repository=repository)
    recorder.trace = trace
    recorder.record_mutation(
        1,
        StateMutationTrace(
            entity_type=entity_type,
            entity_id=f"entity-{agent_id}",
            operation="create",
            after_ref=f"snapshot:{agent_id}:v1",
        ),
    )
    repository.save(recorder.trace)
    saved = repository.get(trace.trace_id)
    assert saved.steps[0].policy.allowed is True
    assert saved.steps[0].approval.required is True
    assert saved.steps[0].approval.approved is True
    assert saved.steps[0].state_mutations[0].created_by_trace_id == trace.trace_id


def test_context_mutation_and_retrieval_metadata_exclude_source_body(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    recorder = AgentTraceRecorder(repository=repository)
    recorder.trace = trace
    recorder.record_context(
        ContextCategory.MEMORY,
        {"preference": "Hangzhou", "api_key": "secret"},
        included=True,
        reason="location filter",
        sensitive=True,
    )
    recorder.record_mutation(
        1,
        StateMutationTrace(
            entity_type="Job",
            entity_id="job-1",
            operation="create",
            after_ref="snapshot:job-1:v1",
        ),
    )
    recorder.record_retrieval(
        1,
        RetrievalTrace(
            query=summarize("MCP runtime", sensitive=True),
            requirement_atom_id="req-1",
            method="hybrid",
            candidates=[
                RetrievalCandidateTrace(chunk_id="chunk-1", rank=1, score=0.9, selected=True)
            ],
            entailment="SUPPORTED",
            selected_evidence_ids=["evidence-1"],
            source_span_refs=["span-1"],
            aggregation="best_supported",
        ),
    )
    repository.save(recorder.trace)
    saved = repository.get(trace.trace_id)
    assert saved.context[0].content.preview is None
    assert saved.steps[0].state_mutations[0].created_by_trace_id == trace.trace_id
    assert saved.steps[0].retrievals[0].candidates[0].chunk_id == "chunk-1"
    assert "source body" not in saved.model_dump_json()


def test_repository_filters_every_required_dimension(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    assert repository.list(TraceQuery(session_id="session-1"))
    assert repository.list(TraceQuery(provider="scripted", model="scripted"))
    assert repository.list(TraceQuery(capability="career.query"))
    assert repository.list(TraceQuery(status=trace.status, job_id="job-1"))
    assert repository.list(TraceQuery(started_after=trace.started_at - timedelta(seconds=1)))
    assert repository.list(TraceQuery(application_id="missing")) == []


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("model_schema_error", FailureCategory.MODEL_SCHEMA),
        ("referent_ambiguous", FailureCategory.REFERENT),
        ("policy_denied", FailureCategory.POLICY),
        ("tool_input_error", FailureCategory.TOOL_INPUT),
        ("tool_timeout", FailureCategory.TIMEOUT),
        ("evidence_gap", FailureCategory.EVIDENCE),
        ("step_budget_exhausted", FailureCategory.STEP_BUDGET),
        ("provider_rate_limit", FailureCategory.EXTERNAL_PROVIDER),
    ],
)
def test_failure_taxonomy(code, category) -> None:
    assert classify_failure(code).category == category


def test_deterministic_replay_uses_recording_and_never_mutates_production(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    replay = ReplayRunner(repository).deterministic(
        trace.trace_id,
        provider="transformers",
        model="Qwen2.5-7B-Instruct",
    )
    assert replay.used_recorded_observations is True
    assert replay.used_recorded_state is True
    assert replay.production_mutation is False
    assert replay.trace.provider == "transformers"
    assert replay.trace.steps[0].tool.result.sha256 == trace.steps[0].tool.result.sha256


def test_live_replay_blocks_writes_without_isolated_sandbox(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    with pytest.raises(UnsafeReplayError, match="isolated sandbox"):
        ReplayRunner(repository).live_isolated(
            trace.trace_id,
            execute=lambda source: source,
            isolated_sandbox=False,
            read_only_capabilities=set(),
        )


def test_trajectory_diff_and_provider_comparison_have_no_total_score(tmp_path) -> None:
    repository, baseline = _run_trace(tmp_path, run_id="baseline")
    replay = ReplayRunner(repository).deterministic(
        baseline.trace_id,
        provider="deepseek",
        model="deepseek-chat",
    ).trace
    replay = replay.model_copy(update={"steps": replay.steps[:-1]})
    diff = diff_trajectories(baseline, replay)
    comparison = compare_providers([baseline, replay])
    assert diff.removed_actions == ["finish"]
    assert diff.step_delta == -1
    assert "total_score" not in comparison.model_dump()
    assert comparison.providers == ["scripted:scripted", "deepseek:deepseek-chat"]


def test_metrics_aggregate_tokens_latency_tools_and_mutations(tmp_path) -> None:
    repository, first = _run_trace(tmp_path, run_id="first")
    _, second = _run_trace(tmp_path / "other", run_id="second")
    metrics = trace_metrics([first, second])
    assert metrics.traces == 2
    assert metrics.completed == 2
    assert metrics.tool_calls == 2
    assert {item.capability for item in metrics.capabilities} == {"career.query", "finish"}
    assert len(metrics.sessions) == 1
    assert metrics.sessions[0].traces == 2


def test_redundant_tool_analysis_is_deterministic(tmp_path) -> None:
    _, trace = _run_trace(tmp_path)
    duplicate = trace.steps[0].model_copy(
        update={"step_index": 2, "tool": trace.steps[0].tool.model_copy(update={"action_id": "duplicate"})}
    )
    trace = trace.model_copy(update={"steps": [trace.steps[0], duplicate]})
    result = analyze_tool_necessity(trace)
    assert result == {"JUSTIFIED": [trace.steps[0].tool.action_id], "REDUNDANT": ["duplicate"]}


def test_debug_bundle_is_redacted(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    bundle = build_debug_bundle(repository, trace.trace_id, tmp_path / "debug.zip")
    with zipfile.ZipFile(bundle) as archive:
        contents = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
    assert "SECRET RESUME" not in contents
    assert "raw prompt" not in contents.casefold()
    assert "Redacted Job Agent debug bundle" in contents


def test_trace_api_lists_reads_replays_compares_and_renders(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    client = TestClient(create_trace_app(repository))
    assert client.get("/traces").status_code == 200
    assert client.get(f"/traces/{trace.trace_id}").json()["trace_id"] == trace.trace_id
    assert len(client.get(f"/traces/{trace.trace_id}/steps").json()) == 2
    replay = client.post(
        f"/traces/{trace.trace_id}/replay",
        json={"provider": "mock", "model": "comparison"},
    )
    assert replay.status_code == 200
    replay_id = replay.json()["trace"]["trace_id"]
    compared = client.post("/traces/compare", json={"trace_ids": [trace.trace_id, replay_id]})
    assert compared.status_code == 200
    assert client.get("/traces-metrics/summary").json()["traces"] == 2
    assert client.get(f"/debug/traces/{trace.trace_id}").status_code == 200


def test_retention_defaults_to_forever_and_supports_metadata_only(tmp_path) -> None:
    repository, trace = _run_trace(tmp_path)
    assert repository.apply_retention(now=trace.started_at + timedelta(days=100)) == 0
    metadata_repository = SQLiteTraceRepository(
        tmp_path / "metadata.sqlite3",
        retention=RetentionPolicy(mode="metadata_only_after_days", days=30),
    )
    metadata_repository.save(trace)
    assert metadata_repository.apply_retention(now=trace.started_at + timedelta(days=31)) == 1
    retained = metadata_repository.get(trace.trace_id)
    assert retained.privacy_level == PrivacyLevel.METADATA_ONLY
    assert retained.steps == []


def test_cost_is_estimated_only_from_explicit_local_config(tmp_path) -> None:
    _, trace = _run_trace(tmp_path)
    assert trace.cost is None
    trace = trace.model_copy(
        update={"tokens": TokenUsage(input_tokens=100, output_tokens=50)}
    )
    catalog = LocalPriceCatalog(
        {"scripted:scripted": {"input_per_million": 1.0, "output_per_million": 2.0}}
    )
    estimated = catalog.estimate(trace)
    assert estimated is not None
    assert estimated.estimated is True
    assert estimated.source == "local_price_config"


def test_provider_supplied_cached_reasoning_tokens_and_cost_are_preserved(tmp_path) -> None:
    _, trace = _run_trace(tmp_path, with_usage=True)
    assert trace.tokens.input_tokens == 130
    assert trace.tokens.output_tokens == 30
    assert trace.tokens.cached_tokens == 10
    assert trace.tokens.reasoning_tokens == 5
    assert trace.cost.amount == pytest.approx(0.003)
    assert trace.cost.estimated is False


def test_r16_evaluation_covers_fifty_traces_and_five_flows(tmp_path) -> None:
    report = run_evaluation(tmp_path / "evaluation", trace_count=50)
    assert report["trace_count"] == 50
    assert set(report["flows"]) == {
        "job_analysis",
        "evidence_mapping",
        "resume_tailoring",
        "application_update",
        "interview_copilot",
    }
    assert all(value == 0 for value in report["missing"].values())
    assert report["production_mutations_during_replay"] == 0
    assert report["replay_demo"]["flow"] == "job_analysis"
    assert report["replay_demo"]["tool_necessity"]["REDUNDANT"] == [
        "qwen-redundant-read"
    ]
    assert set(report["failure_demos"]) == {
        "TOOL_INPUT",
        "POLICY",
        "EVIDENCE",
        "STEP_BUDGET",
    }
    assert report["mutation_coverage"]["audited_mutations"] == 46
    assert report["performance"]["overhead"]["incremental_p50_ms"] >= 0
    assert (tmp_path / "evaluation" / "r16_agent_ops_report.json").exists()
