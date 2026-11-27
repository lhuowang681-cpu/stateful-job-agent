"""Versioned identity of actual encoder inputs; separate from citation identity."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
from typing import Literal, Sequence

from job_agent.knowledge.contracts import KnowledgeChunk


def fingerprint(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                             allow_nan=False).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model: str
    revision: str
    dimension: int | None = None
    normalization: Literal['l2', 'none'] = 'l2'
    query_template: str = '{query}'
    max_input_tokens: int = 1024
    encoder_version: str = 'caller-managed'

    def __post_init__(self):
        if not all((self.provider, self.model, self.revision)):
            raise ValueError('embedding_identity_required')
        if self.dimension is not None and not 1 <= self.dimension <= 8192:
            raise ValueError('embedding_dimension_invalid')
        if self.normalization not in ('l2', 'none') or self.query_template.count('{query}') != 1:
            raise ValueError('embedding_semantics_invalid')
        if not 1 <= self.max_input_tokens <= 32768:
            raise ValueError('embedding_input_budget_invalid')

    def with_dimension(self, dimension: int):
        if self.dimension is not None and dimension != self.dimension:
            raise ValueError('embedding_dimension_changed')
        return replace(self, dimension=dimension)


@dataclass(frozen=True)
class IndexManifest:
    corpus_kind: Literal['code', 'project_documentation', 'public_knowledge']
    scope: tuple[str, ...]
    input_hash: str
    parser_version: str
    splitter_version: str
    embedding: EmbeddingIdentity
    schema_version: str = 'retrieval-manifest-1'

    @property
    def key(self) -> str:
        return 'index-' + fingerprint(asdict(self))


def manifest_for(chunks: Sequence[KnowledgeChunk], *, corpus_kind, scope, parser_version,
                 splitter_version, embedding: EmbeddingIdentity) -> IndexManifest:
    # Order and searchable text (including metadata augmentation) affect encoder output.
    inputs = [(c.chunk_id, c.document_id, c.document_version, c.document_content_hash,
               c.start_offset, c.end_offset, c.text) for c in chunks]
    return IndexManifest(corpus_kind, tuple(scope), fingerprint(inputs), parser_version,
                         splitter_version, embedding)


def valid_vector(vector, dimension=None) -> bool:
    try:
        return (1 <= len(vector) <= 8192 and (dimension is None or len(vector) == dimension)
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                        for x in vector) and 0 < sum(x*x for x in vector) < math.inf)
    except (TypeError, OverflowError):
        return False


def declared_identity(backend, legacy_name='local-configured-embedding') -> EmbeddingIdentity:
    identity = getattr(backend, 'identity', None)
    if identity is not None:
        if not isinstance(identity, EmbeddingIdentity):
            raise ValueError('embedding_identity_type_invalid')
        return identity
    # Compatibility for explicitly injected legacy/test adapters. Actual dimension is
    # resolved from each query before cache lookup. This is not a verified model revision.
    return EmbeddingIdentity('legacy_adapter_unverified', legacy_name, 'caller-managed-revision')
