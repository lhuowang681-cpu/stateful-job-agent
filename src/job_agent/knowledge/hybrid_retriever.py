from __future__ import annotations

from typing import Protocol

from job_agent.knowledge.contracts import RetrievedChunk
from job_agent.knowledge.rrf import reciprocal_rank_fusion


class DenseRetriever(Protocol):
    def retrieve(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        ...


class SparseRetriever(Protocol):
    def search(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        ...


class HybridRetriever:
    def __init__(
        self,
        *,
        dense_retriever: DenseRetriever,
        sparse_retriever: SparseRetriever,
        candidate_depth: int = 10,
        rrf_k: int = 60,
    ) -> None:
        if candidate_depth <= 0:
            raise ValueError("candidate_depth must be greater than zero")
        if rrf_k <= 0:
            raise ValueError("rrf_k must be greater than zero")

        self.dense_retriever = dense_retriever
        self.sparse_retriever = sparse_retriever
        self.candidate_depth = candidate_depth
        self.rrf_k = rrf_k

    def retrieve(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        if limit <= 0:
            return []

        dense_results = self.dense_retriever.retrieve(
            query=query,
            limit=self.candidate_depth,
        )
        bm25_results = self.sparse_retriever.search(
            query=query,
            limit=self.candidate_depth,
        )
        return reciprocal_rank_fusion(
            dense_results=dense_results,
            bm25_results=bm25_results,
            limit=limit,
            k=self.rrf_k,
        )
