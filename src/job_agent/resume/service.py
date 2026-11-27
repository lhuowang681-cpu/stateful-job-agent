from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, Sequence

from job_agent.text_identity import normalize_text, sha256_bytes
from .contracts import (
    ApplicationResumeLink,
    CandidateClaim,
    ChangeType,
    ClaimAudit,
    ClaimEvidence,
    ClaimVerification,
    CoverageReport,
    CoverageStatus,
    DisclosureVisibility,
    DraftStatus,
    RequirementCoverage,
    RequirementFact,
    Resume,
    ResumeItem,
    ResumeSection,
    ResumeSourceType,
    ResumeVersion,
    ResumeVersionDiff,
    ResumeVersionStatus,
    RewriteProposal,
    SectionKind,
    TailoringChange,
    TailoringDraft,
    TailoringPlan,
)
from .repository import ResumeRepository

if TYPE_CHECKING:
    from job_agent.tools.application_tracker import ApplicationTrackerStore


TECHNOLOGIES = (
    "Agent Runtime",
    "DeepSeek",
    "Docker",
    "DPO",
    "FAISS",
    "FastAPI",
    "GRPO",
    "Kubernetes",
    "LangGraph",
    "LoRA",
    "MCP",
    "Milvus",
    "PyTorch",
    "Qwen",
    "Qwen3-VL",
    "RAG",
    "Redis",
    "RLHF",
)
RESPONSIBILITY_TERMS = (
    "主导",
    "负责",
    "独立完成",
    "生产环境",
    "大规模",
    "高并发",
    "企业级",
    "上线",
    "led ",
    "owned ",
    "production",
    "enterprise",
)
SECTION_ALIASES = {
    "summary": SectionKind.SUMMARY,
    "profile": SectionKind.SUMMARY,
    "education": SectionKind.EDUCATION,
    "教育": SectionKind.EDUCATION,
    "research": SectionKind.RESEARCH,
    "科研": SectionKind.RESEARCH,
    "projects": SectionKind.PROJECT,
    "project": SectionKind.PROJECT,
    "项目": SectionKind.PROJECT,
    "experience": SectionKind.EXPERIENCE,
    "work experience": SectionKind.EXPERIENCE,
    "经历": SectionKind.EXPERIENCE,
    "skills": SectionKind.SKILLS,
    "技能": SectionKind.SKILLS,
    "awards": SectionKind.AWARDS,
    "奖项": SectionKind.AWARDS,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _stable_id(namespace: str, *parts: str) -> str:
    payload = "\x1f".join((namespace, *parts)).encode("utf-8")
    return f"{namespace}-{hashlib.sha256(payload).hexdigest()[:24]}"


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256_bytes(encoded)


def _content_hash(sections: Sequence[ResumeSection]) -> str:
    payload = [section.model_dump(mode="json") for section in sections]
    return _digest(payload)


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,}|[\u4e00-\u9fff]{2,}", value)
        if token.casefold() not in {"and", "with", "the", "for", "using", "以及", "使用", "基于"}
    }


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _numbers(value: str) -> list[str]:
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?:%|ms|s|B|M|K|年|个月|份|条|个)?", value)


def _technologies(value: str) -> list[str]:
    lower = value.casefold()
    return [item for item in TECHNOLOGIES if re.search(rf"(?<!\w){re.escape(item.casefold())}(?!\w)", lower)]


def _claims(value: str) -> list[str]:
    normalized = normalize_text(value).strip()
    parts = [item.strip(" -•\t") for item in re.split(r"[；;。\n]+", normalized)]
    return [item for item in parts if item]


class GroundedResumeService:
    def __init__(
        self,
        repository: ResumeRepository,
        *,
        now: Callable[[], datetime] = _now,
    ) -> None:
        self.repository = repository
        self._now = now

    def import_text(
        self,
        *,
        name: str,
        text: str,
        source_type: ResumeSourceType = ResumeSourceType.PLAIN_TEXT,
        resume_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ResumeVersion:
        name = name.strip()
        normalized = normalize_text(text).strip()
        if not name or not normalized:
            raise ValueError("resume name and text are required")
        resume_id = resume_id or _stable_id("resume", name.casefold())
        try:
            resume = self.repository.get_resume(resume_id)
        except KeyError:
            resume = self.repository.save_resume(
                Resume(resume_id=resume_id, name=name, created_at=self._now())
            )
        sections = self._parse_text(resume.resume_id, normalized)
        content_hash = _content_hash(sections)
        existing = self.repository.list_versions(resume.resume_id)
        for version in existing:
            if version.content_hash == content_hash and version.target_job_id is None:
                return version
        version_number = self.repository.next_version(resume.resume_id)
        parent = existing[-1] if existing else None
        version = ResumeVersion(
            resume_version_id=_stable_id("resume-version", resume.resume_id, str(version_number), content_hash),
            resume_id=resume.resume_id,
            version=version_number,
            parent_version_id=parent.resume_version_id if parent else None,
            created_at=self._now(),
            source_type=source_type,
            status=ResumeVersionStatus.BASE if version_number == 1 else ResumeVersionStatus.SAVED,
            content_hash=content_hash,
            raw_text=normalized,
            sections=sections,
            metadata=dict(metadata or {}),
        )
        return self.repository.save_version(version)

    def import_structured(
        self,
        *,
        name: str,
        sections: Sequence[Mapping[str, Any]],
        resume_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ResumeVersion:
        lines: list[str] = []
        for section in sections:
            lines.append(f"## {section.get('title') or section.get('kind') or 'Other'}")
            for item in section.get("items", []):
                text = item.get("text") if isinstance(item, Mapping) else str(item)
                if text and str(text).strip():
                    lines.append(f"- {str(text).strip()}")
        return self.import_text(
            name=name,
            text="\n".join(lines),
            source_type=ResumeSourceType.STRUCTURED_JSON,
            resume_id=resume_id,
            metadata=metadata,
        )

    def audit_claims(
        self,
        resume_version_id: str,
        *,
        evidence_by_text: Mapping[str, Sequence[ClaimEvidence]] | None = None,
        conflicts: Iterable[str] = (),
        gaps: Iterable[str] = (),
        visibility_by_text: Mapping[str, DisclosureVisibility] | None = None,
    ) -> ClaimAudit:
        version = self.repository.get_version(resume_version_id)
        evidence_by_text = evidence_by_text or {}
        visibility_by_text = visibility_by_text or {}
        conflict_terms = tuple(item.casefold() for item in conflicts)
        gap_terms = tuple(item.casefold() for item in gaps)
        claims: list[CandidateClaim] = []
        for section in version.sections:
            for item in section.items:
                for claim_index, claim_text in enumerate(_claims(item.current_text)):
                    evidence = self._matching_evidence(claim_text, evidence_by_text)
                    lower = claim_text.casefold()
                    if any(term in lower for term in conflict_terms):
                        state = ClaimVerification.CONFLICT
                    elif any(term in lower for term in gap_terms):
                        state = ClaimVerification.GAP
                    elif evidence:
                        state = ClaimVerification.SUPPORTED
                    else:
                        state = ClaimVerification.UNVERIFIED
                    visibility = next(
                        (value for key, value in visibility_by_text.items() if key.casefold() in lower),
                        self._evidence_visibility(evidence),
                    )
                    claims.append(
                        CandidateClaim(
                            claim_id=_stable_id(
                                "claim",
                                version.resume_version_id,
                                item.item_id,
                                str(claim_index),
                                normalize_text(claim_text),
                            ),
                            canonical_claim=claim_text,
                            category=section.kind.value,
                            resume_version_id=version.resume_version_id,
                            item_id=item.item_id,
                            verification_state=state,
                            visibility=visibility,
                            evidence=evidence,
                            numeric_values=_numbers(claim_text),
                            technologies=_technologies(claim_text),
                            updated_at=self._now(),
                        )
                    )
        self.repository.replace_claims(version.resume_version_id, claims)
        counts = Counter(item.verification_state for item in claims)
        return ClaimAudit(
            resume_version_id=version.resume_version_id,
            claims=claims,
            supported=counts[ClaimVerification.SUPPORTED],
            unverified=counts[ClaimVerification.UNVERIFIED],
            conflict=counts[ClaimVerification.CONFLICT],
            gap=counts[ClaimVerification.GAP],
            numeric_claims=sum(bool(item.numeric_values) for item in claims),
            technology_claims=sum(bool(item.technologies) for item in claims),
        )

    def coverage(
        self,
        *,
        resume_version_id: str,
        target_job_id: str,
        requirements: Sequence[RequirementFact],
    ) -> CoverageReport:
        version = self.repository.get_version(resume_version_id)
        claims = self.repository.list_claims(resume_version_id)
        items = [item for section in version.sections for item in section.items]
        entries: list[RequirementCoverage] = []
        for requirement in requirements:
            if requirement.evidence_state != ClaimVerification.SUPPORTED:
                entries.append(
                    RequirementCoverage(
                        requirement_id=requirement.requirement_id,
                        requirement_text=requirement.text,
                        status=CoverageStatus.GAP,
                        rationale="candidate evidence does not support this requirement",
                    )
                )
                continue
            matching_claims = [
                claim
                for claim in claims
                if claim.verification_state == ClaimVerification.SUPPORTED
                and claim.superseded_by_claim_id is None
                and _overlap(requirement.text, claim.canonical_claim) >= 0.34
            ]
            matching_items = [item for item in items if _overlap(requirement.text, item.current_text) >= 0.34]
            if matching_claims and matching_items:
                status = CoverageStatus.ALREADY_COVERED
                rationale = "supported claim is already explicit on the resume"
            elif matching_items:
                status = CoverageStatus.COVERED_BUT_WEAK
                rationale = "resume mentions the requirement but lacks verified claim coverage"
            else:
                status = CoverageStatus.SUPPORTED_NOT_ON_RESUME
                rationale = "candidate evidence supports the requirement but the resume does not show it"
            entries.append(
                RequirementCoverage(
                    requirement_id=requirement.requirement_id,
                    requirement_text=requirement.text,
                    status=status,
                    item_ids=[item.item_id for item in matching_items],
                    claim_ids=[claim.claim_id for claim in matching_claims],
                    evidence_ids=[
                        binding.evidence_link.link_id
                        for binding in requirement.evidence
                        if binding.visibility != DisclosureVisibility.PRIVATE_ONLY
                    ],
                    rationale=rationale,
                )
            )
        counts = Counter(item.status for item in entries)
        return CoverageReport(
            resume_version_id=resume_version_id,
            target_job_id=target_job_id,
            total_required_atoms=len(entries),
            covered_on_resume=counts[CoverageStatus.ALREADY_COVERED],
            supported_not_on_resume=counts[CoverageStatus.SUPPORTED_NOT_ON_RESUME],
            partial=counts[CoverageStatus.COVERED_BUT_WEAK],
            gap=counts[CoverageStatus.GAP],
            entries=entries,
        )

    def plan_tailoring(
        self,
        *,
        target_job_id: str,
        target_jd_snapshot_id: str,
        target_jd_version: int,
        analysis_snapshot_id: str,
        base_resume_version_id: str,
        requirements: Sequence[RequirementFact],
    ) -> TailoringPlan:
        report = self.coverage(
            resume_version_id=base_resume_version_id,
            target_job_id=target_job_id,
            requirements=requirements,
        )
        version = self.repository.get_version(base_resume_version_id)
        covered_ids = [item_id for entry in report.entries for item_id in entry.item_ids]
        all_items = [item.item_id for section in version.sections for item in section.items]
        material = {
            "target_job_id": target_job_id,
            "target_jd_snapshot_id": target_jd_snapshot_id,
            "base_resume_version_id": base_resume_version_id,
            "analysis_snapshot_id": analysis_snapshot_id,
            "coverage": [entry.model_dump(mode="json") for entry in report.entries],
        }
        plan = TailoringPlan(
            tailoring_plan_id=_stable_id("tailoring-plan", _digest(material)),
            target_job_id=target_job_id,
            target_jd_snapshot_id=target_jd_snapshot_id,
            target_jd_version=target_jd_version,
            analysis_snapshot_id=analysis_snapshot_id,
            base_resume_version_id=base_resume_version_id,
            created_at=self._now(),
            coverage=report.entries,
            highlight_items=list(dict.fromkeys(covered_ids)),
            deemphasize_items=[item for item in all_items if item not in covered_ids],
            rewrite_candidates=list(dict.fromkeys(covered_ids)),
            missing_supported_capabilities=[
                entry.requirement_text
                for entry in report.entries
                if entry.status == CoverageStatus.SUPPORTED_NOT_ON_RESUME
            ],
            true_gaps=[entry.requirement_text for entry in report.entries if entry.status == CoverageStatus.GAP],
            do_not_claim=[entry.requirement_text for entry in report.entries if entry.status == CoverageStatus.GAP],
        )
        return self.repository.save_plan(plan)

    def generate_draft(
        self,
        *,
        plan_id: str,
        proposals: Sequence[RewriteProposal],
        allowed_evidence_by_item: Mapping[str, Sequence[ClaimEvidence]],
        token_usage: Mapping[str, int] | None = None,
    ) -> TailoringDraft:
        plan = self.repository.get_plan(plan_id)
        base = self.repository.get_version(plan.base_resume_version_id)
        items = {item.item_id: item for section in base.sections for item in section.items}
        claims = self.repository.list_claims(base.resume_version_id)
        supported_by_item: dict[str, list[CandidateClaim]] = {}
        for claim in claims:
            if claim.verification_state == ClaimVerification.SUPPORTED and claim.superseded_by_claim_id is None:
                supported_by_item.setdefault(claim.item_id, []).append(claim)
        changes: list[TailoringChange] = []
        for proposal in proposals:
            if proposal.item_id not in items:
                raise ValueError(f"rewrite references unknown resume item: {proposal.item_id}")
            evidence = list(allowed_evidence_by_item.get(proposal.item_id, ()))
            allowed_ids = {item.evidence_link.link_id for item in evidence}
            reasons = self._verify_rewrite(
                original=items[proposal.item_id].current_text,
                rewritten=proposal.rewritten_text,
                supported_original=supported_by_item.get(proposal.item_id, []),
                allowed_evidence=evidence,
                declared_evidence_ids=proposal.used_evidence_ids,
                allowed_evidence_ids=allowed_ids,
                forbidden_claims=plan.do_not_claim,
            )
            changes.append(
                TailoringChange(
                    change_id=_stable_id("resume-change", plan.plan_id if hasattr(plan, "plan_id") else plan.tailoring_plan_id, proposal.item_id, proposal.rewritten_text),
                    item_id=proposal.item_id,
                    before=items[proposal.item_id].current_text,
                    after=proposal.rewritten_text,
                    reason="grounded rewrite for target requirements",
                    requirement_ids=proposal.target_requirement_ids,
                    evidence_ids=proposal.used_evidence_ids,
                    change_type=proposal.change_type,
                    accepted_by_gate=not reasons,
                    rejection_reasons=reasons,
                )
            )
        draft_material = [change.model_dump(mode="json") for change in changes]
        draft = TailoringDraft(
            draft_id=_stable_id("resume-draft", plan.tailoring_plan_id, _digest(draft_material)),
            plan_id=plan.tailoring_plan_id,
            base_resume_version_id=base.resume_version_id,
            created_at=self._now(),
            changes=changes,
            allowed_evidence_by_item={
                item_id: list(values)
                for item_id, values in allowed_evidence_by_item.items()
            },
            token_usage={key: int(value) for key, value in (token_usage or {}).items()},
        )
        return self.repository.save_draft(draft)

    def review_draft(
        self,
        draft_id: str,
        *,
        approved_change_ids: Sequence[str],
    ) -> TailoringDraft:
        draft = self.repository.get_draft(draft_id)
        available = {change.change_id: change for change in draft.changes}
        approved = list(dict.fromkeys(approved_change_ids))
        unknown = set(approved) - set(available)
        if unknown:
            raise ValueError(f"unknown draft changes: {sorted(unknown)}")
        rejected_by_gate = [item for item in approved if not available[item].accepted_by_gate]
        if rejected_by_gate:
            raise ValueError("unsupported changes cannot be approved")
        reviewed = draft.model_copy(
            update={
                "status": DraftStatus.REVIEWED,
                "approved_change_ids": approved,
                "rejected_change_ids": [item for item in available if item not in approved],
            }
        )
        return self.repository.save_draft(reviewed)

    def save_approved_version(self, draft_id: str, *, approval_action_id: str) -> ResumeVersion:
        draft = self.repository.get_draft(draft_id)
        if draft.status not in {DraftStatus.REVIEWED, DraftStatus.SAVED}:
            raise ValueError("draft must be explicitly reviewed before saving")
        plan = self.repository.get_plan(draft.plan_id)
        base = self.repository.get_version(draft.base_resume_version_id)
        approved = {item.change_id: item for item in draft.changes if item.change_id in draft.approved_change_ids}
        by_item = {item.item_id: item for item in approved.values()}
        sections = copy.deepcopy(base.sections)
        for section in sections:
            for index, item in enumerate(section.items):
                change = by_item.get(item.item_id)
                if change is not None:
                    section.items[index] = item.model_copy(update={"current_text": change.after})
            section.items.sort(key=lambda item: (item.item_id not in plan.highlight_items, item.order))
            section.items = [item.model_copy(update={"order": index}) for index, item in enumerate(section.items)]
        content_hash = _content_hash(sections)
        approval_digest = _digest({"draft_id": draft_id, "action_id": approval_action_id, "changes": sorted(approved)})
        version_number = self.repository.next_version(base.resume_id)
        version = ResumeVersion(
            resume_version_id=_stable_id("resume-version", base.resume_id, approval_digest),
            resume_id=base.resume_id,
            version=version_number,
            parent_version_id=base.resume_version_id,
            target_job_id=plan.target_job_id,
            target_jd_snapshot_id=plan.target_jd_snapshot_id,
            target_jd_version=plan.target_jd_version,
            analysis_snapshot_id=plan.analysis_snapshot_id,
            tailoring_plan_id=plan.tailoring_plan_id,
            created_at=self._now(),
            source_type=base.source_type,
            status=ResumeVersionStatus.SAVED,
            content_hash=content_hash,
            raw_text=self.render_text(sections),
            sections=sections,
            metadata={**base.metadata, "approved_change_ids": sorted(approved)},
        )
        saved = self.repository.save_version(version, approval_digest=approval_digest)
        if not self.repository.list_claims(saved.resume_version_id):
            evidence_by_text: dict[str, list[ClaimEvidence]] = {}
            for claim in self.repository.list_claims(base.resume_version_id):
                if claim.evidence:
                    evidence_by_text[claim.canonical_claim] = claim.evidence
            for change in approved.values():
                evidence_by_text[change.after] = list(
                    draft.allowed_evidence_by_item.get(change.item_id, ())
                )
            self.audit_claims(
                saved.resume_version_id,
                evidence_by_text=evidence_by_text,
            )
        if draft.status != DraftStatus.SAVED:
            self.repository.save_draft(draft.model_copy(update={"status": DraftStatus.SAVED}))
        return saved

    def compare_versions(self, from_version_id: str, to_version_id: str) -> ResumeVersionDiff:
        before = self.repository.get_version(from_version_id)
        after = self.repository.get_version(to_version_id)
        before_items = {item.item_id: (section, item) for section in before.sections for item in section.items}
        after_items = {item.item_id: (section, item) for section in after.sections for item in section.items}
        added = [
            {"item_id": item_id, "text": item.current_text, "section": section.kind.value}
            for item_id, (section, item) in after_items.items()
            if item_id not in before_items
        ]
        removed = [
            {"item_id": item_id, "text": item.current_text, "section": section.kind.value}
            for item_id, (section, item) in before_items.items()
            if item_id not in after_items
        ]
        rewritten, moved, skills = [], [], []
        for item_id in before_items.keys() & after_items.keys():
            before_section, before_item = before_items[item_id]
            after_section, after_item = after_items[item_id]
            if before_item.current_text != after_item.current_text:
                change = {"item_id": item_id, "before": before_item.current_text, "after": after_item.current_text}
                rewritten.append(change)
                if before_section.kind == SectionKind.SKILLS:
                    skills.append(change)
            if before_section.kind != after_section.kind or before_item.order != after_item.order:
                moved.append(
                    {
                        "item_id": item_id,
                        "from_section": before_section.kind.value,
                        "to_section": after_section.kind.value,
                        "from_order": before_item.order,
                        "to_order": after_item.order,
                    }
                )
        return ResumeVersionDiff(
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            added=added,
            removed=removed,
            rewritten=rewritten,
            moved=moved,
            skills=skills,
        )

    def is_stale_for_job(self, resume_version_id: str, *, active_jd_snapshot_id: str) -> bool:
        version = self.repository.get_version(resume_version_id)
        return bool(version.target_jd_snapshot_id and version.target_jd_snapshot_id != active_jd_snapshot_id)

    def link_to_application(
        self,
        *,
        tracker: ApplicationTrackerStore,
        user_id: str,
        application_id: str,
        job_id: str,
        resume_version_id: str,
    ) -> ApplicationResumeLink:
        version = self.repository.get_version(resume_version_id)
        if version.status != ResumeVersionStatus.SAVED:
            raise ValueError("only a formally saved resume version may be used for an application")
        application = next(
            (item for item in tracker.load(user_id=user_id).applications if item.id == application_id),
            None,
        )
        if application is None:
            raise ValueError(f"application not found: {application_id}")
        if application.job_id and application.job_id != job_id:
            raise ValueError("application belongs to another job")
        return self.repository.link_application(
            ApplicationResumeLink(
                application_id=application_id,
                job_id=job_id,
                resume_version_id=resume_version_id,
                linked_at=self._now(),
            )
        )

    @staticmethod
    def render_text(sections: Sequence[ResumeSection]) -> str:
        blocks = []
        for section in sorted(sections, key=lambda item: item.order):
            blocks.append(f"## {section.title}")
            blocks.extend(f"- {item.current_text}" for item in sorted(section.items, key=lambda item: item.order))
        return "\n".join(blocks)

    def _parse_text(self, resume_id: str, text: str) -> list[ResumeSection]:
        sections: list[tuple[SectionKind, str, list[str]]] = []
        current_kind, current_title, current_items = SectionKind.OTHER, "Other", []
        saw_heading = False
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading = re.sub(r"^#{1,6}\s*", "", line).strip().rstrip(":：")
            heading_kind = SECTION_ALIASES.get(heading.casefold())
            looks_like_heading = heading_kind is not None or line.startswith("#")
            if looks_like_heading:
                if current_items or saw_heading:
                    sections.append((current_kind, current_title, current_items))
                current_kind = heading_kind or SectionKind.OTHER
                current_title = heading
                current_items = []
                saw_heading = True
                continue
            value = re.sub(r"^(?:[-*•]|\d+[.)])\s*", "", line).strip()
            if value:
                current_items.append(value)
        if current_items or not sections:
            sections.append((current_kind, current_title, current_items))
        result: list[ResumeSection] = []
        for section_order, (kind, title, values) in enumerate(sections):
            section_id = _stable_id("resume-section", resume_id, str(section_order), kind.value)
            items = [
                ResumeItem(
                    item_id=_stable_id("resume-item", resume_id, section_id, str(item_order)),
                    section=kind,
                    original_text=value,
                    current_text=value,
                    order=item_order,
                )
                for item_order, value in enumerate(values)
            ]
            result.append(
                ResumeSection(
                    section_id=section_id,
                    kind=kind,
                    title=title or kind.value.title(),
                    order=section_order,
                    items=items,
                )
            )
        return result

    @staticmethod
    def _matching_evidence(
        claim_text: str,
        evidence_by_text: Mapping[str, Sequence[ClaimEvidence]],
    ) -> list[ClaimEvidence]:
        matched: list[ClaimEvidence] = []
        for key, values in evidence_by_text.items():
            if key.casefold() in claim_text.casefold() or _overlap(key, claim_text) >= 0.5:
                matched.extend(values)
        return list({item.evidence_link.link_id: item for item in matched}.values())

    def _verify_rewrite(
        self,
        *,
        original: str,
        rewritten: str,
        supported_original: Sequence[CandidateClaim],
        allowed_evidence: Sequence[ClaimEvidence],
        declared_evidence_ids: Sequence[str],
        allowed_evidence_ids: set[str],
        forbidden_claims: Sequence[str],
    ) -> list[str]:
        reasons: list[str] = []
        if set(declared_evidence_ids) - allowed_evidence_ids:
            reasons.append("rewrite cites evidence outside the allowed context")
        public_evidence = [
            item for item in allowed_evidence if item.visibility != DisclosureVisibility.PRIVATE_ONLY
        ]
        support_texts = [
            item.anonymized_text
            if item.visibility == DisclosureVisibility.ANONYMIZED_ONLY
            else f"{item.evidence_link.claim} {item.evidence_link.source_span.exact_quote}"
            for item in public_evidence
        ]
        supported_texts = [item.canonical_claim for item in supported_original]
        all_support = [*supported_texts, *(item or "" for item in support_texts)]
        if normalize_text(rewritten).strip() == normalize_text(original).strip():
            return list(dict.fromkeys(reasons))
        for forbidden in forbidden_claims:
            if _overlap(forbidden, rewritten) >= 0.5 or forbidden.casefold() in rewritten.casefold():
                reasons.append(f"gap laundering: {forbidden}")
        for number in _numbers(rewritten):
            if not any(number in text for text in all_support):
                reasons.append(f"unsupported numeric claim: {number}")
        for technology in _technologies(rewritten):
            if not any(technology.casefold() in text.casefold() for text in all_support):
                reasons.append(f"unsupported technology: {technology}")
        support_lower = " ".join(all_support).casefold()
        for term in RESPONSIBILITY_TERMS:
            if term in rewritten.casefold() and term not in support_lower:
                reasons.append(f"responsibility inflation: {term.strip()}")
        for claim in _claims(rewritten):
            if not any(_overlap(claim, support) >= 0.34 for support in all_support):
                reasons.append(f"unsupported factual claim: {claim}")
        if any(item.visibility == DisclosureVisibility.PRIVATE_ONLY for item in allowed_evidence):
            private_text = " ".join(
                f"{item.evidence_link.claim} {item.evidence_link.source_span.exact_quote}"
                for item in allowed_evidence
                if item.visibility == DisclosureVisibility.PRIVATE_ONLY
            )
            if _overlap(rewritten, private_text) >= 0.5:
                reasons.append("private-only evidence leaked into resume output")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _evidence_visibility(evidence: Sequence[ClaimEvidence]) -> DisclosureVisibility:
        priority = {
            DisclosureVisibility.PUBLIC: 0,
            DisclosureVisibility.RESUME_SAFE: 1,
            DisclosureVisibility.ANONYMIZED_ONLY: 2,
            DisclosureVisibility.PRIVATE_ONLY: 3,
        }
        if not evidence:
            return DisclosureVisibility.RESUME_SAFE
        return max((item.visibility for item in evidence), key=priority.__getitem__)
