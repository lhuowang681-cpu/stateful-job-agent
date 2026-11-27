from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Sequence

from job_agent.knowledge.contracts import KnowledgeChunk, RetrievedChunk


@dataclass
class _FusionCandidate:
    chunk: KnowledgeChunk
    score: float = 0.0
    metadata: dict[str, float | int] = field(default_factory=dict)


def reciprocal_rank_fusion(
    *,
    dense_results: Sequence[RetrievedChunk],
    bm25_results: Sequence[RetrievedChunk],
    limit: int,
    k: int = 60,
    dense_weight: float = 1.0,
    bm25_weight: float = 1.0,
) -> list[RetrievedChunk]:
    if k <= 0:
        raise ValueError("k must be greater than zero")
    if any(isinstance(w,bool) or not isinstance(w,(int,float)) or not math.isfinite(w) or not 0<w<=4
           for w in (dense_weight,bm25_weight)):
        raise ValueError('rrf_weight_invalid')
    if limit <= 0:
        return []

    candidates: dict[str, _FusionCandidate] = {}

    for source, results in (
        ("dense", dense_results),
        ("bm25", bm25_results),
    ):
        seen_chunk_ids: set[str] = set()
        for result in results:
            chunk_id = result.chunk.chunk_id
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)

            if source == "bm25" and result.score <= 0.0:
                continue

            candidate = candidates.get(chunk_id)
            if candidate is None:
                candidate = _FusionCandidate(chunk=result.chunk)
                candidates[chunk_id] = candidate

            weight=dense_weight if source=='dense' else bm25_weight
            candidate.score += weight / (k + result.rank)
            candidate.metadata[f"{source}_rank"] = result.rank
            candidate.metadata[f"{source}_score"] = result.score

    ranked_candidates = sorted(
        candidates.values(),
        key=lambda candidate: (-candidate.score, candidate.chunk.chunk_id),
    )[:limit]

    return [
        RetrievedChunk(
            chunk=candidate.chunk,
            score=candidate.score,
            rank=rank,
            retrieval_method="rrf",
            retrieval_metadata=candidate.metadata,
        )
        for rank, candidate in enumerate(ranked_candidates, start=1)
    ]
