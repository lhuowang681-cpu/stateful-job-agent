from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from job_agent.evaluation.real_career_data import (
    ExtractionPrediction,
    RequirementGoldRecord,
    evaluate_requirement_extraction,
    load_real_career_dataset,
    requirement_matches,
)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _status_class(value: str) -> str:
    if value == "supported":
        return "supported"
    if value in {"partial", "unverified_lead"}:
        return "partial"
    return "gap"


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _load_job_results(*roots: Path) -> dict[str, dict[str, Any]]:
    results = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            results[path.stem] = payload
    return results


def _match(gold: RequirementGoldRecord, requirements: list[dict[str, Any]], raw_jd: str) -> dict[str, Any] | None:
    for item in requirements:
        source = item.get("requirement_source", {})
        quote = raw_jd[source.get("start_offset", 0) : source.get("end_offset", 0)]
        if requirement_matches(gold.raw_requirement_text, item["text"]) or requirement_matches(gold.raw_requirement_text, quote):
            return item
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-summary", type=Path, required=True)
    parser.add_argument("--initial-full-report", type=Path, required=True)
    parser.add_argument("--continuation-report", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--main-job-results", type=Path, required=True)
    parser.add_argument("--continuation-job-results", type=Path, required=True)
    parser.add_argument("--stability", type=Path)
    parser.add_argument("--regression-summary")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    initial = json.loads(args.initial_summary.read_text(encoding="utf-8"))
    initial_full = json.loads(args.initial_full_report.read_text(encoding="utf-8"))
    continuation = json.loads(args.continuation_report.read_text(encoding="utf-8"))
    stability = json.loads(args.stability.read_text(encoding="utf-8")) if args.stability else None
    jobs = _jsonl(args.jobs)
    dataset = load_real_career_dataset(
        jobs_path=args.jobs,
        requirements_path=args.requirements,
        dataset_version=initial["dataset_version"],
    )
    aliases = {item["job_id"]: f"holdout-{index:02d}" for index, item in enumerate(jobs, start=1)}
    raw_by_job = {item["job_id"]: item["raw_jd_text"] for item in jobs}
    job_results = _load_job_results(args.main_job_results, args.continuation_job_results)
    predictions = []
    for job in dataset.jobs:
        result = job_results.get(job.job_id)
        if result is None:
            predictions.append(ExtractionPrediction(job_id=job.job_id, schema_valid=False, error="blind_run_schema_failure"))
            continue
        requirements = result["requirements"]
        predictions.append(
            ExtractionPrediction(
                job_id=job.job_id,
                schema_valid=True,
                requirements=[item["text"] for item in requirements],
                source_quotes=[
                    job.raw_jd_text[item["requirement_source"]["start_offset"] : item["requirement_source"]["end_offset"]]
                    for item in requirements
                ],
            )
        )
    extraction = evaluate_requirement_extraction(dataset, predictions, split="frozen")
    requirements_by_job: dict[str, list[RequirementGoldRecord]] = defaultdict(list)
    for item in dataset.requirements:
        requirements_by_job[item.job_id].append(item)
    attribution: Counter[str] = Counter()
    representatives: dict[str, str] = {}
    public_cases = []
    correct_requirements = fully = partially = major = 0
    for job in dataset.jobs:
        result = job_results.get(job.job_id)
        requirements = result["requirements"] if result else []
        correct = 0
        for gold in requirements_by_job[job.job_id]:
            matched = _match(gold, requirements, raw_by_job[job.job_id])
            if matched is None:
                failure = "REQUIREMENT_MISS"
                attribution[failure] += 1
                representatives.setdefault(failure, aliases[job.job_id])
                continue
            predicted = _status_class(matched["status"])
            if predicted == gold.expected_evidence_status:
                correct += 1
                correct_requirements += 1
            else:
                failure = "EVIDENCE_FALSE_SUPPORT" if gold.expected_evidence_status == "gap" else "EVIDENCE_FALSE_GAP"
                attribution[failure] += 1
                representatives.setdefault(failure, aliases[job.job_id])
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
        public_cases.append({"holdout_id": aliases[job.job_id], "correct_parents": correct, "parents": total, "status": status})
    gold_attr = initial["failure_attribution"]["gold_atomic"]
    gold_representatives: dict[str, str] = {}
    for parent in initial_full["gold_atomic"]["parents"]:
        for atom in parent["atoms"]:
            gold = atom["gold_entailment"]
            predicted = atom["predicted_entailment"]
            expected = set(atom["acceptable_sources"])
            top3 = {item["document_id"] for item in atom["retrieved_top5"][:3]}
            if gold == "supported" and not expected.intersection(top3):
                gold_representatives.setdefault("RETRIEVAL_RANKING", atom["atom_id"])
            elif gold == "supported" and predicted == "unsupported":
                gold_representatives.setdefault("EVIDENCE_FALSE_GAP", atom["atom_id"])
            elif gold == "unsupported" and predicted == "supported":
                gold_representatives.setdefault("EVIDENCE_FALSE_SUPPORT", atom["atom_id"])
            elif gold == "supported" and atom["evidence_links"] and not any(item["acceptable_source"] for item in atom["evidence_links"]):
                gold_representatives.setdefault("SOURCE_SELECTION", atom["atom_id"])
    initial_api = initial["api"]
    continuation_api = continuation["api"]
    public = {
        **{key: initial[key] for key in ("dataset_version", "dataset_hash", "production_code_commit", "holdout_integrity", "dataset")},
        "blind_run_integrity": {
            "initial_result_sha256": hashlib.sha256(args.initial_summary.read_bytes()).hexdigest(),
            "technical_continuation_jobs": 2,
            "semantic_retries": 0,
            "post_result_gold_edits": 0,
        },
        "requirement_extraction": extraction.model_dump(mode="json"),
        "gold_atomic_retrieval": initial["gold_atomic_retrieval"],
        "gold_atomic_evidence": initial["gold_atomic_evidence"],
        "parent_aggregation": initial["parent_aggregation"],
        "end_to_end_job_match": {
            "jobs_completed": len(job_results),
            "strength_gap_correctness": _ratio(correct_requirements, len(dataset.requirements)),
            "fully_correct_jobs": fully,
            "partially_correct_jobs": partially,
            "major_error_jobs": major,
            "cases": public_cases,
        },
        "failure_attribution": {
            "gold_atomic": [
                {"layer": layer, "count": count, "representative_case": gold_representatives.get(layer)}
                for layer, count in sorted(gold_attr.items())
            ],
            "end_to_end": [
                {"layer": layer, "count": count, "representative_case": representatives.get(layer)}
                for layer, count in sorted(attribution.items())
            ],
        },
        "stability": stability,
        "regression": {"tests": args.regression_summary} if args.regression_summary else None,
        "api": {
            "total_calls": initial_api["calls"] + continuation_api["calls"] + (stability["api"]["calls"] if stability else 0),
            "main_and_continuation_calls": initial_api["calls"] + continuation_api["calls"],
            "input_tokens": initial_api["input_tokens"] + continuation_api["input_tokens"] + (stability["api"]["input_tokens"] if stability else 0),
            "output_tokens": initial_api["output_tokens"] + continuation_api["output_tokens"] + (stability["api"]["output_tokens"] if stability else 0),
            "initial_blind_run": initial_api,
            "technical_continuation": continuation_api,
            "stability": stability["api"] if stability else None,
        },
    }
    args.output.write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(public, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
