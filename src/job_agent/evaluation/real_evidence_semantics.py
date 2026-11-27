from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal, Sequence

from job_agent.evaluation.real_career_data import (
    EvidencePrediction,
    RequirementGoldRecord,
    evaluate_evidence,
    load_real_career_dataset,
)
from job_agent.evaluation.real_career_runner import (
    DATASET_VERSION,
    _DiagnosticDeepSeekProvider,
    _source_cap,
)
from job_agent.evidence.contracts import RetrievedEvidenceMappingCandidate
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.durable import (
    CareerKnowledgeLifecycle,
    EmbeddingIdentity,
    KnowledgeRepository,
)
from job_agent.llm.harness import LLMHarness
from job_agent.llm.skill_registry import SkillSpec
from job_agent.requirement_evidence import RequirementEvidenceService


SemanticLabel = Literal["supported", "partial", "unsupported"]


class _EvidenceRegistry:
    def get(self, skill_id: str) -> SkillSpec:
        return SkillSpec(
            skill_id=skill_id,
            version="real-evidence-semantics-v1",
            instructions=(
                "Judge only whether retrieved candidate material explicitly "
                "supports the requirement. Return one JSON object matching the schema."
            ),
            reference_paths=(),
            output_schema=RetrievedEvidenceMappingCandidate,
        )


def run_real_evidence_semantics(
    *,
    jobs_path: str | Path,
    requirements_path: str | Path,
    state_root: str | Path,
    model_path: str,
    deepseek_api_key: str,
    split: Literal["dev", "frozen"],
    requirement_ids: set[str] | None = None,
    sample_size: int | None = None,
    run_label: str = "default",
    device: str = "cuda",
    top_k: int = 5,
) -> dict[str, Any]:
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    state = Path(state_root)
    repository = KnowledgeRepository(state / "knowledge.sqlite")
    embedding_identity = EmbeddingIdentity(
        provider="sentence-transformers",
        model="Qwen/Qwen3-Embedding-0.6B",
        dimension=1024,
    )
    lifecycle = CareerKnowledgeLifecycle(
        repository=repository,
        embedding_backend=QwenEmbeddingBackend(model_path, device=device),
        embedding_identity=embedding_identity,
        index_path=state / "career.faiss",
        manifest_path=state / "career-index-manifest.json",
        max_chars=2000,
    )
    retrieval = CareerKnowledgeService(
        lifecycle.candidate_retriever(),
        lifecycle=lifecycle,
    )
    documents = tuple(repository.list_active_documents())
    documents_by_id = {item.document_id: item for item in documents}
    source_caps = {item.document_id: _source_cap(item) for item in documents}
    dataset = load_real_career_dataset(
        jobs_path=jobs_path,
        requirements_path=requirements_path,
        dataset_version=DATASET_VERSION,
    )
    selected = [
        item
        for item in dataset.requirements
        if item.split == split
        and (requirement_ids is None or item.requirement_id in requirement_ids)
    ]
    if sample_size is not None:
        selected = _representative_sample(selected, sample_size)

    provider = _DiagnosticDeepSeekProvider(
        api_key=deepseek_api_key,
        timeout_s=120.0,
    )
    harness = LLMHarness(provider)
    evidence_service = RequirementEvidenceService(
        candidate_retriever=None,
        candidate_documents=documents,
        registry=_EvidenceRegistry(),
        harness=harness,
        session_dir=state / f"r10-{split}-evidence-{run_label}",
    )
    predictions: list[EvidencePrediction] = []
    cases: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for gold in selected:
        diagnostic_start = len(provider.diagnostics)
        hits = retrieval.query_candidate_evidence(gold.raw_requirement_text, top_k)
        case: dict[str, Any] = {
            "requirement_id": gold.requirement_id,
            "job_id": gold.job_id,
            "requirement": gold.raw_requirement_text,
            "category": gold.category,
            "gold_status": gold.expected_evidence_status,
            "gold_sources": gold.expected_source_documents,
            "top3": [_hit_record(item) for item in hits[:3]],
        }
        try:
            result = evidence_service.assess_retrieved(
                requirement=gold.raw_requirement_text,
                retrieved_chunks=hits,
                run_id=f"r10-{split}-{run_label}-{gold.requirement_id}",
                session_id=f"r10-{split}",
                atom_id=gold.requirement_id,
                parent_requirement_id=f"{gold.requirement_id}-parent",
            )
            selected_sources = [item.document_id for item in result.evidence_items]
            quotes = [
                item.evidence_link.source_span.exact_quote
                for item in result.evidence_items
            ]
            provenance_valid = _provenance_valid(result.evidence_items, documents_by_id)
            quote_valid = _quote_valid(result.evidence_items, hits)
            prediction = EvidencePrediction(
                requirement_id=gold.requirement_id,
                semantic_status=result.semantic_support,
                status=result.status,
                source_document_ids=selected_sources,
                provenance_valid=provenance_valid,
            )
            predictions.append(prediction)
            case.update(
                {
                    "completed": True,
                    "semantic_judgment": result.semantic_support,
                    "selected_sources": selected_sources,
                    "exact_quotes": quotes,
                    "final_status": result.status,
                    "quote_valid": quote_valid,
                    "provenance_valid": provenance_valid,
                    "source_cap_compliant": _source_cap_compliant(
                        result.semantic_support,
                        result.status,
                        result.evidence_items,
                        source_caps,
                    ),
                }
            )
        except Exception as exc:
            case.update(
                {
                    "completed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            failures.append(
                {
                    "requirement_id": gold.requirement_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        case["model_attempts"] = [
            {
                "json_extraction_result": item.get("json_extraction_result"),
                "schema_valid": item.get("schema_valid"),
                "validation_error": item.get("validation_error"),
            }
            for item in provider.diagnostics[diagnostic_start:]
        ]
        cases.append(case)

    metrics = evaluate_evidence(
        dataset.model_copy(update={"requirements": selected}),
        predictions,
        split=split,
        source_caps=source_caps,
    )
    detailed = _detailed_metrics(selected, predictions, cases)
    traces = harness.traces
    return {
        "split": split,
        "requirement_count": len(selected),
        "metrics": metrics.model_dump(mode="json"),
        "detailed_metrics": detailed,
        "cases": cases,
        "failures": failures,
        "api": {
            "provider": "deepseek",
            "calls": len(traces),
            "input_tokens": sum(item.input_tokens or 0 for item in traces),
            "output_tokens": sum(item.output_tokens or 0 for item in traces),
            "schema_valid_calls": sum(item.schema_valid for item in traces),
        },
    }


def _hit_record(hit: Any) -> dict[str, Any]:
    return {
        "chunk_id": hit.chunk.chunk_id,
        "document_id": hit.chunk.document_id,
        "rank": hit.rank,
        "score": hit.score,
        "text": hit.chunk.text,
    }


def _representative_sample(
    items: Sequence[RequirementGoldRecord],
    size: int,
) -> list[RequirementGoldRecord]:
    if size < 1:
        raise ValueError("sample_size must be positive")
    groups: dict[tuple[str, str], list[RequirementGoldRecord]] = {}
    for item in sorted(items, key=lambda value: value.requirement_id):
        groups.setdefault((item.expected_evidence_status, item.category), []).append(item)
    selected: list[RequirementGoldRecord] = []
    keys = sorted(groups)
    while len(selected) < min(size, len(items)):
        progressed = False
        for key in keys:
            if groups[key] and len(selected) < size:
                selected.append(groups[key].pop(0))
                progressed = True
        if not progressed:
            break
    return selected


def _provenance_valid(items: Sequence[Any], documents: dict[str, Any]) -> bool:
    for item in items:
        document = documents.get(item.document_id)
        if document is None:
            return False
        span = item.evidence_link.source_span
        if span.content_hash != document.content_hash:
            return False
        if document.text[span.start_offset : span.end_offset] != span.exact_quote:
            return False
    return True


def _quote_valid(items: Sequence[Any], hits: Sequence[Any]) -> bool:
    chunks = {item.chunk.chunk_id: item.chunk for item in hits}
    for item in items:
        chunk = chunks.get(item.chunk_id)
        quote = item.evidence_link.source_span.exact_quote
        if chunk is None or chunk.text.count(quote) != 1:
            return False
    return True


def _source_cap_compliant(
    semantic_support: str,
    final_status: str,
    items: Sequence[Any],
    source_caps: dict[str, str],
) -> bool:
    if semantic_support == "unsupported":
        return final_status == "gap" and not items
    if len(items) != 1:
        return False
    item = items[0]
    cap = source_caps.get(item.document_id)
    if item.evidence_link.level.value != cap:
        return False
    if cap in {"C0", "C1", None}:
        return final_status == "unverified_lead"
    return final_status == semantic_support


def _detailed_metrics(
    gold_items: Sequence[RequirementGoldRecord],
    predictions: Sequence[EvidencePrediction],
    cases: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    predicted = {item.requirement_id: item for item in predictions}
    labels: tuple[SemanticLabel, ...] = ("supported", "partial", "unsupported")
    matrix = {gold: {pred: 0 for pred in labels} for gold in labels}
    false_support = 0
    false_gap = 0
    positive_source_correct = 0
    positives = 0
    for gold in gold_items:
        prediction = predicted.get(gold.requirement_id)
        if prediction is None:
            continue
        gold_label: SemanticLabel = (
            "unsupported"
            if gold.expected_evidence_status == "gap"
            else gold.expected_evidence_status
        )
        pred_label: SemanticLabel = prediction.semantic_status
        matrix[gold_label][pred_label] += 1
        if gold_label == "unsupported":
            false_support += pred_label != "unsupported"
        else:
            positives += 1
            false_gap += pred_label == "unsupported"
            positive_source_correct += bool(
                set(prediction.source_document_ids) & set(gold.expected_source_documents)
            )
    per_class: dict[str, dict[str, float | int]] = {}
    for label in labels:
        true_positive = matrix[label][label]
        predicted_count = sum(matrix[gold][label] for gold in labels)
        gold_count = sum(matrix[label].values())
        per_class[label] = {
            "true_positive": true_positive,
            "predicted": predicted_count,
            "gold": gold_count,
            "precision": true_positive / predicted_count if predicted_count else 0.0,
            "recall": true_positive / gold_count if gold_count else 0.0,
        }
    completed_cases = [item for item in cases if item.get("completed")]
    return {
        "confusion_matrix": matrix,
        "per_class": per_class,
        "false_support": {
            "count": false_support,
            "gold_gaps": sum(matrix["unsupported"].values()),
        },
        "false_gap": {"count": false_gap, "gold_positives": positives},
        "positive_source_correct": {
            "count": positive_source_correct,
            "gold_positives": positives,
        },
        "quote_validity": {
            "count": sum(bool(item.get("quote_valid")) for item in completed_cases),
            "completed": len(completed_cases),
        },
        "source_cap_compliance": {
            "count": sum(
                bool(item.get("source_cap_compliant")) for item in completed_cases
            ),
            "completed": len(completed_cases),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument(
        "--model-path", default=os.environ.get("QWEN_EMBEDDING_MODEL_PATH")
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--split", choices=("dev", "frozen"), required=True)
    parser.add_argument("--requirement-id", action="append", default=[])
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--run-label", default="default")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required")
    if not args.model_path:
        raise SystemExit("QWEN_EMBEDDING_MODEL_PATH or --model-path is required")
    report = run_real_evidence_semantics(
        jobs_path=args.jobs,
        requirements_path=args.requirements,
        state_root=args.state_root,
        model_path=args.model_path,
        deepseek_api_key=api_key,
        split=args.split,
        requirement_ids=set(args.requirement_id) or None,
        sample_size=args.sample_size,
        run_label=args.run_label,
        device=args.device,
        top_k=args.top_k,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "cases"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
