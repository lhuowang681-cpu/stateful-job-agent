from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalEvalCase:
    query: str
    relevant_ids: set[str]


@dataclass(frozen=True)
class RetrievalEvalMetrics:
    recall_at_k: float
    precision_at_k: float
    mrr: float
    
def evaluate_rankings(
    rankings: Sequence[Sequence[str]],
    cases: Sequence[RetrievalEvalCase],
    k: int,
) -> RetrievalEvalMetrics:
    if len(rankings) != len(cases):
        raise ValueError("rankings and cases must have the same length")

    if not cases:
        raise ValueError("cases must not be empty")

    recalls: list[float] = []
    precisions: list[float] = []
    reciprocal_ranks: list[float] = []

    for retrieved_ids, case in zip(rankings, cases):
        recalls.append(
            recall_at_k(
                retrieved_ids,
                case.relevant_ids,
                k,
            )
        )

        precisions.append(
            precision_at_k(
                retrieved_ids,
                case.relevant_ids,
                k,
            )
        )

        reciprocal_ranks.append(
            reciprocal_rank(
                retrieved_ids,
                case.relevant_ids,
            )
        )

    return RetrievalEvalMetrics(
        recall_at_k=sum(recalls) / len(recalls),
        precision_at_k=sum(precisions) / len(precisions),
        mrr=sum(reciprocal_ranks) / len(reciprocal_ranks),
    )


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")

    top_k = retrieved_ids[:k]

    hit_count = 0

    for chunk_id in top_k:
        if chunk_id in relevant_ids:
            hit_count += 1

    return hit_count / len(relevant_ids)


def precision_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    
    top_k = retrieved_ids[:k]
    
    if not top_k:
        return 0.0
    
    hit_count = 0
    
    for chunk_id in top_k:
        if chunk_id in relevant_ids:
            hit_count += 1
    
    return hit_count / len(top_k)


def reciprocal_rank(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
) -> float:
    for rank, chunk_id in enumerate(
        retrieved_ids,
        start=1,
    ):
        if chunk_id in relevant_ids:
            return 1.0 / rank

    return 0.0