from __future__ import annotations

from job_agent.agents.base import (
    AgentGuardError,
    GuardFeedback,
    SkillLookup,
    reject_forbidden_output,
)
from job_agent.evidence.contracts import (
    EvidenceV2Error,
    ParentRequirement,
    RequirementAnalysis,
    RequirementAnalysisCandidate,
    RequirementAtom,
    SourceCatalog,
    SourceDocumentRef,
    SourceQuoteLocator,
)
from job_agent.evidence.semantic_skill import with_output_schema
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.llm.harness import LLMHarness, LLMInvocationError, NodePolicy
from job_agent.llm.provider import AgentResult, TraceContext


SKILL_ID = "jd-analysis"
PROMPT_VERSION = "evidence-requirements-v2.6-compact-semantic"


class RequirementAnalyzer:
    def __init__(
        self,
        *,
        registry: SkillLookup,
        harness: LLMHarness,
        source_store: EvidenceSourceStore,
    ) -> None:
        self.registry = registry
        self.harness = harness
        self.source_store = source_store
        self.policy = NodePolicy(
            max_retries=0,
            max_schema_repairs=0,
            allow_rule_fallback=False,
            max_output_tokens=2048,
        )

    def analyze(
        self,
        jd_source: SourceDocumentRef,
        *,
        catalog: SourceCatalog,
        session_id: str,
        run_id: str,
        forbidden_output_strings: tuple[str, ...] = (),
    ) -> RequirementAnalysis:
        if jd_source.kind != "raw_jd":
            raise ValueError("requirement analysis requires raw_jd source")
        jd_text = self.source_store.read(catalog, jd_source.source_id)
        skill = with_output_schema(self.registry.get(SKILL_ID), RequirementAnalysisCandidate)
        trace = TraceContext(
            session_id=session_id,
            run_id=run_id,
            node_id="evidence_requirements_v2",
            skill_id=skill.skill_id,
            skill_version=skill.version,
            prompt_version=PROMPT_VERSION,
        )

        def invoke(feedback: GuardFeedback | None) -> AgentResult[RequirementAnalysisCandidate]:
            context: dict[str, object] = {
                "source_id": jd_source.source_id,
                "instruction": (
                    "Return one compact JSON object matching the supplied schema. Output JSON only: no Markdown, "
                    "prose, comments, or extra keys. Emit only requirements and warnings. For each major candidate "
                    "requirement include text, importance, hard_gate, exact_quote, and verification_signals. "
                    "importance must be must, should, or nice. exact_quote must be a short verbatim substring from "
                    "the raw JD that states the requirement. Do not emit IDs, parent/atom references, source IDs, "
                    "hashes, offsets, rationales, or explanations; Python creates all structural identity. Select "
                    "major candidate requirements across technical capability, engineering experience, required "
                    "frameworks/tools, model/training, deployment/infra, and evaluation when explicitly present. "
                    "Include a core technical responsibility when it clearly defines capability or experience the "
                    "candidate must bring; rewrite it as a candidate requirement. Preserve distinct qualification "
                    "or technical-responsibility bullets as separate requirements unless they are exact duplicates. "
                    "When a JD separates responsibilities from qualifications, first retain every distinct core "
                    "technical responsibility, then add the strongest required qualifications; omit optional or "
                    "preferred qualifications before omitting a core technical responsibility. "
                    "Exclude company description, role marketing, generic routine duties, salary, benefits, "
                    "logistics, equal-opportunity text, and generic culture statements. For a long JD, prioritize "
                    "the strongest 6 to 16 requirements. Keep each requirement concise, preserve source order, "
                    "avoid duplicates, and do not split one requirement into trivial fragments. Return an empty "
                    "requirements list only when the "
                    "JD truly contains no candidate requirements."
                ),
            }
            if feedback:
                context["guard_feedback"] = feedback
            result = self.harness.invoke_structured(
                skill=skill,
                task_context=context,
                untrusted_inputs={"raw_jd": jd_text},
                output_schema=RequirementAnalysisCandidate,
                tools=[],
                policy=self.policy,
                trace=trace,
            )
            return result

        result: AgentResult[RequirementAnalysisCandidate] | None = None
        feedback: GuardFeedback | None = None
        for attempt in range(2):
            try:
                result = invoke(feedback)
            except LLMInvocationError as exc:
                if attempt == 1:
                    raise
                feedback = {
                    "error_code": exc.error_code,
                    "instruction": (
                        "The first response was invalid. Return one complete compact JSON object matching the "
                        "schema, with requirements and warnings only. Do not add Markdown or explanations."
                    ),
                }
                continue
            try:
                self._guard(
                    result,
                    catalog=catalog,
                    jd_source=jd_source,
                    forbidden_output_strings=forbidden_output_strings,
                )
            except AgentGuardError as exc:
                if attempt == 1:
                    raise
                feedback = {
                    "error_code": exc.error_code,
                    "instruction": (
                        "Regenerate one complete compact JSON object. Every exact_quote must occur exactly once "
                        "in the raw JD; use a longer verbatim quote when the short quote repeats."
                    ),
                }
                continue
            break
        assert result is not None
        analysis = self._materialize(result.value, catalog, jd_source=jd_source)
        if len(analysis.atoms) < 3 and "insufficient_jd_detail" not in analysis.warnings:
            analysis = analysis.model_copy(update={"warnings": [*analysis.warnings, "insufficient_jd_detail"]})
        return analysis

    def _materialize(
        self,
        candidate: RequirementAnalysisCandidate,
        catalog: SourceCatalog,
        *,
        jd_source: SourceDocumentRef,
    ) -> RequirementAnalysis:
        parents: list[ParentRequirement] = []
        atoms: list[RequirementAtom] = []
        for index, item in enumerate(candidate.requirements, start=1):
            requirement_id = f"req_{index:03d}"
            atom_id = f"atom_{index:03d}"
            span = self.source_store.resolve_locator(
                catalog,
                SourceQuoteLocator(
                    source_id=jd_source.source_id,
                    exact_quote=item.exact_quote,
                ),
            )
            parents.append(
                ParentRequirement(
                    requirement_id=requirement_id,
                    text=item.text,
                    importance=item.importance,
                    hard_gate=item.hard_gate,
                    source_span=span,
                    atom_ids=[atom_id],
                )
            )
            atoms.append(
                RequirementAtom(
                    atom_id=atom_id,
                    parent_requirement_id=requirement_id,
                    text=item.text,
                    source_span=span,
                    verification_signals=item.verification_signals,
                )
            )
        return RequirementAnalysis(parents=parents, atoms=atoms, warnings=candidate.warnings)

    def _guard(
        self,
        result: AgentResult[RequirementAnalysisCandidate],
        *,
        catalog: SourceCatalog,
        jd_source: SourceDocumentRef,
        forbidden_output_strings: tuple[str, ...],
    ) -> None:
        try:
            materialized = self._materialize(
                result.value,
                catalog,
                jd_source=jd_source,
            )
        except EvidenceV2Error as exc:
            raise AgentGuardError(exc.error_code, result.trace, node_id=trace_node()) from exc
        except ValueError as exc:
            raise AgentGuardError("invalid_requirement_graph", result.trace, node_id=trace_node()) from exc
        for parent in materialized.parents:
            if parent.source_span.source_id != jd_source.source_id:
                raise AgentGuardError("requirement_source_mismatch", result.trace, node_id=trace_node())
            self._validate_span(result, catalog, parent.source_span)
        for atom in materialized.atoms:
            self._validate_span(result, catalog, atom.source_span)
        reject_forbidden_output(
            result.value.model_dump_json(),
            forbidden_output_strings=forbidden_output_strings,
            trace=result.trace,
            node_id=trace_node(),
        )

    def _validate_span(self, result: AgentResult, catalog: SourceCatalog, span) -> None:
        try:
            self.source_store.validate_span(catalog, span)
        except ValueError as exc:
            raise AgentGuardError("invalid_requirement_span", result.trace, node_id=trace_node()) from exc


def trace_node() -> str:
    return "evidence_requirements_v2"
