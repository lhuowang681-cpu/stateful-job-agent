from __future__ import annotations

import argparse
import json
from pathlib import Path

from job_agent.evaluation.atomic_evidence_v2 import (
    BENCHMARK_VERSION,
    EvidenceBenchmarkV2,
    aggregate_parent_status,
    atomic_requirement_id,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_benchmark(
    *,
    requirements_path: Path,
    annotations_path: Path,
    source_split: str,
    dataset_status: str,
    require_complete_split: bool,
) -> dict:
    requirements = {
        item["requirement_id"]: item
        for item in _read_jsonl(requirements_path)
        if item["split"] == source_split
    }
    annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
    annotation_ids = {item["requirement_id"] for item in annotations}
    if not annotation_ids <= set(requirements):
        extra = sorted(annotation_ids - set(requirements))
        raise ValueError(f"annotations are outside source split: {extra}")
    if require_complete_split and annotation_ids != set(requirements):
        missing = sorted(set(requirements) - annotation_ids)
        raise ValueError(f"annotation coverage mismatch; missing={missing}")

    parents = []
    for annotation in annotations:
        lineage = requirements[annotation["requirement_id"]]
        atoms = []
        for index, atom in enumerate(annotation["atoms"], start=1):
            atoms.append(
                {
                    "atom_id": atomic_requirement_id(lineage["requirement_id"], index),
                    **atom,
                }
            )
        atom_support = {
            item["atom_id"]: item["gold_entailment"] == "supported"
            for item in atoms
        }
        gold_parent_status = aggregate_parent_status(
            atom_support,
            required_atom_ids=[item["atom_id"] for item in atoms if item.get("required", True)],
        ).status
        source_union = sorted(
            {
                source
                for item in atoms
                for source in item.get("acceptable_sources", [])
            }
        )
        corrections = []
        if lineage["expected_evidence_status"] != gold_parent_status:
            corrections.append(
                {
                    "old_label": lineage["expected_evidence_status"],
                    "new_label": gold_parent_status,
                    "reason": annotation["correction_reason"],
                }
            )
        parents.append(
            {
                "requirement_id": lineage["requirement_id"],
                "job_id": lineage["job_id"],
                "original_split": lineage["split"],
                "dataset_status": dataset_status,
                "raw_requirement": lineage["raw_requirement_text"],
                "lineage_gold_status": lineage["expected_evidence_status"],
                "lineage_sources": lineage["expected_source_documents"],
                "atoms": atoms,
                "aggregation_rule": "all_required",
                "gold_parent_status": gold_parent_status,
                "acceptable_sources": source_union,
                "annotation_notes": annotation["annotation_notes"],
                "correction_history": corrections,
                "ambiguity_status": annotation.get("ambiguity_status", "resolved"),
            }
        )
    return EvidenceBenchmarkV2.model_validate(
        {
            "benchmark_version": BENCHMARK_VERSION,
            "source_dataset_version": "real-career-v1",
            "dataset_status": dataset_status,
            "parents": parents,
        }
    ).model_dump(mode="json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-split", choices=("dev", "frozen"), required=True)
    parser.add_argument(
        "--dataset-status",
        choices=("dev", "regression", "holdout"),
        required=True,
    )
    parser.add_argument("--require-complete-split", action="store_true")
    args = parser.parse_args()
    payload = build_benchmark(
        requirements_path=args.requirements,
        annotations_path=args.annotations,
        source_split=args.source_split,
        dataset_status=args.dataset_status,
        require_complete_split=args.require_complete_split,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "parents": len(payload["parents"]),
                "atoms": sum(len(item["atoms"]) for item in payload["parents"]),
                "corrections": sum(
                    bool(item["correction_history"]) for item in payload["parents"]
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
