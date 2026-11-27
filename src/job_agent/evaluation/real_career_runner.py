from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from job_agent.agent_runtime.budgets import (
    AgentBudget,
    BudgetManager,
    BudgetProfile,
)
from job_agent.agent_runtime.mcp_adapter import MCPToolAdapter
from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.evaluation.real_career_data import (
    EvidencePrediction,
    ExtractionPrediction,
    RequirementGoldRecord,
    audit_real_career_dataset,
    compare_job_analyses,
    dataset_summary,
    evaluate_evidence,
    evaluate_requirement_extraction,
    evaluate_retrieval,
    load_real_career_dataset,
)
from job_agent.evidence.contracts import (
    EvidenceMappingCandidate,
    RequirementAnalysisCandidate,
    SourceDocumentRef,
    SourceInput,
)
from job_agent.evidence.level_policy import EvidenceLevelPolicy
from job_agent.evidence.requirements import RequirementAnalyzer
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.jd_match_analysis import JobBasicInfo, JobMatchAnalysis
from job_agent.knowledge.career_knowledge_eval import load_durable_career_eval
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.durable import (
    CareerKnowledgeLifecycle,
    EmbeddingIdentity,
    KnowledgeRepository,
)
from job_agent.llm.harness import LLMHarness
from job_agent.llm.providers.deepseek_compatible import DeepSeekCompatibleProvider
from job_agent.llm.skill_registry import SkillSpec
from job_agent.memory.contracts import UserState
from job_agent.memory.user_state_store import UserStateStore
from job_agent.memory_aware_job_analysis import (
    GovernedCareerKnowledgeRuntime,
    MemoryAwareJobAnalysisService,
)


DATASET_VERSION = "real-career-v1"


class _SemanticRegistry:
    def get(self, skill_id: str) -> SkillSpec:
        output_schema = (
            RequirementAnalysisCandidate
            if skill_id == "jd-analysis"
            else EvidenceMappingCandidate
        )
        return SkillSpec(
            skill_id=skill_id,
            version="real-career-eval-v1",
            instructions=(
                "Use only explicit job requirements and directly cited candidate "
                "evidence. Return exactly one JSON object matching the schema."
            ),
            reference_paths=(),
            output_schema=output_schema,
        )


class _DiagnosticDeepSeekProvider(DeepSeekCompatibleProvider):
    """Keep raw structured-output diagnostics outside formal business results."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.diagnostics: list[dict[str, Any]] = []

    def generate_structured(self, **kwargs: Any):
        record: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": kwargs["system_prompt"]},
                {"role": "user", "content": kwargs["user_prompt"]},
            ],
            "provider": self.provider_name,
            "model": self.model,
            "config": {
                "response_format_mode": self.response_format_mode,
                "temperature": kwargs["temperature"],
                "max_output_tokens": kwargs["max_output_tokens"],
                "timeout_s": self.timeout_s,
            },
            "output_schema": kwargs["output_schema"].__name__,
        }
        try:
            result = super().generate_structured(**kwargs)
        except Exception as exc:
            record.update(
                {
                    "raw_output": None,
                    "output_length": 0,
                    "json_extraction_result": None,
                    "schema_valid": False,
                    "validation_error": f"{type(exc).__name__}: {exc}",
                    "termination": None,
                }
            )
            self.diagnostics.append(record)
            raise
        record.update(
            {
                "raw_output": result.raw_output,
                "output_length": len(result.raw_output or ""),
                "json_extraction_result": result.parsed_output,
                "schema_valid": result.schema_valid,
                "validation_error": result.error_detail or result.error_code,
                "termination": {
                    "finish_reason": result.finish_reason,
                    "completion_truncated": result.completion_truncated,
                },
                "tokens": {
                    "input": result.input_tokens,
                    "output": result.output_tokens,
                },
            }
        )
        self.diagnostics.append(record)
        return result


def run_real_career_evaluation(
    *,
    jobs_path: str | Path,
    requirements_path: str | Path,
    career_dataset_root: str | Path,
    repository_root: str | Path,
    state_root: str | Path,
    model_path: str,
    deepseek_api_key: str,
    device: str = "cuda",
    full_match_jobs: int = 12,
) -> dict[str, Any]:
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    state = Path(state_root)
    state.mkdir(parents=True, exist_ok=True)
    dataset = load_real_career_dataset(
        jobs_path=jobs_path,
        requirements_path=requirements_path,
        dataset_version=DATASET_VERSION,
    )
    career_dataset = load_durable_career_eval(
        career_dataset_root,
        repository_root=repository_root,
    )
    embedding_identity = EmbeddingIdentity(
        provider="sentence-transformers",
        model="Qwen/Qwen3-Embedding-0.6B",
        dimension=1024,
    )
    embedding_backend = QwenEmbeddingBackend(model_path, device=device)
    repository_path = state / "knowledge.sqlite"
    index_path = state / "career.faiss"
    manifest_path = state / "career-index-manifest.json"
    repository = KnowledgeRepository(repository_path)
    lifecycle = CareerKnowledgeLifecycle(
        repository=repository,
        embedding_backend=embedding_backend,
        embedding_identity=embedding_identity,
        index_path=index_path,
        manifest_path=manifest_path,
        max_chars=2000,
    )
    for source in career_dataset.documents:
        lifecycle.ingest_file(
            source.path,
            document_id=source.document_id,
            source_type=source.source_type,
            title=source.title,
            source_uri=source.source_uri,
            metadata={"material_kind": "real_project_material"},
        )
    candidate_documents = tuple(repository.list_active_documents())
    audit = audit_real_career_dataset(
        dataset,
        candidate_documents=candidate_documents,
    )
    if not audit.passed:
        raise RuntimeError(f"dataset leakage audit failed: {audit.errors}")

    service = CareerKnowledgeService(
        lifecycle.candidate_retriever(load=False),
        lifecycle=lifecycle,
    )
    active_versions = {
        item.document_id: item.version for item in candidate_documents
    }
    retrieval = evaluate_retrieval(
        dataset,
        service=service,
        active_versions=active_versions,
        split="frozen",
    )
    evaluation_rankings = dict(retrieval.rankings)
    for requirement in dataset.requirements:
        if requirement.split != "frozen" or requirement.requirement_id in evaluation_rankings:
            continue
        evaluation_rankings[requirement.requirement_id] = [
            item.chunk.document_id
            for item in service.query_candidate_evidence(
                requirement.raw_requirement_text,
                5,
            )
        ]

    provider = _DiagnosticDeepSeekProvider(
        api_key=deepseek_api_key,
        timeout_s=120.0,
    )
    harness = LLMHarness(provider)
    (
        extraction_predictions,
        extraction_bad_cases,
        requirement_diagnostics,
    ) = _run_extraction(
        dataset.jobs,
        harness=harness,
        diagnostic_provider=provider,
        session_root=state / "requirement-extraction",
    )
    extraction = evaluate_requirement_extraction(
        dataset,
        extraction_predictions,
        split="frozen",
    )
    requirement_diagnostics["coverage"] = _requirement_coverage_diagnostics(
        dataset,
        extraction_predictions,
    )

    bridge = StdioMCPClientBridge(
        "src/job_agent/knowledge/career_mcp_server.py",
        startup_timeout_s=90,
        call_timeout_s=120,
        server_env={
            "QWEN_EMBEDDING_MODEL_PATH": model_path,
            "CAREER_KNOWLEDGE_DEVICE": device,
            "CAREER_KNOWLEDGE_DB_PATH": str(repository_path),
            "CAREER_KNOWLEDGE_INDEX_PATH": str(index_path),
            "CAREER_KNOWLEDGE_MANIFEST_PATH": str(manifest_path),
            "CAREER_KNOWLEDGE_EMBEDDING_DIMENSION": "1024",
        },
    )
    bridge.start()
    try:
        runtime = _career_runtime(bridge)
        analyses, full_bad_cases = _run_full_matches(
            dataset.jobs,
            dataset.requirements,
            count=full_match_jobs,
            candidate_documents=candidate_documents,
            runtime=runtime,
            harness=harness,
            state_root=state,
        )
        evidence_predictions = _evidence_predictions(
            analyses,
            dataset.requirements,
            candidate_documents=candidate_documents,
        )
        evidence = evaluate_evidence(
            dataset,
            evidence_predictions,
            split="frozen",
            source_caps={
                document.document_id: _source_cap(document)
                for document in candidate_documents
            },
        )
        evidence_cases = _evidence_case_details(
            dataset,
            evidence_predictions,
            retrieval_rankings=evaluation_rankings,
        )
        integration_hits = runtime.query_candidate_evidence(
            query="它要求 Kubernetes production experience，我有相关经历吗？",
            top_k=5,
            session_id="r8-real-agent-integration",
            run_id="r8-real-agent-integration",
        )
        requested_matches = min(
            full_match_jobs,
            sum(item.split == "frozen" for item in dataset.jobs),
        )
        agent_integration = {
            "passed": bool(integration_hits) and len(analyses) == requested_matches,
            "governed_query_passed": bool(integration_hits),
            "full_flow_passed": len(analyses) == requested_matches,
            "flow": "Agent Runtime -> MCP -> durable Career Knowledge",
            "tool": CAREER_QUERY_TOOL,
            "top_document_id": (
                integration_hits[0].chunk.document_id
                if integration_hits
                else None
            ),
            "trajectory_events": len(runtime.trajectory.events),
        }
    finally:
        bridge.close()

    comparison = None
    if len(analyses) >= 2:
        compared = compare_job_analyses(analyses[0][1], analyses[1][1])
        comparison = compared.model_dump(mode="json")

    evaluated_requirement_ids = {
        item.requirement_id for item in evidence_predictions
    }
    full_gold = [
        item
        for item in dataset.requirements
        if item.split == "frozen" and item.requirement_id in evaluated_requirement_ids
    ]
    full_correct = sum(
        _status_class(prediction.status)
        == next(
            item.expected_evidence_status
            for item in full_gold
            if item.requirement_id == prediction.requirement_id
        )
        for prediction in evidence_predictions
        if prediction.requirement_id in {item.requirement_id for item in full_gold}
    )
    preference_checks = sum(
        _preference_is_consistent(analysis)
        for _, analysis in analyses
    )
    traces = harness.traces
    completed_jobs = len(analyses)
    total_tokens = sum(
        (item.input_tokens or 0) + (item.output_tokens or 0)
        for item in traces
    )
    return {
        "dataset": dataset_summary(dataset),
        "leakage_audit": audit.model_dump(mode="json"),
        "requirement_extraction": extraction.model_dump(mode="json"),
        "requirement_diagnostics": requirement_diagnostics,
        "retrieval": retrieval.model_dump(mode="json"),
        "evidence": evidence.model_dump(mode="json"),
        "evidence_cases": evidence_cases,
        "full_job_match": {
            "jobs_requested": min(
                full_match_jobs,
                sum(item.split == "frozen" for item in dataset.jobs),
            ),
            "jobs_completed": len(analyses),
            "requirements_evaluated": len(full_gold),
            "correct_strength_or_gap": full_correct,
            "correct_strength_or_gap_rate": (
                full_correct / len(full_gold) if full_gold else 0.0
            ),
            "preference_consistency": (
                preference_checks / len(analyses) if analyses else 0.0
            ),
            "comparison": comparison,
        },
        "agent_integration": agent_integration,
        "api": {
            "provider": "deepseek",
            "calls": len(traces),
            "input_tokens": sum(item.input_tokens or 0 for item in traces),
            "output_tokens": sum(item.output_tokens or 0 for item in traces),
            "cost": None,
            "schema_valid_calls": sum(item.schema_valid for item in traces),
            "calls_per_completed_job": (
                len(traces) / completed_jobs if completed_jobs else None
            ),
            "tokens_per_completed_job": (
                total_tokens / completed_jobs if completed_jobs else None
            ),
        },
        "local_qwen": {
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
            "device": device,
        },
        "bad_cases": [
            *extraction_bad_cases,
            *retrieval.bad_cases,
            *full_bad_cases,
        ],
    }


def _run_extraction(
    jobs: Sequence[Any],
    *,
    harness: LLMHarness,
    diagnostic_provider: _DiagnosticDeepSeekProvider | None,
    session_root: Path,
    job_ids: set[str] | None = None,
) -> tuple[
    list[ExtractionPrediction],
    list[dict[str, str]],
    dict[str, Any],
]:
    predictions: list[ExtractionPrediction] = []
    bad_cases: list[dict[str, str]] = []
    root_causes: Counter[str] = Counter()
    repaired_jobs = 0
    diagnostics_root = session_root / "diagnostics"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    for job in jobs:
        if job.split != "frozen" or (job_ids is not None and job.job_id not in job_ids):
            continue
        diagnostic_start = (
            len(diagnostic_provider.diagnostics) if diagnostic_provider else 0
        )
        source_store = EvidenceSourceStore(session_root / job.job_id)
        catalog = source_store.snapshot(
            f"{job.job_id}-requirements",
            [
                SourceInput(
                    kind="raw_jd",
                    display_label=job.title,
                    text=job.raw_jd_text,
                )
            ],
        )
        try:
            analysis = RequirementAnalyzer(
                registry=_SemanticRegistry(),
                harness=harness,
                source_store=source_store,
            ).analyze(
                catalog.documents[0],
                catalog=catalog,
                session_id="r8-frozen-requirement-extraction",
                run_id=job.job_id,
            )
            predictions.append(
                ExtractionPrediction(
                    job_id=job.job_id,
                    schema_valid=True,
                    requirements=[item.text for item in analysis.atoms],
                    source_quotes=[
                        item.source_span.exact_quote for item in analysis.atoms
                    ],
                )
            )
        except Exception as exc:
            predictions.append(
                ExtractionPrediction(
                    job_id=job.job_id,
                    schema_valid=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            bad_cases.append(
                {
                    "case": job.job_id,
                    "layer": "REQUIREMENT_EXTRACTION",
                    "observation": f"{type(exc).__name__}: {exc}",
                }
            )
        attempts = (
            diagnostic_provider.diagnostics[diagnostic_start:]
            if diagnostic_provider
            else []
        )
        for index, attempt in enumerate(attempts, start=1):
            attempt["attempt"] = index
        failed_attempts = [item for item in attempts if not item.get("schema_valid")]
        if failed_attempts:
            root_causes[_classify_requirement_failure(failed_attempts[0])] += 1
        if len(attempts) > 1 and predictions[-1].schema_valid:
            repaired_jobs += 1
        diagnostic_record = {
            "job_id": job.job_id,
            "input_jd_length": len(job.raw_jd_text),
            "completed": predictions[-1].schema_valid,
            "final_error": predictions[-1].error,
            "attempts": attempts,
            "repair_output": (
                attempts[1].get("raw_output") if len(attempts) > 1 else None
            ),
        }
        (diagnostics_root / f"{job.job_id}.json").write_text(
            json.dumps(diagnostic_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return (
        predictions,
        bad_cases,
        {
            "root_cause_distribution": dict(sorted(root_causes.items())),
            "jobs_repaired": repaired_jobs,
            "diagnostic_directory": str(diagnostics_root),
        },
    )


def _career_runtime(bridge: StdioMCPClientBridge) -> GovernedCareerKnowledgeRuntime:
    registry = ToolRegistry()
    adapter = MCPToolAdapter(bridge)
    for tool in bridge.list_tools():
        adapter.register_tool(registry=registry, tool=tool)
    return GovernedCareerKnowledgeRuntime(
        registry=registry,
        policy_context=PolicyContext(
            skill_allowed_tools=(CAREER_QUERY_TOOL,),
            agent_allowed_tools=(CAREER_QUERY_TOOL,),
            runtime_allowed_tools=(CAREER_QUERY_TOOL,),
        ),
        budget=BudgetManager(
            AgentBudget.for_profile(
                BudgetProfile.EVAL,
                max_model_calls=100,
                max_tool_calls=100,
                max_active_seconds=60 * 60,
            )
        ),
    )


def _run_full_matches(
    jobs: Sequence[Any],
    requirements: Sequence[RequirementGoldRecord],
    *,
    count: int,
    candidate_documents: Sequence[Any],
    runtime: GovernedCareerKnowledgeRuntime,
    harness: LLMHarness,
    state_root: Path,
) -> tuple[list[tuple[str, JobMatchAnalysis]], list[dict[str, str]]]:
    selected = sorted(
        (item for item in jobs if item.split == "frozen"),
        key=lambda item: item.job_id,
    )[:count]
    requirements_by_job: dict[str, list[RequirementGoldRecord]] = {}
    for item in requirements:
        if item.split == "frozen":
            requirements_by_job.setdefault(item.job_id, []).append(item)

    state_store = UserStateStore(state_root / "user-state.json")
    user_id = "r8-real-evaluation"
    existing_state = state_store.load(user_id=user_id)
    if not existing_state.preferences:
        state_store.save(
            user_id=user_id,
            state=UserState(
                user_id=user_id,
                preferences={
                    "preferred_city": "杭州",
                    "acceptable_cities": ["Remote"],
                    "target_role": "Agent / LLM Application",
                    "job_type": "internship",
                },
            ),
            expected_version=existing_state.version,
        )
    service = MemoryAwareJobAnalysisService(
        user_state_store=state_store,
        user_id=user_id,
        career_runtime=runtime,
        candidate_documents=candidate_documents,
        semantic_registry=_SemanticRegistry(),
        harness=harness,
        session_dir=state_root / "full-match-evidence",
    )
    analyses: list[tuple[str, JobMatchAnalysis]] = []
    bad_cases: list[dict[str, str]] = []
    for job in selected:
        frozen_requirements = requirements_by_job[job.job_id]
        requirement_lines = "\n".join(
            f"- {item.raw_requirement_text}" for item in frozen_requirements
        )
        evaluation_excerpt = (
            f"# {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location}\n"
            f"Employment type: {job.employment_type}\n\n"
            f"## Requirements\n{requirement_lines}\n"
        )
        try:
            analysis = service.analyze(
                jd=JobBasicInfo(
                    title=job.title,
                    city=job.location,
                    role_direction="Agent / LLM Application",
                    job_type=job.employment_type,
                    text=evaluation_excerpt,
                ),
                session_id="r8-full-job-match",
                run_id=job.job_id,
                top_k=5,
            )
            analyses.append((job.job_id, analysis))
        except Exception as exc:
            bad_cases.append(
                {
                    "case": job.job_id,
                    "layer": _failure_layer(exc),
                    "observation": f"{type(exc).__name__}: {exc}",
                }
            )
    return analyses, bad_cases


def _evidence_predictions(
    analyses: Sequence[tuple[str, JobMatchAnalysis]],
    requirements: Sequence[RequirementGoldRecord],
    *,
    candidate_documents: Sequence[Any],
) -> list[EvidencePrediction]:
    from job_agent.evaluation.real_career_data import requirement_matches

    documents = {item.document_id: item for item in candidate_documents}
    gold_by_job: dict[str, list[RequirementGoldRecord]] = {}
    for item in requirements:
        if item.split == "frozen":
            gold_by_job.setdefault(item.job_id, []).append(item)
    predictions: list[EvidencePrediction] = []
    for job_id, analysis in analyses:
        for gold in gold_by_job[job_id]:
            result = next(
                (
                    item
                    for item in analysis.requirements
                    if requirement_matches(gold.raw_requirement_text, item.atom.text)
                    or requirement_matches(
                        gold.raw_requirement_text,
                        item.atom.source_span.exact_quote,
                    )
                ),
                None,
            )
            if result is None:
                continue
            predictions.append(
                EvidencePrediction(
                    requirement_id=gold.requirement_id,
                    semantic_status=result.semantic_support,
                    status=result.status,
                    source_document_ids=[
                        item.document_id for item in result.evidence_items
                    ],
                    provenance_valid=_provenance_valid(result, documents),
                )
            )
    return predictions


def _provenance_valid(requirement: Any, documents: dict[str, Any]) -> bool:
    for evidence in requirement.evidence_items:
        document = documents.get(evidence.document_id)
        if document is None:
            return False
        span = evidence.evidence_link.source_span
        if span.content_hash != document.content_hash:
            return False
        if document.text[span.start_offset : span.end_offset] != span.exact_quote:
            return False
    return True


def _evidence_case_details(
    dataset: Any,
    predictions: Sequence[EvidencePrediction],
    *,
    retrieval_rankings: dict[str, list[str]],
) -> list[dict[str, Any]]:
    predicted = {item.requirement_id: item for item in predictions}
    return [
        {
            "requirement_id": gold.requirement_id,
            "requirement": gold.raw_requirement_text,
            "expected_status": gold.expected_evidence_status,
            "expected_sources": gold.expected_source_documents,
            "retrieved_top3": retrieval_rankings.get(gold.requirement_id, [])[:3],
            "semantic_judgment": (
                predicted[gold.requirement_id].semantic_status
                if gold.requirement_id in predicted
                else None
            ),
            "selected_sources": (
                predicted[gold.requirement_id].source_document_ids
                if gold.requirement_id in predicted
                else []
            ),
            "final_status": (
                predicted[gold.requirement_id].status
                if gold.requirement_id in predicted
                else None
            ),
            "source_span_valid": (
                predicted[gold.requirement_id].provenance_valid
                if gold.requirement_id in predicted
                else None
            ),
        }
        for gold in dataset.requirements
        if gold.split == "frozen"
    ]


def _source_cap(document: Any) -> str:
    artifact_type = document.metadata.get("artifact_type")
    if not isinstance(artifact_type, str):
        material_kind = document.metadata.get("material_kind")
        artifact_type = material_kind if isinstance(material_kind, str) else None
    source = SourceDocumentRef(
        source_id=f"eval-{document.document_id}",
        kind="project_source",
        version=document.version,
        content_hash=document.content_hash,
        snapshot_path="evaluation-only",
        display_label=document.title or document.document_id,
        artifact_type=artifact_type,
    )
    return EvidenceLevelPolicy().maximum_level(source).value


def _classify_requirement_failure(record: dict[str, Any]) -> str:
    termination = record.get("termination") or {}
    if (
        termination.get("completion_truncated") is True
        or termination.get("finish_reason") == "length"
    ):
        return "truncation"
    error = str(record.get("validation_error") or "")
    raw = str(record.get("raw_output") or "").strip()
    if error == "schema_error" or "validation" in error.casefold():
        return "schema shape"
    if raw.startswith("```") or (
        raw and not raw.startswith(("{", "["))
    ):
        return "wrapper/text"
    if raw and not raw.endswith(("}", "]")):
        return "incomplete closing structure"
    if error == "invalid_json":
        return "malformed JSON"
    if "repair" in error.casefold():
        return "repair failure"
    return "other"


def _requirement_coverage_diagnostics(
    dataset: Any,
    predictions: Sequence[ExtractionPrediction],
) -> dict[str, Any]:
    from job_agent.evaluation.real_career_data import requirement_matches

    predicted_by_job = {item.job_id: item for item in predictions}
    gold_by_job: dict[str, list[RequirementGoldRecord]] = {}
    for item in dataset.requirements:
        if item.split == "frozen":
            gold_by_job.setdefault(item.job_id, []).append(item)
    counts: Counter[str] = Counter()
    cases: list[dict[str, Any]] = []
    for job_id, gold_items in gold_by_job.items():
        candidates = predicted_by_job.get(
            job_id,
            ExtractionPrediction(job_id=job_id, schema_valid=False),
        ).requirements
        source_quotes = predicted_by_job.get(
            job_id,
            ExtractionPrediction(job_id=job_id, schema_valid=False),
        ).source_quotes
        for gold in gold_items:
            matches = [
                candidate
                for index, candidate in enumerate(candidates)
                if requirement_matches(gold.raw_requirement_text, candidate)
                or (
                    index < len(source_quotes)
                    and requirement_matches(
                        gold.raw_requirement_text,
                        source_quotes[index],
                    )
                )
            ]
            if not matches and gold.is_major:
                counts["OMITTED_MAJOR_REQUIREMENT"] += 1
                cases.append(
                    {
                        "job_id": job_id,
                        "requirement_id": gold.requirement_id,
                        "classification": "OMITTED_MAJOR_REQUIREMENT",
                    }
                )
            elif len(matches) > 1:
                counts["OVER_SPLIT_REQUIREMENT"] += 1
                cases.append(
                    {
                        "job_id": job_id,
                        "requirement_id": gold.requirement_id,
                        "classification": "OVER_SPLIT_REQUIREMENT",
                    }
                )
        for index, candidate in enumerate(candidates):
            matches = [
                gold
                for gold in gold_items
                if requirement_matches(gold.raw_requirement_text, candidate)
                or (
                    index < len(source_quotes)
                    and requirement_matches(
                        gold.raw_requirement_text,
                        source_quotes[index],
                    )
                )
            ]
            if len(matches) > 1:
                counts["OVER_MERGED_REQUIREMENT"] += 1
                cases.append(
                    {
                        "job_id": job_id,
                        "candidate": candidate,
                        "classification": "OVER_MERGED_REQUIREMENT",
                    }
                )
    return {
        "distribution": dict(sorted(counts.items())),
        "cases": cases,
        "irrelevant_extraction": "NOT_EVALUATED_GOLD_NOT_EXHAUSTIVE",
    }


def _failure_layer(error: Exception) -> str:
    message = str(error)
    if "evidence_span_outside_retrieved_chunks" in message:
        return "PROVENANCE"
    if "evidence_level_exceeds_source_cap" in message:
        return "EVIDENCE_FALSE_SUPPORT"
    if "requirement" in message.casefold() or "invalid_json" in message:
        return "REQUIREMENT_EXTRACTION"
    return "CONTEXT"


def _status_class(value: str) -> str:
    if value == "supported":
        return "supported"
    if value in {"partial", "unverified_lead"}:
        return "partial"
    return "gap"


def _preference_is_consistent(analysis: JobMatchAnalysis) -> bool:
    if analysis.preference_analysis is None or analysis.jd_basic_info is None:
        return False
    dimensions = analysis.preference_analysis
    expected_job_type = analysis.jd_basic_info.job_type.casefold() in {
        "intern",
        "internship",
        "实习",
        "实习生",
    }
    return (
        dimensions.role.fit is True
        and dimensions.job_type.fit is expected_job_type
        and dimensions.city.fit
        is ("remote" in analysis.jd_basic_info.city.casefold())
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--career-dataset-root", default="eval/career_knowledge_v1")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--model-path", default=os.environ.get("QWEN_EMBEDDING_MODEL_PATH"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--full-match-jobs", type=int, default=12)
    parser.add_argument("--extraction-only", action="store_true")
    parser.add_argument("--job-id", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")
    if args.extraction_only:
        dataset = load_real_career_dataset(
            jobs_path=args.jobs,
            requirements_path=args.requirements,
            dataset_version=DATASET_VERSION,
        )
        provider = _DiagnosticDeepSeekProvider(
            api_key=api_key,
            timeout_s=120.0,
        )
        harness = LLMHarness(provider)
        predictions, bad_cases, diagnostics = _run_extraction(
            dataset.jobs,
            harness=harness,
            diagnostic_provider=provider,
            session_root=Path(args.state_root) / "requirement-extraction-only",
            job_ids=set(args.job_id) or None,
        )
        report = {
            "dataset": dataset_summary(dataset),
            "requirement_extraction": evaluate_requirement_extraction(
                dataset,
                predictions,
                split="frozen",
            ).model_dump(mode="json"),
            "requirement_diagnostics": diagnostics,
            "api": {
                "provider": "deepseek",
                "calls": len(harness.traces),
                "input_tokens": sum(
                    item.input_tokens or 0 for item in harness.traces
                ),
                "output_tokens": sum(
                    item.output_tokens or 0 for item in harness.traces
                ),
                "cost": None,
                "schema_valid_calls": sum(
                    item.schema_valid for item in harness.traces
                ),
            },
            "bad_cases": bad_cases,
            "predictions": [item.model_dump(mode="json") for item in predictions],
        }
    else:
        if not args.model_path:
            raise SystemExit(
                "QWEN_EMBEDDING_MODEL_PATH or --model-path is required"
            )
        report = run_real_career_evaluation(
            jobs_path=args.jobs,
            requirements_path=args.requirements,
            career_dataset_root=args.career_dataset_root,
            repository_root=args.repository_root,
            state_root=args.state_root,
            model_path=args.model_path,
            deepseek_api_key=api_key,
            device=args.device,
            full_match_jobs=args.full_match_jobs,
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
