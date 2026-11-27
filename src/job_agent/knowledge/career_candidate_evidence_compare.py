from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from job_agent.knowledge.candidate_evidence import CandidateEvidenceRetriever
from job_agent.knowledge.career_benchmark import (
    CareerBenchmarkDataset,
    CareerBenchmarkMetrics,
    ingest_benchmark_documents,
    load_career_benchmark,
    resolve_relevant_chunk_ids,
)
from job_agent.knowledge.contracts import EmbeddingBackend, VectorIndex
from job_agent.knowledge.eval import RetrievalEvalCase, evaluate_rankings
from job_agent.knowledge.ingestion import create_knowledge_document
from job_agent.knowledge.retriever import KnowledgeRetriever


@dataclass(frozen=True)
class CandidateEvidenceCaseComparison:
    case_id: str
    category: str
    expected_document_ids: tuple[str, ...]
    global_rank: int | None
    candidate_rank: int | None


@dataclass(frozen=True)
class CandidateEvidenceGapResult:
    case_id: str
    global_document_ids: tuple[str, ...]
    candidate_document_ids: tuple[str, ...]


@dataclass(frozen=True)
class CandidateEvidenceComparisonReport:
    global_metrics: CareerBenchmarkMetrics
    candidate_metrics: CareerBenchmarkMetrics
    global_requirement_metrics: CareerBenchmarkMetrics
    candidate_requirement_metrics: CareerBenchmarkMetrics
    candidate_document_ids: tuple[str, ...]
    positive_cases: tuple[CandidateEvidenceCaseComparison, ...]
    gap_cases: tuple[CandidateEvidenceGapResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_candidate_evidence_comparison(
    dataset: CareerBenchmarkDataset,
    *,
    embedding_backend: EmbeddingBackend,
    global_vector_index: VectorIndex,
    candidate_vector_index: VectorIndex,
    top_k: int = 5,
    max_chars: int = 2000,
) -> CandidateEvidenceComparisonReport:
    if top_k < 5:
        raise ValueError("top_k must be at least 5")

    chunks_by_document = ingest_benchmark_documents(
        dataset,
        embedding_backend=embedding_backend,
        vector_index=global_vector_index,
        max_chars=max_chars,
    )
    global_retriever = KnowledgeRetriever(
        embedding_backend=embedding_backend,
        vector_index=global_vector_index,
    )
    knowledge_documents = tuple(
        create_knowledge_document(
            document_id=document.document_id,
            source_type=document.source_type,
            text=document.text,
            version=1,
            title=document.title,
            source_uri=document.source_uri,
            metadata={
                "material_kind": document.material_kind,
                "fixture_path": document.fixture_path,
                "source_uri": document.source_uri,
            },
        )
        for document in dataset.documents
    )
    candidate_retriever = CandidateEvidenceRetriever.from_documents(
        knowledge_documents,
        embedding_backend=embedding_backend,
        vector_index=candidate_vector_index,
        max_chars=max_chars,
    )

    all_eval_cases: list[RetrievalEvalCase] = []
    global_rankings: list[list[str]] = []
    candidate_rankings: list[list[str]] = []
    requirement_eval_cases: list[RetrievalEvalCase] = []
    global_requirement_rankings: list[list[str]] = []
    candidate_requirement_rankings: list[list[str]] = []
    positive_cases: list[CandidateEvidenceCaseComparison] = []
    gap_cases: list[CandidateEvidenceGapResult] = []

    for case in dataset.cases:
        global_hits = global_retriever.retrieve(query=case.query, limit=top_k)
        candidate_hits = candidate_retriever.retrieve(
            query=case.query,
            limit=top_k,
        )
        global_ranking = [hit.chunk.chunk_id for hit in global_hits]
        candidate_ranking = [hit.chunk.chunk_id for hit in candidate_hits]
        relevant_ids = resolve_relevant_chunk_ids(case, chunks_by_document)

        if not relevant_ids:
            gap_cases.append(
                CandidateEvidenceGapResult(
                    case_id=case.case_id,
                    global_document_ids=tuple(
                        hit.chunk.document_id for hit in global_hits[:3]
                    ),
                    candidate_document_ids=tuple(
                        hit.chunk.document_id for hit in candidate_hits[:3]
                    ),
                )
            )
            continue

        eval_case = RetrievalEvalCase(
            query=case.query,
            relevant_ids=relevant_ids,
        )
        all_eval_cases.append(eval_case)
        global_rankings.append(global_ranking)
        candidate_rankings.append(candidate_ranking)

        if case.category == "requirement":
            requirement_eval_cases.append(eval_case)
            global_requirement_rankings.append(global_ranking)
            candidate_requirement_rankings.append(candidate_ranking)

        positive_cases.append(
            CandidateEvidenceCaseComparison(
                case_id=case.case_id,
                category=case.category,
                expected_document_ids=case.expected_document_ids,
                global_rank=_first_relevant_rank(global_ranking, relevant_ids),
                candidate_rank=_first_relevant_rank(
                    candidate_ranking,
                    relevant_ids,
                ),
            )
        )

    return CandidateEvidenceComparisonReport(
        global_metrics=_evaluate(global_rankings, all_eval_cases),
        candidate_metrics=_evaluate(candidate_rankings, all_eval_cases),
        global_requirement_metrics=_evaluate(
            global_requirement_rankings,
            requirement_eval_cases,
        ),
        candidate_requirement_metrics=_evaluate(
            candidate_requirement_rankings,
            requirement_eval_cases,
        ),
        candidate_document_ids=tuple(
            document.document_id
            for document in dataset.documents
            if document.document_id in candidate_retriever.indexed_document_ids
        ),
        positive_cases=tuple(positive_cases),
        gap_cases=tuple(gap_cases),
    )


def _evaluate(
    rankings: Sequence[Sequence[str]],
    cases: Sequence[RetrievalEvalCase],
) -> CareerBenchmarkMetrics:
    recall_1 = evaluate_rankings(rankings, cases, k=1)
    recall_3 = evaluate_rankings(rankings, cases, k=3)
    recall_5 = evaluate_rankings(rankings, cases, k=5)
    return CareerBenchmarkMetrics(
        recall_at_1=recall_1.recall_at_k,
        recall_at_3=recall_3.recall_at_k,
        recall_at_5=recall_5.recall_at_k,
        mrr=recall_5.mrr,
    )


def _first_relevant_rank(
    ranking: Sequence[str],
    relevant_ids: set[str],
) -> int | None:
    return next(
        (
            rank
            for rank, chunk_id in enumerate(ranking, start=1)
            if chunk_id in relevant_ids
        ),
        None,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        default="tests/fixtures/career_retrieval",
    )
    parser.add_argument(
        "--model-path",
        default=os.environ.get("QWEN_EMBEDDING_MODEL_PATH"),
    )
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if not args.model_path:
        raise SystemExit("QWEN_EMBEDDING_MODEL_PATH or --model-path is required")

    from job_agent.knowledge.faiss_vector_index import FAISSVectorIndex
    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    report = run_candidate_evidence_comparison(
        load_career_benchmark(args.fixture_root),
        embedding_backend=QwenEmbeddingBackend(
            model_path=args.model_path,
            device=args.device,
        ),
        global_vector_index=FAISSVectorIndex(),
        candidate_vector_index=FAISSVectorIndex(),
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
