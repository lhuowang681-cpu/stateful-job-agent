from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_agent.agent_runtime.mcp_adapter import MCPToolAdapter
from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.evidence.contracts import (
    EvidenceMappingCandidate,
    RequirementAnalysisCandidate,
)
from job_agent.jd_match_analysis import JobBasicInfo
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.jd_match_demo import (
    knowledge_documents_from_career_dataset,
)
from job_agent.knowledge.ingestion import chunk_knowledge_document
from job_agent.llm.harness import LLMHarness
from job_agent.llm.providers.mock import MockLLMProvider
from job_agent.llm.skill_registry import SkillSpec
from job_agent.memory.contracts import UserState
from job_agent.memory.user_state_store import UserStateStore
from job_agent.memory_aware_job_analysis import (
    GovernedCareerKnowledgeRuntime,
    MemoryAwareJobAnalysisService,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"
SERVER_SCRIPT = "tests/fixtures/career_knowledge_mcp_server.py"

REQUIREMENTS = (
    (
        "agent-runtime",
        "候选人实现过 Agent Runtime 和 Tool Calling。",
        "real-agent-runtime-governance",
        "src_002_project_source",
    ),
    (
        "rag",
        "候选人实现过 RAG 或语义检索。",
        "real-dense-knowledge-retrieval",
        "src_003_project_source",
    ),
    (
        "async-backend",
        "候选人做过可恢复的异步 Agent 后端。",
        "real-backend-reliability",
        "src_002_project_source",
    ),
    (
        "kubernetes",
        "候选人具备 Kubernetes 生产集群运维经验。",
        None,
        None,
    ),
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
            version="memory-aware-job-analysis-test-v1",
            instructions="Use explicit requirements and cited evidence only.",
            reference_paths=(),
            output_schema=output_schema,
        )


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


@pytest.fixture(scope="module")
def mcp_bridge():
    bridge = StdioMCPClientBridge(SERVER_SCRIPT)
    bridge.start()
    try:
        yield bridge
    finally:
        bridge.close()


def _jd(city: str) -> JobBasicInfo:
    requirement_lines = "\n".join(
        f"- {text}" for _, text, _, _ in REQUIREMENTS
    )
    return JobBasicInfo(
        title=f"{city} Agent 实习岗位",
        city=city,
        role_direction="Agent / 大模型应用",
        job_type="internship",
        text=(
            f"# {city} Agent 实习岗位\n\n"
            f"城市：{city}\n"
            "方向：Agent / 大模型应用\n"
            "类型：实习\n\n"
            f"## 技术要求\n{requirement_lines}\n"
        ),
    )


def _requirement_response() -> dict:
    return {
        "requirements": [
            {
                "text": text,
                "importance": "must",
                "hard_gate": False,
                "exact_quote": text,
                "verification_signals": [],
            }
            for _, text, _, _ in REQUIREMENTS
        ],
        "warnings": [],
    }


def _mapping_response(
    *,
    atom_id: str,
    exact_quote: str | None,
    chunk_id: str | None,
) -> dict:
    return {
        "atom_results": [
            {
                "atom_id": atom_id,
                "semantic_support": (
                    "supported" if chunk_id is not None else "unsupported"
                ),
                "selected_chunk_id": chunk_id,
                "exact_quote": exact_quote,
            }
        ]
    }


def _responses(documents_by_id) -> list[dict]:
    responses = [_requirement_response()]
    for index, (_, _, document_id, _) in enumerate(REQUIREMENTS, start=1):
        document = documents_by_id.get(document_id)
        responses.append(
            _mapping_response(
                atom_id=f"atom_{index:03d}",
                exact_quote=document.text if document is not None else None,
                chunk_id=(
                    chunk_knowledge_document(document, max_chars=2000)[0].chunk_id
                    if document is not None
                    else None
                ),
            )
        )
    return responses


def _state_store(tmp_path: Path) -> UserStateStore:
    store = UserStateStore(tmp_path / "user-state.json")
    store.save(
        user_id="candidate-1",
        state=UserState(
            user_id="candidate-1",
            preferences={
                "preferred_city": "杭州",
                "target_role": "Agent / 大模型应用",
                "job_type": "internship",
            },
        ),
        expected_version=1,
    )
    return store


def _career_runtime(
    bridge: CountingBridge,
    *,
    allow_tool: bool,
) -> GovernedCareerKnowledgeRuntime:
    registry = ToolRegistry()
    adapter = MCPToolAdapter(bridge)
    for tool in bridge.list_tools():
        adapter.register_tool(registry=registry, tool=tool)
    return GovernedCareerKnowledgeRuntime(
        registry=registry,
        policy_context=PolicyContext(
            skill_allowed_tools=(CAREER_QUERY_TOOL,),
            agent_allowed_tools=(CAREER_QUERY_TOOL,),
            runtime_allowed_tools=(CAREER_QUERY_TOOL,) if allow_tool else (),
        ),
    )


def _service(
    tmp_path: Path,
    bridge: CountingBridge,
    *,
    city: str,
    allow_tool: bool = True,
):
    dataset = load_career_benchmark(FIXTURE_ROOT)
    documents = knowledge_documents_from_career_dataset(dataset)
    documents_by_id = {
        document.document_id: document for document in documents
    }
    provider = MockLLMProvider(_responses(documents_by_id))
    store = _state_store(tmp_path)
    service = MemoryAwareJobAnalysisService(
        user_state_store=store,
        user_id="candidate-1",
        career_runtime=_career_runtime(bridge, allow_tool=allow_tool),
        candidate_documents=documents,
        semantic_registry=_Registry(),
        harness=LLMHarness(provider),
        session_dir=tmp_path / "evidence",
    )
    return service, store, documents_by_id, _jd(city)


def _evidence_documents(analysis) -> dict[str, tuple[str, ...]]:
    return {
        item.atom.atom_id: tuple(
            evidence.document_id for evidence in item.evidence_items
        )
        for item in analysis.requirements
    }


def test_hangzhou_job_uses_memory_and_governed_capability_evidence(
    tmp_path: Path,
    mcp_bridge,
) -> None:
    bridge = CountingBridge(mcp_bridge)
    service, store, documents, jd = _service(
        tmp_path,
        bridge,
        city="杭州",
    )
    state_before = store.path.read_text(encoding="utf-8")

    analysis = service.analyze(
        jd=jd,
        session_id="memory-aware-session",
        run_id="hangzhou-analysis",
    )

    assert store.path.read_text(encoding="utf-8") == state_before
    assert analysis.preference_analysis is not None
    assert analysis.preference_analysis.city.fit is True
    assert analysis.preference_analysis.role.fit is True
    assert analysis.preference_analysis.job_type.fit is True
    assert analysis.summary is not None
    assert analysis.summary.preference_conflicts == ()
    assert set(analysis.partial_or_unverified) == {
        "atom_001",
        "atom_002",
        "atom_003",
    }
    assert analysis.gaps == ("atom_004",)
    assert len(bridge.calls) == 4
    assert all(call[0] == CAREER_QUERY_TOOL for call in bridge.calls)
    action_events = [
        event
        for event in service.career_runtime.trajectory.events
        if event.event_type == "model_decision"
        and event.decision.kind == "action"
    ]
    observed_events = [
        event
        for event in service.career_runtime.trajectory.events
        if event.event_type == "tool_observed"
    ]
    assert len(action_events) == len(observed_events) == 4
    assert all(
        event.decision.tool_name == CAREER_QUERY_TOOL
        for event in action_events
    )
    assert all(event.observation.data for event in observed_events)

    evidence_documents = _evidence_documents(analysis)
    assert evidence_documents["atom_001"] == (
        "real-agent-runtime-governance",
    )
    assert evidence_documents["atom_002"] == (
        "real-dense-knowledge-retrieval",
    )
    assert evidence_documents["atom_003"] == (
        "real-backend-reliability",
    )
    assert evidence_documents["atom_004"] == ()

    for requirement in analysis.requirements:
        for evidence in requirement.evidence_items:
            document = documents[evidence.document_id]
            span = evidence.evidence_link.source_span
            assert evidence.document_version == document.version
            assert evidence.document_content_hash == document.content_hash
            assert evidence.evidence_link.atom_id == requirement.atom.atom_id
            assert document.text[span.start_offset:span.end_offset] == (
                span.exact_quote
            )


def test_shanghai_changes_only_preference_fit(
    tmp_path: Path,
    mcp_bridge,
) -> None:
    hangzhou_bridge = CountingBridge(mcp_bridge)
    hangzhou_service, _, _, hangzhou_jd = _service(
        tmp_path / "hangzhou",
        hangzhou_bridge,
        city="杭州",
    )
    hangzhou = hangzhou_service.analyze(
        jd=hangzhou_jd,
        session_id="comparison-session",
        run_id="hangzhou-comparison",
    )

    shanghai_bridge = CountingBridge(mcp_bridge)
    shanghai_service, _, _, shanghai_jd = _service(
        tmp_path / "shanghai",
        shanghai_bridge,
        city="上海",
    )
    shanghai = shanghai_service.analyze(
        jd=shanghai_jd,
        session_id="comparison-session",
        run_id="shanghai-comparison",
    )

    assert shanghai.preference_analysis is not None
    assert shanghai.preference_analysis.city.fit is False
    assert shanghai.preference_analysis.role.fit is True
    assert shanghai.preference_analysis.job_type.fit is True
    assert shanghai.summary is not None
    assert shanghai.summary.preference_conflicts == ("city",)
    assert _evidence_documents(shanghai) == _evidence_documents(hangzhou)
    assert shanghai.gaps == hangzhou.gaps == ("atom_004",)


def test_policy_denial_stops_job_analysis_without_retriever_fallback(
    tmp_path: Path,
    mcp_bridge,
) -> None:
    bridge = CountingBridge(mcp_bridge)
    service, _, _, jd = _service(
        tmp_path,
        bridge,
        city="杭州",
        allow_tool=False,
    )

    with pytest.raises(RuntimeError, match="runtime_tool_denied"):
        service.analyze(
            jd=jd,
            session_id="denied-session",
            run_id="denied-analysis",
        )

    assert bridge.calls == []
