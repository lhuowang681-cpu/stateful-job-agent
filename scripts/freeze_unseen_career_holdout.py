from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from job_agent.evaluation.atomic_evidence_v2 import (
    PROMPT_VERSION as EVIDENCE_PROMPT_VERSION,
    load_evidence_benchmark_v2,
)
from job_agent.evidence.requirements import PROMPT_VERSION as REQUIREMENT_PROMPT_VERSION
from job_agent.knowledge.durable import KnowledgeRepository
from job_agent.text_identity import normalize_text


TOKEN = re.compile(r"[a-z0-9+#.]+", re.IGNORECASE)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, " ".join(left.casefold().split()), " ".join(right.casefold().split())).ratio()


def _tokens(value: str) -> set[str]:
    return set(TOKEN.findall(value.casefold()))


def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a or b else 1.0


def freeze(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    jobs = _jsonl(args.jobs)
    requirements = _jsonl(args.requirements)
    old_jobs = _jsonl(args.old_jobs)
    old_requirements = _jsonl(args.old_requirements)
    benchmark = load_evidence_benchmark_v2(args.benchmark)
    old_hashes = {_text_hash(item["raw_jd_text"]) for item in old_jobs}
    old_company_titles = {
        (item["company"].casefold().strip(), item["title"].casefold().strip()) for item in old_jobs
    }
    exact_overlaps = 0
    company_title_overlaps = 0
    max_text_similarity = 0.0
    max_requirement_overlap = 0.0
    cases = []
    new_requirements_by_job: dict[str, list[str]] = {}
    for item in requirements:
        new_requirements_by_job.setdefault(item["job_id"], []).append(item["raw_requirement_text"])
    old_requirement_texts = [item["raw_requirement_text"] for item in old_requirements]
    for index, job in enumerate(jobs, start=1):
        exact = _text_hash(job["raw_jd_text"]) in old_hashes
        company_title = (job["company"].casefold().strip(), job["title"].casefold().strip()) in old_company_titles
        text_similarity = max(_similarity(job["raw_jd_text"], old["raw_jd_text"]) for old in old_jobs)
        requirement_overlap = max(
            _jaccard(new, old)
            for new in new_requirements_by_job[job["job_id"]]
            for old in old_requirement_texts
        )
        exact_overlaps += exact
        company_title_overlaps += company_title
        max_text_similarity = max(max_text_similarity, text_similarity)
        max_requirement_overlap = max(max_requirement_overlap, requirement_overlap)
        cases.append(
            {
                "holdout_id": f"holdout-{index:02d}",
                "exact_hash_overlap": exact,
                "company_title_overlap": company_title,
                "max_normalized_text_similarity": round(text_similarity, 6),
                "max_requirement_token_jaccard": round(requirement_overlap, 6),
                "excluded_as_duplicate": exact or company_title or text_similarity >= 0.9 or requirement_overlap >= 0.9,
            }
        )
    dedup = {
        "holdout_jobs": len(jobs),
        "prior_jobs": len(old_jobs),
        "exact_hash_overlaps": exact_overlaps,
        "company_title_overlaps": company_title_overlaps,
        "max_normalized_text_similarity": round(max_text_similarity, 6),
        "max_requirement_token_jaccard": round(max_requirement_overlap, 6),
        "duplicate_thresholds": {"normalized_text_similarity": 0.9, "requirement_token_jaccard": 0.9},
        "excluded_duplicates": sum(item["excluded_as_duplicate"] for item in cases),
        "cases": cases,
    }
    job_ids = {item["job_id"] for item in jobs}
    requirement_ids = {item["requirement_id"] for item in requirements}
    source_repository = KnowledgeRepository(args.knowledge_db)
    documents = source_repository.list_active_documents()
    source_ids = {item.document_id for item in documents}
    parent_ids = {item.requirement_id for item in benchmark.parents}
    source_references = {
        source for parent in benchmark.parents for atom in parent.atoms for source in atom.acceptable_sources
    }
    raw_requirements_by_id = {item["requirement_id"]: item for item in requirements}
    jobs_by_id = {item["job_id"]: item for item in jobs}
    checks = {
        "job_ids_unique": len(job_ids) == len(jobs),
        "requirement_ids_unique": len(requirement_ids) == len(requirements),
        "all_parents_link_to_jobs": all(parent.job_id in job_ids for parent in benchmark.parents),
        "requirements_match_benchmark": requirement_ids == parent_ids,
        "requirements_are_verbatim_jd_substrings": all(
            raw_requirements_by_id[parent.requirement_id]["raw_requirement_text"]
            in jobs_by_id[parent.job_id]["raw_jd_text"]
            for parent in benchmark.parents
        ),
        "acceptable_sources_exist": source_references <= source_ids,
        "gold_is_pre_model_human": all(
            item["label_provenance"] == "human_pre_model_not_model_or_retrieval_generated"
            for item in requirements
        ),
        "no_dedup_failures": dedup["excluded_duplicates"] == 0,
    }
    audit = {
        "passed": all(checks.values()),
        "checks": checks,
        "jobs": len(jobs),
        "parents": len(benchmark.parents),
        "atoms": sum(len(parent.atoms) for parent in benchmark.parents),
        "positive_atoms": sum(atom.gold_entailment == "supported" for parent in benchmark.parents for atom in parent.atoms),
        "gap_atoms": sum(atom.gold_entailment == "unsupported" for parent in benchmark.parents for atom in parent.atoms),
        "unresolved": sum(parent.ambiguity_status == "unresolved" for parent in benchmark.parents),
        "acceptable_source_documents": sorted(source_references),
    }
    if not audit["passed"]:
        raise ValueError(f"gold audit failed: {checks}")
    dataset_hash_payload = {
        "jobs_sha256": _sha256(args.jobs),
        "requirements_sha256": _sha256(args.requirements),
        "benchmark_sha256": _sha256(args.benchmark),
    }
    dataset_hash = hashlib.sha256(
        json.dumps(dataset_hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    index_manifest = json.loads(args.index_manifest.read_text(encoding="utf-8"))
    manifest = {
        "dataset_version": "unseen-career-holdout-v2.0",
        "dataset_status": "frozen_unseen_holdout",
        "job_count": len(jobs),
        "parent_count": len(benchmark.parents),
        "atom_count": audit["atoms"],
        "positive_atom_count": audit["positive_atoms"],
        "gap_atom_count": audit["gap_atoms"],
        "unresolved_count": audit["unresolved"],
        "dataset_hash": dataset_hash,
        "private_payload_hashes": dataset_hash_payload,
        "annotation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "gold_frozen_before_model_run": True,
        "corpus": {
            "version": index_manifest["corpus_version"],
            "document_count": len(documents),
            "documents": [
                {"document_id": item.document_id, "version": item.version, "content_hash": item.content_hash}
                for item in documents
            ],
            "index_manifest_sha256": _sha256(args.index_manifest),
            "index_checksum": index_manifest["index_checksum"],
            "chunk_ids_checksum": index_manifest["chunk_ids_checksum"],
        },
        "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
        "retrieval_config": {
            "backend": "FAISS IndexFlatIP over normalized embeddings",
            "gold_atomic_metrics_top_k": 5,
            "evidence_candidate_top_k": 3,
            "end_to_end_top_k": 5,
            "chunk_max_chars": 2000,
        },
        "requirement_prompt_version": REQUIREMENT_PROMPT_VERSION,
        "evidence_prompt_version": EVIDENCE_PROMPT_VERSION,
        "model_provider_config": {"provider": "deepseek", "model": "deepseek-chat", "temperature": 0.0},
        "production_code_commit": args.code_commit,
        "dedup_report_sha256": None,
        "gold_audit_sha256": None,
    }
    return dedup, audit, manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--old-jobs", type=Path, required=True)
    parser.add_argument("--old-requirements", type=Path, required=True)
    parser.add_argument("--knowledge-db", type=Path, required=True)
    parser.add_argument("--index-manifest", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    dedup, audit, manifest = freeze(args)
    args.output_root.mkdir(parents=True, exist_ok=True)
    dedup_path = args.output_root / "holdout_dedup_report.json"
    audit_path = args.output_root / "gold_audit.json"
    dedup_path.write_text(json.dumps(dedup, indent=2) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    manifest["dedup_report_sha256"] = _sha256(dedup_path)
    manifest["gold_audit_sha256"] = _sha256(audit_path)
    (args.output_root / "holdout_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"dedup": dedup, "audit": audit, "manifest": manifest}, indent=2))


if __name__ == "__main__":
    main()
