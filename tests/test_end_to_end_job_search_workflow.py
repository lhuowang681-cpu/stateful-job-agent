from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from job_agent.career.durable import DurableCareerRepository

from job_agent.agent_runtime.checkpoint import JsonCheckpointStore
from job_agent.agent_runtime.contracts import ApprovalDecision
from job_agent.agent_runtime.mcp_adapter import MCPToolAdapter
from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.domain_agents.application_lifecycle import (
    GovernedApplicationLifecycleFlow,
)
from job_agent.domain_agents.application_tracking import (
    GovernedApplicationTrackingFlow,
)
from job_agent.evidence.contracts import (
    EvidenceMappingCandidate,
    RequirementAnalysisCandidate,
)
from job_agent.job_search_workflow import (
    JobSearchWorkflow,
    JobSearchWorkflowError,
    JobSearchWorkflowRequest,
)
from job_agent.jd_match_analysis import JobBasicInfo
from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
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
from job_agent.schemas import ApplicationStatus
from job_agent.tools.application_tracker import ApplicationTrackerStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"
DEMO_ARTIFACT = (
    Path(__file__).parent
    / "fixtures"
    / "job_search_workflow"
    / "demo_result.json"
)
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
            version="job-search-workflow-test-v1",
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


class ApproveAll:
    def __init__(self) -> None:
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return ApprovalDecision(
            request_id=request.request_id,
            action_digest=request.action_digest,
            approved=True,
            reason="Explicit workflow demo approval.",
            session_id=request.session_id,
            run_id=request.run_id,
        )


@pytest.fixture(scope="module")
def mcp_bridge():
    bridge = StdioMCPClientBridge(SERVER_SCRIPT)
    bridge.start()
    try:
        yield bridge
    finally:
        bridge.close()


def _request() -> JobSearchWorkflowRequest:
    requirement_lines = "\n".join(
        f"- {text}" for _, text, _, _ in REQUIREMENTS
    )
    return JobSearchWorkflowRequest(
        job_id="synthetic-hangzhou-agent-intern",
        company="Example AI",
        source="synthetic-jd",
        jd_reference="career://jd/synthetic-hangzhou-agent-intern",
        jd=JobBasicInfo(
            title="SYNTHETIC JD — 杭州 Agent 实习岗位",
            city="杭州",
            role_direction="Agent / 大模型应用",
            job_type="internship",
            text=(
                "# SYNTHETIC JD — 杭州 Agent 实习岗位\n"
                "城市：杭州\n"
                "方向：Agent / 大模型应用\n"
                "类型：实习\n\n"
                f"## 技术要求\n{requirement_lines}\n"
            ),
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


def _workflow(
    tmp_path,
    bridge,
    *,
    allow_knowledge=True,
    allow_application=True,
    durable=False,
):
    documents = knowledge_documents_from_career_dataset(
        load_career_benchmark(FIXTURE_ROOT)
    )
    documents_by_id = {
        document.document_id: document for document in documents
    }
    provider = MockLLMProvider(_responses(documents_by_id))
    user_state_store = UserStateStore(tmp_path / "user-state.json")
    user_state_store.save(
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
    counting = CountingBridge(bridge)
    analysis_service = MemoryAwareJobAnalysisService(
        user_state_store=user_state_store,
        user_id="candidate-1",
        career_runtime=_career_runtime(
            counting,
            allow_tool=allow_knowledge,
        ),
        candidate_documents=documents,
        semantic_registry=_Registry(),
        harness=LLMHarness(provider),
        session_dir=tmp_path / "evidence",
    )
    tracker_store = ApplicationTrackerStore(
        tmp_path / "application-tracker.json"
    )
    tracking = GovernedApplicationTrackingFlow(
        tracker_store=tracker_store,
        user_id="candidate-1",
        checkpoint_store=JsonCheckpointStore(
            tmp_path / "tracking-checkpoint.json"
        ),
        allow_write=allow_application,
    )
    lifecycle = GovernedApplicationLifecycleFlow(
        tracker_store=tracker_store,
        user_id="candidate-1",
        checkpoint_store=JsonCheckpointStore(
            tmp_path / "lifecycle-checkpoint.json"
        ),
    )
    approvals = ApproveAll()
    career_repository = (
        DurableCareerRepository.open(tmp_path / "career-state")
        if durable
        else None
    )
    workflow = JobSearchWorkflow(
        analysis_service=analysis_service,
        tracking_flow=tracking,
        lifecycle_flow=lifecycle,
        tracker_store=tracker_store,
        user_id="candidate-1",
        approval_resolver=approvals,
        career_repository=career_repository,
    )
    return workflow, tracker_store, counting, approvals


def test_end_to_end_job_search_workflow_matches_demo_artifact(
    tmp_path,
    mcp_bridge,
) -> None:
    workflow, store, bridge, approvals = _workflow(
        tmp_path,
        mcp_bridge,
        durable=True,
    )

    result = workflow.run(
        _request(),
        session_id="job-search-session",
        run_id="job-search-demo",
        workspace_root=tmp_path,
    )

    assert result.analysis.preference_analysis is not None
    assert result.analysis.preference_analysis.city.fit is True
    assert result.analysis.preference_analysis.role.fit is True
    assert result.analysis.preference_analysis.job_type.fit is True
    assert result.analysis.gaps == ("atom_004",)
    assert result.application.current_state == ApplicationStatus.FIRST_INTERVIEW
    assert [
        event.state for event in result.application.state_history
    ] == [
        ApplicationStatus.TO_APPLY,
        ApplicationStatus.APPLIED,
        ApplicationStatus.RESUME_SCREEN,
        ApplicationStatus.FIRST_INTERVIEW,
    ]
    assert len(approvals.requests) == 4
    assert len(bridge.calls) == 7
    assert all(call[0] == CAREER_QUERY_TOOL for call in bridge.calls)

    prep = result.interview_preparation
    assert {question.topic for question in prep.evidence_backed_questions} == {
        "Agent Runtime / Tool Calling",
        "MCP integration",
        "RAG retrieval",
        "Async backend / recovery",
    }
    assert prep.gap_risks[0].candidate_experience_claimed is False
    assert all(
        question.provenance.exact_quote
        and question.provenance.end_offset
        > question.provenance.start_offset
        for question in prep.evidence_backed_questions
    )
    tracker = store.load(user_id="candidate-1")
    assert len(tracker.applications) == 1
    assert result.demo_artifact() == json.loads(
        DEMO_ARTIFACT.read_text(encoding="utf-8")
    )
    assert workflow.career_repository is not None
    workflow.career_repository.close()
    recovered_repository = DurableCareerRepository.open(
        tmp_path / "career-state"
    )
    recovered = recovered_repository.get_state(result.request.job_id)
    assert recovered.latest_jd.version == 1
    assert recovered.latest_analysis.jd_snapshot_id == recovered.latest_jd.snapshot_id
    assert recovered.application_link.application_id == result.application.id
    assert recovered.latest_interview_prep.application_stage_at_generation == "first_interview"
    assert recovered.latest_interview_prep.analysis_id == recovered.latest_analysis.analysis_id
    recovered_repository.close()


def test_knowledge_policy_deny_stops_before_application_write(
    tmp_path,
    mcp_bridge,
) -> None:
    workflow, store, bridge, approvals = _workflow(
        tmp_path,
        mcp_bridge,
        allow_knowledge=False,
    )

    with pytest.raises(RuntimeError, match="runtime_tool_denied"):
        workflow.run(
            _request(),
            session_id="job-search-session",
            run_id="knowledge-denied",
            workspace_root=tmp_path,
        )
    assert bridge.calls == []
    assert approvals.requests == []
    assert store.load(user_id="candidate-1").applications == []


def test_application_policy_deny_causes_no_mutation(
    tmp_path,
    mcp_bridge,
) -> None:
    workflow, store, bridge, approvals = _workflow(
        tmp_path,
        mcp_bridge,
        allow_application=False,
    )

    with pytest.raises(
        JobSearchWorkflowError,
        match="application_tracking_failed",
    ):
        workflow.run(
            _request(),
            session_id="job-search-session",
            run_id="application-denied",
            workspace_root=tmp_path,
        )
    assert len(bridge.calls) == 4
    assert approvals.requests == []
    assert store.load(user_id="candidate-1").applications == []
