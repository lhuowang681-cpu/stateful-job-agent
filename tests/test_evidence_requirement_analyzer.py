from pathlib import Path

import pytest

from job_agent.evidence.contracts import SourceInput
from job_agent.evidence.requirements import RequirementAnalyzer
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.llm.harness import LLMHarness, LLMInvocationError
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.skill_registry import SkillSpec
from job_agent.schemas import StructuredJD


class _Registry:
    def get(self, skill_id: str) -> SkillSpec:
        return SkillSpec(
            skill_id=skill_id,
            version="fixture-v1",
            instructions="Extract explicit requirements only.",
            reference_paths=(Path("skill-references/jd-analysis.md"),),
            output_schema=StructuredJD,
        )


def test_requirement_analyzer_builds_bounded_atoms_with_exact_jd_span(tmp_path: Path):
    jd = "独立完成训练和评测"
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot("run-1", [SourceInput(kind="raw_jd", display_label="JD", text=jd)])
    document = catalog.documents[0]
    provider = MockLLMProvider(
        [
            {
                "requirements": [
                    {
                        "text": "训练",
                        "importance": "must",
                        "hard_gate": True,
                        "exact_quote": "训练",
                        "verification_signals": ["训练流程"],
                    },
                    {
                        "text": "评测",
                        "importance": "must",
                        "hard_gate": True,
                        "exact_quote": "评测",
                        "verification_signals": ["评测设计"],
                    },
                ],
                "warnings": [],
            }
        ]
    )
    analysis = RequirementAnalyzer(
        registry=_Registry(), harness=LLMHarness(provider), source_store=store
    ).analyze(document, catalog=catalog, session_id="s1", run_id="run-1")
    assert [item.text for item in analysis.atoms] == ["训练", "评测"]
    assert analysis.warnings == ["insufficient_jd_detail"]
    assert len(provider.calls) == 1


def test_requirement_analyzer_accepts_explicit_zero_requirement_result(tmp_path: Path):
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot("run-1", [SourceInput(kind="raw_jd", display_label="JD", text="岗位介绍")])
    provider = MockLLMProvider([{"requirements": [], "warnings": []}])
    result = RequirementAnalyzer(
        registry=_Registry(), harness=LLMHarness(provider), source_store=store
    ).analyze(catalog.documents[0], catalog=catalog, session_id="s1", run_id="run-1")
    assert result.atoms == []
    assert "insufficient_jd_detail" in result.warnings


def test_requirement_analyzer_materializes_quote_only_candidate(tmp_path: Path):
    jd = "前缀 独立评测 后缀"
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot(
        "run-1", [SourceInput(kind="raw_jd", display_label="JD", text=jd)]
    )
    document = catalog.documents[0]
    provider = MockLLMProvider(
        [
            {
                "requirements": [
                    {
                        "text": "独立评测",
                        "importance": "must",
                        "hard_gate": False,
                        "exact_quote": "独立评测",
                        "verification_signals": [],
                    }
                ],
                "warnings": [],
            }
        ]
    )
    analysis = RequirementAnalyzer(
        registry=_Registry(), harness=LLMHarness(provider), source_store=store
    ).analyze(document, catalog=catalog, session_id="s1", run_id="run-1")
    assert analysis.atoms[0].source_span.start_offset == 3
    assert len(provider.calls) == 1


def test_requirement_analyzer_repairs_ambiguous_quote_with_longer_quote(
    tmp_path: Path,
):
    jd = "要求：Python。加分：Python。"
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot("run-1", [SourceInput(kind="raw_jd", display_label="JD", text=jd)])
    base = {
        "requirements": [
            {
                "text": "Python",
                "importance": "must",
                "hard_gate": False,
                "exact_quote": "Python",
                "verification_signals": [],
            }
        ],
        "warnings": [],
    }
    repaired = {
        "requirements": [
            {
                "text": "Python",
                "importance": "must",
                "hard_gate": False,
                "exact_quote": "要求：Python",
                "verification_signals": [],
            }
        ],
        "warnings": [],
    }
    provider = MockLLMProvider([base, repaired])
    result = RequirementAnalyzer(
        registry=_Registry(), harness=LLMHarness(provider), source_store=store
    ).analyze(catalog.documents[0], catalog=catalog, session_id="s1", run_id="run-1")
    assert result.parents[0].source_span.start_offset == 0
    assert len(provider.calls) == 2
    assert "ambiguous_source_quote" in provider.calls[1]["user_prompt"]


def _compact_requirement(text: str) -> dict:
    return {
        "requirements": [
            {
                "text": text,
                "importance": "must",
                "hard_gate": False,
                "exact_quote": text,
                "verification_signals": [],
            }
        ],
        "warnings": [],
    }


def test_long_jd_compact_output_uses_deterministic_ids(tmp_path: Path) -> None:
    requirement = "Experience building reliable evaluation frameworks"
    jd = ("Company introduction and benefits. " * 500) + requirement
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot(
        "long-jd",
        [SourceInput(kind="raw_jd", display_label="JD", text=jd)],
    )
    provider = MockLLMProvider([_compact_requirement(requirement)])

    result = RequirementAnalyzer(
        registry=_Registry(), harness=LLMHarness(provider), source_store=store
    ).analyze(
        catalog.documents[0],
        catalog=catalog,
        session_id="long-jd",
        run_id="long-jd",
    )

    assert result.parents[0].requirement_id == "req_001"
    assert result.parents[0].atom_ids == ["atom_001"]
    assert result.atoms[0].atom_id == "atom_001"
    assert result.atoms[0].parent_requirement_id == "req_001"
    assert provider.calls[0]["max_output_tokens"] == 2048
    schema_properties = provider.calls[0]["output_schema"].model_json_schema()[
        "properties"
    ]
    assert set(schema_properties) == {"requirements", "warnings"}


def test_invalid_first_output_gets_exactly_one_repair(tmp_path: Path) -> None:
    requirement = "Build RAG retrieval"
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot(
        "repair",
        [SourceInput(kind="raw_jd", display_label="JD", text=requirement)],
    )
    provider = MockLLMProvider(["not-json", _compact_requirement(requirement)])

    result = RequirementAnalyzer(
        registry=_Registry(), harness=LLMHarness(provider), source_store=store
    ).analyze(
        catalog.documents[0],
        catalog=catalog,
        session_id="repair",
        run_id="repair",
    )

    assert result.atoms[0].text == requirement
    assert len(provider.calls) == 2


def test_failed_requirement_repair_fails_closed_without_fallback(tmp_path: Path) -> None:
    store = EvidenceSourceStore(tmp_path)
    catalog = store.snapshot(
        "failed-repair",
        [SourceInput(kind="raw_jd", display_label="JD", text="Build RAG retrieval")],
    )
    provider = MockLLMProvider(["not-json", "still-not-json"])
    harness = LLMHarness(provider)

    with pytest.raises(LLMInvocationError, match="invalid_json"):
        RequirementAnalyzer(
            registry=_Registry(), harness=harness, source_store=store
        ).analyze(
            catalog.documents[0],
            catalog=catalog,
            session_id="failed-repair",
            run_id="failed-repair",
        )

    assert len(provider.calls) == 2
    assert all(not trace.fallback_used for trace in harness.traces)
