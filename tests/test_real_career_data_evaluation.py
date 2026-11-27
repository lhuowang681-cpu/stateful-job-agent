from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.evaluation.real_career_data import (
    EvidencePrediction,
    ExtractionPrediction,
    RequirementGoldRecord,
    audit_real_career_dataset,
    dataset_summary,
    evaluate_evidence,
    evaluate_requirement_extraction,
    evaluate_retrieval,
    load_real_career_dataset,
)
from job_agent.knowledge.contracts import RetrievedChunk
from job_agent.knowledge.ingestion import (
    chunk_knowledge_document,
    create_knowledge_document,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows),
        encoding="utf-8",
    )


def _dataset(tmp_path: Path):
    jobs = [
        {
            "job_id": "job-dev",
            "company": "Public AI",
            "title": "Agent Engineer",
            "location": "杭州",
            "employment_type": "internship",
            "source": "https://jobs.example.test/dev",
            "captured_at": "2026-09-20T00:00:00+08:00",
            "raw_jd_text": "Build Agent tools and RAG.",
            "split": "dev",
        },
        {
            "job_id": "job-frozen",
            "company": "Public AI",
            "title": "LLM Engineer",
            "location": "上海",
            "employment_type": "full_time",
            "source": "https://jobs.example.test/frozen",
            "captured_at": "2026-09-20T00:00:00+08:00",
            "raw_jd_text": "Build RAG. Kubernetes production is required.",
            "split": "frozen",
        },
    ]
    requirements = [
        {
            "requirement_id": "req-dev-agent",
            "job_id": "job-dev",
            "split": "dev",
            "raw_requirement_text": "Build Agent tools.",
            "normalized_requirement": "build agent tools.",
            "category": "agent/tool calling",
            "expected_evidence_status": "supported",
            "expected_source_documents": ["project-agent"],
            "notes": "Curated direct project match.",
            "label_provenance": "curated_static_v1_not_model_or_retrieval_generated",
        },
        {
            "requirement_id": "req-frozen-rag",
            "job_id": "job-frozen",
            "split": "frozen",
            "raw_requirement_text": "Build RAG retrieval.",
            "normalized_requirement": "build rag retrieval.",
            "category": "RAG/retrieval",
            "expected_evidence_status": "supported",
            "expected_source_documents": ["project-rag"],
            "notes": "Curated direct project match.",
            "label_provenance": "curated_static_v1_not_model_or_retrieval_generated",
        },
        {
            "requirement_id": "req-frozen-k8s",
            "job_id": "job-frozen",
            "split": "frozen",
            "raw_requirement_text": "Kubernetes production experience.",
            "normalized_requirement": "kubernetes production experience.",
            "category": "infra/deployment",
            "expected_evidence_status": "gap",
            "expected_source_documents": [],
            "notes": "No verified production source.",
            "label_provenance": "curated_static_v1_not_model_or_retrieval_generated",
        },
    ]
    jobs_path = tmp_path / "jobs.jsonl"
    requirements_path = tmp_path / "requirements.jsonl"
    _write_jsonl(jobs_path, jobs)
    _write_jsonl(requirements_path, requirements)
    return load_real_career_dataset(
        jobs_path=jobs_path,
        requirements_path=requirements_path,
    )


def _document(document_id: str, text: str):
    return create_knowledge_document(
        document_id=document_id,
        source_type="project",
        text=text,
        version=1,
        metadata={"material_kind": "real_project_material"},
    )


class _RetrievalService:
    def __init__(self, document) -> None:
        self.chunk = chunk_knowledge_document(document, max_chars=1000)[0]

    def query_candidate_evidence(self, query: str, top_k: int):
        return [
            RetrievedChunk(
                chunk=self.chunk,
                score=1.0,
                rank=1,
                retrieval_method="dense",
            )
        ]


def test_grouped_split_labels_and_leakage_audit(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    documents = [
        _document("project-agent", "Agent tool calling runtime."),
        _document("project-rag", "RAG retrieval with FAISS."),
    ]
    audit = audit_real_career_dataset(dataset, candidate_documents=documents)
    summary = dataset_summary(dataset)

    assert audit.passed is True
    assert summary["jobs_by_split"] == {"dev": 1, "frozen": 1}
    assert summary["requirements_by_split"] == {"dev": 1, "frozen": 2}
    assert {item.job_id for item in dataset.requirements if item.split == "dev"} == {"job-dev"}
    assert {item.job_id for item in dataset.requirements if item.split == "frozen"} == {"job-frozen"}


def test_requirement_gold_rejects_gap_with_expected_source() -> None:
    with pytest.raises(ValidationError):
        RequirementGoldRecord(
            requirement_id="req-invalid",
            job_id="job-1",
            split="dev",
            raw_requirement_text="Kubernetes production",
            normalized_requirement="kubernetes production",
            category="infra/deployment",
            expected_evidence_status="gap",
            expected_source_documents=["project-rag"],
            notes="invalid",
            label_provenance="manual",
        )


def test_retrieval_metrics_use_positive_requirements_only(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    document = _document("project-rag", "RAG retrieval with FAISS.")
    report = evaluate_retrieval(
        dataset,
        service=_RetrievalService(document),
        active_versions={"project-rag": 1},
    )
    assert report.overall.query_count == 1
    assert report.overall.recall_at_1 == 1.0
    assert report.overall.mrr == 1.0
    assert report.overall.active_version_correctness == 1.0
    assert "req-frozen-k8s" not in report.rankings


def test_requirement_and_evidence_metrics(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    extraction = evaluate_requirement_extraction(
        dataset,
        [
            ExtractionPrediction(
                job_id="job-frozen",
                schema_valid=True,
                requirements=[
                    "Build RAG retrieval.",
                    "Kubernetes production experience.",
                ],
            )
        ],
    )
    evidence = evaluate_evidence(
        dataset,
        [
            EvidencePrediction(
                requirement_id="req-frozen-rag",
                semantic_status="supported",
                status="unverified_lead",
                source_document_ids=["project-rag"],
                provenance_valid=True,
            ),
            EvidencePrediction(
                requirement_id="req-frozen-k8s",
                semantic_status="unsupported",
                status="gap",
                source_document_ids=[],
                provenance_valid=True,
            ),
        ],
        source_caps={"project-rag": "C1"},
    )
    assert extraction.schema_validity == 1.0
    assert extraction.requirement_recall == 1.0
    assert extraction.duplicate_rate == 0.0
    assert extraction.irrelevant_rate is None
    assert extraction.completion_rate == 1.0
    assert evidence.completion_rate == 1.0
    assert evidence.semantic_status_accuracy == 1.0
    assert evidence.final_status_accuracy == 1.0
    assert evidence.status_accuracy == 1.0
    assert evidence.positive_source_correctness == 1.0
    assert evidence.false_support_rate == 0.0
    assert evidence.false_gap_rate == 0.0
    assert evidence.provenance_validity == 1.0


def test_extraction_matching_is_one_to_one(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    dataset = dataset.model_copy(
        update={
            "requirements": [
                dataset.requirements[0],
                dataset.requirements[1],
                dataset.requirements[2].model_copy(
                    update={
                        "raw_requirement_text": "Build RAG retrieval.",
                        "normalized_requirement": "build rag retrieval.",
                    }
                ),
            ]
        }
    )
    extraction = evaluate_requirement_extraction(
        dataset,
        [
            ExtractionPrediction(
                job_id="job-frozen",
                schema_valid=True,
                requirements=["Build RAG retrieval."],
            )
        ],
    )

    assert extraction.requirement_recall == 0.5


def test_extraction_coverage_accepts_model_selected_exact_source_quote(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    extraction = evaluate_requirement_extraction(
        dataset,
        [
            ExtractionPrediction(
                job_id="job-frozen",
                schema_valid=True,
                requirements=["semantic summary", "infra experience"],
                source_quotes=[
                    "Build RAG retrieval.",
                    "Kubernetes production experience.",
                ],
            )
        ],
    )

    assert extraction.requirement_recall == 1.0


def test_missing_evidence_predictions_count_against_full_gold(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    evidence = evaluate_evidence(dataset, [])

    assert evidence.requirement_count == 2
    assert evidence.completed_count == 0
    assert evidence.completion_rate == 0.0
    assert evidence.semantic_status_accuracy == 0.0
    assert evidence.final_status_accuracy == 0.0
    assert evidence.status_accuracy == 0.0
    assert evidence.positive_source_correctness == 0.0
    assert evidence.false_support_rate == 0.0
    assert evidence.false_gap_rate == 0.0
    assert evidence.provenance_validity == 0.0
