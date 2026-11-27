from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from job_agent.agent_runtime.mcp_adapter import MCPToolAdapter
from job_agent.agent_runtime.mcp_bridge import StdioMCPClientBridge
from job_agent.agent_runtime.policy import PolicyContext
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.evidence.contracts import (
    EvidenceLink,
    ParentRequirement,
    RequirementAnalysis,
    RequirementAtom,
    SourceSpan,
)
from job_agent.interview.preparation import (
    InterviewPreparationError,
    JobSpecificInterviewPreparationService,
)
from job_agent.jd_match_analysis import (
    JobBasicInfo,
    JobMatchRequirement,
    build_job_match_analysis,
)
from job_agent.knowledge.career_benchmark import load_career_benchmark
from job_agent.knowledge.career_mcp_server import CAREER_QUERY_TOOL
from job_agent.knowledge.jd_match_demo import (
    knowledge_documents_from_career_dataset,
)
from job_agent.memory_aware_job_analysis import (
    GovernedCareerKnowledgeRuntime,
)
from job_agent.requirement_evidence import RequirementEvidenceItem
from job_agent.schemas import ApplicationStatus
from job_agent.text_identity import sha256_bytes
from job_agent.tools.application_tracker import ApplicationTrackerStore


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "career_retrieval"
SERVER_SCRIPT = "tests/fixtures/career_knowledge_mcp_server.py"
JOB_ID = "hangzhou-agent-intern"

REQUIREMENTS = (
    (
        "agent-runtime",
        "候选人实现过 Agent Runtime 和 Tool Calling。",
        "real-agent-runtime-governance",
    ),
    (
        "rag",
        "候选人实现过 RAG 或语义检索。",
        "real-dense-knowledge-retrieval",
    ),
    (
        "async-backend",
        "候选人做过可恢复的异步 Agent 后端。",
        "real-backend-reliability",
    ),
    (
        "kubernetes",
        "候选人具备 Kubernetes 生产集群运维经验。",
        None,
    ),
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


def _runtime(
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


def _analysis():
    documents = knowledge_documents_from_career_dataset(
        load_career_benchmark(FIXTURE_ROOT)
    )
    documents_by_id = {
        document.document_id: document for document in documents
    }
    jd_text = "\n".join(text for _, text, _ in REQUIREMENTS)
    jd_hash = sha256_bytes(jd_text.encode("utf-8"))
    parents = []
    atoms = []
    results = []
    for case_id, text, document_id in REQUIREMENTS:
        start = jd_text.index(text)
        requirement_span = SourceSpan(
            source_id="jd-source",
            content_hash=jd_hash,
            start_offset=start,
            end_offset=start + len(text),
            exact_quote=text,
        )
        atom_id = f"atom-{case_id}"
        requirement_id = f"requirement-{case_id}"
        atom = RequirementAtom(
            atom_id=atom_id,
            parent_requirement_id=requirement_id,
            text=text,
            source_span=requirement_span,
        )
        parents.append(
            ParentRequirement(
                requirement_id=requirement_id,
                text=text,
                importance="must",
                source_span=requirement_span,
                atom_ids=[atom_id],
            )
        )
        atoms.append(atom)
        evidence_items = ()
        status = "gap"
        if document_id is not None:
            document = documents_by_id[document_id]
            evidence_items = (
                RequirementEvidenceItem(
                    document_id=document.document_id,
                    document_version=document.version,
                    document_content_hash=document.content_hash,
                    chunk_id=f"analysis-{case_id}",
                    retrieval_rank=1,
                    retrieval_score=1.0,
                    retrieval_method="hybrid_rrf",
                    retrieval_metadata={},
                    evidence_link=EvidenceLink(
                        link_id=f"evidence-{case_id}",
                        atom_id=atom_id,
                        source_span=SourceSpan(
                            source_id=f"candidate-{case_id}",
                            content_hash=document.content_hash,
                            start_offset=0,
                            end_offset=len(document.text),
                            exact_quote=document.text,
                        ),
                        claim=document.text,
                        support_status="supported",
                        level="C1",
                        confidence=0.9,
                        needs_confirmation=True,
                    ),
                ),
            )
            status = "unverified_lead"
        results.append(
            JobMatchRequirement(
                atom=atom,
                status=status,
                evidence_items=evidence_items,
                explanation=(
                    "Candidate project material is available."
                    if evidence_items
                    else "No candidate evidence is available."
                ),
            )
        )
    requirement_analysis = RequirementAnalysis(
        parents=parents,
        atoms=atoms,
    )
    analysis = build_job_match_analysis(
        requirement_analysis=requirement_analysis,
        requirements=results,
        jd_source_id="jd-source",
        jd_basic_info=JobBasicInfo(
            title="杭州 Agent 实习岗位",
            city="杭州",
            role_direction="Agent / 大模型应用",
            job_type="internship",
            text=jd_text,
        ),
    )
    return analysis


def _store(tmp_path, *, stage=ApplicationStatus.FIRST_INTERVIEW):
    store = ApplicationTrackerStore(tmp_path / "application-tracker.json")
    application = store.record_application(
        user_id="candidate-1",
        job_id=JOB_ID,
        company="Example AI",
        title="杭州 Agent 实习岗位",
        city="杭州",
        source="job-analysis",
        url="career://jd/hangzhou-agent-intern",
        initial_status=ApplicationStatus.TO_APPLY,
        notes="",
        user_confirmed=True,
    )
    transitions = [
        ApplicationStatus.APPLIED,
        ApplicationStatus.RESUME_SCREEN,
        ApplicationStatus.FIRST_INTERVIEW,
    ]
    for new_status in transitions:
        if new_status == stage or application.current_state == stage:
            if application.current_state == stage:
                break
        application = store.update_status(
            user_id="candidate-1",
            application_id=application.id,
            new_status=new_status,
            notes="",
            user_confirmed=True,
        )
        if application.current_state == stage:
            break
    return store, application


def _service(tmp_path, bridge, *, allow_tool=True, stage=None):
    store, application = _store(
        tmp_path,
        stage=stage or ApplicationStatus.FIRST_INTERVIEW,
    )
    counting = CountingBridge(bridge)
    service = JobSpecificInterviewPreparationService(
        tracker_store=store,
        user_id="candidate-1",
        analyses_by_job_id={JOB_ID: _analysis()},
        career_runtime=_runtime(counting, allow_tool=allow_tool),
    )
    return service, application, counting


def test_first_interview_prep_is_job_specific_and_grounded(
    tmp_path,
    mcp_bridge,
) -> None:
    service, application, bridge = _service(tmp_path, mcp_bridge)

    prep = service.prepare(
        application.id,
        session_id="interview-prep-session",
        run_id="example-ai-prep",
    )

    assert prep.company == "Example AI"
    assert prep.role == "Agent / 大模型应用"
    assert prep.stage == ApplicationStatus.FIRST_INTERVIEW
    topics = {question.topic for question in prep.evidence_backed_questions}
    assert {
        "Agent Runtime / Tool Calling",
        "MCP integration",
        "RAG retrieval",
        "Async backend / recovery",
    }.issubset(topics)
    assert len(bridge.calls) == 3
    assert all(call[0] == CAREER_QUERY_TOOL for call in bridge.calls)

    for question in prep.evidence_backed_questions:
        provenance = question.provenance
        assert provenance.requirement_atom_id.startswith("atom-")
        assert provenance.requirement_text
        assert provenance.document_id.startswith("real-")
        assert provenance.chunk_id
        assert provenance.document_content_hash
        assert provenance.end_offset > provenance.start_offset
        assert provenance.exact_quote == question.evidence_claim
        assert provenance.retrieval_method

    assert len(prep.gap_risks) == 1
    gap = prep.gap_risks[0]
    assert "Kubernetes" in gap.requirement_text
    assert gap.candidate_experience_claimed is False
    assert "没有可验证" in gap.risk
    assert all(
        "Kubernetes" not in question.topic
        for question in prep.evidence_backed_questions
    )

    reviews = {
        topic.topic: topic.classification
        for topic in prep.technical_review_topics
    }
    assert reviews == {
        "Tool Calling / Runtime governance": "prep_topic",
        "RAG retrieval / evaluation": "prep_topic",
        "async backend reliability": "prep_topic",
        "Kubernetes fundamentals": "prep_topic",
    }


def test_unknown_or_non_interview_application_is_rejected(
    tmp_path,
    mcp_bridge,
) -> None:
    service, application, bridge = _service(
        tmp_path,
        mcp_bridge,
        stage=ApplicationStatus.TO_APPLY,
    )

    with pytest.raises(
        InterviewPreparationError,
        match="application_stage_mismatch:to_apply",
    ):
        service.prepare(
            application.id,
            session_id="interview-prep-session",
            run_id="too-early-prep",
        )
    with pytest.raises(
        InterviewPreparationError,
        match="application_not_found",
    ):
        service.prepare(
            "missing-application",
            session_id="interview-prep-session",
            run_id="missing-prep",
        )
    assert bridge.calls == []


def test_runtime_policy_deny_has_no_knowledge_fallback(
    tmp_path,
    mcp_bridge,
) -> None:
    service, application, bridge = _service(
        tmp_path,
        mcp_bridge,
        allow_tool=False,
    )

    with pytest.raises(RuntimeError, match="runtime_tool_denied"):
        service.prepare(
            application.id,
            session_id="interview-prep-session",
            run_id="denied-prep",
        )
    assert bridge.calls == []
