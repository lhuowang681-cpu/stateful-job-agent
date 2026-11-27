from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import pytest

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
from job_agent.agent_runtime.mcp_adapter import MCPToolAdapter
from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.agent_runtime.policy import PolicyContext, PolicyEngine
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.agent_runtime.trajectory import InMemoryTrajectory
from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.career_service import CareerKnowledgeService
from job_agent.knowledge.contracts import RetrievedChunk
from job_agent.knowledge.vector_index import InMemoryVectorIndex


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"
SERVER_SCRIPT = "tests/fixtures/career_knowledge_mcp_server.py"
QUERY = "哪个项目体现了 MCP 和 Agent Runtime 的集成？"


class MCPRuntimeEmbeddingBackend:
    _groups = (
        ("mcp", "mcpclientbridge", "mcptooladapter"),
        ("agent runtime", "agent_runtime", "toolregistry", "toolexecutor"),
    )

    def _embed(self, text: str) -> list[float]:
        lowered = text.casefold()
        return [
            float(any(term in lowered for term in group))
            for group in self._groups
        ]

    def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class CountingBridge:
    def __init__(self, bridge: StdioMCPClientBridge) -> None:
        self.bridge = bridge
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> list[dict[str, Any]]:
        return self.bridge.list_tools()

    def call_tool_sync(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        self.calls.append((name, dict(arguments)))
        return self.bridge.call_tool_sync(name, arguments)


class ObservationVerifier:
    def verify(self, finish, *, goal, steps) -> VerificationResult:
        return VerificationResult(
            passed=bool(steps),
            reason_code="complete" if steps else "missing_observation",
            feedback="complete" if steps else "Call the retrieval tool.",
        )


@pytest.fixture(scope="module")
def mcp_bridge():
    bridge = StdioMCPClientBridge(SERVER_SCRIPT)
    bridge.start()
    try:
        yield bridge
    finally:
        bridge.close()


def _service() -> CareerKnowledgeService:
    return CareerKnowledgeService.from_career_dataset(
        load_career_benchmark(FIXTURE_ROOT),
        embedding_backend=MCPRuntimeEmbeddingBackend(),
        vector_index=InMemoryVectorIndex(),
    )


def _action(*, top_k: int = 3) -> AgentAction:
    return AgentAction(
        action_id=f"career-query-{top_k}",
        tool_name=CAREER_QUERY_TOOL,
        tool_arguments={"query": QUERY, "top_k": top_k},
        expected_observation="structured career knowledge results",
        progress_claim="query candidate-owned career evidence",
    )


def _run_action(
    bridge: CountingBridge,
    *,
    action: AgentAction,
    runtime_allowed_tools: tuple[str, ...] = (CAREER_QUERY_TOOL,),
):
    registry = ToolRegistry()
    adapter = MCPToolAdapter(bridge)
    for tool in bridge.list_tools():
        adapter.register_tool(registry=registry, tool=tool)

    model = ScriptedAgentModel(
        [
            action,
            AgentFinish(
                result={"retrieval_complete": True},
                completion_evidence=["career knowledge observation"],
                confidence=1.0,
            ),
        ]
    )
    trajectory = InMemoryTrajectory()
    loop = AgentLoop(
        agent_id="career-knowledge-agent",
        model=model,
        registry=registry,
        policy=PolicyEngine(),
        policy_context=PolicyContext(
            skill_allowed_tools=(CAREER_QUERY_TOOL,),
            agent_allowed_tools=(CAREER_QUERY_TOOL,),
            runtime_allowed_tools=runtime_allowed_tools,
        ),
        budget=BudgetManager(
            AgentBudget.for_profile(
                BudgetProfile.EVAL,
                max_model_calls=4,
                max_tool_calls=4,
                max_active_seconds=60,
            )
        ),
        verifier=ObservationVerifier(),
        trajectory=trajectory,
    )
    result = loop.run(
        session_id="career-session",
        run_id=f"career-run-{action.action_id}",
        goal={"query": QUERY},
        tool_context=ToolContext(
            session_id="career-session",
            run_id=f"career-run-{action.action_id}",
            agent_id="career-knowledge-agent",
            workspace_root="fixtures/workspace",
            sandbox_root="fixtures/workspace/sandbox",
        ),
    )
    return result, model, trajectory


def test_career_knowledge_service_returns_retrieved_chunks() -> None:
    hits = _service().query_candidate_evidence(QUERY, top_k=3)

    assert len(hits) == 3
    assert all(isinstance(hit, RetrievedChunk) for hit in hits)
    assert hits[0].chunk.document_id == "real-mcp-integration"
    assert hits[0].retrieval_method == "dense"


def test_career_mcp_tool_returns_structured_provenance(mcp_bridge) -> None:
    result = mcp_bridge.call_tool_sync(
        CAREER_QUERY_TOOL,
        {"query": QUERY, "top_k": 3},
    )

    top = result["results"][0]
    assert top["document_id"] == "real-mcp-integration"
    assert top["document_version"] == 1
    assert len(top["document_content_hash"]) == 64
    assert top["chunk_id"]
    assert top["text"]
    assert top["start_offset"] == 0
    assert top["end_offset"] > top["start_offset"]
    assert top["rank"] == 1
    assert top["retrieval_method"] == "dense"


def test_runtime_calls_career_knowledge_through_governed_mcp(mcp_bridge) -> None:
    bridge = CountingBridge(mcp_bridge)
    result, model, trajectory = _run_action(bridge, action=_action())

    observation = model.calls[1].steps[0].observation
    top = observation.data["data"]["results"][0]
    assert result.state.status == AgentRunStatus.COMPLETED
    assert observation.status == ToolObservationStatus.OK
    assert top["document_id"] == "real-mcp-integration"
    assert top["source_uri"] == "src/job_agent/agent_runtime/mcp_adapter.py"
    assert bridge.calls == [
        (CAREER_QUERY_TOOL, {"query": QUERY, "top_k": 3})
    ]

    decision_event = next(
        event
        for event in trajectory.events
        if event.event_type == "model_decision"
        and event.decision.kind == "action"
    )
    observed_event = next(
        event
        for event in trajectory.events
        if event.event_type == "tool_observed"
    )
    assert decision_event.decision.tool_name == CAREER_QUERY_TOOL
    assert decision_event.decision.tool_arguments == {
        "query": QUERY,
        "top_k": 3,
    }
    assert observed_event.observation.data == observation.data


def test_runtime_policy_denial_never_reaches_mcp_server(mcp_bridge) -> None:
    bridge = CountingBridge(mcp_bridge)
    result, model, trajectory = _run_action(
        bridge,
        action=_action(),
        runtime_allowed_tools=(),
    )

    observation = model.calls[1].steps[0].observation
    assert result.state.status == AgentRunStatus.COMPLETED
    assert observation.status == ToolObservationStatus.FATAL_ERROR
    assert observation.error_code == "runtime_tool_denied"
    assert bridge.calls == []
    assert any(
        event.event_type == "tool_observed"
        and event.observation.error_code == "runtime_tool_denied"
        for event in trajectory.events
    )


def test_invalid_top_k_is_runtime_tool_input_error(mcp_bridge) -> None:
    bridge = CountingBridge(mcp_bridge)
    result, model, trajectory = _run_action(
        bridge,
        action=_action(top_k=0),
    )

    observation = model.calls[1].steps[0].observation
    assert result.state.status == AgentRunStatus.COMPLETED
    assert observation.status == ToolObservationStatus.FATAL_ERROR
    assert observation.error_code == "tool_input_error"
    assert bridge.calls == []
    assert any(
        event.event_type == "tool_observed"
        and event.observation.error_code == "tool_input_error"
        for event in trajectory.events
    )


def test_real_qwen_retrieval_through_career_mcp() -> None:
    model_path = os.environ.get("QWEN_EMBEDDING_MODEL_PATH")
    if not model_path or not Path(model_path).is_dir():
        pytest.skip("QWEN_EMBEDDING_MODEL_PATH is unavailable")
    pytest.importorskip("faiss")
    pytest.importorskip("sentence_transformers")

    bridge = StdioMCPClientBridge(
        "src/job_agent/knowledge/career_mcp_server.py",
        startup_timeout_s=90,
        call_timeout_s=60,
        server_env={
            "QWEN_EMBEDDING_MODEL_PATH": model_path,
            "CAREER_KNOWLEDGE_FIXTURE_ROOT": str(FIXTURE_ROOT),
            "CAREER_KNOWLEDGE_DEVICE": "cuda",
        },
    )
    bridge.start()
    try:
        result = bridge.call_tool_sync(
            CAREER_QUERY_TOOL,
            {"query": QUERY, "top_k": 3},
        )
    finally:
        bridge.close()

    assert result["results"][0]["document_id"] == "real-mcp-integration"
