from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from job_agent.evidence.contracts import (
    EvidenceMappingCandidate,
    RequirementAnalysisCandidate,
)
from job_agent.jd_match_analysis import JobMatchAnalysis, JDMatchAnalysisService
from job_agent.knowledge.candidate_evidence import CandidateEvidenceRetriever
from job_agent.knowledge.career_benchmark import (
    CareerBenchmarkDataset,
    load_career_benchmark,
)
from job_agent.knowledge.contracts import (
    EmbeddingBackend,
    KnowledgeDocument,
    VectorIndex,
)
from job_agent.knowledge.ingestion import create_knowledge_document
from job_agent.llm.harness import LLMHarness
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.skill_registry import SkillSpec


JD_MATCH_CASE_IDS = (
    "requirement-rag-experience",
    "requirement-async-backend",
    "requirement-legacy-migration",
    "gap-kubernetes",
    "gap-pdf-docx",
)


class _Registry:
    def get(self, skill_id: str) -> SkillSpec:
        output_schema = (
            RequirementAnalysisCandidate
            if skill_id == "jd-analysis"
            else EvidenceMappingCandidate
        )
        return SkillSpec(
            skill_id=skill_id,
            version="jd-match-demo-v1",
            instructions="Use only explicit requirements and cited evidence.",
            reference_paths=(),
            output_schema=output_schema,
        )


def run_jd_match_demo(
    dataset: CareerBenchmarkDataset,
    *,
    jd_text: str,
    embedding_backend: EmbeddingBackend,
    vector_index: VectorIndex,
    session_dir: Path,
    top_k: int = 5,
) -> JobMatchAnalysis:
    documents = knowledge_documents_from_career_dataset(dataset)
    retriever = CandidateEvidenceRetriever.from_documents(
        documents,
        embedding_backend=embedding_backend,
        vector_index=vector_index,
        max_chars=2000,
    )
    cases_by_id = {case.case_id: case for case in dataset.cases}
    cases = [cases_by_id[case_id] for case_id in JD_MATCH_CASE_IDS]

    responses = [_requirement_analysis_response(cases)]
    for index, case in enumerate(cases, start=1):
        atom_id = f"atom_{index:03d}"
        if not case.expected_document_ids:
            responses.append(_gap_response(atom_id))
            continue

        expected_document_id = case.expected_document_ids[0]
        hits = retriever.retrieve(query=case.query, limit=top_k)
        try:
            expected_hit = next(
                hit
                for hit in hits
                if hit.chunk.document_id == expected_document_id
            )
        except StopIteration as exc:
            raise ValueError(
                f"expected evidence not retrieved for {case.case_id}"
            ) from exc
        responses.append(
            _support_response(
                atom_id=atom_id,
                chunk_id=expected_hit.chunk.chunk_id,
                exact_quote=expected_hit.chunk.text,
            )
        )

    return JDMatchAnalysisService(
        candidate_retriever=retriever,
        candidate_documents=documents,
        registry=_Registry(),
        harness=LLMHarness(MockLLMProvider(responses)),
        session_dir=session_dir,
    ).analyze(
        jd_text=jd_text,
        run_id="jd-match-demo",
        session_id="jd-match-demo",
        limit=top_k,
    )


def knowledge_documents_from_career_dataset(
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


def _requirement_analysis_response(cases) -> dict:
    return {
        "requirements": [
            {
                "text": case.query,
                "importance": "must",
                "hard_gate": False,
                "exact_quote": case.query,
                "verification_signals": [],
            }
            for case in cases
        ],
        "warnings": [],
    }


def _support_response(
    *,
    atom_id: str,
    chunk_id: str,
    exact_quote: str,
) -> dict:
    return {
        "atom_results": [
            {
                "atom_id": atom_id,
                "semantic_support": "supported",
                "selected_chunk_id": chunk_id,
                "exact_quote": exact_quote,
            }
        ]
    }


def _gap_response(atom_id: str) -> dict:
    return {
        "atom_results": [
            {
                "atom_id": atom_id,
                "semantic_support": "unsupported",
                "selected_chunk_id": None,
                "exact_quote": None,
            }
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-root",
        default="tests/fixtures/career_retrieval",
    )
    parser.add_argument(
        "--jd-path",
        default="tests/fixtures/jd_match/synthetic_jd.md",
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

    with TemporaryDirectory(prefix="job-agent-jd-match-") as session_dir:
        analysis = run_jd_match_demo(
            load_career_benchmark(args.fixture_root),
            jd_text=Path(args.jd_path).read_text(encoding="utf-8"),
            embedding_backend=QwenEmbeddingBackend(
                model_path=args.model_path,
                device=args.device,
            ),
            vector_index=FAISSVectorIndex(),
            session_dir=Path(session_dir),
        )
    print(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
