from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_agent.evaluation.atomic_evidence_v2 import (
    AtomicCandidateEntailment,
    AtomicEntailmentCache,
    EvidenceBenchmarkV2,
    aggregate_parent_status,
    atomic_requirement_id,
    entailment_cache_key,
    load_evidence_benchmark_v2,
)
from job_agent.evaluation.real_atomic_evidence import _fail_closed_invalid_quote
from job_agent.evaluation.real_atomic_evidence import _observations
from job_agent.knowledge.contracts import RetrievedChunk
from job_agent.knowledge.ingestion import (
    chunk_knowledge_document,
    create_knowledge_document,
)


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "eval" / "real_career_evidence_v2" / "regression.json"
DEV_REVIEW = ROOT / "eval" / "real_career_evidence_v2" / "dev_review.json"


def test_regression_benchmark_has_complete_atomic_lineage() -> None:
    benchmark = load_evidence_benchmark_v2(BENCHMARK)

    assert benchmark.dataset_status == "regression"
    assert len(benchmark.parents) == 36
    assert sum(len(parent.atoms) for parent in benchmark.parents) == 97
    assert sum(len(parent.atoms) > 1 for parent in benchmark.parents) >= 8
    assert all(parent.original_split == "frozen" for parent in benchmark.parents)
    assert all(
        atom.atom_id == atomic_requirement_id(parent.requirement_id, index)
        for parent in benchmark.parents
        for index, atom in enumerate(parent.atoms, start=1)
    )


def test_compound_parent_maps_atoms_and_multiple_acceptable_sources() -> None:
    benchmark = load_evidence_benchmark_v2(BENCHMARK)
    parent = next(
        item
        for item in benchmark.parents
        if item.requirement_id == "greenhouse-scaleai-4720478005-req-02"
    )

    assert len(parent.atoms) == 5
    assert parent.gold_parent_status == "partial"
    assert any(len(atom.acceptable_sources) > 1 for atom in parent.atoms)
    assert parent.correction_history[0].old_label == "supported"
    assert parent.correction_history[0].new_label == "partial"


def test_named_dev_review_cases_use_same_auditable_v2_schema() -> None:
    benchmark = load_evidence_benchmark_v2(DEV_REVIEW)

    assert benchmark.dataset_status == "dev"
    assert len(benchmark.parents) == 2
    assert sum(len(parent.atoms) for parent in benchmark.parents) == 7
    assert {parent.requirement_id for parent in benchmark.parents} == {
        "greenhouse-anthropic-5285246008-req-01",
        "greenhouse-anthropic-5395767008-req-02",
    }
    assert all(parent.correction_history for parent in benchmark.parents)


@pytest.mark.parametrize(
    ("supported", "expected"),
    [
        ((True, True, True), "supported"),
        ((True, False, False), "partial"),
        ((False, False, False), "gap"),
    ],
)
def test_parent_aggregation_is_deterministic(
    supported: tuple[bool, bool, bool],
    expected: str,
) -> None:
    atom_ids = ["a", "b", "c"]
    result = aggregate_parent_status(
        dict(zip(atom_ids, supported)),
        required_atom_ids=atom_ids,
    )

    assert result.status == expected
    assert result.explanation == f"{sum(supported)}/3 required atoms supported"


def test_parent_aggregation_rejects_missing_atom_decision() -> None:
    with pytest.raises(ValueError, match="missing atom decisions"):
        aggregate_parent_status({"a": True}, required_atom_ids=["a", "b"])


def test_binary_entailment_requires_quote_only_for_supported_pair() -> None:
    supported = AtomicCandidateEntailment(
        chunk_id="chunk-1",
        entails=True,
        exact_quote="direct support",
        concise_reason="The quote directly states the atomic capability.",
    )
    unsupported = AtomicCandidateEntailment(
        chunk_id="chunk-2",
        entails=False,
        concise_reason="The chunk is only topically related.",
    )

    assert supported.entails is True
    assert unsupported.exact_quote is None
    with pytest.raises(ValidationError):
        AtomicCandidateEntailment(
            chunk_id="chunk-3",
            entails=False,
            exact_quote="must not be linked",
            concise_reason="Unsupported atoms have no EvidenceLink.",
        )


def test_invalid_or_ambiguous_quote_fails_closed_without_evidence_link() -> None:
    judgment = AtomicCandidateEntailment(
        chunk_id="chunk-1",
        entails=True,
        exact_quote="repeat",
        concise_reason="The model proposed a repeated quote.",
    )

    result = _fail_closed_invalid_quote(judgment, "repeat then repeat")

    assert result.entails is False
    assert result.exact_quote is None
    assert result.concise_reason == "Invalid or ambiguous exact quote; failed closed."


def test_atomic_observation_preserves_exact_quote_and_provenance() -> None:
    document = create_knowledge_document(
        document_id="project-runtime",
        source_type="project",
        text="The runtime persists checkpoints for durable recovery.",
        version=1,
    )
    chunk = chunk_knowledge_document(document, max_chars=200)[0]
    hit = RetrievedChunk(
        chunk=chunk,
        score=0.9,
        rank=1,
        retrieval_method="dense",
    )
    benchmark = load_evidence_benchmark_v2(BENCHMARK)
    template = benchmark.parents[0].atoms[0]
    atom = template.model_copy(
        update={"acceptable_sources": ["project-runtime"]}
    )
    quote = "persists checkpoints for durable recovery"
    judgment = AtomicCandidateEntailment(
        chunk_id=chunk.chunk_id,
        entails=True,
        exact_quote=quote,
        concise_reason="The source directly states durable checkpoint recovery.",
    )

    observation = _observations(
        atom,
        [hit],
        {chunk.chunk_id: judgment},
        {document.document_id: document},
    )[0]

    assert observation["quote_valid"] is True
    assert observation["provenance_valid"] is True
    assert observation["acceptable_source"] is True
    span = observation["source_span"]
    assert document.text[span["start_offset"] : span["end_offset"]] == quote


def test_cache_identity_covers_atom_chunk_model_prompt_schema_and_temperature() -> None:
    base = {
        "atom_text": "Built a retrieval pipeline",
        "chunk_id": "chunk-1",
        "chunk_content_hash": "a" * 64,
        "model_identity": "deepseek/deepseek-chat",
    }
    first = entailment_cache_key(**base)

    assert first == entailment_cache_key(**base)
    assert first != entailment_cache_key(**{**base, "atom_text": "Built memory"})
    assert first != entailment_cache_key(**{**base, "chunk_id": "chunk-2"})
    assert first != entailment_cache_key(**{**base, "model_identity": "other"})
    assert first != entailment_cache_key(**base, prompt_version="v2")
    assert first != entailment_cache_key(**base, schema_version="v2")
    assert first != entailment_cache_key(**base, temperature=0.1)


def test_entailment_cache_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    value = AtomicCandidateEntailment(
        chunk_id="chunk-1",
        entails=True,
        exact_quote="explicit statement",
        concise_reason="Direct support.",
    )
    cache = AtomicEntailmentCache(path)
    cache.put("key", value)

    assert AtomicEntailmentCache(path).get("key") == value
    assert json.loads(path.read_text(encoding="utf-8"))["key"]["entails"] is True


def test_changed_gold_requires_a_correction_log() -> None:
    benchmark = load_evidence_benchmark_v2(BENCHMARK)
    payload = benchmark.model_dump(mode="json")
    changed = next(
        item
        for item in payload["parents"]
        if item["lineage_gold_status"] != item["gold_parent_status"]
    )
    changed["correction_history"] = []

    with pytest.raises(ValidationError, match="changed parent gold"):
        EvidenceBenchmarkV2.model_validate(payload)


def test_job_match_explanation_reports_supported_atom_ratio() -> None:
    result = aggregate_parent_status(
        {"atom-1": True, "atom-2": True, "atom-3": False},
        required_atom_ids=["atom-1", "atom-2", "atom-3"],
    )

    assert result.status == "partial"
    assert result.supported_atoms == 2
    assert result.required_atoms == 3
    assert result.explanation == "2/3 required atoms supported"
