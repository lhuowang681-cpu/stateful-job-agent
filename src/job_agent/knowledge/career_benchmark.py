from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from job_agent.knowledge.contracts import (
    EmbeddingBackend,
    KnowledgeChunk,
    VectorIndex,
)
from job_agent.knowledge.eval import RetrievalEvalCase, evaluate_rankings
from job_agent.knowledge.ingestion import ingest_text
from job_agent.knowledge.retriever import KnowledgeRetriever


_BENCHMARK_CREATED_AT = datetime(2026, 9, 17, tzinfo=timezone.utc)


@dataclass(frozen=True)
class CareerBenchmarkDocument:
    document_id: str
    source_type: str
    title: str
    material_kind: str
    source_uri: str | None
    fixture_path: str
    text: str


@dataclass(frozen=True)
class CareerBenchmarkCase:
    case_id: str
    category: str
    query: str
    expected_document_ids: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class CareerBenchmarkDataset:
    documents: tuple[CareerBenchmarkDocument, ...]
    cases: tuple[CareerBenchmarkCase, ...]


@dataclass(frozen=True)
class CareerBenchmarkMetrics:
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float


@dataclass(frozen=True)
class CareerBenchmarkHit:
    rank: int
    chunk_id: str
    document_id: str
    score: float
    source_uri: str | None
    text_preview: str


@dataclass(frozen=True)
class CareerBenchmarkBadCase:
    case_id: str
    query: str
    expected_document_ids: tuple[str, ...]
    actual_top_results: tuple[CareerBenchmarkHit, ...]
    failure_category: str


@dataclass(frozen=True)
class CareerBenchmarkReport:
    document_count: int
    real_document_count: int
    synthetic_document_count: int
    query_count: int
    evaluated_positive_query_count: int
    categories: tuple[str, ...]
    metrics: CareerBenchmarkMetrics
    bad_cases: tuple[CareerBenchmarkBadCase, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_career_benchmark(fixture_root: str | Path) -> CareerBenchmarkDataset:
    root = Path(fixture_root)
    documents_root = (root / "documents").resolve()
    document_records = _read_json(root / "documents.json")
    query_records = _read_json(root / "queries.json")

    documents: list[CareerBenchmarkDocument] = []
    document_ids: set[str] = set()

    for record in document_records:
        document_id = str(record["document_id"])
        if document_id in document_ids:
            raise ValueError(f"duplicate document_id: {document_id}")

        fixture_path = str(record["path"])
        path = (documents_root / fixture_path).resolve()
        if not path.is_relative_to(documents_root):
            raise ValueError(f"document path escapes fixture root: {fixture_path}")
        if not path.is_file():
            raise ValueError(f"document file not found: {fixture_path}")

        documents.append(
            CareerBenchmarkDocument(
                document_id=document_id,
                source_type=str(record["source_type"]),
                title=str(record["title"]),
                material_kind=str(record["material_kind"]),
                source_uri=record.get("source_uri"),
                fixture_path=fixture_path,
                text=path.read_text(encoding="utf-8"),
            )
        )
        document_ids.add(document_id)

    cases: list[CareerBenchmarkCase] = []
    case_ids: set[str] = set()

    for record in query_records:
        case_id = str(record["case_id"])
        if case_id in case_ids:
            raise ValueError(f"duplicate case_id: {case_id}")

        expected_document_ids = tuple(record["expected_document_ids"])
        unknown_ids = set(expected_document_ids) - document_ids
        if unknown_ids:
            raise ValueError(
                f"unknown expected document IDs for {case_id}: "
                f"{sorted(unknown_ids)}"
            )

        cases.append(
            CareerBenchmarkCase(
                case_id=case_id,
                category=str(record["category"]),
                query=str(record["query"]),
                expected_document_ids=expected_document_ids,
                rationale=str(record["rationale"]),
            )
        )
        case_ids.add(case_id)

    if not documents:
        raise ValueError("benchmark documents must not be empty")
    if not cases:
        raise ValueError("benchmark queries must not be empty")

    return CareerBenchmarkDataset(
        documents=tuple(documents),
        cases=tuple(cases),
    )


def ingest_benchmark_documents(
    dataset: CareerBenchmarkDataset,
    *,
    embedding_backend: EmbeddingBackend,
    vector_index: VectorIndex,
    max_chars: int = 2000,
) -> dict[str, list[KnowledgeChunk]]:
    chunks_by_document: dict[str, list[KnowledgeChunk]] = {}

    for document in dataset.documents:
        _, chunks = ingest_text(
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
            created_at=_BENCHMARK_CREATED_AT,
            embedding_backend=embedding_backend,
            vector_index=vector_index,
            max_chars=max_chars,
        )
        chunks_by_document[document.document_id] = chunks

    return chunks_by_document


def resolve_relevant_chunk_ids(
    case: CareerBenchmarkCase,
    chunks_by_document: dict[str, list[KnowledgeChunk]],
) -> set[str]:
    relevant_ids: set[str] = set()

    for document_id in case.expected_document_ids:
        relevant_ids.update(
            chunk.chunk_id
            for chunk in chunks_by_document[document_id]
        )

    return relevant_ids


def run_career_dense_benchmark(
    dataset: CareerBenchmarkDataset,
    *,
    embedding_backend: EmbeddingBackend,
    vector_index: VectorIndex,
    top_k: int = 5,
    max_chars: int = 2000,
) -> CareerBenchmarkReport:
    if top_k < 5:
        raise ValueError("top_k must be at least 5")

    chunks_by_document = ingest_benchmark_documents(
        dataset,
        embedding_backend=embedding_backend,
        vector_index=vector_index,
        max_chars=max_chars,
    )
    retriever = KnowledgeRetriever(
        embedding_backend=embedding_backend,
        vector_index=vector_index,
    )

    positive_cases: list[RetrievalEvalCase] = []
    positive_rankings: list[list[str]] = []
    bad_cases: list[CareerBenchmarkBadCase] = []

    for case in dataset.cases:
        hits = retriever.retrieve(query=case.query, limit=top_k)
        ranking = [hit.chunk.chunk_id for hit in hits]
        relevant_ids = resolve_relevant_chunk_ids(case, chunks_by_document)

        if relevant_ids:
            positive_cases.append(
                RetrievalEvalCase(
                    query=case.query,
                    relevant_ids=relevant_ids,
                )
            )
            positive_rankings.append(ranking)

        if not relevant_ids or not relevant_ids.intersection(ranking[:3]):
            bad_cases.append(
                CareerBenchmarkBadCase(
                    case_id=case.case_id,
                    query=case.query,
                    expected_document_ids=case.expected_document_ids,
                    actual_top_results=tuple(
                        CareerBenchmarkHit(
                            rank=hit.rank,
                            chunk_id=hit.chunk.chunk_id,
                            document_id=hit.chunk.document_id,
                            score=hit.score,
                            source_uri=hit.chunk.metadata.get("source_uri"),
                            text_preview=_preview(hit.chunk.text),
                        )
                        for hit in hits[:3]
                    ),
                    failure_category=_classify_failure(
                        case=case,
                        relevant_ids=relevant_ids,
                        ranking=ranking,
                        hits=hits,
                    ),
                )
            )

    if not positive_cases:
        raise ValueError("benchmark must contain at least one positive query")

    recall_1 = evaluate_rankings(
        positive_rankings,
        positive_cases,
        k=1,
    )
    recall_3 = evaluate_rankings(
        positive_rankings,
        positive_cases,
        k=3,
    )
    recall_5 = evaluate_rankings(
        positive_rankings,
        positive_cases,
        k=5,
    )

    return CareerBenchmarkReport(
        document_count=len(dataset.documents),
        real_document_count=sum(
            document.material_kind == "real_project_material"
            for document in dataset.documents
        ),
        synthetic_document_count=sum(
            document.material_kind == "synthetic_jd"
            for document in dataset.documents
        ),
        query_count=len(dataset.cases),
        evaluated_positive_query_count=len(positive_cases),
        categories=tuple(sorted({case.category for case in dataset.cases})),
        metrics=CareerBenchmarkMetrics(
            recall_at_1=recall_1.recall_at_k,
            recall_at_3=recall_3.recall_at_k,
            recall_at_5=recall_5.recall_at_k,
            mrr=recall_5.mrr,
        ),
        bad_cases=tuple(bad_cases),
    )


def _classify_failure(
    *,
    case: CareerBenchmarkCase,
    relevant_ids: set[str],
    ranking: Sequence[str],
    hits: Sequence[Any],
) -> str:
    if not relevant_ids:
        return "corpus missing evidence"

    first_relevant_rank = next(
        (
            rank
            for rank, chunk_id in enumerate(ranking, start=1)
            if chunk_id in relevant_ids
        ),
        None,
    )
    if first_relevant_rank is not None:
        return "ranking issue"

    actual_document_ids = {hit.chunk.document_id for hit in hits}
    if actual_document_ids.intersection(case.expected_document_ids):
        return "chunking issue"
    if case.category == "ambiguous":
        return "ambiguous gold"
    if case.category in {"exact_term", "exact_entity"}:
        return "exact-term miss"
    return "semantic miss"


def _preview(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _read_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected a JSON list: {path}")
    return payload


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

    dataset = load_career_benchmark(args.fixture_root)
    report = run_career_dense_benchmark(
        dataset,
        embedding_backend=QwenEmbeddingBackend(
            model_path=args.model_path,
            device=args.device,
        ),
        vector_index=FAISSVectorIndex(),
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
