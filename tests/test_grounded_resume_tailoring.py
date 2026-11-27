from __future__ import annotations

from pathlib import Path

import pytest

from job_agent.agent_runtime.contracts import (
    AgentAction,
    ApprovalDecision,
    ToolContext,
    ToolEffect,
    ToolObservationStatus,
)
from job_agent.agent_runtime.policy import PolicyContext, PolicyEngine
from job_agent.agent_runtime.tool_executor import ToolExecutor
from job_agent.evidence.contracts import EvidenceLink, SourceSpan
from job_agent.resume.contracts import (
    ChangeType,
    ClaimEvidence,
    ClaimVerification,
    CoverageStatus,
    DisclosureVisibility,
    RequirementFact,
    RewriteProposal,
)
from job_agent.resume.repository import ResumeRepository
from job_agent.resume.service import GroundedResumeService
from job_agent.resume.tools import (
    APPLICATION_RESUME_TOOL,
    GENERATE_DRAFT_TOOL,
    IMPORT_RESUME_TOOL,
    SAVE_VERSION_TOOL,
    build_resume_registry,
)
from job_agent.schemas import ApplicationStatus, EvidenceLevel
from job_agent.text_identity import sha256_bytes
from job_agent.tools.application_tracker import ApplicationTrackerStore


BASE_RESUME = """# Projects
- Built RAG retrieval with Qwen and FAISS; Recall@5 reached 100% on 18 positive cases.
- Implemented an Agent Runtime and MCP integration.
# Research
- Conducted anonymous multimodal LoRA research.
# Skills
- Python, FastAPI, PyTorch
"""


def _service(tmp_path: Path) -> tuple[ResumeRepository, GroundedResumeService]:
    repository = ResumeRepository.open(tmp_path)
    return repository, GroundedResumeService(repository)


def _evidence(
    claim: str,
    quote: str,
    *,
    visibility: DisclosureVisibility = DisclosureVisibility.RESUME_SAFE,
    anonymized_text: str | None = None,
    suffix: str = "1",
) -> ClaimEvidence:
    digest = sha256_bytes(quote.encode("utf-8"))
    return ClaimEvidence(
        evidence_link=EvidenceLink(
            link_id=f"link-{suffix}",
            atom_id=f"atom-{suffix}",
            source_span=SourceSpan(
                source_id=f"source-{suffix}",
                content_hash=digest,
                start_offset=0,
                end_offset=len(quote),
                exact_quote=quote,
            ),
            claim=claim,
            support_status="supported",
            level=EvidenceLevel.C3,
            confidence=1.0,
        ),
        knowledge_document_id=f"document-{suffix}",
        knowledge_document_version=1,
        knowledge_content_hash=digest,
        visibility=visibility,
        anonymized_text=anonymized_text,
    )


def _import_and_audit(service: GroundedResumeService):
    version = service.import_text(name="Candidate Resume", text=BASE_RESUME)
    retrieval = _evidence(
        "Built Agent RAG retrieval with Qwen and FAISS",
        "Implemented an Agent RAG retrieval system using Qwen embeddings and FAISS.",
        suffix="retrieval",
    )
    metric = _evidence(
        "Recall@5 reached 100% on 18 positive cases",
        "The fixed retrieval benchmark contains 18 positive cases and Recall@5 is 100%.",
        suffix="metric",
    )
    runtime = _evidence(
        "Implemented Agent Runtime and MCP integration",
        "Implemented the governed Agent Runtime to MCP integration.",
        suffix="runtime",
    )
    anonymous = _evidence(
        "Conducted anonymous multimodal LoRA research",
        "SecretFramework for an anonymous conference submission using multimodal LoRA.",
        visibility=DisclosureVisibility.ANONYMIZED_ONLY,
        anonymized_text="Conducted anonymous multimodal LoRA research.",
        suffix="anonymous",
    )
    audit = service.audit_claims(
        version.resume_version_id,
        evidence_by_text={
            "RAG retrieval": [retrieval],
            "Recall@5": [metric],
            "Agent Runtime": [runtime],
            "anonymous multimodal": [anonymous],
        },
    )
    return version, audit, {"retrieval": retrieval, "metric": metric, "runtime": runtime, "anonymous": anonymous}


def test_resume_import_has_structured_stable_items_and_is_idempotent(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    first = service.import_text(name="Candidate Resume", text=BASE_RESUME)
    second = service.import_text(name="Candidate Resume", text=BASE_RESUME)
    assert first.resume_version_id == second.resume_version_id
    assert first.version == 1
    assert [section.kind.value for section in first.sections] == ["project", "research", "skills"]
    assert len({item.item_id for section in first.sections for item in section.items}) == 4
    assert all(item.original_text == item.current_text for section in first.sections for item in section.items)
    assert len(repository.list_versions(first.resume_id)) == 1


def test_claim_audit_binds_evidence_and_keeps_unverified_claims(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    version, audit, _ = _import_and_audit(service)
    assert audit.resume_version_id == version.resume_version_id
    assert audit.supported == 4
    assert audit.unverified == 1
    assert audit.numeric_claims == 1
    assert audit.technology_claims >= 3
    metric = next(claim for claim in audit.claims if "Recall@5" in claim.canonical_claim)
    assert metric.numeric_values == ["5", "100%", "18"]
    assert metric.verification_state == ClaimVerification.SUPPORTED
    skills = next(claim for claim in audit.claims if "Python" in claim.canonical_claim)
    assert skills.verification_state == ClaimVerification.UNVERIFIED
    anonymous = next(claim for claim in audit.claims if "anonymous multimodal" in claim.canonical_claim)
    assert anonymous.visibility == DisclosureVisibility.ANONYMIZED_ONLY


def test_coverage_and_plan_separate_supported_missing_from_real_gap(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    version, _, evidence = _import_and_audit(service)
    requirements = [
        RequirementFact(
            requirement_id="req-rag",
            text="Agent RAG retrieval with Qwen and FAISS",
            evidence_state=ClaimVerification.SUPPORTED,
            evidence=[evidence["retrieval"]],
        ),
        RequirementFact(
            requirement_id="req-lora",
            text="Multimodal LoRA research",
            evidence_state=ClaimVerification.SUPPORTED,
            evidence=[evidence["anonymous"]],
        ),
        RequirementFact(
            requirement_id="req-k8s",
            text="Production Kubernetes operations",
            evidence_state=ClaimVerification.GAP,
        ),
    ]
    report = service.coverage(
        resume_version_id=version.resume_version_id,
        target_job_id="job-agent",
        requirements=requirements,
    )
    by_id = {item.requirement_id: item for item in report.entries}
    assert by_id["req-rag"].status == CoverageStatus.ALREADY_COVERED
    assert by_id["req-k8s"].status == CoverageStatus.GAP
    plan = service.plan_tailoring(
        target_job_id="job-agent",
        target_jd_snapshot_id="jd-agent-v1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-agent-v1",
        base_resume_version_id=version.resume_version_id,
        requirements=requirements,
    )
    assert "Production Kubernetes operations" in plan.true_gaps
    assert "Production Kubernetes operations" in plan.do_not_claim
    assert plan.highlight_items


def test_claim_gate_rejects_gap_numeric_skill_and_responsibility_inflation(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    version, _, evidence = _import_and_audit(service)
    item = version.sections[0].items[0]
    requirements = [
        RequirementFact(
            requirement_id="req-rag",
            text="Agent RAG retrieval",
            evidence_state=ClaimVerification.SUPPORTED,
            evidence=[evidence["retrieval"], evidence["metric"]],
        ),
        RequirementFact(
            requirement_id="req-k8s",
            text="Kubernetes",
            evidence_state=ClaimVerification.GAP,
        ),
    ]
    plan = service.plan_tailoring(
        target_job_id="job-agent",
        target_jd_snapshot_id="jd-v1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-v1",
        base_resume_version_id=version.resume_version_id,
        requirements=requirements,
    )
    proposals = [
        RewriteProposal(
            item_id=item.item_id,
            rewritten_text="Built Agent RAG retrieval with Qwen and FAISS; Recall@5 reached 100% on 18 positive cases.",
            used_evidence_ids=["link-retrieval", "link-metric"],
            target_requirement_ids=["req-rag"],
            change_type=ChangeType.EMPHASIZE,
        ),
        RewriteProposal(
            item_id=item.item_id,
            rewritten_text="主导生产环境 Kubernetes RAG，Recall@5 达到 120%。",
            used_evidence_ids=["link-retrieval"],
            target_requirement_ids=["req-k8s"],
            change_type=ChangeType.EXPAND_WITH_EVIDENCE,
        ),
    ]
    draft = service.generate_draft(
        plan_id=plan.tailoring_plan_id,
        proposals=proposals,
        allowed_evidence_by_item={item.item_id: [evidence["retrieval"], evidence["metric"]]},
    )
    assert draft.changes[0].accepted_by_gate is True
    assert draft.changes[1].accepted_by_gate is False
    reasons = " ".join(draft.changes[1].rejection_reasons)
    assert "gap laundering" in reasons
    assert "unsupported numeric" in reasons
    assert "responsibility inflation" in reasons


def test_visibility_policy_prevents_private_leak_and_allows_anonymized_output(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    version, _, evidence = _import_and_audit(service)
    research_item = version.sections[1].items[0]
    private = _evidence(
        "SecretFramework accepted at SecretConf",
        "SecretFramework accepted at SecretConf 2027.",
        visibility=DisclosureVisibility.PRIVATE_ONLY,
        suffix="private",
    )
    requirement = RequirementFact(
        requirement_id="req-mm",
        text="multimodal LoRA research",
        evidence_state=ClaimVerification.SUPPORTED,
        evidence=[evidence["anonymous"]],
    )
    plan = service.plan_tailoring(
        target_job_id="job-model",
        target_jd_snapshot_id="jd-model-v1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-model-v1",
        base_resume_version_id=version.resume_version_id,
        requirements=[requirement],
    )
    draft = service.generate_draft(
        plan_id=plan.tailoring_plan_id,
        proposals=[
            RewriteProposal(
                item_id=research_item.item_id,
                rewritten_text="Conducted anonymous multimodal LoRA research.",
                used_evidence_ids=["link-anonymous"],
                target_requirement_ids=["req-mm"],
                change_type=ChangeType.REPHRASE,
            ),
            RewriteProposal(
                item_id=research_item.item_id,
                rewritten_text="SecretFramework accepted at SecretConf 2027.",
                used_evidence_ids=["link-private"],
                target_requirement_ids=["req-mm"],
                change_type=ChangeType.EXPAND_WITH_EVIDENCE,
            ),
        ],
        allowed_evidence_by_item={research_item.item_id: [evidence["anonymous"], private]},
    )
    assert draft.changes[0].accepted_by_gate is True
    assert draft.changes[1].accepted_by_gate is False
    assert any("private-only" in item for item in draft.changes[1].rejection_reasons)


def test_partial_approval_creates_immutable_version_diff_and_is_idempotent(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    version, _, evidence = _import_and_audit(service)
    first_item, second_item = version.sections[0].items
    requirements = [
        RequirementFact(
            requirement_id="req-runtime",
            text="Agent Runtime MCP integration",
            evidence_state=ClaimVerification.SUPPORTED,
            evidence=[evidence["runtime"]],
        )
    ]
    plan = service.plan_tailoring(
        target_job_id="job-agent",
        target_jd_snapshot_id="jd-v1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-v1",
        base_resume_version_id=version.resume_version_id,
        requirements=requirements,
    )
    draft = service.generate_draft(
        plan_id=plan.tailoring_plan_id,
        proposals=[
            RewriteProposal(
                item_id=second_item.item_id,
                rewritten_text="Implemented governed Agent Runtime and MCP integration.",
                used_evidence_ids=["link-runtime"],
                target_requirement_ids=["req-runtime"],
                change_type=ChangeType.EMPHASIZE,
            ),
            RewriteProposal(
                item_id=first_item.item_id,
                rewritten_text=first_item.current_text,
                used_evidence_ids=[],
                target_requirement_ids=[],
                change_type=ChangeType.REORDER,
            ),
        ],
        allowed_evidence_by_item={second_item.item_id: [evidence["runtime"]]},
    )
    accepted = next(change for change in draft.changes if change.item_id == second_item.item_id)
    reviewed = service.review_draft(draft.draft_id, approved_change_ids=[accepted.change_id])
    assert len(reviewed.approved_change_ids) == 1
    saved = service.save_approved_version(draft.draft_id, approval_action_id="approve-1")
    replay = service.save_approved_version(draft.draft_id, approval_action_id="approve-1")
    assert saved.resume_version_id == replay.resume_version_id
    assert saved.parent_version_id == version.resume_version_id
    assert repository.get_version(version.resume_version_id).sections[0].items[1].current_text == second_item.current_text
    diff = service.compare_versions(version.resume_version_id, saved.resume_version_id)
    assert len(diff.rewritten) == 1
    assert diff.rewritten[0]["item_id"] == second_item.item_id
    saved_claims = repository.list_claims(saved.resume_version_id)
    rewritten_claim = next(claim for claim in saved_claims if "governed Agent Runtime" in claim.canonical_claim)
    assert rewritten_claim.verification_state == ClaimVerification.SUPPORTED
    assert rewritten_claim.evidence[0].evidence_link.link_id == "link-runtime"


def test_jd_change_marks_targeted_resume_stale(tmp_path: Path) -> None:
    _, service = _service(tmp_path)
    version, _, evidence = _import_and_audit(service)
    item = version.sections[0].items[1]
    requirement = RequirementFact(
        requirement_id="req-runtime",
        text="Agent Runtime MCP integration",
        evidence_state=ClaimVerification.SUPPORTED,
        evidence=[evidence["runtime"]],
    )
    plan = service.plan_tailoring(
        target_job_id="job-agent",
        target_jd_snapshot_id="jd-v1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-v1",
        base_resume_version_id=version.resume_version_id,
        requirements=[requirement],
    )
    draft = service.generate_draft(
        plan_id=plan.tailoring_plan_id,
        proposals=[RewriteProposal(
            item_id=item.item_id,
            rewritten_text="Implemented governed Agent Runtime and MCP integration.",
            used_evidence_ids=["link-runtime"],
            target_requirement_ids=["req-runtime"],
            change_type=ChangeType.EMPHASIZE,
        )],
        allowed_evidence_by_item={item.item_id: [evidence["runtime"]]},
    )
    service.review_draft(draft.draft_id, approved_change_ids=[draft.changes[0].change_id])
    saved = service.save_approved_version(draft.draft_id, approval_action_id="approve-stale")
    assert service.is_stale_for_job(saved.resume_version_id, active_jd_snapshot_id="jd-v1") is False
    assert service.is_stale_for_job(saved.resume_version_id, active_jd_snapshot_id="jd-v2") is True


def test_application_links_exact_saved_version_and_survives_restart(tmp_path: Path) -> None:
    repository, service = _service(tmp_path / "workspace")
    version, _, evidence = _import_and_audit(service)
    item = version.sections[0].items[1]
    requirement = RequirementFact(
        requirement_id="req-runtime",
        text="Agent Runtime MCP integration",
        evidence_state=ClaimVerification.SUPPORTED,
        evidence=[evidence["runtime"]],
    )
    plan = service.plan_tailoring(
        target_job_id="job-agent",
        target_jd_snapshot_id="jd-v1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-v1",
        base_resume_version_id=version.resume_version_id,
        requirements=[requirement],
    )
    draft = service.generate_draft(
        plan_id=plan.tailoring_plan_id,
        proposals=[RewriteProposal(
            item_id=item.item_id,
            rewritten_text="Implemented governed Agent Runtime and MCP integration.",
            used_evidence_ids=["link-runtime"],
            target_requirement_ids=["req-runtime"],
            change_type=ChangeType.EMPHASIZE,
        )],
        allowed_evidence_by_item={item.item_id: [evidence["runtime"]]},
    )
    service.review_draft(draft.draft_id, approved_change_ids=[draft.changes[0].change_id])
    saved = service.save_approved_version(draft.draft_id, approval_action_id="approve-app")
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    application = tracker.record_application(
        user_id="user-1", job_id="job-agent", company="Example AI", title="Agent Engineer",
        city="Hangzhou", source="workspace", url="", initial_status=ApplicationStatus.TO_APPLY,
        notes="", user_confirmed=True,
    )
    link = service.link_to_application(
        tracker=tracker, user_id="user-1", application_id=application.id,
        job_id="job-agent", resume_version_id=saved.resume_version_id,
    )
    replay = service.link_to_application(
        tracker=tracker, user_id="user-1", application_id=application.id,
        job_id="job-agent", resume_version_id=saved.resume_version_id,
    )
    assert link == replay
    repository.close()
    reopened = ResumeRepository.open(tmp_path / "workspace")
    assert reopened.application_link(application.id).resume_version_id == saved.resume_version_id
    assert reopened.get_version(saved.resume_version_id).target_job_id == "job-agent"


def test_runtime_policy_governs_save_and_application_binding(tmp_path: Path) -> None:
    repository, service = _service(tmp_path)
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json")
    registry = build_resume_registry(service, tracker, user_id="user-1")
    assert registry.get(GENERATE_DRAFT_TOOL).spec.effect == ToolEffect.LOCAL_DRAFT_WRITE
    assert registry.get(GENERATE_DRAFT_TOOL).spec.requires_approval is False
    assert registry.get(SAVE_VERSION_TOOL).spec.requires_approval is True
    assert registry.get(APPLICATION_RESUME_TOOL).spec.requires_approval is True
    action = AgentAction(
        action_id="import-resume",
        tool_name=IMPORT_RESUME_TOOL,
        tool_arguments={"name": "Candidate Resume", "text": BASE_RESUME},
        expected_observation="resume imported",
        progress_claim="import through governed runtime",
    )
    tool = registry.get(IMPORT_RESUME_TOOL)
    denied_context = PolicyContext(
        skill_allowed_tools=registry.names(), agent_allowed_tools=registry.names(), runtime_allowed_tools=()
    )
    denied = PolicyEngine().authorize(action, tool.spec, denied_context, session_id="s", run_id="r")
    assert denied.allowed is False and denied.reason_code == "runtime_tool_denied"
    assert repository.list_resumes() == []
    allowed_context = denied_context.model_copy(update={"runtime_allowed_tools": registry.names()})
    pending = PolicyEngine().authorize(action, tool.spec, allowed_context, session_id="s", run_id="r")
    assert pending.reason_code == "approval_required"
    assert repository.list_resumes() == []
    request = pending.approval_request
    authorized = PolicyEngine().authorize(
        action,
        tool.spec,
        allowed_context,
        approval=ApprovalDecision(
            request_id=request.request_id,
            action_digest=request.action_digest,
            approved=True,
            session_id="s",
            run_id="r",
        ),
        session_id="s",
        run_id="r",
    )
    observation = ToolExecutor(registry).execute(
        action,
        authorized,
        ToolContext(session_id="s", run_id="r", agent_id="resume-agent", workspace_root=str(tmp_path)),
    )
    assert observation.status == ToolObservationStatus.OK
    assert len(repository.list_resumes()) == 1


def test_supported_claim_requires_evidence() -> None:
    with pytest.raises(ValueError, match="supported claims require evidence"):
        from job_agent.resume.contracts import CandidateClaim
        from datetime import UTC, datetime

        CandidateClaim(
            claim_id="claim",
            canonical_claim="unsupported assertion",
            category="project",
            resume_version_id="v1",
            item_id="item",
            verification_state=ClaimVerification.SUPPORTED,
            updated_at=datetime.now(UTC),
        )
