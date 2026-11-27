from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from job_agent.knowledge.bm25_index import BM25Index
from job_agent.knowledge.career_benchmark import (
    CareerBenchmarkDataset,
    CareerBenchmarkMetrics,
    load_career_benchmark,
    ingest_benchmark_documents,
    resolve_relevant_chunk_ids,
)
from job_agent.knowledge.contracts import (
    EmbeddingBackend,
    KnowledgeChunk,
    VectorIndex,
)
from job_agent.knowledge.eval import RetrievalEvalCase, evaluate_rankings
from job_agent.knowledge.hybrid_retriever import HybridRetriever
from job_agent.knowledge.retriever import KnowledgeRetriever


@dataclass(frozen=True)
class DenseBM25CaseComparison:
    case_id: str
    category: str
    expected_document_ids: tuple[str, ...]
    expected_chunk_ids: tuple[str, ...]
    dense_rank: int | None
    bm25_rank: int | None
    rrf_rank: int | None


@dataclass(frozen=True)
class GapHit:
    rank: int
    document_id: str
    score: float


@dataclass(frozen=True)
class GapResult:
    case_id: str
    query: str
    dense_top_results: tuple[GapHit, ...]
    bm25_effective_candidate_count: int
    hybrid_top_results: tuple[GapHit, ...]


@dataclass(frozen=True)
class DenseBM25ComparisonReport:
    dense_metrics: CareerBenchmarkMetrics
    bm25_metrics: CareerBenchmarkMetrics
    rrf_metrics: CareerBenchmarkMetrics
    positive_cases: tuple[DenseBM25CaseComparison, ...]
    gap_cases: tuple[GapResult, ...]
    bm25_rescues: tuple[str, ...]
    dense_rescues: tuple[str, ...]
    rrf_improvements: tuple[str, ...]
    semantic_regressions: tuple[str, ...]
    decision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_dense_bm25_comparison(
    dataset: CareerBenchmarkDataset,
    *,
    dense_embedding_backend: EmbeddingBackend,
    dense_vector_index: VectorIndex,
    top_k: int = 5,
    max_chars: int = 2000,
) -> DenseBM25ComparisonReport:
    if top_k < 5:
        raise ValueError("top_k must be at least 5")

    chunks_by_document = ingest_benchmark_documents(
        dataset,
        embedding_backend=dense_embedding_backend,
        vector_index=dense_vector_index,
        max_chars=max_chars,
    )
    shared_chunks = [
        chunk
        for document in dataset.documents
        for chunk in chunks_by_document[document.document_id]
    ]

    dense_retriever = KnowledgeRetriever(
        embedding_backend=dense_embedding_backend,
        vector_index=dense_vector_index,
    )
    bm25_index = BM25Index()
    bm25_index.add(shared_chunks)
    hybrid_retriever = HybridRetriever(
        dense_retriever=dense_retriever,
        sparse_retriever=bm25_index,
    )

    positive_cases: list[DenseBM25CaseComparison] = []
    eval_cases: list[RetrievalEvalCase] = []
    dense_rankings: list[list[str]] = []
    bm25_rankings: list[list[str]] = []
    rrf_rankings: list[list[str]] = []
    gap_cases: list[GapResult] = []

    for case in dataset.cases:
        dense_hits = dense_retriever.retrieve(
            query=case.query,
            limit=top_k,
        )
        bm25_candidates = bm25_index.search(
            query=case.query,
            limit=hybrid_retriever.candidate_depth,
        )
        bm25_hits = bm25_candidates[:top_k]
        rrf_hits = hybrid_retriever.retrieve(
            query=case.query,
            limit=top_k,
        )
        dense_ranking = [hit.chunk.chunk_id for hit in dense_hits]
        bm25_ranking = [hit.chunk.chunk_id for hit in bm25_hits]
        rrf_ranking = [hit.chunk.chunk_id for hit in rrf_hits]
        relevant_ids = resolve_relevant_chunk_ids(case, chunks_by_document)

        if not relevant_ids:
            gap_cases.append(
                GapResult(
                    case_id=case.case_id,
                    query=case.query,
                    dense_top_results=tuple(
                        GapHit(
                            rank=hit.rank,
                            document_id=hit.chunk.document_id,
                            score=hit.score,
                        )
                        for hit in dense_hits[:3]
                    ),
                    bm25_effective_candidate_count=sum(
                        hit.score > 0.0 for hit in bm25_candidates
                    ),
                    hybrid_top_results=tuple(
                        GapHit(
                            rank=hit.rank,
                            document_id=hit.chunk.document_id,
                            score=hit.score,
                        )
                        for hit in rrf_hits[:3]
                    ),
                )
            )
            continue

        eval_cases.append(
            RetrievalEvalCase(
                query=case.query,
                relevant_ids=relevant_ids,
            )
        )
        dense_rankings.append(dense_ranking)
        bm25_rankings.append(bm25_ranking)
        rrf_rankings.append(rrf_ranking)
        positive_cases.append(
            DenseBM25CaseComparison(
                case_id=case.case_id,
                category=case.category,
                expected_document_ids=case.expected_document_ids,
                expected_chunk_ids=tuple(sorted(relevant_ids)),
                dense_rank=_first_relevant_rank(
                    dense_ranking,
                    relevant_ids,
                ),
                bm25_rank=_first_relevant_rank(
                    bm25_ranking,
                    relevant_ids,
                ),
                rrf_rank=_first_relevant_rank(
                    rrf_ranking,
                    relevant_ids,
                ),
            )
        )

    dense_metrics = _evaluate(dense_rankings, eval_cases)
    bm25_metrics = _evaluate(bm25_rankings, eval_cases)
    rrf_metrics = _evaluate(rrf_rankings, eval_cases)
    bm25_rescues = tuple(
        case.case_id
        for case in positive_cases
        if _outside_top_3(case.dense_rank)
        and not _outside_top_3(case.bm25_rank)
    )
    dense_rescues = tuple(
        case.case_id
        for case in positive_cases
        if _outside_top_3(case.bm25_rank)
        and not _outside_top_3(case.dense_rank)
    )
    rrf_improvements = tuple(
        case.case_id
        for case in positive_cases
        if _is_better(case.rrf_rank, case.dense_rank)
    )
    semantic_regressions = tuple(
        case.case_id
        for case in positive_cases
        if case.category == "semantic"
        and _is_worse(case.rrf_rank, case.dense_rank)
    )
    exact_improvements = tuple(
        case.case_id
        for case in positive_cases
        if case.category in {"exact_term", "exact_entity"}
        and _is_better(case.rrf_rank, case.dense_rank)
    )
    keeps_dense_metrics = (
        rrf_metrics.recall_at_1 >= dense_metrics.recall_at_1
        and rrf_metrics.recall_at_3 >= dense_metrics.recall_at_3
        and rrf_metrics.recall_at_5 >= dense_metrics.recall_at_5
        and rrf_metrics.mrr >= dense_metrics.mrr
    )
    decision = (
        "KEEP HYBRID"
        if exact_improvements and keeps_dense_metrics
        else "DO NOT KEEP HYBRID"
    )

    return DenseBM25ComparisonReport(
        dense_metrics=dense_metrics,
        bm25_metrics=bm25_metrics,
        rrf_metrics=rrf_metrics,
        positive_cases=tuple(positive_cases),
        gap_cases=tuple(gap_cases),
        bm25_rescues=bm25_rescues,
        dense_rescues=dense_rescues,
        rrf_improvements=rrf_improvements,
        semantic_regressions=semantic_regressions,
        decision=decision,
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


def _outside_top_3(rank: int | None) -> bool:
    return rank is None or rank > 3


def _is_better(candidate_rank: int | None, baseline_rank: int | None) -> bool:
    if candidate_rank is None:
        return False
    return baseline_rank is None or candidate_rank < baseline_rank


def _is_worse(candidate_rank: int | None, baseline_rank: int | None) -> bool:
    if baseline_rank is None:
        return False
    return candidate_rank is None or candidate_rank > baseline_rank


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

    report = run_dense_bm25_comparison(
        load_career_benchmark(args.fixture_root),
        dense_embedding_backend=QwenEmbeddingBackend(
            model_path=args.model_path,
            device=args.device,
        ),
        dense_vector_index=FAISSVectorIndex(),
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
