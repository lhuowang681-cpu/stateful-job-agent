from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from job_agent.evaluation.atomic_evidence_v2 import load_evidence_benchmark_v2
from job_agent.evaluation.real_atomic_evidence import _invoke_entailment, _validated_judgments
from job_agent.evaluation.real_career_runner import _DiagnosticDeepSeekProvider
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.durable import CareerKnowledgeLifecycle, EmbeddingIdentity, KnowledgeRepository
from job_agent.llm.harness import LLMHarness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--main-report", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    full = json.loads(args.main_report.read_text(encoding="utf-8"))
    buckets: dict[str, list[str]] = defaultdict(list)
    for parent in full["gold_atomic"]["parents"]:
        for atom in parent["atoms"]:
            gold = atom["gold_entailment"]
            predicted = atom["predicted_entailment"]
            if gold == "supported" and predicted == "supported":
                bucket = "correct_supported"
            elif gold == "unsupported" and predicted == "unsupported":
                bucket = "correct_gap"
            elif gold == "unsupported":
                bucket = "false_support"
            else:
                bucket = "false_gap"
            buckets[bucket].append(atom["atom_id"])
    selected = [
        *buckets["correct_supported"][:3],
        *buckets["correct_gap"][:3],
        *buckets["false_support"][:1],
        *buckets["false_gap"][:3],
    ]
    selected = selected[:10]
    category_by_id = {atom_id: category for category, ids in buckets.items() for atom_id in ids}
    benchmark = load_evidence_benchmark_v2(args.benchmark)
    atoms = {atom.atom_id: atom for parent in benchmark.parents for atom in parent.atoms}

    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    repository = KnowledgeRepository(args.state_root / "knowledge.sqlite")
    lifecycle = CareerKnowledgeLifecycle(
        repository=repository,
        embedding_backend=QwenEmbeddingBackend(args.model_path, device="cuda"),
        embedding_identity=EmbeddingIdentity(provider="sentence-transformers", model="Qwen/Qwen3-Embedding-0.6B", dimension=1024),
        index_path=args.state_root / "career.faiss",
        manifest_path=args.state_root / "career-index-manifest.json",
        max_chars=2000,
    )
    retrieval = CareerKnowledgeService(lifecycle.candidate_retriever(), lifecycle=lifecycle)
    provider = _DiagnosticDeepSeekProvider(api_key=api_key, timeout_s=120.0)
    harness = LLMHarness(provider)
    cases = []
    agreeing_pairs = total_pairs = 0
    for atom_id in selected:
        atom = atoms[atom_id]
        hits = retrieval.query_candidate_evidence(atom.text, 3)
        signatures = []
        for repeat in range(3):
            batch = _invoke_entailment(
                atom=atom,
                hits=hits,
                harness=harness,
                session_id="r12-unseen-stability",
                run_id=f"r12-stability-{atom_id}-{repeat}",
            )
            signatures.append(
                tuple(sorted((item.chunk_id, item.entails) for item in _validated_judgments(batch, hits)))
            )
        for left in range(3):
            for right in range(left + 1, 3):
                total_pairs += 1
                agreeing_pairs += signatures[left] == signatures[right]
        cases.append(
            {
                "atom_id": atom_id,
                "category": category_by_id[atom_id],
                "all_runs_agree": len(set(signatures)) == 1,
                "signatures": signatures,
            }
        )
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    args.private_output.write_text(
        json.dumps({"cases": cases, "diagnostics": provider.diagnostics}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    public = {
        "main_report_sha256": hashlib.sha256(args.main_report.read_bytes()).hexdigest(),
        "atoms": len(selected),
        "runs_per_atom": 3,
        "category_sample": {
            category: sum(item["category"] == category for item in cases)
            for category in ("correct_supported", "correct_gap", "false_support", "false_gap")
        },
        "pairwise_agreement": agreeing_pairs / total_pairs if total_pairs else None,
        "all_runs_agree_atoms": sum(item["all_runs_agree"] for item in cases),
        "api": {
            "calls": len(harness.traces),
            "input_tokens": sum(item.input_tokens or 0 for item in harness.traces),
            "output_tokens": sum(item.output_tokens or 0 for item in harness.traces),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(public, indent=2))


if __name__ == "__main__":
    main()
