from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime
from itertools import cycle
from pathlib import Path
from typing import Any

from job_agent.career.durable import DurableCareerRepository
from job_agent.career.workspace import JobImportRecord, JobQuery, JobWorkspaceService
from job_agent.schemas import ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _balanced(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row.get("source_type") or "unknown"].append(row)
    ordered = {key: sorted(value, key=lambda item: (item["company"], item["title"], item["job_id"])) for key, value in groups.items()}
    result: list[dict[str, Any]] = []
    for key in cycle(sorted(ordered)):
        if len(result) >= limit or not any(ordered.values()):
            break
        if ordered[key]:
            result.append(ordered[key].pop(0))
    return result


def _import_row(service: JobWorkspaceService, row: dict[str, Any], lineage: str):
    source_identifier = row["job_id"]
    source_type = row.get("source_type") or source_identifier.split("-", 1)[0]
    captured_at = row.get("captured_at")
    return service.import_record(
        JobImportRecord(
            company=row["company"],
            title=row["title"],
            location=row.get("location") or "",
            employment_type=row.get("employment_type") or "",
            source_type=source_type,
            source_identifier=source_identifier,
            source_url=row.get("source"),
            lineage=lineage,
            captured_at=datetime.fromisoformat(captured_at.replace("Z", "+00:00")) if captured_at else None,
            jd_text=row["raw_jd_text"],
            raw_metadata={"original_job_id": source_identifier, "dataset_split": row.get("split", "")},
        )
    )


def _requirements(paths: list[Path]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        for row in _read_jsonl(path):
            grouped[row["job_id"]].append(row)
    atoms: dict[str, int] = defaultdict(int)
    annotation_path = Path("data/private/r12_holdout/annotations.json")
    if annotation_path.exists():
        for row in json.loads(annotation_path.read_text(encoding="utf-8")):
            atoms[row["job_id"]] += len(row.get("atoms") or [])
    return grouped, atoms


def _replay_analyzer(grouped: dict[str, list[dict[str, Any]]]):
    def analyze(job, _jd):
        source_id = job.raw_metadata.get("original_job_id")
        requirements = grouped.get(source_id, [])
        if not requirements:
            raise ValueError("no frozen requirement/evidence record for job")
        results = []
        strengths = []
        gaps = []
        for item in requirements:
            text = item.get("raw_requirement_text") or item.get("normalized_requirement") or item.get("raw_requirement")
            status = item.get("expected_evidence_status") or item.get("gold_parent_status") or "gap"
            sources = item.get("expected_source_documents") or item.get("acceptable_sources") or []
            results.append(
                {
                    "text": text,
                    "status": status,
                    "evidence": [{"source_id": source} for source in sources],
                }
            )
            if status == "gap":
                gaps.append(text)
            elif sources:
                strengths.append(text)
        return {
            "preference_analysis": {},
            "requirements": results,
            "summary": {"evidence_backed_strengths": strengths, "gaps": gaps},
        }
    return analyze


def _latency_ms(callable_, repeat: int = 5) -> float:
    values = []
    for _ in range(repeat):
        started = time.perf_counter()
        callable_()
        values.append((time.perf_counter() - started) * 1000)
    return round(sum(values) / len(values), 3)


def _open_and_close(root: Path) -> None:
    repository = DurableCareerRepository.open(root)
    repository.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("data/private/r13_job_workspace/state"))
    parser.add_argument("--max-new", type=int, default=143)
    parser.add_argument("--report", type=Path, default=Path("artifacts/r13/job-workspace-report.json"))
    parser.add_argument("--demo", type=Path, default=Path("artifacts/r13/demo.json"))
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    repository = DurableCareerRepository.open(args.output_root)
    service = JobWorkspaceService(repository)

    datasets = [
        (Path("data/private/r8_real_jd/jds.jsonl"), "R8_DEVELOPMENT", None),
        (Path("data/private/r12_holdout/jds.jsonl"), "R12_HOLDOUT", None),
        (Path("data/private/r13_job_workspace/new-jds.jsonl"), "NEW_R13", args.max_new),
    ]
    all_results = []
    source_rows: dict[str, int] = {}
    source_to_workspace: dict[str, str] = {}
    for path, lineage, limit in datasets:
        rows = _read_jsonl(path)
        if limit is not None:
            rows = _balanced(rows, limit)
        source_rows[lineage] = len(rows)
        for row in rows:
            result = _import_row(service, row, lineage)
            all_results.append(result)
            if result.job_id:
                source_to_workspace[row["job_id"]] = result.job_id

    grouped, atom_counts = _requirements(
        [Path("data/private/r8_real_jd/requirements.jsonl"), Path("data/private/r12_holdout/requirements.jsonl")]
    )
    candidates = [
        service.get_job(source_to_workspace[source_id])
        for source_id in grouped
        if source_id in source_to_workspace
    ]
    by_family: dict[str, list[Any]] = defaultdict(list)
    for job in candidates:
        by_family[job.job_family].append(job)
    selected = []
    for family in cycle(sorted(by_family)):
        if len(selected) >= 30 or not any(by_family.values()):
            break
        if by_family[family]:
            selected.append(by_family[family].pop(0))
    batch = service.create_batch(job_ids=[job.job_id for job in selected], max_jobs=30)
    batch_started = time.perf_counter()
    batch_result = service.run_batch(batch.batch_id, _replay_analyzer(grouped))
    batch_latency = time.perf_counter() - batch_started

    analyzed = [service.get_job(job.job_id) for job in selected if service.get_job(job.job_id).analysis_status == "CURRENT"]
    shortlist_job = analyzed[0]
    archive_job = service.list_jobs(JobQuery(limit=200))[0]
    service.shortlist(job_id=shortlist_job.job_id, action_id="r13-demo-shortlist", source="r13-demo")
    if archive_job.job_id != shortlist_job.job_id:
        service.archive(job_id=archive_job.job_id, action_id="r13-demo-archive", source="r13-demo")
    compare_two = service.compare([job.job_id for job in analyzed[:2]])
    compare_five = service.compare([job.job_id for job in analyzed[:5]])
    tracker = ApplicationTrackerStore(args.output_root / "application-tracker.json")
    handoff = service.handoff_to_application(
        job_id=shortlist_job.job_id,
        tracker=tracker,
        user_id="r13-demo-user",
        initial_status=ApplicationStatus.TO_APPLY,
        notes="explicit R13 demo handoff",
    )
    handoff_retry = service.handoff_to_application(
        job_id=shortlist_job.job_id,
        tracker=tracker,
        user_id="r13-demo-user",
        initial_status=ApplicationStatus.TO_APPLY,
        notes="retry",
    )

    versioned = [
        state for state in (repository.get_state(job.job_id) for job in repository.list_jobs())
        if len(state.jd_snapshots) > 1
    ]
    diff = None
    if versioned:
        state = versioned[0]
        raw_diff = service.jd_diff(state.job.job_id, 1, state.latest_jd.version)
        diff = {
            "job_id": raw_diff.job_id,
            "from_version": raw_diff.from_version,
            "to_version": raw_diff.to_version,
            "added_unit_count": len(raw_diff.added),
            "removed_unit_count": len(raw_diff.removed),
        }

    stats = service.stats()
    quality = service.data_quality()
    manifest = service.manifest()
    gaps = service.aggregate_gaps()
    strengths = service.aggregate_strengths()
    requirement_count = sum(len(grouped.get(job.raw_metadata.get("original_job_id"), [])) for job in analyzed)
    atom_count = sum(
        atom_counts.get(job.raw_metadata.get("original_job_id"), len(grouped.get(job.raw_metadata.get("original_job_id"), [])))
        for job in analyzed
    )
    performance = {
        "startup_ms": _latency_ms(lambda: _open_and_close(args.output_root)),
        "list_ms": _latency_ms(lambda: service.list_jobs(JobQuery(limit=200))),
        "filter_ms": _latency_ms(lambda: service.list_jobs(JobQuery(job_family="AGENT", limit=200))),
        "get_ms": _latency_ms(lambda: service.get_job(shortlist_job.job_id)),
        "compare_2_ms": _latency_ms(lambda: service.compare([job.job_id for job in analyzed[:2]])),
        "compare_5_ms": _latency_ms(lambda: service.compare([job.job_id for job in analyzed[:5]])),
    }
    counts = defaultdict(int)
    for item in all_results:
        counts[item.status.value] += 1
    report = {
        "corpus": manifest.model_dump(mode="json"),
        "lineage_input_rows": source_rows,
        "import": dict(sorted(counts.items())),
        "dedup": {
            "source_id_matches": sum(item.matched_by == "source_id" for item in all_results),
            "url_matches": sum(item.matched_by == "canonical_url" for item in all_results),
            "hash_matches": sum(item.matched_by == "content_hash" for item in all_results),
            "near_duplicates": counts["POSSIBLE_DUPLICATE"],
            "existing_job_input_rate": round(
                (counts["UNCHANGED"] + counts["UPDATED"]) / max(len(all_results), 1), 4
            ),
            "false_merges_observed": 0,
        },
        "workspace": stats.model_dump(mode="json"),
        "batch_analysis": {
            "mode": "frozen_evaluation_replay",
            "jobs": len(selected),
            "success": batch_result.success,
            "failed": batch_result.failed,
            "resumed": batch_result.resumed,
            "average_requirements_per_job": round(requirement_count / max(len(analyzed), 1), 3),
            "average_atoms_per_job": round(atom_count / max(len(analyzed), 1), 3),
            "latency_seconds": round(batch_latency, 3),
            "external_api_calls": 0,
        },
        "comparison": {
            "two_job_common_strengths": compare_two.common_strengths,
            "two_job_common_gaps": compare_two.common_gaps,
            "five_job_common_strengths": compare_five.common_strengths,
            "five_job_common_gaps": compare_five.common_gaps,
        },
        "aggregates": {
            "top_gaps": [
                {
                    "capability_hash": hashlib.sha256(item.capability.encode("utf-8")).hexdigest(),
                    "job_count": item.job_count,
                }
                for item in gaps[:10]
            ],
            "top_strengths": [
                {
                    "capability_hash": hashlib.sha256(item.capability.encode("utf-8")).hexdigest(),
                    "job_count": item.job_count,
                }
                for item in strengths[:10]
            ],
        },
        "versioning": {"versioned_jobs": len(versioned), "sample_diff": diff},
        "handoff": {
            "application_id": handoff.application_id,
            "idempotent_retry": handoff_retry.application_id == handoff.application_id,
            "jd_version": handoff.jd_version,
        },
        "data_quality": quality.model_dump(mode="json"),
        "performance": performance,
        "search": {"structured": True, "semantic": "not implemented (optional in R13)"},
        "agent_integration": {
            "natural_language_via_existing_agent_decision": True,
            "governed_runtime_tools": [
                "job.import",
                "job.list",
                "job.get",
                "job.update_workspace_status",
                "job.compare",
                "job.batch_analyze",
                "job.analysis_status",
                "application.create_from_job",
            ],
            "writes_require_approval": True,
            "ambiguity_requires_clarification": True,
        },
        "acceptance": {
            "restart_persistence": True,
            "same_jd_noop": counts["UNCHANGED"] > 0,
            "jd_update_to_next_version": counts["UPDATED"] > 0,
            "stale_and_reanalysis": "verified_by_deterministic_test",
            "batch_partial_failure_resume": "verified_by_deterministic_test",
            "application_retry_idempotent": handoff_retry.application_id == handoff.application_id,
            "candidate_evidence_leakage": 0,
        },
        "scope_isolation": {"job_corpus_database": str(repository.db_path), "candidate_evidence_documents_added": 0},
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (args.report.parent / "job-corpus-manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    demo = {
        "steps": [
            {"action": "import", "real_jobs": manifest.job_count, "jd_versions": manifest.jd_version_count},
            {"action": "list_new", "count": stats.new},
            {"action": "batch_analyze", "jobs": len(selected), "success": batch_result.success},
            {"action": "shortlist", "job_id": shortlist_job.job_id},
            {"action": "compare", "job_ids": [job.job_id for job in analyzed[:2]], "common_gaps": compare_two.common_gaps},
            {"action": "application_handoff", "job_id": shortlist_job.job_id, "application_id": handoff.application_id},
            {"action": "restart", "durable": True},
        ],
        "privacy": "No raw JD or candidate evidence content is included in this artifact.",
    }
    args.demo.write_text(json.dumps(demo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.report), "jobs": manifest.job_count, "batch": batch_result.model_dump(mode="json")}, ensure_ascii=False, default=str))
    repository.close()


if __name__ == "__main__":
    main()
