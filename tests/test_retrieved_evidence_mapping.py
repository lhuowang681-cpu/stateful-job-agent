from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_agent.agents.base import AgentGuardError
from job_agent.evidence.contracts import (
    ParentRequirement,
    RequirementAnalysis,
    RequirementAtom,
    RetrievedAtomEvidenceCandidate,
    RetrievedEvidenceMappingCandidate,
    SourceInput,
)
from job_agent.evidence.retrieved_mapping import (
    RetrievedEvidenceMappingService,
    _select_best_judgment,
)
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.knowledge.contracts import KnowledgeChunk, RetrievedChunk
from job_agent.knowledge.ingestion import create_knowledge_document
from job_agent.llm.harness import LLMHarness
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.skill_registry import SkillSpec


class _Registry:
    def get(self, skill_id: str) -> SkillSpec:
        return SkillSpec(
            skill_id=skill_id,
            version="retrieved-evidence-test-v1",
            instructions="Judge semantic support from retrieved chunks only.",
            reference_paths=(),
            output_schema=RetrievedEvidenceMappingCandidate,
        )


def _fixture(
    tmp_path: Path,
    responses,
    *,
    text: str = "Header\nImplemented Qwen embeddings and FAISS retrieval.\nFooter",
    artifact_type: str = "real_project_material",
):
    document = create_knowledge_document(
        document_id="project-rag",
        source_type="project",
        text=text,
        version=1,
        title="RAG project",
        metadata={"artifact_type": artifact_type},
        created_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    chunk_text = text[len("Header\n") : -len("\nFooter")]
    chunk = KnowledgeChunk(
        chunk_id="chunk-rag",
        document_id=document.document_id,
        document_version=document.version,
        document_content_hash=document.content_hash,
        text=chunk_text,
        chunk_index=1,
        start_offset=len("Header\n"),
        end_offset=len(text) - len("\nFooter"),
    )
    hit = RetrievedChunk(
        chunk=chunk,
        score=0.9,
        rank=1,
        retrieval_method="dense",
    )
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot(
        "retrieved-mapping",
        [
            SourceInput(kind="raw_jd", display_label="JD", text="Build RAG retrieval"),
            SourceInput(
                kind="project_source",
                display_label="RAG project",
                text=document.text,
                artifact_type=artifact_type,
            ),
        ],
    )
    jd_span = store.make_span(
        catalog,
        catalog.documents[0].source_id,
        0,
        len("Build RAG retrieval"),
    )
    analysis = RequirementAnalysis(
        parents=[
            ParentRequirement(
                requirement_id="req_001",
                text="Build RAG retrieval",
                importance="must",
                source_span=jd_span,
                atom_ids=["atom_001"],
            )
        ],
        atoms=[
            RequirementAtom(
                atom_id="atom_001",
                parent_requirement_id="req_001",
                text="Build RAG retrieval",
                source_span=jd_span,
            )
        ],
    )
    provider = MockLLMProvider(responses)
    service = RetrievedEvidenceMappingService(
        registry=_Registry(),
        harness=LLMHarness(provider),
        source_store=store,
        documents_by_id={document.document_id: document},
        source_ids_by_document_id={
            document.document_id: catalog.documents[1].source_id
        },
    )
    return service, provider, analysis, catalog, hit, document


def _positive(quote: str, **extra) -> dict:
    judgment = {
        "chunk_id": "chunk-rag",
        "semantic_support": "supported",
        "exact_quote": quote,
        **extra,
    }
    return {
        "atom_results": [
            {
                "atom_id": "atom_001",
                "candidate_judgments": [judgment],
            }
        ]
    }


def _run(service, analysis, catalog, hit):
    return service.map(
        analysis,
        retrieved_chunks=[hit],
        catalog=catalog,
        session_id="test",
        run_id="test",
    )


def test_exact_quote_derives_document_offset_and_c1_cap(tmp_path: Path) -> None:
    quote = "Qwen embeddings and FAISS retrieval"
    service, _, analysis, catalog, hit, document = _fixture(
        tmp_path,
        [_positive(quote)],
    )

    mapping = _run(service, analysis, catalog, hit)
    result = mapping.atom_results[0]
    link = result.links[0]

    assert result.semantic_support == "supported"
    assert result.match_status == "unverified_lead"
    assert link.level.value == "C1"
    assert link.source_span.start_offset == document.text.index(quote)
    assert document.text[
        link.source_span.start_offset : link.source_span.end_offset
    ] == quote


def test_quote_outside_chunk_repairs_once(tmp_path: Path) -> None:
    valid = "Implemented Qwen embeddings and FAISS retrieval."
    service, provider, analysis, catalog, hit, _ = _fixture(
        tmp_path,
        [_positive("Header"), _positive(valid)],
    )

    mapping = _run(service, analysis, catalog, hit)

    assert mapping.atom_results[0].links[0].source_span.exact_quote == valid
    assert len(provider.calls) == 2
    assert "quote_not_in_selected_chunk" in provider.calls[1]["user_prompt"]
    assert "Header" in provider.calls[1]["user_prompt"]


def test_ambiguous_quote_repairs_to_unique_quote(tmp_path: Path) -> None:
    text = "Header\nFAISS retrieval; FAISS retrieval with Qwen.\nFooter"
    service, provider, analysis, catalog, hit, _ = _fixture(
        tmp_path,
        [_positive("FAISS retrieval"), _positive("FAISS retrieval with Qwen")],
        text=text,
    )

    mapping = _run(service, analysis, catalog, hit)

    assert mapping.atom_results[0].links[0].source_span.exact_quote == (
        "FAISS retrieval with Qwen"
    )
    assert len(provider.calls) == 2


def test_failed_quote_repair_downgrades_candidate_and_fails_closed(
    tmp_path: Path,
) -> None:
    service, provider, analysis, catalog, hit, _ = _fixture(
        tmp_path,
        [_positive("outside"), _positive("still outside")],
    )

    result = _run(service, analysis, catalog, hit).atom_results[0]

    assert len(provider.calls) == 2
    assert result.semantic_support == "unsupported"
    assert result.match_status == "gap"
    assert result.links == []


def test_model_supplied_offset_is_rejected_and_cannot_affect_span(tmp_path: Path) -> None:
    quote = "Qwen embeddings and FAISS retrieval"
    service, provider, analysis, catalog, hit, document = _fixture(
        tmp_path,
        [_positive(quote, start_offset=999), _positive(quote)],
    )

    mapping = _run(service, analysis, catalog, hit)

    assert mapping.atom_results[0].links[0].source_span.start_offset == (
        document.text.index(quote)
    )
    assert len(provider.calls) == 2


def test_system_applies_c2_cap_without_model_level(tmp_path: Path) -> None:
    quote = "Qwen embeddings and FAISS retrieval"
    service, _, analysis, catalog, hit, _ = _fixture(
        tmp_path,
        [_positive(quote)],
        artifact_type="design_record",
    )

    result = _run(service, analysis, catalog, hit).atom_results[0]

    assert result.semantic_support == "supported"
    assert result.links[0].level.value == "C2"
    assert result.match_status == "supported"


def test_unsupported_has_no_evidence_link(tmp_path: Path) -> None:
    response = {
        "atom_results": [
            {
                "atom_id": "atom_001",
                "candidate_judgments": [
                    {
                        "chunk_id": "chunk-rag",
                        "semantic_support": "unsupported",
                        "exact_quote": None,
                    }
                ],
            }
        ]
    }
    service, _, analysis, catalog, hit, _ = _fixture(tmp_path, [response])

    result = _run(service, analysis, catalog, hit).atom_results[0]

    assert result.semantic_support == "unsupported"
    assert result.match_status == "gap"
    assert result.links == []


def test_historical_provenance_remains_bound_to_original_document_version(
    tmp_path: Path,
) -> None:
    quote = "Qwen embeddings and FAISS retrieval"
    service, _, analysis, catalog, hit, original = _fixture(
        tmp_path,
        [_positive(quote)],
    )

    link = _run(service, analysis, catalog, hit).atom_results[0].links[0]
    newer = create_knowledge_document(
        document_id=original.document_id,
        source_type=original.source_type,
        text="A later version without the original evidence quote.",
        version=2,
        title=original.title,
        metadata=original.metadata,
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert link.source_span.content_hash == original.content_hash
    assert link.source_span.content_hash != newer.content_hash
    assert original.text[
        link.source_span.start_offset : link.source_span.end_offset
    ] == quote


def test_candidate_wise_aggregation_prefers_support_then_retrieval_rank() -> None:
    first_chunk = KnowledgeChunk(
        chunk_id="chunk-first",
        document_id="doc-first",
        document_version=1,
        document_content_hash="a" * 64,
        text="Explicit subset.",
        chunk_index=0,
        start_offset=0,
        end_offset=len("Explicit subset."),
    )
    second_chunk = first_chunk.model_copy(
        update={
            "chunk_id": "chunk-second",
            "document_id": "doc-second",
            "document_content_hash": "b" * 64,
            "text": "Explicit whole requirement.",
            "end_offset": len("Explicit whole requirement."),
        }
    )
    hits = {
        "chunk-first": RetrievedChunk(
            chunk=first_chunk,
            score=0.9,
            rank=1,
            retrieval_method="dense",
        ),
        "chunk-second": RetrievedChunk(
            chunk=second_chunk,
            score=0.8,
            rank=2,
            retrieval_method="dense",
        ),
    }
    item = RetrievedAtomEvidenceCandidate.model_validate(
        {
            "atom_id": "atom_001",
            "candidate_judgments": [
                {
                    "chunk_id": "chunk-first",
                    "semantic_support": "partial",
                    "exact_quote": "Explicit subset.",
                },
                {
                    "chunk_id": "chunk-second",
                    "semantic_support": "supported",
                    "exact_quote": "Explicit whole requirement.",
                },
            ],
        }
    )

    assert _select_best_judgment(item, hits).chunk_id == "chunk-second"

    partial_item = item.model_copy(
        update={
            "candidate_judgments": [
                judgment.model_copy(update={"semantic_support": "partial"})
                for judgment in item.candidate_judgments
            ]
        }
    )
    assert _select_best_judgment(partial_item, hits).chunk_id == "chunk-first"


def test_unknown_candidate_id_is_rejected(tmp_path: Path) -> None:
    response = {
        "atom_results": [
            {
                "atom_id": "atom_001",
                "candidate_judgments": [
                    {
                        "chunk_id": "unknown-chunk",
                        "semantic_support": "unsupported",
                        "exact_quote": None,
                    }
                ],
            }
        ]
    }
    service, provider, analysis, catalog, hit, _ = _fixture(tmp_path, [response])

    with pytest.raises(AgentGuardError, match="unknown_candidate_chunk"):
        _run(service, analysis, catalog, hit)

    assert len(provider.calls) == 1
