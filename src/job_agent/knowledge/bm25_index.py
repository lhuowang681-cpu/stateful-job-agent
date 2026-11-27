from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

from job_agent.knowledge.contracts import KnowledgeChunk, RetrievedChunk


_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]")


def tokenize_for_bm25(text: str) -> list[str]:
    separated = _ACRONYM_BOUNDARY.sub(r"\1 \2", text)
    separated = _CAMEL_BOUNDARY.sub(r"\1 \2", separated)
    return _TOKEN_PATTERN.findall(separated.casefold())


class BM25Index:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0.0:
            raise ValueError("k1 must be greater than zero")
        if not 0.0 <= b <= 1.0:
            raise ValueError("b must be between zero and one")

        self.k1 = k1
        self.b = b
        self._chunks: list[KnowledgeChunk] = []
        self._term_frequencies: list[Counter[str]] = []
        self._document_lengths: list[int] = []
        self._document_frequencies: Counter[str] = Counter()
        self._total_document_length = 0

    def add(self, chunks: Sequence[KnowledgeChunk]) -> None:
        for chunk in chunks:
            tokens = tokenize_for_bm25(chunk.text)
            frequencies = Counter(tokens)

            self._chunks.append(chunk)
            self._term_frequencies.append(frequencies)
            self._document_lengths.append(len(tokens))
            self._total_document_length += len(tokens)

            for term in frequencies:
                self._document_frequencies[term] += 1

    def search(self, *, query: str, limit: int) -> list[RetrievedChunk]:
        if limit <= 0 or not self._chunks:
            return []

        query_terms = set(tokenize_for_bm25(query))
        scores = [
            self._score_document(
                query_terms=query_terms,
                frequencies=frequencies,
                document_length=document_length,
            )
            for frequencies, document_length in zip(
                self._term_frequencies,
                self._document_lengths,
            )
        ]
        ranked_indexes = sorted(
            range(len(self._chunks)),
            key=lambda index: scores[index],
            reverse=True,
        )[:limit]

        return [
            RetrievedChunk(
                chunk=self._chunks[index],
                score=scores[index],
                rank=rank,
                retrieval_method="bm25",
                retrieval_metadata={
                    "k1": self.k1,
                    "b": self.b,
                },
            )
            for rank, index in enumerate(ranked_indexes, start=1)
        ]

    def _score_document(
        self,
        *,
        query_terms: set[str],
        frequencies: Counter[str],
        document_length: int,
    ) -> float:
        average_length = (
            self._total_document_length / len(self._chunks)
            if self._chunks
            else 0.0
        )
        score = 0.0

        for term in query_terms:
            term_frequency = frequencies.get(term, 0)
            if term_frequency == 0:
                continue

            document_frequency = self._document_frequencies[term]
            inverse_document_frequency = math.log(
                1.0
                + (
                    len(self._chunks) - document_frequency + 0.5
                )
                / (document_frequency + 0.5)
            )
            length_normalization = self.k1 * (
                1.0
                - self.b
                + self.b * document_length / average_length
            )
            score += inverse_document_frequency * (
                term_frequency * (self.k1 + 1.0)
                / (term_frequency + length_normalization)
            )

        return score
