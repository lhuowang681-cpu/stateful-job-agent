from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from job_agent.knowledge.durable import (
    CareerKnowledgeLifecycle,
    EmbeddingIdentity,
    KnowledgeRepository,
)


@dataclass(frozen=True)
class DurableCareerEvalDocument:
    document_id: str
    source_type: str
    title: str
    path: str
    source_uri: str


@dataclass(frozen=True)
class DurableCareerEvalCase:
    case_id: str
    split: str
    category: str
    query: str
    expected_document_ids: tuple[str, ...]
    source_type: str | None

    @property
    def is_positive(self) -> bool:
        return bool(self.expected_document_ids)


@dataclass(frozen=True)
class DurableCareerEvalDataset:
    documents: tuple[DurableCareerEvalDocument, ...]
    cases: tuple[DurableCareerEvalCase, ...]


@dataclass(frozen=True)
class DurableCareerEvalMetrics:
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float
    source_correctness: float
    active_version_correctness: float


@dataclass(frozen=True)
class DurableCareerPerformance:
    cold_load_ms: float
    index_load_ms: float
    build_ms: float
    retrieval_p50_ms: float
    retrieval_p95_ms: float
    document_count: int
    chunk_count: int


@dataclass(frozen=True)
class DurableCareerBadCase:
    case_id: str
    layer: str
    observation: str


@dataclass(frozen=True)
class DurableCareerEvalReport:
    query_count: int
    positive_query_count: int
    gap_query_count: int
    categories: tuple[str, ...]
    metrics: DurableCareerEvalMetrics
    performance: DurableCareerPerformance
    bad_cases: tuple[DurableCareerBadCase, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_durable_career_eval(
    dataset_root: str | Path,
    *,
    repository_root: str | Path,
) -> DurableCareerEvalDataset:
    root = Path(dataset_root)
    source_root = Path(repository_root).resolve()
    document_records = _read_list(root / "documents.json")
    documents: list[DurableCareerEvalDocument] = []
    document_ids: set[str] = set()
    for record in document_records:
        source_path = (source_root / str(record["path"])).resolve()
        if not source_path.is_relative_to(source_root) or not source_path.is_file():
            raise ValueError(f"LOAD: invalid evaluation source: {record['path']}")
        document = DurableCareerEvalDocument(
            document_id=str(record["document_id"]),
            source_type=str(record["source_type"]),
            title=str(record["title"]),
            path=str(source_path),
            source_uri=str(record["source_uri"]),
        )
        if document.document_id in document_ids:
            raise ValueError(f"VERSIONING: duplicate document_id {document.document_id}")
        document_ids.add(document.document_id)
        documents.append(document)

    cases: list[DurableCareerEvalCase] = []
    case_ids: set[str] = set()
    for split, filename in (("dev", "dev.json"), ("frozen", "frozen_test.json")):
        for record in _read_list(root / filename):
            case_id = str(record["case_id"])
            if case_id in case_ids:
                raise ValueError(f"duplicate case_id {case_id}")
            expected = tuple(str(item) for item in record["expected_document_ids"])
            if set(expected) - document_ids:
                raise ValueError(f"SOURCE_SCOPE: unknown expected source for {case_id}")
            cases.append(
                DurableCareerEvalCase(
                    case_id=case_id,
                    split=split,
                    category=str(record["category"]),
                    query=str(record["query"]),
                    expected_document_ids=expected,
                    source_type=record.get("source_type"),
                )
            )
            case_ids.add(case_id)
    return DurableCareerEvalDataset(tuple(documents), tuple(cases))


def run_durable_career_eval(
    dataset: DurableCareerEvalDataset,
    *,
    repository_root: str | Path,
    state_root: str | Path,
    embedding_backend,
    embedding_identity: EmbeddingIdentity,
    max_chars: int = 2000,
) -> DurableCareerEvalReport:
    state = Path(state_root)
    lifecycle = CareerKnowledgeLifecycle(
        repository=KnowledgeRepository(state / "knowledge.sqlite"),
        embedding_backend=embedding_backend,
        embedding_identity=embedding_identity,
        index_path=state / "career.faiss",
        manifest_path=state / "career-index-manifest.json",
        max_chars=max_chars,
    )
    build_started = time.perf_counter()
    for document in dataset.documents:
        lifecycle.ingest_file(
            document.path,
            document_id=document.document_id,
            source_type=document.source_type,
            title=document.title,
            source_uri=document.source_uri,
            metadata={"material_kind": "real_project_material"},
        )
    build_ms = (time.perf_counter() - build_started) * 1000

    cold_started = time.perf_counter()
    reopened_repository = KnowledgeRepository(state / "knowledge.sqlite")
    cold_load_ms = (time.perf_counter() - cold_started) * 1000
    reopened = CareerKnowledgeLifecycle(
        repository=reopened_repository,
        embedding_backend=embedding_backend,
        embedding_identity=embedding_identity,
        index_path=state / "career.faiss",
        manifest_path=state / "career-index-manifest.json",
        max_chars=max_chars,
    )
    index_started = time.perf_counter()
    manifest = reopened.load_index()
    index_load_ms = (time.perf_counter() - index_started) * 1000
    retriever = reopened.candidate_retriever(load=False)

    ranks: list[int | None] = []
    source_hits = 0
    retrieved_count = 0
    active_hits = 0
    latencies: list[float] = []
    bad_cases: list[DurableCareerBadCase] = []
    active_versions = {
        item.document_id: item.version
        for item in reopened_repository.list_active_documents()
    }
    positives = [case for case in dataset.cases if case.is_positive]
    for case in dataset.cases:
        started = time.perf_counter()
        hits = retriever.retrieve(query=case.query, limit=5)
        latencies.append((time.perf_counter() - started) * 1000)
        retrieved_count += len(hits)
        active_hits += sum(
            hit.chunk.document_version == active_versions.get(hit.chunk.document_id)
            for hit in hits
        )
        if not case.is_positive:
            continue
        expected = set(case.expected_document_ids)
        rank = next(
            (
                hit.rank
                for hit in hits
                if hit.chunk.document_id in expected
            ),
            None,
        )
        ranks.append(rank)
        if hits and hits[0].chunk.document_id in expected:
            source_hits += 1
        if rank is None:
            bad_cases.append(
                DurableCareerBadCase(
                    case_id=case.case_id,
                    layer="RETRIEVAL_RANKING",
                    observation=(
                        f"expected {sorted(expected)}; got "
                        f"{[hit.chunk.document_id for hit in hits]}"
                    ),
                )
            )

    positive_count = len(positives)
    metrics = DurableCareerEvalMetrics(
        recall_at_1=_recall(ranks, 1),
        recall_at_3=_recall(ranks, 3),
        recall_at_5=_recall(ranks, 5),
        mrr=sum(0.0 if rank is None else 1.0 / rank for rank in ranks) / positive_count,
        source_correctness=source_hits / positive_count,
        active_version_correctness=(
            active_hits / retrieved_count if retrieved_count else 1.0
        ),
    )
    return DurableCareerEvalReport(
        query_count=len(dataset.cases),
        positive_query_count=positive_count,
        gap_query_count=len(dataset.cases) - positive_count,
        categories=tuple(sorted({case.category for case in dataset.cases})),
        metrics=metrics,
        performance=DurableCareerPerformance(
            cold_load_ms=cold_load_ms,
            index_load_ms=index_load_ms,
            build_ms=build_ms,
            retrieval_p50_ms=statistics.median(latencies),
            retrieval_p95_ms=_percentile(latencies, 0.95),
            document_count=manifest.document_count,
            chunk_count=manifest.chunk_count,
        ),
        bad_cases=tuple(bad_cases),
    )


def _recall(ranks: list[int | None], k: int) -> float:
    return sum(rank is not None and rank <= k for rank in ranks) / len(ranks)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return ordered[index]


def _read_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected JSON list: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", default="eval/career_knowledge_v1")
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--state-root")
    parser.add_argument("--model-path", default=os.environ.get("QWEN_EMBEDDING_MODEL_PATH"))
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if not args.model_path:
        raise SystemExit("QWEN_EMBEDDING_MODEL_PATH or --model-path is required")

    from job_agent.knowledge.qwen_embedding import QwenEmbeddingBackend

    dataset = load_durable_career_eval(
        args.dataset_root,
        repository_root=args.repository_root,
    )
    with tempfile.TemporaryDirectory(prefix="career-knowledge-eval-") as temporary:
        report = run_durable_career_eval(
            dataset,
            repository_root=args.repository_root,
            state_root=args.state_root or temporary,
            embedding_backend=QwenEmbeddingBackend(args.model_path, device=args.device),
            embedding_identity=EmbeddingIdentity(
                provider="sentence-transformers",
                model="Qwen/Qwen3-Embedding-0.6B",
                dimension=1024,
            ),
        )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
