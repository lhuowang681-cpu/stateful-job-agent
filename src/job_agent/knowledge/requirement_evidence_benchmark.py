from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from job_agent.evidence.contracts import EvidenceMappingCandidate
from job_agent.knowledge.candidate_evidence import CandidateEvidenceRetriever
from job_agent.knowledge.career_benchmark import (
    CareerBenchmarkDataset,
    load_career_benchmark,
)
from job_agent.knowledge.contracts import EmbeddingBackend, KnowledgeDocument
from job_agent.knowledge.ingestion import create_knowledge_document
from job_agent.llm.harness import LLMHarness
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.skill_registry import SkillSpec
from job_agent.requirement_evidence import RequirementEvidenceService


@dataclass(frozen=True)
class RequirementEvidenceBenchmarkCase:
    case_id: str
    query_case_id: str
    expected_status: str
    expected_document_id: str | None
    applicable: bool = True


@dataclass(frozen=True)
class RequirementEvidenceBenchmarkResult:
    case_id: str
    expected_status: str
    actual_status: str
    evidence_document_ids: tuple[str, ...]


@dataclass(frozen=True)
class RequirementEvidenceBenchmarkMetrics:
    status_accuracy: float
    source_correctness: float
    span_validity: float
    gap_detection: float


@dataclass(frozen=True)
class RequirementEvidenceBenchmarkReport:
    metrics: RequirementEvidenceBenchmarkMetrics
    cases: tuple[RequirementEvidenceBenchmarkResult, ...]

    def to_dict(self) -> dict:
        return asdict(self)


BENCHMARK_CASES = (
    RequirementEvidenceBenchmarkCase(
        case_id="rag-experience",
        query_case_id="requirement-rag-experience",
        expected_status="unverified_lead",
        expected_document_id="real-dense-knowledge-retrieval",
    ),
    RequirementEvidenceBenchmarkCase(
        case_id="async-backend",
        query_case_id="requirement-async-backend",
        expected_status="unverified_lead",
        expected_document_id="real-backend-reliability",
    ),
    RequirementEvidenceBenchmarkCase(
        case_id="legacy-migration",
        query_case_id="requirement-legacy-migration",
        expected_status="unverified_lead",
        expected_document_id="real-career-store",
    ),
    RequirementEvidenceBenchmarkCase(
        case_id="kubernetes-gap",
        query_case_id="gap-kubernetes",
        expected_status="gap",
        expected_document_id=None,
    ),
    RequirementEvidenceBenchmarkCase(
        case_id="pdf-docx-gap",
        query_case_id="gap-pdf-docx",
        expected_status="gap",
        expected_document_id=None,
    ),
    RequirementEvidenceBenchmarkCase(
        case_id="synthetic-jd",
        query_case_id="requirement-synthetic-agent-jd",
        expected_status="not_applicable",
        expected_document_id=None,
        applicable=False,
    ),
)


class _Registry:
    def get(self, skill_id: str) -> SkillSpec:
        return SkillSpec(
            skill_id=skill_id,
            version="requirement-evidence-benchmark-v1",
            instructions="Map evidence without fabrication.",
            reference_paths=(Path("skill-references/evidence-contract.md"),),
            output_schema=EvidenceMappingCandidate,
        )


def run_requirement_evidence_benchmark(
    dataset: CareerBenchmarkDataset,
    *,
    embedding_backend: EmbeddingBackend,
    vector_index,
    session_dir: Path,
    top_k: int = 5,
    max_chars: int = 2000,
) -> RequirementEvidenceBenchmarkReport:
    cases_by_id = {case.case_id: case for case in dataset.cases}
    documents = _knowledge_documents(dataset)
    documents_by_id = {document.document_id: document for document in documents}
    retriever = CandidateEvidenceRetriever.from_documents(
        documents,
        embedding_backend=embedding_backend,
        vector_index=vector_index,
        max_chars=max_chars,
    )

    applicable_cases = [case for case in BENCHMARK_CASES if case.applicable]
    responses: list[dict] = []
    for benchmark_case in applicable_cases:
        query = cases_by_id[benchmark_case.query_case_id].query
        hits = retriever.retrieve(query=query, limit=top_k)
        if benchmark_case.expected_document_id is None:
            responses.append(_gap_response())
            continue
        expected_hit = next(
            hit
            for hit in hits
            if hit.chunk.document_id == benchmark_case.expected_document_id
        )
        ordered_document_ids = list(
            dict.fromkeys(hit.chunk.document_id for hit in hits)
        )
        source_number = ordered_document_ids.index(
            benchmark_case.expected_document_id
        ) + 2
        responses.append(
            _support_response(
                source_id=f"src_{source_number:03d}_project_source",
                exact_quote=expected_hit.chunk.text,
            )
        )

    provider = MockLLMProvider(responses)
    service = RequirementEvidenceService(
        candidate_retriever=retriever,
        candidate_documents=documents,
        registry=_Registry(),
        harness=LLMHarness(provider),
        session_dir=session_dir,
    )
    results: list[RequirementEvidenceBenchmarkResult] = []
    status_correct = 0
    source_correct = 0
    span_valid = 0
    positive_count = 0
    gap_correct = 0
    gap_count = 0

    for benchmark_case in BENCHMARK_CASES:
        if not benchmark_case.applicable:
            results.append(
                RequirementEvidenceBenchmarkResult(
                    case_id=benchmark_case.case_id,
                    expected_status="not_applicable",
                    actual_status="not_applicable",
                    evidence_document_ids=(),
                )
            )
            continue

        query = cases_by_id[benchmark_case.query_case_id].query
        result = service.assess(
            requirement=query,
            run_id=f"requirement-evidence-{benchmark_case.case_id}",
            session_id="requirement-evidence-benchmark",
            limit=top_k,
        )
        evidence_document_ids = tuple(
            item.document_id for item in result.evidence_items
        )
        status_correct += result.status == benchmark_case.expected_status

        if benchmark_case.expected_document_id is None:
            gap_count += 1
            gap_correct += result.status == "gap" and not result.evidence_items
        else:
            positive_count += 1
            source_correct += (
                benchmark_case.expected_document_id in evidence_document_ids
                and set(evidence_document_ids)
                == {benchmark_case.expected_document_id}
            )
            span_valid += all(
                item.evidence_link.source_span.exact_quote
                == documents_by_id[item.document_id].text[
                    item.evidence_link.source_span.start_offset:
                    item.evidence_link.source_span.end_offset
                ]
                for item in result.evidence_items
            ) and bool(result.evidence_items)

        results.append(
            RequirementEvidenceBenchmarkResult(
                case_id=benchmark_case.case_id,
                expected_status=benchmark_case.expected_status,
                actual_status=result.status,
                evidence_document_ids=evidence_document_ids,
            )
        )

    return RequirementEvidenceBenchmarkReport(
        metrics=RequirementEvidenceBenchmarkMetrics(
            status_accuracy=status_correct / len(applicable_cases),
            source_correctness=source_correct / positive_count,
            span_validity=span_valid / positive_count,
            gap_detection=gap_correct / gap_count,
        ),
        cases=tuple(results),
    )


def _knowledge_documents(
    dataset: CareerBenchmarkDataset,
) -> tuple[KnowledgeDocument, ...]:
    return tuple(
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


def _support_response(*, source_id: str, exact_quote: str) -> dict:
    return {
        "atom_results": [
            {
                "atom_id": "requirement-atom-1",
                "links": [
                    {
                        "link_id": "evidence-1",
                        "atom_id": "requirement-atom-1",
                        "source_locator": {
                            "source_id": source_id,
                            "exact_quote": exact_quote,
                        },
                        "claim": exact_quote,
                        "support_status": "supported",
                        "level": "C1",
                        "confidence": 0.9,
                        "needs_confirmation": True,
                    }
                ],
                "rationale": "Candidate project material supports the requirement.",
            }
        ],
        "warnings": [],
    }


def _gap_response() -> dict:
    return {
        "atom_results": [
            {
                "atom_id": "requirement-atom-1",
                "links": [],
                "rationale": "Retrieved text does not support the requirement.",
            }
        ],
        "warnings": [],
    }


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

    with TemporaryDirectory(prefix="requirement-evidence-") as directory:
        report = run_requirement_evidence_benchmark(
            load_career_benchmark(args.fixture_root),
            embedding_backend=QwenEmbeddingBackend(
                model_path=args.model_path,
                device=args.device,
            ),
            vector_index=FAISSVectorIndex(),
            session_dir=Path(directory),
        )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
