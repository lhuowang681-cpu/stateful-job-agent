from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import Field, model_validator

from job_agent.jd_match_analysis import JobMatchAnalysis
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.contracts import KnowledgeDocument
from job_agent.schemas import StrictModel


EvidenceGoldStatus = Literal["supported", "partial", "gap"]
DatasetSplit = Literal["dev", "frozen"]


class RealJDRecord(StrictModel):
    job_id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str
    employment_type: str = Field(min_length=1)
    source: str = Field(min_length=1)
    captured_at: str = Field(min_length=1)
    raw_jd_text: str = Field(min_length=1)
    split: DatasetSplit


class RequirementGoldRecord(StrictModel):
    requirement_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    split: DatasetSplit
    raw_requirement_text: str = Field(min_length=1)
    normalized_requirement: str = Field(min_length=1)
    category: str = Field(min_length=1)
    expected_evidence_status: EvidenceGoldStatus
    expected_source_documents: list[str] = Field(default_factory=list)
    notes: str = Field(min_length=1)
    label_provenance: str = Field(min_length=1)
    is_major: bool = True

    @model_validator(mode="after")
    def validate_sources(self) -> "RequirementGoldRecord":
        if self.expected_evidence_status == "gap" and self.expected_source_documents:
            raise ValueError("gap requirement cannot declare expected sources")
        if self.expected_evidence_status != "gap" and not self.expected_source_documents:
            raise ValueError("positive requirement must declare expected sources")
        return self


class RealCareerDataset(StrictModel):
    dataset_version: str = Field(min_length=1)
    jobs: list[RealJDRecord] = Field(min_length=1)
    requirements: list[RequirementGoldRecord] = Field(min_length=1)


class LeakageAuditResult(StrictModel):
    passed: bool
    checks: dict[str, bool]
    errors: list[str] = Field(default_factory=list)


class RetrievalBucketMetrics(StrictModel):
    query_count: int = Field(ge=0)
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    source_correctness: float = Field(ge=0.0, le=1.0)
    active_version_correctness: float = Field(ge=0.0, le=1.0)


class RetrievalEvaluation(StrictModel):
    overall: RetrievalBucketMetrics
    by_category: dict[str, RetrievalBucketMetrics]
    rankings: dict[str, list[str]]
    bad_cases: list[dict[str, str]] = Field(default_factory=list)


class ExtractionPrediction(StrictModel):
    job_id: str
    schema_valid: bool
    requirements: list[str] = Field(default_factory=list)
    source_quotes: list[str] = Field(default_factory=list)
    error: str | None = None


class RequirementExtractionMetrics(StrictModel):
    job_count: int = Field(ge=0)
    schema_validity: float = Field(ge=0.0, le=1.0)
    completion_rate: float = Field(ge=0.0, le=1.0)
    non_empty_rate: float = Field(ge=0.0, le=1.0)
    requirement_recall: float = Field(ge=0.0, le=1.0)
    major_requirement_coverage: float = Field(ge=0.0, le=1.0)
    duplicate_rate: float = Field(ge=0.0, le=1.0)
    irrelevant_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidencePrediction(StrictModel):
    requirement_id: str
    semantic_status: Literal["supported", "partial", "unsupported"]
    status: Literal["supported", "partial", "unverified_lead", "unsupported", "gap"]
    source_document_ids: list[str] = Field(default_factory=list)
    provenance_valid: bool


class EvidenceEvaluationMetrics(StrictModel):
    requirement_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    completion_rate: float = Field(ge=0.0, le=1.0)
    semantic_status_accuracy: float = Field(ge=0.0, le=1.0)
    final_status_accuracy: float = Field(ge=0.0, le=1.0)
    status_accuracy: float = Field(ge=0.0, le=1.0)
    positive_source_correctness: float = Field(ge=0.0, le=1.0)
    false_support_rate: float = Field(ge=0.0, le=1.0)
    false_gap_rate: float = Field(ge=0.0, le=1.0)
    provenance_validity: float = Field(ge=0.0, le=1.0)


class JobComparison(StrictModel):
    common_strengths: list[str]
    job_a_specific_gaps: list[str]
    job_b_specific_gaps: list[str]
    preference_differences: dict[str, tuple[bool | None, bool | None]]


def load_real_career_dataset(
    *,
    jobs_path: str | Path,
    requirements_path: str | Path,
    dataset_version: str = "real-career-v1",
) -> RealCareerDataset:
    return RealCareerDataset(
        dataset_version=dataset_version,
        jobs=[RealJDRecord.model_validate(item) for item in _read_jsonl(jobs_path)],
        requirements=[
            RequirementGoldRecord.model_validate(item)
            for item in _read_jsonl(requirements_path)
        ],
    )


def audit_real_career_dataset(
    dataset: RealCareerDataset,
    *,
    candidate_documents: Sequence[KnowledgeDocument],
) -> LeakageAuditResult:
    errors: list[str] = []
    job_ids = [item.job_id for item in dataset.jobs]
    requirement_ids = [item.requirement_id for item in dataset.requirements]
    jobs_by_id = {item.job_id: item for item in dataset.jobs}
    candidate_ids = {item.document_id for item in candidate_documents}

    checks = {
        "unique_job_ids": len(job_ids) == len(set(job_ids)),
        "unique_requirement_ids": len(requirement_ids) == len(set(requirement_ids)),
        "grouped_job_split": True,
        "jd_candidate_isolation": True,
        "expected_sources_are_curated": True,
        "expected_sources_exist": True,
        "no_synthetic_real_records": True,
    }
    for requirement in dataset.requirements:
        job = jobs_by_id.get(requirement.job_id)
        if job is None or job.split != requirement.split:
            checks["grouped_job_split"] = False
        if "model" in requirement.label_provenance.casefold() and "not_model" not in requirement.label_provenance.casefold():
            checks["expected_sources_are_curated"] = False
        if "retrieval_generated" in requirement.label_provenance.casefold() and "not_model_or_retrieval_generated" not in requirement.label_provenance.casefold():
            checks["expected_sources_are_curated"] = False
        if set(requirement.expected_source_documents) - candidate_ids:
            checks["expected_sources_exist"] = False
    if set(job_ids) & candidate_ids:
        checks["jd_candidate_isolation"] = False
    if any(
        item.source_type in {"job_description", "external_knowledge"}
        for item in candidate_documents
    ):
        checks["jd_candidate_isolation"] = False
    if any(
        "synthetic" in item.source.casefold() or "fixture" in item.source.casefold()
        for item in dataset.jobs
    ):
        checks["no_synthetic_real_records"] = False
    for name, passed in checks.items():
        if not passed:
            errors.append(name)
    return LeakageAuditResult(passed=all(checks.values()), checks=checks, errors=errors)


def evaluate_retrieval(
    dataset: RealCareerDataset,
    *,
    service: CareerKnowledgeService,
    active_versions: Mapping[str, int],
    split: DatasetSplit = "frozen",
    top_k: int = 5,
) -> RetrievalEvaluation:
    records: list[tuple[RequirementGoldRecord, int | None, list[str], bool]] = []
    rankings: dict[str, list[str]] = {}
    bad_cases: list[dict[str, str]] = []
    for requirement in dataset.requirements:
        if requirement.split != split or requirement.expected_evidence_status == "gap":
            continue
        hits = service.query_candidate_evidence(requirement.raw_requirement_text, top_k)
        ranking = [item.chunk.document_id for item in hits]
        rankings[requirement.requirement_id] = ranking
        expected = set(requirement.expected_source_documents)
        rank = next(
            (item.rank for item in hits if item.chunk.document_id in expected),
            None,
        )
        active_correct = all(
            item.chunk.document_version == active_versions.get(item.chunk.document_id)
            for item in hits
        )
        records.append((requirement, rank, ranking, active_correct))
        if rank is None:
            bad_cases.append(
                {
                    "case": requirement.requirement_id,
                    "layer": "RETRIEVAL_RANKING",
                    "observation": f"expected={sorted(expected)} actual={ranking}",
                }
            )

    by_category_records: dict[str, list[tuple[RequirementGoldRecord, int | None, list[str], bool]]] = defaultdict(list)
    for item in records:
        by_category_records[item[0].category].append(item)
    return RetrievalEvaluation(
        overall=_retrieval_bucket(records),
        by_category={
            category: _retrieval_bucket(items)
            for category, items in sorted(by_category_records.items())
        },
        rankings=rankings,
        bad_cases=bad_cases,
    )


def evaluate_requirement_extraction(
    dataset: RealCareerDataset,
    predictions: Sequence[ExtractionPrediction],
    *,
    split: DatasetSplit = "frozen",
    gold_exhaustive: bool = False,
) -> RequirementExtractionMetrics:
    jobs = [item for item in dataset.jobs if item.split == split]
    gold_by_job: dict[str, list[RequirementGoldRecord]] = defaultdict(list)
    for item in dataset.requirements:
        if item.split == split:
            gold_by_job[item.job_id].append(item)
    predicted_by_job = {item.job_id: item for item in predictions}
    schema_valid = 0
    non_empty = 0
    gold_total = 0
    gold_matched = 0
    major_total = 0
    major_matched = 0
    extracted_total = 0
    duplicates = 0
    irrelevant = 0
    for job in jobs:
        prediction = predicted_by_job.get(
            job.job_id,
            ExtractionPrediction(job_id=job.job_id, schema_valid=False),
        )
        schema_valid += prediction.schema_valid
        non_empty += bool(prediction.requirements)
        normalized_predictions = [_normalize(item) for item in prediction.requirements]
        extracted_total += len(normalized_predictions)
        duplicates += len(normalized_predictions) - len(set(normalized_predictions))
        gold = gold_by_job[job.job_id]
        gold_total += len(gold)
        major_total += sum(item.is_major for item in gold)
        matched_prediction_indexes: set[int] = set()
        for item in gold:
            match = next(
                (
                    index
                    for index, candidate in enumerate(prediction.requirements)
                    if index not in matched_prediction_indexes
                    if requirement_matches(item.raw_requirement_text, candidate)
                    or (
                        index < len(prediction.source_quotes)
                        and requirement_matches(
                            item.raw_requirement_text,
                            prediction.source_quotes[index],
                        )
                    )
                ),
                None,
            )
            if match is not None:
                gold_matched += 1
                major_matched += item.is_major
                matched_prediction_indexes.add(match)
        irrelevant += len(prediction.requirements) - len(matched_prediction_indexes)
    count = len(jobs)
    return RequirementExtractionMetrics(
        job_count=count,
        schema_validity=schema_valid / count if count else 0.0,
        completion_rate=non_empty / count if count else 0.0,
        non_empty_rate=non_empty / count if count else 0.0,
        requirement_recall=gold_matched / gold_total if gold_total else 0.0,
        major_requirement_coverage=major_matched / major_total if major_total else 0.0,
        duplicate_rate=duplicates / extracted_total if extracted_total else 0.0,
        irrelevant_rate=(
            irrelevant / extracted_total
            if gold_exhaustive and extracted_total
            else 0.0
            if gold_exhaustive
            else None
        ),
    )


def evaluate_evidence(
    dataset: RealCareerDataset,
    predictions: Sequence[EvidencePrediction],
    *,
    split: DatasetSplit = "frozen",
    source_caps: Mapping[str, str] | None = None,
) -> EvidenceEvaluationMetrics:
    gold = {
        item.requirement_id: item
        for item in dataset.requirements
        if item.split == split
    }
    predicted = {item.requirement_id: item for item in predictions}
    semantic_correct = 0
    final_correct = 0
    completed = 0
    completed_positive = 0
    completed_gap = 0
    positive_source_correct = 0
    false_support = 0
    false_gap = 0
    provenance_valid = 0
    for requirement_id, item in gold.items():
        prediction = predicted.get(requirement_id)
        if prediction is None:
            continue
        completed += 1
        semantic_status = _semantic_status_class(prediction.semantic_status)
        final_status = _status_class(prediction.status)
        expected_final = _expected_final_status(item, source_caps or {})
        semantic_correct += semantic_status == item.expected_evidence_status
        final_correct += final_status == expected_final
        provenance_valid += prediction.provenance_valid
        if item.expected_evidence_status != "gap":
            completed_positive += 1
            positive_source_correct += bool(
                set(prediction.source_document_ids)
                & set(item.expected_source_documents)
            )
            false_gap += semantic_status == "gap"
        else:
            completed_gap += 1
            false_support += semantic_status != "gap"
    total = len(gold)
    return EvidenceEvaluationMetrics(
        requirement_count=total,
        completed_count=completed,
        completion_rate=completed / total if total else 0.0,
        semantic_status_accuracy=(
            semantic_correct / completed if completed else 0.0
        ),
        final_status_accuracy=final_correct / completed if completed else 0.0,
        status_accuracy=final_correct / completed if completed else 0.0,
        positive_source_correctness=(
            positive_source_correct / completed_positive
            if completed_positive
            else 0.0
        ),
        false_support_rate=false_support / completed_gap if completed_gap else 0.0,
        false_gap_rate=false_gap / completed_positive if completed_positive else 0.0,
        provenance_validity=provenance_valid / completed if completed else 0.0,
    )


def compare_job_analyses(
    job_a: JobMatchAnalysis,
    job_b: JobMatchAnalysis,
) -> JobComparison:
    strengths_a = set(job_a.summary.evidence_backed_strengths if job_a.summary else ())
    strengths_b = set(job_b.summary.evidence_backed_strengths if job_b.summary else ())
    gaps_a = set(job_a.summary.gaps if job_a.summary else ())
    gaps_b = set(job_b.summary.gaps if job_b.summary else ())
    preference_differences: dict[str, tuple[bool | None, bool | None]] = {}
    if job_a.preference_analysis and job_b.preference_analysis:
        for left, right in zip(
            (
                job_a.preference_analysis.city,
                job_a.preference_analysis.role,
                job_a.preference_analysis.job_type,
            ),
            (
                job_b.preference_analysis.city,
                job_b.preference_analysis.role,
                job_b.preference_analysis.job_type,
            ),
        ):
            if left.fit != right.fit:
                preference_differences[left.dimension] = (left.fit, right.fit)
    return JobComparison(
        common_strengths=sorted(strengths_a & strengths_b),
        job_a_specific_gaps=sorted(gaps_a - gaps_b),
        job_b_specific_gaps=sorted(gaps_b - gaps_a),
        preference_differences=preference_differences,
    )


def dataset_summary(dataset: RealCareerDataset) -> dict[str, Any]:
    return {
        "dataset_version": dataset.dataset_version,
        "job_count": len(dataset.jobs),
        "requirement_count": len(dataset.requirements),
        "jobs_by_split": dict(Counter(item.split for item in dataset.jobs)),
        "requirements_by_split": dict(
            Counter(item.split for item in dataset.requirements)
        ),
        "jobs_by_company": dict(Counter(item.company for item in dataset.jobs)),
        "requirements_by_category": dict(
            Counter(item.category for item in dataset.requirements)
        ),
        "requirements_by_status": dict(
            Counter(item.expected_evidence_status for item in dataset.requirements)
        ),
    }


def _retrieval_bucket(
    records: Sequence[tuple[RequirementGoldRecord, int | None, list[str], bool]],
) -> RetrievalBucketMetrics:
    count = len(records)
    if not count:
        return RetrievalBucketMetrics(
            query_count=0,
            recall_at_1=0.0,
            recall_at_3=0.0,
            recall_at_5=0.0,
            mrr=0.0,
            source_correctness=0.0,
            active_version_correctness=0.0,
        )
    ranks = [item[1] for item in records]
    return RetrievalBucketMetrics(
        query_count=count,
        recall_at_1=sum(rank is not None and rank <= 1 for rank in ranks) / count,
        recall_at_3=sum(rank is not None and rank <= 3 for rank in ranks) / count,
        recall_at_5=sum(rank is not None and rank <= 5 for rank in ranks) / count,
        mrr=sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / count,
        source_correctness=sum(rank == 1 for rank in ranks) / count,
        active_version_correctness=sum(item[3] for item in records) / count,
    )


def requirement_matches(left: str, right: str) -> bool:
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return True
    left_tokens = set(_tokens(left_normalized))
    right_tokens = set(_tokens(right_normalized))
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return overlap >= 0.45 or SequenceMatcher(None, left_normalized, right_normalized).ratio() >= 0.68


def _tokens(value: str) -> Iterable[str]:
    return re.findall(r"[a-z0-9+#.-]+|[\u4e00-\u9fff]", value)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _status_class(value: str) -> EvidenceGoldStatus:
    if value == "supported":
        return "supported"
    if value in {"partial", "unverified_lead"}:
        return "partial"
    return "gap"


def _semantic_status_class(value: str) -> EvidenceGoldStatus:
    if value == "supported":
        return "supported"
    if value == "partial":
        return "partial"
    return "gap"


def _expected_final_status(
    requirement: RequirementGoldRecord,
    source_caps: Mapping[str, str],
) -> EvidenceGoldStatus:
    if requirement.expected_evidence_status != "supported":
        return requirement.expected_evidence_status
    expected_caps = {
        source_caps.get(document_id)
        for document_id in requirement.expected_source_documents
    }
    if expected_caps and expected_caps <= {"C0", "C1", "None", None}:
        return "partial"
    return "supported"


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]
