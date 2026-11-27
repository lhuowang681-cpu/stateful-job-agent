from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Sequence

from job_agent.agent_runtime.budgets import (
    AgentBudget,
    BudgetManager,
    BudgetProfile,
)
from job_agent.agent_runtime.contracts import (
    AgentAction,
    AgentFinish,
    AgentRunStatus,
    ToolContext,
    ToolObservationStatus,
    VerificationResult,
)
from job_agent.agent_runtime.loop import AgentLoop, ScriptedAgentModel
from job_agent.agent_runtime.policy import PolicyContext, PolicyEngine
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.agent_runtime.trajectory import InMemoryTrajectory
from job_agent.evidence.contracts import SourceInput
from job_agent.evidence.requirements import RequirementAnalyzer
from job_agent.evidence.sources import EvidenceSourceStore
from job_agent.jd_match_analysis import (
    JobBasicInfo,
    JobMatchAnalysis,
    JobMatchRequirement,
    PreferenceAnalysis,
    PreferenceDimensionAnalysis,
    build_job_match_analysis,
)
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.contracts import (
    KnowledgeChunk,
    KnowledgeDocument,
    RetrievedChunk,
)
from job_agent.llm.harness import LLMHarness
from job_agent.memory.contracts import UserState
from job_agent.memory.user_state_store import UserStateStore
from job_agent.requirement_evidence import RequirementEvidenceService


class _ObservationVerifier:
    def verify(self, finish, *, goal, steps) -> VerificationResult:
        return VerificationResult(
            passed=bool(steps),
            reason_code="complete" if steps else "missing_observation",
            feedback="complete" if steps else "Execute the governed tool action.",
        )


class GovernedCareerKnowledgeRuntime:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy_context: PolicyContext,
        trajectory: InMemoryTrajectory | None = None,
        budget: BudgetManager | None = None,
        workspace_root: str = ".",
    ) -> None:
        self.registry = registry
        self.policy_context = policy_context
        self.trajectory = trajectory or InMemoryTrajectory()
        self.budget = budget or BudgetManager(
            AgentBudget.for_profile(BudgetProfile.STANDARD)
        )
        self.workspace_root = workspace_root
        self._query_count = 0

    def query_candidate_evidence(
        self,
        *,
        query: str,
        top_k: int,
        session_id: str,
        run_id: str,
    ) -> list[RetrievedChunk]:
        self._query_count += 1
        action = AgentAction(
            action_id=f"career-query-{self._query_count:03d}",
            tool_name=CAREER_QUERY_TOOL,
            tool_arguments={"query": query, "top_k": top_k},
            expected_observation="structured candidate evidence chunks",
            progress_claim="query candidate-owned career knowledge",
        )
        model = ScriptedAgentModel(
            [
                action,
                AgentFinish(
                    result={"career_query_complete": True},
                    completion_evidence=["governed MCP tool observation"],
                    confidence=1.0,
                ),
            ]
        )
        tool_run_id = f"{run_id}-career-{self._query_count:03d}"
        event_start = len(self.trajectory.events)
        result = AgentLoop(
            agent_id="memory-aware-job-analysis",
            model=model,
            registry=self.registry,
            policy=PolicyEngine(),
            policy_context=self.policy_context,
            budget=self.budget,
            verifier=_ObservationVerifier(),
            trajectory=self.trajectory,
        ).run(
            session_id=session_id,
            run_id=tool_run_id,
            goal={"query": query},
            tool_context=ToolContext(
                session_id=session_id,
                run_id=tool_run_id,
                agent_id="memory-aware-job-analysis",
                workspace_root=self.workspace_root,
            ),
        )
        observed = next(
            (
                event.observation
                for event in reversed(self.trajectory.events[event_start:])
                if event.event_type == "tool_observed"
            ),
            None,
        )
        if observed is None:
            raise RuntimeError(
                "career knowledge runtime failed: "
                f"{result.error_code or result.state.status.value}"
            )
        if observed.status != ToolObservationStatus.OK:
            raise RuntimeError(
                "career knowledge runtime failed: "
                f"{observed.error_code or observed.status.value}"
            )
        if result.state.status != AgentRunStatus.COMPLETED:
            raise RuntimeError(
                f"career knowledge runtime failed: {result.state.status.value}"
            )
        return _retrieved_chunks_from_mcp(observed.data.get("data"))


class MemoryAwareJobAnalysisService:
    def __init__(
        self,
        *,
        user_state_store: UserStateStore,
        user_id: str,
        career_runtime: GovernedCareerKnowledgeRuntime,
        candidate_documents: Sequence[KnowledgeDocument],
        semantic_registry,
        harness: LLMHarness,
        session_dir: Path,
    ) -> None:
        self.user_state_store = user_state_store
        self.user_id = user_id
        self.career_runtime = career_runtime
        self.candidate_documents = tuple(candidate_documents)
        self.semantic_registry = semantic_registry
        self.harness = harness
        self.session_dir = Path(session_dir)

    def analyze(
        self,
        *,
        jd: JobBasicInfo,
        session_id: str,
        run_id: str,
        top_k: int = 5,
    ) -> JobMatchAnalysis:
        state = self.user_state_store.load(user_id=self.user_id)
        preferences = _preference_analysis(state, jd)

        source_store = EvidenceSourceStore(self.session_dir)
        catalog = source_store.snapshot(
            f"{run_id}-requirements",
            [
                SourceInput(
                    kind="raw_jd",
                    display_label=jd.title,
                    text=jd.text,
                )
            ],
        )
        jd_source = catalog.documents[0]
        requirements = RequirementAnalyzer(
            registry=self.semantic_registry,
            harness=self.harness,
            source_store=source_store,
        ).analyze(
            jd_source,
            catalog=catalog,
            session_id=session_id,
            run_id=f"{run_id}-requirements",
        )

        evidence_service = RequirementEvidenceService(
            candidate_retriever=None,
            candidate_documents=self.candidate_documents,
            registry=self.semantic_registry,
            harness=self.harness,
            session_dir=self.session_dir,
        )
        results: list[JobMatchRequirement] = []
        for index, atom in enumerate(requirements.atoms, start=1):
            retrieved = self.career_runtime.query_candidate_evidence(
                query=atom.text,
                top_k=top_k,
                session_id=session_id,
                run_id=run_id,
            )
            evidence = evidence_service.assess_atom_retrieved(
                atom,
                retrieved_chunks=retrieved,
                run_id=f"{run_id}-evidence-{index:03d}",
                session_id=session_id,
            )
            results.append(
                JobMatchRequirement(
                    atom=atom,
                    status=evidence.status,
                    evidence_items=evidence.evidence_items,
                    explanation=evidence.explanation,
                    semantic_support=evidence.semantic_support,
                )
            )

        return build_job_match_analysis(
            requirement_analysis=requirements,
            requirements=results,
            jd_source_id=jd_source.source_id,
            jd_basic_info=jd,
            preference_analysis=preferences,
        )


def _retrieved_chunks_from_mcp(payload: Any) -> list[RetrievedChunk]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError("career knowledge runtime failed: tool_output_error")

    retrieved: list[RetrievedChunk] = []
    for item in payload["results"]:
        if not isinstance(item, dict):
            raise RuntimeError("career knowledge runtime failed: tool_output_error")
        chunk = KnowledgeChunk(
            chunk_id=item["chunk_id"],
            document_id=item["document_id"],
            document_version=item["document_version"],
            document_content_hash=item["document_content_hash"],
            text=item["text"],
            chunk_index=item["chunk_index"],
            start_offset=item["start_offset"],
            end_offset=item["end_offset"],
            section=item.get("section"),
            page=item.get("page"),
            metadata=dict(item.get("metadata", {})),
        )
        retrieved.append(
            RetrievedChunk(
                chunk=chunk,
                score=item["score"],
                rank=item["rank"],
                retrieval_method=item["retrieval_method"],
                retrieval_metadata=dict(item.get("retrieval_metadata", {})),
            )
        )
    return retrieved


def _preference_analysis(
    state: UserState,
    jd: JobBasicInfo,
) -> PreferenceAnalysis:
    city, city_source = _state_value(
        state,
        preference_keys=("preferred_city", "city"),
        hunt_keys=("preferred_city", "city"),
    )
    role, role_source = _state_value(
        state,
        preference_keys=("target_role", "role_direction", "role"),
        hunt_keys=("target_role", "role_direction", "role"),
    )
    job_type, job_type_source = _state_value(
        state,
        preference_keys=("job_type", "preferred_job_type"),
        hunt_keys=("job_type", "preferred_job_type"),
    )
    acceptable_cities = state.preferences.get("acceptable_cities", [])
    return PreferenceAnalysis(
        city=_city_dimension(
            city,
            acceptable_cities,
            jd.city,
            city_source,
        ),
        role=_dimension(
            "role",
            role,
            jd.role_direction,
            role_source,
        ),
        job_type=_dimension(
            "job_type",
            job_type,
            jd.job_type,
            job_type_source,
            canonicalizer=_canonical_job_type,
        ),
    )


def _state_value(
    state: UserState,
    *,
    preference_keys: Sequence[str],
    hunt_keys: Sequence[str],
) -> tuple[str | None, str]:
    for container, source, keys in (
        (state.preferences, "UserState.preferences", preference_keys),
        (state.current_hunt, "UserState.current_hunt", hunt_keys),
    ):
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), source
    return None, "UserState"


def _dimension(
    dimension: str,
    preferred: str | None,
    actual: str | None,
    source: str,
    *,
    canonicalizer=None,
) -> PreferenceDimensionAnalysis:
    if preferred is None or actual is None or not actual.strip():
        return PreferenceDimensionAnalysis(
            dimension=dimension,
            preferred=preferred,
            actual=actual,
            fit=None,
            explanation=f"Insufficient {dimension} preference data.",
            source=source,
        )
    normalize = canonicalizer or _canonical_text
    fit = normalize(preferred) == normalize(actual)
    explanation = (
        f"JD {dimension} matches the stored preference."
        if fit
        else (
            f"JD {dimension} '{actual}' conflicts with stored preference "
            f"'{preferred}'."
        )
    )
    return PreferenceDimensionAnalysis(
        dimension=dimension,
        preferred=preferred,
        actual=actual,
        fit=fit,
        explanation=explanation,
        source=source,
    )


def _city_dimension(
    preferred: str | None,
    acceptable: Any,
    actual: str | None,
    source: str,
) -> PreferenceDimensionAnalysis:
    acceptable_values = (
        [item.strip() for item in acceptable if isinstance(item, str) and item.strip()]
        if isinstance(acceptable, list)
        else []
    )
    if actual is None or not actual.strip() or (preferred is None and not acceptable_values):
        return PreferenceDimensionAnalysis(
            dimension="city",
            preferred=preferred,
            actual=actual,
            fit=None,
            explanation="Insufficient city preference data.",
            source=source,
        )
    actual_key = _canonical_text(actual)
    if preferred is not None and actual_key == _canonical_text(preferred):
        explanation = "JD city matches the stored preferred city."
        fit = True
    elif any(actual_key == _canonical_text(city) for city in acceptable_values):
        explanation = "JD city matches a stored acceptable alternative city."
        fit = True
    else:
        explanation = (
            f"JD city '{actual}' conflicts with stored preferred/acceptable cities."
        )
        fit = False
    return PreferenceDimensionAnalysis(
        dimension="city",
        preferred=preferred,
        actual=actual,
        fit=fit,
        explanation=explanation,
        source=source,
    )
def _canonical_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _canonical_job_type(value: str) -> str:
    canonical = _canonical_text(value)
    if canonical in {"intern", "internship", "实习", "实习生"}:
        return "internship"
    return canonical
