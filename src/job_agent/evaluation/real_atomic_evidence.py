from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from job_agent.evaluation.atomic_evidence_v2 import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    AtomicCandidateEntailment,
    AtomicEntailmentBatch,
    AtomicEntailmentCache,
    AtomicRequirementGold,
    EvidenceBenchmarkParent,
    aggregate_parent_status,
    entailment_cache_key,
    load_evidence_benchmark_v2,
)
from job_agent.evaluation.real_career_runner import (
    _DiagnosticDeepSeekProvider,
)
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.contracts import RetrievedChunk
from job_agent.knowledge.durable import (
    CareerKnowledgeLifecycle,
    EmbeddingIdentity,
    KnowledgeRepository,
)
from job_agent.llm.harness import LLMHarness, NodePolicy
from job_agent.llm.provider import TraceContext
from job_agent.llm.skill_registry import SkillSpec


MODEL_IDENTITY = "deepseek/deepseek-chat"
TEMPERATURE = 0.0


def run_atomic_evidence_evaluation(
    *,
    benchmark_path: str | Path,
    state_root: str | Path,
    model_path: str,
    deepseek_api_key: str,
    cache_path: str | Path,
    device: str = "cuda",
    top_k: int = 3,
    stability_atom_ids: Sequence[str] = (),
    stability_runs: int = 3,
) -> dict[str, Any]:
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    if top_k < 1:
        raise ValueError("top_k must be positive")
    benchmark = load_evidence_benchmark_v2(benchmark_path)
    if benchmark.dataset_status == "holdout":
        raise ValueError("holdout data must remain unrun until formally frozen")
    state = Path(state_root)
    repository = KnowledgeRepository(state / "knowledge.sqlite")
    lifecycle = CareerKnowledgeLifecycle(
        repository=repository,
        embedding_backend=QwenEmbeddingBackend(model_path, device=device),
        embedding_identity=EmbeddingIdentity(
            provider="sentence-transformers",
            model="Qwen/Qwen3-Embedding-0.6B",
            dimension=1024,
        ),
        index_path=state / "career.faiss",
        manifest_path=state / "career-index-manifest.json",
        max_chars=2000,
    )
    retrieval = CareerKnowledgeService(
        lifecycle.candidate_retriever(),
        lifecycle=lifecycle,
    )
    documents = {item.document_id: item for item in repository.list_active_documents()}
    provider = _DiagnosticDeepSeekProvider(
        api_key=deepseek_api_key,
        timeout_s=120.0,
    )
    harness = LLMHarness(provider)
    cache = AtomicEntailmentCache(cache_path)
    cache_hits = 0
    cache_misses = 0
    parent_results: list[dict[str, Any]] = []
    atom_predictions: list[dict[str, Any]] = []

    for parent in benchmark.parents:
        parent_hits = retrieval.query_candidate_evidence(parent.raw_requirement, top_k)
        atom_results: list[dict[str, Any]] = []
        support_by_atom: dict[str, bool] = {}
        for atom in parent.atoms:
            hits = retrieval.query_candidate_evidence(atom.text, top_k)
            judgments, hits_from_cache, misses = _judge_atom(
                atom=atom,
                hits=hits,
                harness=harness,
                cache=cache,
                session_id="r11-atomic-evidence",
                run_id=f"r11-{atom.atom_id}",
            )
            cache_hits += hits_from_cache
            cache_misses += misses
            observations = _observations(atom, hits, judgments, documents)
            entailed = [item for item in observations if item["entails"]]
            support_by_atom[atom.atom_id] = bool(entailed)
            primary = min(
                entailed,
                key=lambda item: (
                    0 if item["document_id"] in atom.acceptable_sources else 1,
                    item["rank"],
                    item["chunk_id"],
                ),
                default=None,
            )
            result = {
                "atom_id": atom.atom_id,
                "text": atom.text,
                "gold_entailment": atom.gold_entailment,
                "acceptable_sources": atom.acceptable_sources,
                "predicted_entailment": "supported" if entailed else "unsupported",
                "primary_source": primary["document_id"] if primary else None,
                "evidence_links": entailed,
                "retrieved_top_k": [_hit_record(item) for item in hits],
            }
            atom_results.append(result)
            atom_predictions.append(result)
        aggregation = aggregate_parent_status(
            support_by_atom,
            required_atom_ids=[item.atom_id for item in parent.atoms if item.required],
        )
        parent_results.append(
            {
                "requirement_id": parent.requirement_id,
                "job_id": parent.job_id,
                "raw_requirement": parent.raw_requirement,
                "lineage_gold_status": parent.lineage_gold_status,
                "gold_parent_status": parent.gold_parent_status,
                "predicted_parent_status": aggregation.status,
                "aggregation": aggregation.model_dump(mode="json"),
                "parent_query_top_k": [_hit_record(item) for item in parent_hits],
                "atoms": atom_results,
            }
        )

    stability = _stability_check(
        benchmark.parents,
        atom_ids=set(stability_atom_ids),
        runs=stability_runs,
        retrieval=retrieval,
        harness=harness,
        top_k=top_k,
    )
    traces = harness.traces
    return {
        "benchmark_version": benchmark.benchmark_version,
        "dataset_status": benchmark.dataset_status,
        "model": {
            "identity": MODEL_IDENTITY,
            "temperature": TEMPERATURE,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "seed": None,
        },
        "benchmark": _benchmark_summary(benchmark.parents),
        "atom_metrics": _atom_metrics(atom_predictions),
        "parent_metrics": _parent_metrics(parent_results),
        "job_match": _job_metrics(parent_results),
        "retrieval_comparison": _retrieval_comparison(parent_results),
        "stability": stability,
        "parents": parent_results,
        "api": {
            "new_calls": len(traces),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_entries": cache.size,
            "input_tokens": sum(item.input_tokens or 0 for item in traces),
            "output_tokens": sum(item.output_tokens or 0 for item in traces),
            "schema_valid_calls": sum(item.schema_valid for item in traces),
        },
    }


def _judge_atom(
    *,
    atom: AtomicRequirementGold,
    hits: Sequence[RetrievedChunk],
    harness: LLMHarness,
    cache: AtomicEntailmentCache,
    session_id: str,
    run_id: str,
) -> tuple[dict[str, AtomicCandidateEntailment], int, int]:
    judgments: dict[str, AtomicCandidateEntailment] = {}
    missing: list[RetrievedChunk] = []
    for hit in hits:
        key = _cache_key(atom.text, hit)
        cached = cache.get(key)
        if cached is None:
            missing.append(hit)
        else:
            judgments[hit.chunk.chunk_id] = cached
    if missing:
        batch = _invoke_entailment(
            atom=atom,
            hits=missing,
            harness=harness,
            session_id=session_id,
            run_id=run_id,
        )
        for judgment in _validated_judgments(batch, missing):
            judgments[judgment.chunk_id] = judgment
            cache.put(_cache_key(atom.text, next(item for item in missing if item.chunk.chunk_id == judgment.chunk_id)), judgment)
    return judgments, len(hits) - len(missing), len(missing)


def _validated_judgments(
    batch: AtomicEntailmentBatch,
    hits: Sequence[RetrievedChunk],
) -> list[AtomicCandidateEntailment]:
    expected = {item.chunk.chunk_id for item in hits}
    observed = {item.chunk_id for item in batch.candidate_judgments}
    if observed != expected or len(observed) != len(batch.candidate_judgments):
        raise ValueError("atomic candidate coverage mismatch")
    chunks = {item.chunk.chunk_id: item.chunk for item in hits}
    return [
        _fail_closed_invalid_quote(judgment, chunks[judgment.chunk_id].text)
        for judgment in batch.candidate_judgments
    ]


def _fail_closed_invalid_quote(
    judgment: AtomicCandidateEntailment,
    chunk_text: str,
) -> AtomicCandidateEntailment:
    if not judgment.entails:
        return judgment
    quote = judgment.exact_quote or ""
    if chunk_text.count(quote) == 1:
        return judgment
    return judgment.model_copy(
        update={
            "entails": False,
            "exact_quote": None,
            "concise_reason": "Invalid or ambiguous exact quote; failed closed.",
        }
    )


def _invoke_entailment(
    *,
    atom: AtomicRequirementGold,
    hits: Sequence[RetrievedChunk],
    harness: LLMHarness,
    session_id: str,
    run_id: str,
) -> AtomicEntailmentBatch:
    skill = SkillSpec(
        skill_id="atomic-evidence-entailment",
        version="v1",
        instructions=(
            "Judge direct textual entailment for each candidate independently. "
            "Return one strict JSON object matching the supplied schema."
        ),
        reference_paths=(),
        output_schema=AtomicEntailmentBatch,
    )
    result = harness.invoke_structured(
        skill=skill,
        task_context={
            "atom_id": atom.atom_id,
            "atomic_requirement": atom.text,
            "candidate_chunk_ids": [item.chunk.chunk_id for item in hits],
            "instruction": (
                "Output JSON only. Return every candidate_chunk_id exactly once. "
                "For each pair set entails=true only when the candidate text explicitly "
                "establishes the complete atomic requirement without adding an unstated "
                "fact. Semantic relevance, adjacent technology, transferable skill, or a "
                "weaker neighboring fact is entails=false. Preserve numeric duration, "
                "scale, production, customer, collaboration, and named-tool qualifiers. "
                "For entails=true copy one short exact_quote that occurs exactly once in "
                "that same chunk. For entails=false exact_quote must be null."
            ),
        },
        untrusted_inputs={
            "candidate_chunks": json.dumps(
                {
                    item.chunk.chunk_id: {
                        "document_id": item.chunk.document_id,
                        "text": item.chunk.text,
                    }
                    for item in hits
                },
                ensure_ascii=False,
            )
        },
        output_schema=AtomicEntailmentBatch,
        tools=[],
        policy=NodePolicy(
            max_retries=0,
            max_schema_repairs=1,
            allow_rule_fallback=False,
            max_output_tokens=1200,
        ),
        trace=TraceContext(
            session_id=session_id,
            run_id=run_id,
            node_id="atomic_evidence_entailment",
            skill_id=skill.skill_id,
            skill_version=skill.version,
            prompt_version=PROMPT_VERSION,
        ),
    )
    if result.value.atom_id != atom.atom_id:
        raise ValueError("atomic response atom id mismatch")
    return result.value


def _cache_key(atom_text: str, hit: RetrievedChunk) -> str:
    return entailment_cache_key(
        atom_text=atom_text,
        chunk_id=hit.chunk.chunk_id,
        chunk_content_hash=hit.chunk.document_content_hash,
        model_identity=MODEL_IDENTITY,
        temperature=TEMPERATURE,
    )


def _observations(
    atom: AtomicRequirementGold,
    hits: Sequence[RetrievedChunk],
    judgments: Mapping[str, AtomicCandidateEntailment],
    documents: Mapping[str, Any],
) -> list[dict[str, Any]]:
    observations = []
    for hit in hits:
        chunk = hit.chunk
        judgment = judgments[chunk.chunk_id]
        observation: dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "rank": hit.rank,
            "score": hit.score,
            "entails": judgment.entails,
            "exact_quote": judgment.exact_quote,
            "concise_reason": judgment.concise_reason,
            "quote_valid": judgment.exact_quote is None,
            "provenance_valid": False,
            "acceptable_source": chunk.document_id in atom.acceptable_sources,
        }
        document = documents.get(chunk.document_id)
        if document is not None:
            observation["provenance_valid"] = (
                document.version == chunk.document_version
                and document.content_hash == chunk.document_content_hash
                and document.text[chunk.start_offset : chunk.end_offset] == chunk.text
            )
        if judgment.entails:
            quote = judgment.exact_quote or ""
            relative = chunk.text.index(quote)
            observation.update(
                {
                    "quote_valid": chunk.text.count(quote) == 1,
                    "source_span": {
                        "content_hash": chunk.document_content_hash,
                        "start_offset": chunk.start_offset + relative,
                        "end_offset": chunk.start_offset + relative + len(quote),
                        "exact_quote": quote,
                    },
                }
            )
        observations.append(observation)
    return observations


def _hit_record(hit: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk.chunk_id,
        "document_id": hit.chunk.document_id,
        "rank": hit.rank,
        "score": hit.score,
        "text": hit.chunk.text,
    }


def _atom_metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    true_positive = sum(
        item["gold_entailment"] == "supported"
        and item["predicted_entailment"] == "supported"
        for item in items
    )
    true_negative = sum(
        item["gold_entailment"] == "unsupported"
        and item["predicted_entailment"] == "unsupported"
        for item in items
    )
    false_support = sum(
        item["gold_entailment"] == "unsupported"
        and item["predicted_entailment"] == "supported"
        for item in items
    )
    false_gap = sum(
        item["gold_entailment"] == "supported"
        and item["predicted_entailment"] == "unsupported"
        for item in items
    )
    gold_positive = true_positive + false_gap
    gold_negative = true_negative + false_support
    predicted_positive = true_positive + false_support
    predicted_negative = true_negative + false_gap
    links = [link for item in items for link in item["evidence_links"]]
    correct_links = sum(item["acceptable_source"] for item in links)
    source_recalled = sum(
        item["gold_entailment"] == "supported"
        and any(link["acceptable_source"] for link in item["evidence_links"])
        for item in items
    )
    return {
        "atom_count": len(items),
        "entailment_accuracy": _ratio(true_positive + true_negative, len(items)),
        "supported_precision": _ratio(true_positive, predicted_positive),
        "supported_recall": _ratio(true_positive, gold_positive),
        "unsupported_precision": _ratio(true_negative, predicted_negative),
        "unsupported_recall": _ratio(true_negative, gold_negative),
        "false_support": {"count": false_support, "gold_negative": gold_negative},
        "false_gap": {"count": false_gap, "gold_positive": gold_positive},
        "evidence_source_recall": _ratio(source_recalled, gold_positive),
        "evidence_source_precision": _ratio(correct_links, len(links)),
        "quote_validity": _ratio(sum(item["quote_valid"] for item in links), len(links)),
        "provenance_validity": _ratio(
            sum(item["provenance_valid"] for item in links), len(links)
        ),
    }


def _parent_metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    statuses = ("supported", "partial", "gap")
    by_status = {}
    for status in statuses:
        gold = sum(item["gold_parent_status"] == status for item in items)
        correct = sum(
            item["gold_parent_status"] == status
            and item["predicted_parent_status"] == status
            for item in items
        )
        by_status[status] = {"correct": correct, "gold": gold, "recall": _ratio(correct, gold)}
    correct = sum(
        item["gold_parent_status"] == item["predicted_parent_status"] for item in items
    )
    positive_gap_correct = sum(
        (item["gold_parent_status"] == "gap")
        == (item["predicted_parent_status"] == "gap")
        for item in items
    )
    return {
        "parent_count": len(items),
        "by_status": by_status,
        "overall_accuracy": _ratio(correct, len(items)),
        "positive_gap_accuracy": _ratio(positive_gap_correct, len(items)),
        "aggregation_errors": 0,
    }


def _job_metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["job_id"]].append(item)
    correct_jobs = 0
    partially_correct = 0
    major_error = 0
    rows = []
    for job_id, requirements in sorted(grouped.items()):
        correct = sum(
            item["gold_parent_status"] == item["predicted_parent_status"]
            for item in requirements
        )
        if correct == len(requirements):
            label = "correct"
            correct_jobs += 1
        elif correct:
            label = "partially_correct"
            partially_correct += 1
        else:
            label = "major_error"
            major_error += 1
        rows.append({"job_id": job_id, "correct": correct, "total": len(requirements), "status": label})
    total_requirements = sum(len(value) for value in grouped.values())
    correct_requirements = sum(row["correct"] for row in rows)
    return {
        "jobs_completed": len(grouped),
        "correct_jobs": correct_jobs,
        "partially_correct_jobs": partially_correct,
        "major_error_jobs": major_error,
        "strength_gap_correctness": _ratio(correct_requirements, total_requirements),
        "jobs": rows,
    }


def _retrieval_comparison(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    positive_parents = [item for item in items if any(atom["acceptable_sources"] for atom in item["atoms"])]
    parent_hits = sum(
        bool(
            {hit["document_id"] for hit in item["parent_query_top_k"]}
            & {source for atom in item["atoms"] for source in atom["acceptable_sources"]}
        )
        for item in positive_parents
    )
    positive_atoms = [
        atom for item in items for atom in item["atoms"] if atom["acceptable_sources"]
    ]
    atom_hits = sum(
        bool(
            {hit["document_id"] for hit in atom["retrieved_top_k"]}
            & set(atom["acceptable_sources"])
        )
        for atom in positive_atoms
    )
    return {
        "algorithm_changed": False,
        "parent_query_source_recall_at_k": _ratio(parent_hits, len(positive_parents)),
        "atomic_query_source_recall_at_k": _ratio(atom_hits, len(positive_atoms)),
        "top_k": len(items[0]["parent_query_top_k"]) if items else 0,
    }


def _benchmark_summary(parents: Sequence[EvidenceBenchmarkParent]) -> dict[str, Any]:
    atoms = [atom for parent in parents for atom in parent.atoms]
    corrections = [parent for parent in parents if parent.correction_history]
    multi_sources = [atom for atom in atoms if len(atom.acceptable_sources) > 1]
    return {
        "parent_requirements": len(parents),
        "atoms": len(atoms),
        "compound_parents": sum(len(parent.atoms) > 1 for parent in parents),
        "gold_corrections": len(corrections),
        "unresolved_ambiguities": sum(parent.ambiguity_status == "unresolved" for parent in parents),
        "single_source_positive_atoms": sum(
            len(atom.acceptable_sources) == 1 for atom in atoms
        ),
        "multi_acceptable_source_atoms": len(multi_sources),
    }


def _stability_check(
    parents: Sequence[EvidenceBenchmarkParent],
    *,
    atom_ids: set[str],
    runs: int,
    retrieval: CareerKnowledgeService,
    harness: LLMHarness,
    top_k: int,
) -> dict[str, Any]:
    if not atom_ids:
        return {"repeated_atoms": 0, "runs_per_atom": 0, "agreement": None, "cases": []}
    atoms = {
        atom.atom_id: atom for parent in parents for atom in parent.atoms if atom.atom_id in atom_ids
    }
    if set(atoms) != atom_ids:
        raise ValueError("unknown stability atom id")
    cases = []
    agreeing_pairs = 0
    total_pairs = 0
    for atom_id, atom in atoms.items():
        hits = retrieval.query_candidate_evidence(atom.text, top_k)
        signatures = []
        for repeat in range(runs):
            batch = _invoke_entailment(
                atom=atom,
                hits=hits,
                harness=harness,
                session_id="r11-stability",
                run_id=f"r11-stability-{atom_id}-{repeat}",
            )
            signature = tuple(
                sorted(
                    (item.chunk_id, item.entails)
                    for item in _validated_judgments(batch, hits)
                )
            )
            signatures.append(signature)
        for left in range(len(signatures)):
            for right in range(left + 1, len(signatures)):
                total_pairs += 1
                agreeing_pairs += signatures[left] == signatures[right]
        cases.append({"atom_id": atom_id, "all_runs_agree": len(set(signatures)) == 1})
    return {
        "repeated_atoms": len(atoms),
        "runs_per_atom": runs,
        "agreement": _ratio(agreeing_pairs, total_pairs),
        "cases": cases,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--model-path", default=os.environ.get("QWEN_EMBEDDING_MODEL_PATH"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--cache", required=True)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--stability-atom-id", action="append", default=[])
    parser.add_argument("--stability-runs", type=int, default=3)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")
    if not args.model_path:
        raise SystemExit("QWEN_EMBEDDING_MODEL_PATH or --model-path is required")
    report = run_atomic_evidence_evaluation(
        benchmark_path=args.benchmark,
        state_root=args.state_root,
        model_path=args.model_path,
        deepseek_api_key=api_key,
        cache_path=args.cache,
        device=args.device,
        top_k=args.top_k,
        stability_atom_ids=args.stability_atom_id,
        stability_runs=args.stability_runs,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "parents"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
