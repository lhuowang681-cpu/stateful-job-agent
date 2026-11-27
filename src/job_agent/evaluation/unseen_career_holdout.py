from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from job_agent.agent_runtime.mcp_adapter import MCPToolAdapter
from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.agent_runtime.budgets import AgentBudget, BudgetManager, BudgetProfile
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.evaluation.atomic_evidence_v2 import AtomicEntailmentCache, EvidenceBenchmarkParent, load_evidence_benchmark_v2
from job_agent.evaluation.real_atomic_evidence import (
    _atom_metrics,
    _hit_record,
    _job_metrics,
    _judge_atom,
    _observations,
    _parent_metrics,
)
from job_agent.evaluation.real_career_data import (
    ExtractionPrediction,
    RequirementGoldRecord,
    evaluate_requirement_extraction,
    load_real_career_dataset,
    requirement_matches,
)
from job_agent.evaluation.real_career_runner import _DiagnosticDeepSeekProvider, _SemanticRegistry
from job_agent.jd_match_analysis import JobBasicInfo, JobMatchAnalysis
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.durable import CareerKnowledgeLifecycle, EmbeddingIdentity, KnowledgeRepository
from job_agent.llm.harness import LLMHarness
from job_agent.memory.contracts import UserState
from job_agent.memory.user_state_store import UserStateStore
from job_agent.memory_aware_job_analysis import GovernedCareerKnowledgeRuntime, MemoryAwareJobAnalysisService


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze(manifest_path: Path, *, jobs_path: Path, requirements_path: Path, benchmark_path: Path, index_manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["private_payload_hashes"]
    actual = {
        "jobs_sha256": _sha256(jobs_path),
        "requirements_sha256": _sha256(requirements_path),
        "benchmark_sha256": _sha256(benchmark_path),
    }
    if actual != expected:
        raise ValueError("frozen holdout payload hash mismatch")
    if _sha256(index_manifest_path) != manifest["corpus"]["index_manifest_sha256"]:
        raise ValueError("frozen corpus manifest hash mismatch")
    return manifest


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _retrieval_metrics(atom_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    positives = [item for item in atom_rows if item["gold_entailment"] == "supported"]
    ranks = []
    for item in positives:
        expected = set(item["acceptable_sources"])
        rank = next((hit["rank"] for hit in item["retrieved_top5"] if hit["document_id"] in expected), None)
        ranks.append(rank)
    return {
        "positive_atoms": len(positives),
        "recall_at_1": _ratio(sum(rank is not None and rank <= 1 for rank in ranks), len(ranks)),
        "recall_at_3": _ratio(sum(rank is not None and rank <= 3 for rank in ranks), len(ranks)),
        "recall_at_5": _ratio(sum(rank is not None and rank <= 5 for rank in ranks), len(ranks)),
        "mrr": sum(1.0 / rank for rank in ranks if rank is not None) / len(ranks) if ranks else None,
    }


def _run_gold_atomic(
    *,
    benchmark_path: Path,
    state_root: Path,
    model_path: str,
    api_key: str,
    cache_path: Path,
    diagnostics_path: Path,
) -> tuple[dict[str, Any], CareerKnowledgeLifecycle, tuple[Any, ...], int, int]:
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    benchmark = load_evidence_benchmark_v2(benchmark_path)
    repository = KnowledgeRepository(state_root / "knowledge.sqlite")
    lifecycle = CareerKnowledgeLifecycle(
        repository=repository,
        embedding_backend=QwenEmbeddingBackend(model_path, device="cuda"),
        embedding_identity=EmbeddingIdentity(provider="sentence-transformers", model="Qwen/Qwen3-Embedding-0.6B", dimension=1024),
        index_path=state_root / "career.faiss",
        manifest_path=state_root / "career-index-manifest.json",
        max_chars=2000,
    )
    retrieval = CareerKnowledgeService(lifecycle.candidate_retriever(), lifecycle=lifecycle)
    documents = tuple(repository.list_active_documents())
    documents_by_id = {item.document_id: item for item in documents}
    provider = _DiagnosticDeepSeekProvider(api_key=api_key, timeout_s=120.0)
    harness = LLMHarness(provider)
    cache = AtomicEntailmentCache(cache_path)
    cache_hits = cache_misses = 0
    parent_results: list[dict[str, Any]] = []
    atom_results_flat: list[dict[str, Any]] = []
    for parent in benchmark.parents:
        support_by_atom: dict[str, bool] = {}
        atom_rows = []
        for atom in parent.atoms:
            top5 = retrieval.query_candidate_evidence(atom.text, 5)
            evidence_hits = top5[:3]
            judgments, hits, misses = _judge_atom(
                atom=atom,
                hits=evidence_hits,
                harness=harness,
                cache=cache,
                session_id="r12-unseen-gold-atomic",
                run_id=f"r12-{atom.atom_id}",
            )
            cache_hits += hits
            cache_misses += misses
            observations = _observations(atom, evidence_hits, judgments, documents_by_id)
            entailed = [item for item in observations if item["entails"]]
            support_by_atom[atom.atom_id] = bool(entailed)
            primary = min(
                entailed,
                key=lambda item: (0 if item["document_id"] in atom.acceptable_sources else 1, item["rank"], item["chunk_id"]),
                default=None,
            )
            row = {
                "atom_id": atom.atom_id,
                "text": atom.text,
                "gold_entailment": atom.gold_entailment,
                "acceptable_sources": atom.acceptable_sources,
                "predicted_entailment": "supported" if entailed else "unsupported",
                "primary_source": primary["document_id"] if primary else None,
                "evidence_links": entailed,
                "retrieved_top5": [_hit_record(item) for item in top5],
            }
            atom_rows.append(row)
            atom_results_flat.append(row)
        from job_agent.evaluation.atomic_evidence_v2 import aggregate_parent_status

        aggregation = aggregate_parent_status(
            support_by_atom,
            required_atom_ids=[item.atom_id for item in parent.atoms if item.required],
        )
        parent_results.append(
            {
                "requirement_id": parent.requirement_id,
                "job_id": parent.job_id,
                "gold_parent_status": parent.gold_parent_status,
                "predicted_parent_status": aggregation.status,
                "aggregation": aggregation.model_dump(mode="json"),
                "atoms": atom_rows,
            }
        )
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_path.write_text(json.dumps(provider.diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "retrieval": _retrieval_metrics(atom_results_flat),
        "evidence": _atom_metrics(atom_results_flat),
        "parent": _parent_metrics(parent_results),
        "job_match_from_gold_atoms": _job_metrics(parent_results),
        "parents": parent_results,
        "api": {
            "calls": len(harness.traces),
            "input_tokens": sum(item.input_tokens or 0 for item in harness.traces),
            "output_tokens": sum(item.output_tokens or 0 for item in harness.traces),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
        },
    }
    return report, lifecycle, documents, report["api"]["input_tokens"], report["api"]["output_tokens"]


def _runtime(bridge: StdioMCPClientBridge) -> GovernedCareerKnowledgeRuntime:
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
                max_model_calls=2000,
                max_tool_calls=2000,
                max_active_seconds=6 * 60 * 60,
            )
        ),
    )


def _status_class(value: str) -> str:
    if value == "supported":
        return "supported"
    if value in {"partial", "unverified_lead"}:
        return "partial"
    return "gap"


def _match_gold(gold: RequirementGoldRecord, analysis: JobMatchAnalysis) -> Any | None:
    for result in analysis.requirements:
        if requirement_matches(gold.raw_requirement_text, result.atom.text) or requirement_matches(
            gold.raw_requirement_text, result.atom.source_span.exact_quote
        ):
            return result
    return None


def _run_end_to_end(
    *,
    jobs_path: Path,
    requirements_path: Path,
    state_root: Path,
    model_path: str,
    api_key: str,
    documents: Sequence[Any],
    output_root: Path,
) -> dict[str, Any]:
    dataset = load_real_career_dataset(jobs_path=jobs_path, requirements_path=requirements_path, dataset_version="unseen-career-holdout-v2.0")
    provider = _DiagnosticDeepSeekProvider(api_key=api_key, timeout_s=120.0)
    harness = LLMHarness(provider)
    bridge = StdioMCPClientBridge(
        "src/job_agent/knowledge/career_mcp_server.py",
        startup_timeout_s=90,
        call_timeout_s=120,
        server_env={
            "QWEN_EMBEDDING_MODEL_PATH": model_path,
            "CAREER_KNOWLEDGE_DEVICE": "cuda",
            "CAREER_KNOWLEDGE_DB_PATH": str(state_root / "knowledge.sqlite"),
            "CAREER_KNOWLEDGE_INDEX_PATH": str(state_root / "career.faiss"),
            "CAREER_KNOWLEDGE_MANIFEST_PATH": str(state_root / "career-index-manifest.json"),
            "CAREER_KNOWLEDGE_EMBEDDING_DIMENSION": "1024",
        },
    )
    bridge.start()
    state_store = UserStateStore(output_root / "user-state.json")
    current = state_store.load(user_id="r12-unseen")
    if not current.preferences:
        state_store.save(
            user_id="r12-unseen",
            state=UserState(
                user_id="r12-unseen",
                preferences={"preferred_city": "杭州", "acceptable_cities": ["Remote"], "target_role": "Agent / LLM Application", "job_type": "internship"},
            ),
            expected_version=current.version,
        )
    service = MemoryAwareJobAnalysisService(
        user_state_store=state_store,
        user_id="r12-unseen",
        career_runtime=_runtime(bridge),
        candidate_documents=documents,
        semantic_registry=_SemanticRegistry(),
        harness=harness,
        session_dir=output_root / "evidence-snapshots",
    )
    analyses: list[tuple[str, JobMatchAnalysis]] = []
    failures: list[dict[str, str]] = []
    try:
        for job in dataset.jobs:
            try:
                analysis = service.analyze(
                    jd=JobBasicInfo(
                        title=job.title,
                        city=job.location,
                        role_direction="Agent / LLM Application",
                        job_type=job.employment_type,
                        text=job.raw_jd_text,
                    ),
                    session_id="r12-unseen-end-to-end",
                    run_id=job.job_id,
                    top_k=5,
                )
                analyses.append((job.job_id, analysis))
                (output_root / "jobs").mkdir(parents=True, exist_ok=True)
                (output_root / "jobs" / f"{job.job_id}.json").write_text(
                    json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as exc:
                failures.append({"job_id": job.job_id, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        bridge.close()
    predictions = [
        ExtractionPrediction(
            job_id=job_id,
            schema_valid=True,
            requirements=[item.text for item in analysis.requirement_analysis.atoms],
            source_quotes=[item.source_span.exact_quote for item in analysis.requirement_analysis.atoms],
        )
        for job_id, analysis in analyses
    ]
    predictions.extend(
        ExtractionPrediction(job_id=item["job_id"], schema_valid=False, error=item["error"])
        for item in failures
    )
    extraction = evaluate_requirement_extraction(dataset, predictions, split="frozen")
    requirements_by_job: dict[str, list[RequirementGoldRecord]] = defaultdict(list)
    for item in dataset.requirements:
        requirements_by_job[item.job_id].append(item)
    rows = []
    attribution: Counter[str] = Counter()
    fully = partially = major = correct_requirements = 0
    for job in dataset.jobs:
        analysis = next((value for job_id, value in analyses if job_id == job.job_id), None)
        correct = 0
        details = []
        for gold in requirements_by_job[job.job_id]:
            matched = _match_gold(gold, analysis) if analysis else None
            if matched is None:
                attribution["REQUIREMENT_MISS"] += 1
                details.append({"requirement_id": gold.requirement_id, "correct": False, "failure": "REQUIREMENT_MISS"})
                continue
            predicted = _status_class(matched.status)
            is_correct = predicted == gold.expected_evidence_status
            correct += is_correct
            correct_requirements += is_correct
            failure = None
            if not is_correct:
                failure = "EVIDENCE_FALSE_SUPPORT" if gold.expected_evidence_status == "gap" else "EVIDENCE_FALSE_GAP"
                attribution[failure] += 1
            details.append({"requirement_id": gold.requirement_id, "predicted": predicted, "gold": gold.expected_evidence_status, "correct": is_correct, "failure": failure})
        total = len(requirements_by_job[job.job_id])
        if correct == total:
            status = "fully_correct"
            fully += 1
        elif correct:
            status = "partially_correct"
            partially += 1
        else:
            status = "major_error"
            major += 1
        rows.append({"job_id": job.job_id, "correct": correct, "total": total, "status": status, "requirements": details})
    (output_root / "diagnostics.json").write_text(json.dumps(provider.diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "requirement_extraction": extraction.model_dump(mode="json"),
        "job_match": {
            "jobs_completed": len(analyses),
            "strength_gap_correctness": _ratio(correct_requirements, len(dataset.requirements)),
            "fully_correct_jobs": fully,
            "partially_correct_jobs": partially,
            "major_error_jobs": major,
            "jobs": rows,
        },
        "failures": failures,
        "failure_attribution": dict(sorted(attribution.items())),
        "api": {
            "calls": len(harness.traces),
            "input_tokens": sum(item.input_tokens or 0 for item in harness.traces),
            "output_tokens": sum(item.output_tokens or 0 for item in harness.traces),
        },
    }


def _gold_failure_attribution(report: Mapping[str, Any]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for parent in report["parents"]:
        for atom in parent["atoms"]:
            gold = atom["gold_entailment"]
            predicted = atom["predicted_entailment"]
            expected = set(atom["acceptable_sources"])
            top3 = {item["document_id"] for item in atom["retrieved_top5"][:3]}
            top5 = {item["document_id"] for item in atom["retrieved_top5"]}
            if gold == "supported" and not expected.intersection(top5):
                counts["RETRIEVAL_RANKING"] += 1
            elif gold == "supported" and not expected.intersection(top3):
                counts["RETRIEVAL_RANKING"] += 1
            elif gold == "supported" and predicted == "unsupported":
                counts["EVIDENCE_FALSE_GAP"] += 1
            elif gold == "unsupported" and predicted == "supported":
                counts["EVIDENCE_FALSE_SUPPORT"] += 1
            elif gold == "supported" and atom["evidence_links"] and not any(item["acceptable_source"] for item in atom["evidence_links"]):
                counts["SOURCE_SELECTION"] += 1
            if any(not item["quote_valid"] for item in atom["evidence_links"]):
                counts["QUOTE"] += 1
            if any(not item["provenance_valid"] for item in atom["evidence_links"]):
                counts["PROVENANCE"] += 1
    return dict(sorted(counts.items()))


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = verify_freeze(
        args.manifest,
        jobs_path=args.jobs,
        requirements_path=args.requirements,
        benchmark_path=args.benchmark,
        index_manifest_path=args.state_root / "career-index-manifest.json",
    )
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    gold, _, documents, _, _ = _run_gold_atomic(
        benchmark_path=args.benchmark,
        state_root=args.state_root,
        model_path=args.model_path,
        api_key=api_key,
        cache_path=args.cache,
        diagnostics_path=args.private_output / "gold-atomic-diagnostics.json",
    )
    end_to_end = _run_end_to_end(
        jobs_path=args.jobs,
        requirements_path=args.requirements,
        state_root=args.state_root,
        model_path=args.model_path,
        api_key=api_key,
        documents=documents,
        output_root=args.private_output / "end-to-end",
    )
    report = {
        "dataset_version": manifest["dataset_version"],
        "dataset_hash": manifest["dataset_hash"],
        "production_code_commit": manifest["production_code_commit"],
        "holdout_integrity": {
            "gold_frozen_before_model_run": manifest["gold_frozen_before_model_run"],
            "post_result_gold_edits": 0,
            "corpus_version": manifest["corpus"]["version"],
        },
        "dataset": {
            "jobs": manifest["job_count"],
            "parents": manifest["parent_count"],
            "atoms": manifest["atom_count"],
            "positive_atoms": manifest["positive_atom_count"],
            "gap_atoms": manifest["gap_atom_count"],
            "unresolved": manifest["unresolved_count"],
        },
        "requirement_extraction": end_to_end["requirement_extraction"],
        "gold_atomic_retrieval": gold["retrieval"],
        "gold_atomic_evidence": gold["evidence"],
        "parent_aggregation": gold["parent"],
        "end_to_end_job_match": end_to_end["job_match"],
        "failure_attribution": {
            "gold_atomic": _gold_failure_attribution(gold),
            "end_to_end": end_to_end["failure_attribution"],
        },
        "api": {
            "calls": gold["api"]["calls"] + end_to_end["api"]["calls"],
            "input_tokens": gold["api"]["input_tokens"] + end_to_end["api"]["input_tokens"],
            "output_tokens": gold["api"]["output_tokens"] + end_to_end["api"]["output_tokens"],
            "gold_atomic": gold["api"],
            "end_to_end": end_to_end["api"],
        },
    }
    args.private_output.mkdir(parents=True, exist_ok=True)
    (args.private_output / "full-report.json").write_text(
        json.dumps({"summary": report, "gold_atomic": gold, "end_to_end": end_to_end}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
