from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import Field, model_validator

from job_agent.schemas import StrictModel


AtomGoldLabel = Literal["supported", "unsupported"]
ParentEvidenceStatus = Literal["supported", "partial", "gap"]
DatasetStatus = Literal["dev", "regression", "holdout"]

BENCHMARK_VERSION = "real-career-evidence-v2"
SCHEMA_VERSION = "atomic-entailment-v1"
PROMPT_VERSION = "atomic-entailment-v1"


def normalize_atomic_text(value: str) -> str:
    return " ".join(value.casefold().split())


def atomic_requirement_id(parent_requirement_id: str, index: int) -> str:
    if index < 1:
        raise ValueError("atomic requirement index must be positive")
    return f"{parent_requirement_id}::atom-{index:02d}"


class GoldCorrection(StrictModel):
    old_label: str = Field(min_length=1)
    new_label: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class AtomicRequirementGold(StrictModel):
    atom_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    required: bool = True
    gold_entailment: AtomGoldLabel
    acceptable_sources: list[str] = Field(default_factory=list)
    annotation_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sources(self) -> "AtomicRequirementGold":
        if len(self.acceptable_sources) != len(set(self.acceptable_sources)):
            raise ValueError("acceptable_sources must be unique")
        if self.gold_entailment == "unsupported" and self.acceptable_sources:
            raise ValueError("unsupported atom cannot have acceptable sources")
        if self.gold_entailment == "supported" and not self.acceptable_sources:
            raise ValueError("supported atom requires acceptable sources")
        if re.search(r"\b(and|以及|并且)\b", self.text, flags=re.IGNORECASE):
            raise ValueError("atomic text must not join independent claims with 'and'")
        return self


class EvidenceBenchmarkParent(StrictModel):
    requirement_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    original_split: Literal["dev", "frozen"]
    dataset_status: DatasetStatus
    raw_requirement: str = Field(min_length=1)
    lineage_gold_status: str = Field(min_length=1)
    lineage_sources: list[str] = Field(default_factory=list)
    atoms: list[AtomicRequirementGold] = Field(min_length=1)
    aggregation_rule: Literal["all_required"] = "all_required"
    gold_parent_status: ParentEvidenceStatus
    acceptable_sources: list[str] = Field(default_factory=list)
    annotation_notes: str = Field(min_length=1)
    correction_history: list[GoldCorrection] = Field(default_factory=list)
    ambiguity_status: Literal["resolved", "unresolved"] = "resolved"

    @model_validator(mode="after")
    def validate_parent(self) -> "EvidenceBenchmarkParent":
        expected_ids = [
            atomic_requirement_id(self.requirement_id, index)
            for index in range(1, len(self.atoms) + 1)
        ]
        if [item.atom_id for item in self.atoms] != expected_ids:
            raise ValueError("atom ids must be deterministic and ordered")
        atom_ids = [item.atom_id for item in self.atoms]
        if len(atom_ids) != len(set(atom_ids)):
            raise ValueError("atom ids must be unique")
        expected_status = aggregate_parent_status(
            {item.atom_id: item.gold_entailment == "supported" for item in self.atoms},
            required_atom_ids=[item.atom_id for item in self.atoms if item.required],
        ).status
        if self.gold_parent_status != expected_status:
            raise ValueError("gold parent status must match deterministic aggregation")
        union = sorted(
            {
                source
                for item in self.atoms
                for source in item.acceptable_sources
            }
        )
        if sorted(self.acceptable_sources) != union:
            raise ValueError("parent acceptable_sources must equal atom source union")
        if self.lineage_gold_status != self.gold_parent_status and not self.correction_history:
            raise ValueError("changed parent gold requires correction_history")
        return self


class EvidenceBenchmarkV2(StrictModel):
    benchmark_version: Literal["real-career-evidence-v2"] = BENCHMARK_VERSION
    source_dataset_version: str = Field(min_length=1)
    dataset_status: DatasetStatus
    parents: list[EvidenceBenchmarkParent] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dataset(self) -> "EvidenceBenchmarkV2":
        ids = [item.requirement_id for item in self.parents]
        if len(ids) != len(set(ids)):
            raise ValueError("parent requirement ids must be unique")
        if any(item.dataset_status != self.dataset_status for item in self.parents):
            raise ValueError("parent dataset status mismatch")
        return self


class AtomicCandidateEntailment(StrictModel):
    chunk_id: str = Field(min_length=1)
    entails: bool
    exact_quote: str | None = Field(default=None, min_length=1)
    concise_reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_quote(self) -> "AtomicCandidateEntailment":
        if self.entails and self.exact_quote is None:
            raise ValueError("entailed candidate requires an exact quote")
        if not self.entails and self.exact_quote is not None:
            raise ValueError("unsupported candidate cannot contain an exact quote")
        return self


class AtomicEntailmentBatch(StrictModel):
    atom_id: str = Field(min_length=1)
    candidate_judgments: list[AtomicCandidateEntailment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_candidates(self) -> "AtomicEntailmentBatch":
        ids = [item.chunk_id for item in self.candidate_judgments]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate chunk judgments must be unique")
        return self


class ParentAggregation(StrictModel):
    status: ParentEvidenceStatus
    supported_atoms: int = Field(ge=0)
    required_atoms: int = Field(ge=1)
    explanation: str = Field(min_length=1)


def aggregate_parent_status(
    atom_support: Mapping[str, bool],
    *,
    required_atom_ids: Sequence[str],
) -> ParentAggregation:
    required = tuple(required_atom_ids)
    if not required:
        raise ValueError("at least one required atom is needed")
    missing = [atom_id for atom_id in required if atom_id not in atom_support]
    if missing:
        raise ValueError(f"missing atom decisions: {', '.join(missing)}")
    supported = sum(bool(atom_support[atom_id]) for atom_id in required)
    status: ParentEvidenceStatus
    if supported == len(required):
        status = "supported"
    elif supported:
        status = "partial"
    else:
        status = "gap"
    return ParentAggregation(
        status=status,
        supported_atoms=supported,
        required_atoms=len(required),
        explanation=f"{supported}/{len(required)} required atoms supported",
    )


def entailment_cache_key(
    *,
    atom_text: str,
    chunk_id: str,
    chunk_content_hash: str,
    model_identity: str,
    prompt_version: str = PROMPT_VERSION,
    schema_version: str = SCHEMA_VERSION,
    temperature: float = 0.0,
) -> str:
    payload = {
        "atom": normalize_atomic_text(atom_text),
        "chunk_id": chunk_id,
        "chunk_content_hash": chunk_content_hash,
        "model_identity": model_identity,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "temperature": temperature,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AtomicEntailmentCache:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._values: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("atomic entailment cache must be a JSON object")
            self._values = raw

    def get(self, key: str) -> AtomicCandidateEntailment | None:
        value = self._values.get(key)
        return AtomicCandidateEntailment.model_validate(value) if value else None

    def put(self, key: str, value: AtomicCandidateEntailment) -> None:
        self._values[key] = value.model_dump(mode="json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self._values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @property
    def size(self) -> int:
        return len(self._values)


def load_evidence_benchmark_v2(path: str | Path) -> EvidenceBenchmarkV2:
    return EvidenceBenchmarkV2.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
