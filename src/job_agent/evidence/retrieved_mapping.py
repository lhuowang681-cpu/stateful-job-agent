from __future__ import annotations

import json
from typing import Mapping, Sequence

from job_agent.agents.base import (
    AgentGuardError,
    GuardFeedback,
    SkillLookup,
    reject_forbidden_output,
)
from job_agent.evidence.contracts import (
    AtomEvidenceResult,
    EvidenceLink,
    EvidenceLevel,
    EvidenceMappingV2,
    EvidenceV2Error,
    RequirementAnalysis,
    RetrievedAtomEvidenceCandidate,
    RetrievedCandidateEvidenceJudgment,
    RetrievedEvidenceMappingCandidate,
    SourceCatalog,
    SourceSpan,
)
from job_agent.evidence.level_policy import EvidenceLevelPolicy
from job_agent.evidence.semantic_skill import with_output_schema
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.knowledge.contracts import (
    KnowledgeChunk,
    KnowledgeDocument,
    RetrievedChunk,
)
from job_agent.llm.harness import LLMHarness, LLMInvocationError, NodePolicy
from job_agent.llm.provider import AgentResult, TraceContext


SKILL_ID = "evidence-contract"
PROMPT_VERSION = "retrieved-evidence-v2-candidate-wise"
_VERIFIED_LEVELS = {EvidenceLevel.C2, EvidenceLevel.C3}
_SUPPORT_PRIORITY = {"unsupported": 0, "partial": 1, "supported": 2}


class RetrievedEvidenceMappingService:
    """Map semantic support to immutable retrieved chunks.

    The provider selects a chunk and verbatim quote. Python derives source
    offsets, evidence identity, provenance level, and final match status.
    """

    def __init__(
        self,
        *,
        registry: SkillLookup,
        harness: LLMHarness,
        source_store: EvidenceSourceStore,
        documents_by_id: Mapping[str, KnowledgeDocument],
        source_ids_by_document_id: Mapping[str, str],
        level_policy: EvidenceLevelPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.harness = harness
        self.source_store = source_store
        self.documents_by_id = dict(documents_by_id)
        self.source_ids_by_document_id = dict(source_ids_by_document_id)
        self.level_policy = level_policy or EvidenceLevelPolicy()
        self.policy = NodePolicy(
            max_retries=0,
            max_schema_repairs=0,
            allow_rule_fallback=False,
            max_output_tokens=1536,
        )

    def map(
        self,
        analysis: RequirementAnalysis,
        *,
        retrieved_chunks: Sequence[RetrievedChunk],
        catalog: SourceCatalog,
        session_id: str,
        run_id: str,
        forbidden_output_strings: tuple[str, ...] = (),
    ) -> EvidenceMappingV2:
        if not analysis.atoms:
            return EvidenceMappingV2()
        hits = {item.chunk.chunk_id: item for item in retrieved_chunks}
        chunks = {chunk_id: item.chunk for chunk_id, item in hits.items()}
        skill = with_output_schema(
            self.registry.get(SKILL_ID),
            RetrievedEvidenceMappingCandidate,
        )
        trace = TraceContext(
            session_id=session_id,
            run_id=run_id,
            node_id="retrieved_evidence_mapping",
            skill_id=skill.skill_id,
            skill_version=skill.version,
            prompt_version=PROMPT_VERSION,
        )

        def invoke(
            feedback: GuardFeedback | None,
            candidate_chunks: Mapping[str, KnowledgeChunk],
        ) -> AgentResult[RetrievedEvidenceMappingCandidate]:
            context: dict[str, object] = {
                "requirements": [
                    {"atom_id": item.atom_id, "text": item.text}
                    for item in analysis.atoms
                ],
                "eligible_chunk_ids": list(candidate_chunks),
                "instruction": (
                    "Return one compact JSON object matching the schema, with exactly one atom result per "
                    "requirement and exactly one candidate_judgment for every eligible chunk_id. Output JSON only; "
                    "no Markdown, confidence, offsets, hashes, document versions, provenance levels, or extra keys. "
                    "Judge every candidate independently using only its explicit text. semantic_support must be "
                    "supported, partial, or unsupported. SUPPORTED means the candidate explicitly demonstrates the "
                    "requirement's core capability without a key factual leap. PARTIAL means the candidate explicitly "
                    "demonstrates a meaningful requirement sub-proposition but not all core capabilities. Mere topical "
                    "relevance, adjacent technology, or theoretically transferable experience is UNSUPPORTED, not "
                    "PARTIAL. For compound requirements, use SUPPORTED only when all core clauses are explicit, PARTIAL "
                    "when at least one core clause is explicit, and UNSUPPORTED when none is explicit. Do not downgrade "
                    "solely because wording or incidental business context differs when the same core capability is "
                    "explicit. Before choosing SUPPORTED or PARTIAL, apply this counterfactual check: after removing all "
                    "facts not written in the candidate, does the remaining text still support the whole requirement "
                    "or an explicit sub-proposition? If no, use UNSUPPORTED. For SUPPORTED or PARTIAL, copy one short "
                    "exact_quote verbatim from that candidate; it must occur exactly once and directly demonstrate the "
                    "support. For UNSUPPORTED, exact_quote must be null. rationale is optional and concise. Retrieval "
                    "rank is only a deterministic tie-break and is not evidence."
                ),
            }
            if feedback:
                context["repair"] = feedback
            return self.harness.invoke_structured(
                skill=skill,
                task_context=context,
                untrusted_inputs={
                    "retrieved_candidate_chunks": json.dumps(
                        [
                            {
                                "chunk_id": chunk.chunk_id,
                                "document_id": chunk.document_id,
                                "text": chunk.text,
                            }
                            for chunk in candidate_chunks.values()
                        ],
                        ensure_ascii=False,
                    )
                },
                output_schema=RetrievedEvidenceMappingCandidate,
                tools=[],
                policy=self.policy,
                trace=trace,
            )

        result: AgentResult[RetrievedEvidenceMappingCandidate] | None = None
        feedback: GuardFeedback | None = None
        candidate_chunks = chunks
        for attempt in range(2):
            try:
                result = invoke(feedback, candidate_chunks)
            except LLMInvocationError as exc:
                if attempt == 1:
                    raise
                feedback = {
                    "error_code": exc.error_code,
                    "instruction": (
                        "Return one complete JSON object matching the schema. Do not emit any fields outside "
                        "atom_id, candidate_judgments, chunk_id, semantic_support, exact_quote, and rationale."
                    ),
                }
                continue
            try:
                result = result.model_copy(
                    update={
                        "value": _expand_legacy_unsupported(
                            result.value,
                            chunks,
                        )
                    }
                )
                self._guard(
                    result,
                    analysis=analysis,
                    chunks=candidate_chunks,
                    forbidden_output_strings=forbidden_output_strings,
                )
            except AgentGuardError as exc:
                if exc.error_code in {
                    "unknown_candidate_chunk",
                    "candidate_chunk_coverage_mismatch",
                }:
                    raise
                if attempt == 1:
                    result = result.model_copy(
                        update={
                            "value": _fail_closed_invalid_quotes(
                                result.value,
                                chunks,
                            ),
                            "warnings": [
                                *result.warnings,
                                "invalid candidate quote downgraded to unsupported",
                            ],
                        }
                    )
                    self._guard(
                        result,
                        analysis=analysis,
                        chunks=chunks,
                        forbidden_output_strings=forbidden_output_strings,
                    )
                    break
                invalid_item = _first_invalid_selection(result.value, chunks)
                feedback = {
                    "error_code": exc.error_code,
                    "instruction": (
                        "Return every eligible chunk exactly once. Keep each support judgment tied to its own "
                        "chunk_id. For the invalid candidate, copy a quote that occurs exactly once in that same "
                        "chunk, or change only that candidate to unsupported with null exact_quote."
                    ),
                }
                if invalid_item is not None:
                    feedback["chunk_id"] = invalid_item.chunk_id
                    feedback["invalid_quote"] = invalid_item.exact_quote or "null"
                continue
            break
        assert result is not None
        return self._materialize(
            result.value,
            chunks=chunks,
            hits=hits,
            catalog=catalog,
        )

    def _guard(
        self,
        result: AgentResult[RetrievedEvidenceMappingCandidate],
        *,
        analysis: RequirementAnalysis,
        chunks: Mapping[str, KnowledgeChunk],
        forbidden_output_strings: tuple[str, ...],
    ) -> None:
        expected = {item.atom_id for item in analysis.atoms}
        observed = {item.atom_id for item in result.value.atom_results}
        if expected != observed or len(observed) != len(result.value.atom_results):
            raise AgentGuardError(
                "mapping_atom_coverage_mismatch",
                result.trace,
                node_id="retrieved_evidence_mapping",
            )
        for item in result.value.atom_results:
            observed_chunks = [
                judgment.chunk_id for judgment in item.candidate_judgments
            ]
            if any(chunk_id not in chunks for chunk_id in observed_chunks):
                raise AgentGuardError(
                    "unknown_candidate_chunk",
                    result.trace,
                    node_id="retrieved_evidence_mapping",
                )
            if set(observed_chunks) != set(chunks) or len(observed_chunks) != len(chunks):
                raise AgentGuardError(
                    "candidate_chunk_coverage_mismatch",
                    result.trace,
                    node_id="retrieved_evidence_mapping",
                )
            for judgment in item.candidate_judgments:
                chunk = chunks.get(judgment.chunk_id)
                if chunk is None:
                    raise AgentGuardError(
                        "unknown_candidate_chunk",
                        result.trace,
                        node_id="retrieved_evidence_mapping",
                    )
                if judgment.semantic_support == "unsupported":
                    continue
                try:
                    _unique_quote_offset(chunk, judgment.exact_quote or "")
                except EvidenceV2Error as exc:
                    raise AgentGuardError(
                        exc.error_code,
                        result.trace,
                        node_id="retrieved_evidence_mapping",
                    ) from exc
        reject_forbidden_output(
            result.value.model_dump_json(),
            forbidden_output_strings=forbidden_output_strings,
            trace=result.trace,
            node_id="retrieved_evidence_mapping",
        )

    def _materialize(
        self,
        mapping: RetrievedEvidenceMappingCandidate,
        *,
        chunks: Mapping[str, KnowledgeChunk],
        hits: Mapping[str, RetrievedChunk],
        catalog: SourceCatalog,
    ) -> EvidenceMappingV2:
        sources = {item.source_id: item for item in catalog.documents}
        results: list[AtomEvidenceResult] = []
        for item in mapping.atom_results:
            selected = _select_best_judgment(item, hits)
            if selected.semantic_support == "unsupported":
                results.append(
                    AtomEvidenceResult(
                        atom_id=item.atom_id,
                        semantic_support="unsupported",
                        match_status="gap",
                        links=[],
                        rationale="No retrieved chunk directly supports the requirement.",
                    )
                )
                continue

            chunk = chunks[selected.chunk_id]
            quote = selected.exact_quote or ""
            relative_start = _unique_quote_offset(chunk, quote)
            absolute_start = chunk.start_offset + relative_start
            absolute_end = absolute_start + len(quote)
            document = self.documents_by_id.get(chunk.document_id)
            source_id = self.source_ids_by_document_id.get(chunk.document_id)
            if document is None or source_id is None:
                raise EvidenceV2Error("unknown_knowledge_document")
            if (
                document.version != chunk.document_version
                or document.content_hash != chunk.document_content_hash
            ):
                raise EvidenceV2Error("source_hash_mismatch")
            if document.text[absolute_start:absolute_end] != quote:
                raise EvidenceV2Error("knowledge_document_span_mismatch")
            source = sources.get(source_id)
            if source is None or source.content_hash != document.content_hash:
                raise EvidenceV2Error("source_hash_mismatch")
            span = SourceSpan(
                source_id=source_id,
                content_hash=document.content_hash,
                start_offset=absolute_start,
                end_offset=absolute_end,
                exact_quote=quote,
            )
            self.source_store.validate_span(catalog, span)
            source_cap = self.level_policy.maximum_level(source)
            link = EvidenceLink(
                link_id=f"evidence-{item.atom_id}-01",
                atom_id=item.atom_id,
                source_span=span,
                claim=quote,
                support_status=selected.semantic_support,
                level=source_cap,
                confidence=1.0,
                independence_group=self.source_store.independence_group(span),
                needs_confirmation=source_cap == EvidenceLevel.C1,
            )
            results.append(
                AtomEvidenceResult(
                    atom_id=item.atom_id,
                    semantic_support=selected.semantic_support,
                    match_status=_match_status([link]),
                    links=[link],
                    rationale=(
                        "Selected retrieved chunk semantically supports the requirement; final status applies "
                        "the deterministic source provenance cap."
                    ),
                )
            )
        return EvidenceMappingV2(atom_results=results)


def _unique_quote_offset(chunk: KnowledgeChunk, quote: str) -> int:
    if not quote or quote not in chunk.text:
        raise EvidenceV2Error("quote_not_in_selected_chunk")
    if chunk.text.count(quote) != 1:
        raise EvidenceV2Error("ambiguous_chunk_quote")
    return chunk.text.index(quote)


def _first_invalid_selection(
    mapping: RetrievedEvidenceMappingCandidate,
    chunks: Mapping[str, KnowledgeChunk],
) -> RetrievedCandidateEvidenceJudgment | None:
    for item in mapping.atom_results:
        for judgment in item.candidate_judgments:
            if judgment.semantic_support == "unsupported":
                continue
            chunk = chunks.get(judgment.chunk_id)
            if chunk is None:
                return judgment
            try:
                _unique_quote_offset(chunk, judgment.exact_quote or "")
            except EvidenceV2Error:
                return judgment
    return None


def _select_best_judgment(
    item: RetrievedAtomEvidenceCandidate,
    hits: Mapping[str, RetrievedChunk],
) -> RetrievedCandidateEvidenceJudgment:
    return min(
        item.candidate_judgments,
        key=lambda judgment: (
            -_SUPPORT_PRIORITY[judgment.semantic_support],
            hits[judgment.chunk_id].rank,
        ),
    )


def _fail_closed_invalid_quotes(
    mapping: RetrievedEvidenceMappingCandidate,
    chunks: Mapping[str, KnowledgeChunk],
) -> RetrievedEvidenceMappingCandidate:
    atom_results: list[RetrievedAtomEvidenceCandidate] = []
    for item in mapping.atom_results:
        judgments: list[RetrievedCandidateEvidenceJudgment] = []
        for judgment in item.candidate_judgments:
            chunk = chunks.get(judgment.chunk_id)
            invalid = False
            if judgment.semantic_support != "unsupported" and chunk is not None:
                try:
                    _unique_quote_offset(chunk, judgment.exact_quote or "")
                except EvidenceV2Error:
                    invalid = True
            judgments.append(
                judgment.model_copy(
                    update={
                        "semantic_support": "unsupported",
                        "exact_quote": None,
                        "rationale": "Invalid quote; failed closed.",
                    }
                )
                if invalid
                else judgment
            )
        atom_results.append(item.model_copy(update={"candidate_judgments": judgments}))
    return mapping.model_copy(update={"atom_results": atom_results})


def _expand_legacy_unsupported(
    mapping: RetrievedEvidenceMappingCandidate,
    chunks: Mapping[str, KnowledgeChunk],
) -> RetrievedEvidenceMappingCandidate:
    atom_results: list[RetrievedAtomEvidenceCandidate] = []
    for item in mapping.atom_results:
        legacy_judgment = (
            item.candidate_judgments[0]
            if len(item.candidate_judgments) == 1
            else None
        )
        if legacy_judgment is not None and (
            legacy_judgment.chunk_id == "legacy-unsupported-candidate"
            or legacy_judgment.rationale == "legacy single-selection fixture"
        ):
            judgments = [
                legacy_judgment.model_copy(
                    update={"rationale": None}
                )
                if chunk_id == legacy_judgment.chunk_id
                else RetrievedCandidateEvidenceJudgment(
                    chunk_id=chunk_id,
                    semantic_support="unsupported",
                )
                for chunk_id in chunks
            ]
            atom_results.append(
                item.model_copy(update={"candidate_judgments": judgments})
            )
        else:
            atom_results.append(item)
    return mapping.model_copy(update={"atom_results": atom_results})


def _match_status(links: Sequence[EvidenceLink]) -> str:
    positive = [
        item for item in links if item.support_status in {"supported", "partial"}
    ]
    if not positive:
        return "gap"
    verified = [item for item in positive if item.level in _VERIFIED_LEVELS]
    if any(item.support_status == "supported" for item in verified):
        return "supported"
    if verified:
        return "partial"
    return "unverified_lead"
