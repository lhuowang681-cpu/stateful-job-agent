from __future__ import annotations

from pathlib import Path
from typing import Sequence

import faiss
import numpy as np

from job_agent.knowledge.contracts import KnowledgeChunk, RetrievedChunk


class FAISSVectorIndex:
    def __init__(self, dimension: int | None = None) -> None:
        if dimension is not None and dimension < 1:
            raise ValueError("dimension must be positive")
        self._index: faiss.Index | None = (
            faiss.IndexFlatIP(dimension) if dimension is not None else None
        )
        self._chunks: list[KnowledgeChunk] = []
        self._dimension = dimension

    @property
    def dimension(self) -> int | None:
        return self._dimension

    @property
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return tuple(self._chunks)

    def save(self, path: str | Path) -> None:
        if self._index is None:
            raise ValueError("cannot persist an index without a dimension")
        # Python opens Unicode paths on Windows; the FAISS stream format stays
        # unchanged. Callbacks avoid an extra full-index serialization buffer.
        with Path(path).open('wb') as stream:
            faiss.write_index(self._index, faiss.PyCallbackIOWriter(stream.write))

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        chunks: Sequence[KnowledgeChunk],
        expected_dimension: int | None = None,
    ) -> "FAISSVectorIndex":
        with Path(path).open('rb') as stream:
            loaded = faiss.read_index(faiss.PyCallbackIOReader(stream.read))
        if expected_dimension is not None and loaded.d != expected_dimension:
            raise ValueError("persisted index dimension does not match")
        if loaded.ntotal != len(chunks):
            raise ValueError("persisted index/chunk count does not match")
        instance = cls()
        instance._index = loaded
        instance._dimension = int(loaded.d)
        instance._chunks = list(chunks)
        return instance

    def add(
        self,
        *,
        chunks: Sequence[KnowledgeChunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")

        if not chunks:
            return

        matrix = np.asarray(vectors, dtype=np.float32)

        if matrix.ndim != 2:
            raise ValueError("vectors must form a 2D matrix")

        dimension = matrix.shape[1]

        if self._index is None:
            self._dimension = dimension
            self._index = faiss.IndexFlatIP(dimension)
        elif dimension != self._dimension:
            raise ValueError("vector dimensions must match")

        # 归一化后，inner product 等价于 cosine similarity
        faiss.normalize_L2(matrix)

        self._index.add(matrix)
        self._chunks.extend(chunks)

    def search(
        self,
        *,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[RetrievedChunk]:
        if limit <= 0 or self._index is None or not self._chunks:
            return []

        query = np.asarray(
            [query_vector],
            dtype=np.float32,
        )

        if query.shape[1] != self._dimension:
            raise ValueError("query vector dimension must match index")

        faiss.normalize_L2(query)

        k = min(limit, len(self._chunks))

        scores, indices = self._index.search(
            query,
            k,
        )

        hits: list[RetrievedChunk] = []

        for rank, (score, index) in enumerate(
            zip(scores[0], indices[0]),
            start=1,
        ):
            hits.append(
                RetrievedChunk(
                    chunk=self._chunks[int(index)],
                    score=float(score),
                    rank=rank,
                    retrieval_method="dense",
                )
            )

        return hits
