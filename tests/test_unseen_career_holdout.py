from __future__ import annotations

import hashlib
import json

import pytest

from job_agent.evaluation.unseen_career_holdout import _retrieval_metrics, verify_freeze


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_retrieval_metrics_report_rank_cutoffs_and_ignore_gap_atoms() -> None:
    rows = [
        {
            "gold_entailment": "supported",
            "acceptable_sources": ["source-a"],
            "retrieved_top5": [
                {"document_id": "source-a", "rank": 1},
                {"document_id": "other", "rank": 2},
            ],
        },
        {
            "gold_entailment": "supported",
            "acceptable_sources": ["source-b"],
            "retrieved_top5": [
                {"document_id": "other", "rank": 1},
                {"document_id": "source-b", "rank": 2},
            ],
        },
        {
            "gold_entailment": "unsupported",
            "acceptable_sources": [],
            "retrieved_top5": [{"document_id": "other", "rank": 1}],
        },
    ]

    metrics = _retrieval_metrics(rows)

    assert metrics == {
        "positive_atoms": 2,
        "recall_at_1": 0.5,
        "recall_at_3": 1.0,
        "recall_at_5": 1.0,
        "mrr": 0.75,
    }


def test_verify_freeze_rejects_payload_changed_after_manifest(tmp_path) -> None:
    jobs = tmp_path / "jobs.jsonl"
    requirements = tmp_path / "requirements.jsonl"
    benchmark = tmp_path / "benchmark.json"
    index_manifest = tmp_path / "index-manifest.json"
    for path, content in (
        (jobs, "jobs\n"),
        (requirements, "requirements\n"),
        (benchmark, "benchmark\n"),
        (index_manifest, "index\n"),
    ):
        path.write_text(content, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "private_payload_hashes": {
                    "jobs_sha256": _digest(jobs),
                    "requirements_sha256": _digest(requirements),
                    "benchmark_sha256": _digest(benchmark),
                },
                "corpus": {"index_manifest_sha256": _digest(index_manifest)},
            }
        ),
        encoding="utf-8",
    )
    verify_freeze(
        manifest,
        jobs_path=jobs,
        requirements_path=requirements,
        benchmark_path=benchmark,
        index_manifest_path=index_manifest,
    )

    requirements.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="payload hash mismatch"):
        verify_freeze(
            manifest,
            jobs_path=jobs,
            requirements_path=requirements,
            benchmark_path=benchmark,
            index_manifest_path=index_manifest,
        )
