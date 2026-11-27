from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from job_agent.resume.contracts import (
    CandidateClaim,
    ClaimVerification,
    DisclosureVisibility,
    ResumeVersion,
)
from job_agent.resume.repository import ResumeRepository
from job_agent.schemas import ApplicationRecord, ApplicationStatus
from job_agent.text_identity import normalize_text
from job_agent.tools.application_tracker import ApplicationTrackerStore

from .copilot_contracts import (
    AnswerEvaluation,
    ApplicationDashboard,
    ClaimGrounding,
    CopilotHistory,
    EvaluationLevel,
    InterviewAnalytics,
    InterviewMode,
    InterviewPrepSnapshot,
    InterviewQuestion,
    InterviewReviewItem,
    InterviewRound,
    InterviewRoundStatus,
    InterviewRoundType,
    InterviewTurnRecord,
    InterviewWeaknessSnapshot,
    MockInterviewSession,
    PrepGapDefense,
    PrepJobFocus,
    PrepProjectDeepDive,
    PrepResumeFocus,
    PrepTechnicalTopic,
    QuestionDifficulty,
    QuestionSourceType,
    RealInterviewQuestion,
    RealInterviewRecord,
    SessionStatus,
    UnsupportedClaim,
    WeaknessHistoryEvent,
    WeaknessSeverity,
    WeaknessStatus,
)
from .copilot_repository import InterviewCopilotRepository, stable_id


_TECHNOLOGIES = {
    "agent loop",
    "bm25",
    "deepseek",
    "docker",
    "faiss",
    "fastapi",
    "kubernetes",
    "langgraph",
    "lora",
    "mcp",
    "postgresql",
    "python",
    "rag",
    "redis",
    "rrf",
    "sqlite",
}
_PERSONAL_EXPERIENCE = re.compile(
    r"(?:我(?:在|曾|负责|主导|使用|部署|实现|做过|上线|带领)|"
    r"我们(?:在|使用|部署|实现|上线)|"
    r"\bI\s+(?:used|built|deployed|implemented|led|owned)|"
    r"\bwe\s+(?:used|built|deployed|implemented))",
    re.IGNORECASE,
)
_PRODUCTION = re.compile(r"生产环境|线上环境|production", re.IGNORECASE)
_OWNERSHIP = re.compile(r"主导|独立负责|带领|全权负责|\bled\b|\bowned\b", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?%?(?![\w.])")
_WORDS = re.compile(r"[\w+#.-]{2,}", re.UNICODE)


JOB_AGENT_QUESTIONS: tuple[dict[str, Any], ...] = (
    {"prompt": "为什么把 PARTIAL 从模型判断改成 deterministic aggregation？", "category": "Evidence", "difficulty": "ADVANCED", "points": ["可重复性", "原子证据状态", "聚合规则", "失败边界"]},
    {"prompt": "为什么 Recall@1 只有 64% 时没有立刻增加 reranker？", "category": "RAG", "difficulty": "ADVANCED", "points": ["错误分析", "基线优先", "复杂度成本", "评测证据"]},
    {"prompt": "Runtime 中 approval 和 authorization 为什么要分开？", "category": "Tool governance", "difficulty": "ADVANCED", "points": ["策略判定", "用户同意", "action digest", "重放保护"]},
    {"prompt": "R12 为什么 Gold Atomic 93%，E2E 只有 50.98%？", "category": "Atomic benchmark", "difficulty": "CHALLENGE", "points": ["上游误差传播", "候选召回", "端到端分母", "系统瓶颈"]},
    {"prompt": "你怎么证明简历 tailoring 没有 hallucination？", "category": "Resume grounding", "difficulty": "ADVANCED", "points": ["claim inventory", "evidence allowlist", "deterministic gate", "unsupported claim rate"]},
    {"prompt": "为什么这个系统当前不用 Multi-Agent？", "category": "Agent architecture", "difficulty": "INTERMEDIATE", "points": ["单 Agent 能力边界", "状态一致性", "成本", "可观测性"]},
    {"prompt": "Application 和 Job Workspace 为什么分开？", "category": "Durable State", "difficulty": "ADVANCED", "points": ["canonical job identity", "求职流程状态", "生命周期差异", "稳定引用"]},
    {"prompt": "Context / Referent 在多轮任务中如何避免指错岗位？", "category": "Context", "difficulty": "ADVANCED", "points": ["referent resolution", "明确歧义", "稳定 ID", "session state"]},
    {"prompt": "MCP tool 为什么仍然必须经过 Runtime governance？", "category": "MCP", "difficulty": "ADVANCED", "points": ["registry", "policy", "budget", "trajectory"]},
    {"prompt": "Durable Runtime 如何处理 approval 后的 resume 和重复执行？", "category": "Durable State", "difficulty": "CHALLENGE", "points": ["checkpoint", "idempotency", "action digest", "exactly-once effect"]},
    {"prompt": "unseen holdout 与普通回归集分别证明什么？", "category": "Evaluation", "difficulty": "INTERMEDIATE", "points": ["泛化", "泄漏控制", "稳定回归", "失败分层"]},
    {"prompt": "Job Workspace 扩到大规模岗位后，怎样保持版本和 lineage？", "category": "Job Workspace", "difficulty": "ADVANCED", "points": ["稳定 job id", "JD snapshot", "analysis snapshot", "lineage"]},
)


def _now() -> datetime:
    return datetime.now(UTC)


def _terms(value: str) -> set[str]:
    return {item.casefold() for item in _WORDS.findall(normalize_text(value))}


def _contains_point(answer: str, point: str) -> bool:
    answer_key = " ".join(answer.casefold().split())
    point_key = " ".join(point.casefold().split())
    if point_key in answer_key:
        return True
    tokens = _terms(point)
    if not tokens:
        return False
    return len(tokens.intersection(_terms(answer))) / len(tokens) >= 0.5


class ApplicationCopilotService:
    def __init__(
        self,
        *,
        repository: InterviewCopilotRepository,
        tracker_store: ApplicationTrackerStore,
        resume_repository: ResumeRepository,
        user_id: str,
        now=_now,
    ) -> None:
        self.repository = repository
        self.tracker_store = tracker_store
        self.resume_repository = resume_repository
        self.user_id = user_id
        self._now = now

    def application(self, application_id: str) -> ApplicationRecord:
        tracker = self.tracker_store.load(user_id=self.user_id)
        for application in tracker.applications:
            if application.id == application_id:
                return application
        raise ValueError("application not found")

    def set_next_action(
        self,
        application_id: str,
        *,
        action_id: str,
        next_action: str,
        due_at: str | None = None,
    ) -> ApplicationRecord:
        if not next_action.strip():
            raise ValueError("next_action is required")
        return self.tracker_store.update_copilot_fields(
            user_id=self.user_id,
            application_id=application_id,
            action_id=action_id,
            next_action=next_action.strip(),
            next_action_due_at=due_at,
        )

    def bind_resume(self, application_id: str, *, resume_version_id: str, action_id: str) -> ApplicationRecord:
        application = self.application(application_id)
        version = self.resume_repository.get_version(resume_version_id)
        link = self.resume_repository.application_link(application_id)
        if link is None or link.job_id != application.job_id or link.resume_version_id != version.resume_version_id:
            raise ValueError("application must be linked to the exact resume version first")
        return self.tracker_store.update_copilot_fields(
            user_id=self.user_id,
            application_id=application_id,
            action_id=action_id,
            resume_version_id=resume_version_id,
        )

    def create_round(
        self,
        application_id: str,
        *,
        action_id: str,
        round_type: InterviewRoundType,
        scheduled_at: datetime | None = None,
        interviewer_role: str | None = None,
        notes: str = "",
    ) -> InterviewRound:
        application = self.application(application_id)
        existing_id = self.repository.existing_action(action_id, "create_round")
        if existing_id is not None:
            saved = self.repository.get_round(existing_id)
            self.tracker_store.update_copilot_fields(
                user_id=self.user_id,
                application_id=application.id,
                action_id=f"{action_id}-application-link",
                interview_round_id=saved.round_id,
                next_action=f"准备第 {saved.round_number} 轮面试",
                next_action_due_at=(saved.scheduled_at.isoformat() if saved.scheduled_at else None),
            )
            return saved
        rounds = self.repository.list_rounds(application_id)
        number = len(rounds) + 1
        value = InterviewRound(
            round_id=stable_id("round", application_id, action_id),
            application_id=application_id,
            round_type=round_type,
            round_number=number,
            scheduled_at=scheduled_at,
            interviewer_role=interviewer_role,
            created_at=self._now(),
            notes=notes,
        )
        saved = self.repository.create_round(value, action_id=action_id)
        self.tracker_store.update_copilot_fields(
            user_id=self.user_id,
            application_id=application.id,
            action_id=f"{action_id}-application-link",
            interview_round_id=saved.round_id,
            next_action=f"准备第 {saved.round_number} 轮面试",
            next_action_due_at=(scheduled_at.isoformat() if scheduled_at else None),
        )
        return saved

    def create_prep(
        self,
        *,
        application_id: str,
        round_id: str,
        action_id: str,
        jd_snapshot_id: str,
        jd_version: int,
        analysis_snapshot_id: str,
        requirements: Sequence[Mapping[str, Any]],
        mode: InterviewMode = InterviewMode.QUICK_PREP,
    ) -> InterviewPrepSnapshot:
        existing_id = self.repository.existing_action(action_id, "create_prep")
        if existing_id is not None:
            existing = self.repository.get_prep(existing_id)
            if not self.repository.list_questions(existing.prep_version_id):
                claims = self.resume_repository.list_claims(existing.resume_version_id)
                self.generate_questions(existing, requirements=requirements, claims=claims)
            return existing
        application = self.application(application_id)
        if not application.job_id:
            raise ValueError("application is not linked to a job")
        round_value = self.repository.get_round(round_id)
        if round_value.application_id != application_id:
            raise ValueError("interview round belongs to another application")
        resume_version = self._bound_resume(application)
        claims = self.resume_repository.list_claims(resume_version.resume_version_id)
        safe_claims = [
            claim
            for claim in claims
            if claim.verification_state == ClaimVerification.SUPPORTED
            and claim.visibility != DisclosureVisibility.PRIVATE_ONLY
        ]
        strengths = [str(item.get("text", "")) for item in requirements if item.get("strength")]
        gaps = [str(item.get("text", "")) for item in requirements if item.get("gap")]
        requirement_texts = [str(item.get("text", "")) for item in requirements if item.get("text")]
        resume_focus = [
            PrepResumeFocus(
                item_id=claim.item_id,
                text=claim.canonical_claim,
                reason="与目标岗位要求有可验证交集，面试时应准备动机、实现、评测和边界。",
                claim_refs=[claim.claim_id],
            )
            for claim in safe_claims[:8]
        ]
        technical = [
            PrepTechnicalTopic(
                topic=text,
                reason="目标岗位 requirement",
                requirement_refs=[str(item.get("requirement_id") or item.get("atom_id") or text)],
            )
            for item, text in zip(requirements, requirement_texts)
        ]
        projects = [
            PrepProjectDeepDive(
                project=focus.text,
                prompts=["设计动机是什么？", "核心实现和取舍是什么？", "如何评测？", "失败与限制是什么？"],
                evidence_refs=focus.claim_refs,
            )
            for focus in resume_focus[:4]
        ]
        defenses = [
            PrepGapDefense(
                gap=gap,
                honest_boundary="明确没有直接项目经历，不把通用知识表述为个人实践。",
                transferable_experience=[claim.canonical_claim for claim in safe_claims[:2]],
            )
            for gap in gaps
        ]
        version = self.repository.next_prep_version(application_id)
        prep = InterviewPrepSnapshot(
            prep_version_id=stable_id("prep", application_id, action_id),
            version=version,
            application_id=application_id,
            job_id=application.job_id,
            jd_snapshot_id=jd_snapshot_id,
            jd_version=jd_version,
            analysis_snapshot_id=analysis_snapshot_id,
            interview_round_id=round_id,
            resume_version_id=resume_version.resume_version_id,
            mode=mode,
            created_at=self._now(),
            job_focus=PrepJobFocus(requirements=requirement_texts, strengths=strengths, gaps=gaps),
            resume_focus=resume_focus,
            technical_review=technical,
            project_deep_dive=projects,
            gap_defense=defenses,
            questions_to_ask=[
                "这个岗位前三个月最重要的交付和衡量标准是什么？",
                "团队当前在 Agent 可靠性或评测上最需要解决的问题是什么？",
                "这一轮之后的面试重点和后续流程是什么？",
            ],
            token_usage={
                "prep_context_chars": sum(len(value) for value in requirement_texts)
                + len(resume_version.raw_text),
                "prep_estimated_tokens": max(
                    1,
                    (sum(len(value) for value in requirement_texts) + len(resume_version.raw_text)) // 4,
                ),
            },
        )
        saved = self.repository.save_prep(prep, action_id=action_id)
        self.generate_questions(saved, requirements=requirements, claims=claims)
        return saved

    def prep_is_stale(
        self,
        prep_version_id: str,
        *,
        active_jd_snapshot_id: str,
        active_analysis_snapshot_id: str,
        active_resume_version_id: str,
    ) -> bool:
        prep = self.repository.get_prep(prep_version_id)
        return any(
            (
                prep.jd_snapshot_id != active_jd_snapshot_id,
                prep.analysis_snapshot_id != active_analysis_snapshot_id,
                prep.resume_version_id != active_resume_version_id,
            )
        )

    def generate_questions(
        self,
        prep: InterviewPrepSnapshot,
        *,
        requirements: Sequence[Mapping[str, Any]],
        claims: Sequence[CandidateClaim],
    ) -> list[InterviewQuestion]:
        created: list[InterviewQuestion] = []
        timestamp = self._now()
        for index, spec in enumerate(JOB_AGENT_QUESTIONS, start=1):
            created.append(
                self.repository.save_question(
                    InterviewQuestion(
                        question_id=stable_id("question", prep.prep_version_id, "job-agent", index),
                        source_type=QuestionSourceType.RESUME_PROJECT,
                        category=str(spec["category"]),
                        difficulty=QuestionDifficulty(str(spec["difficulty"])),
                        prompt=str(spec["prompt"]),
                        why_asked="验证当前 Job Agent 项目的设计判断、评测意识和真实实现深度。",
                        resume_claim_refs=[claim.claim_id for claim in claims[:3]],
                        evidence_refs=[ref for claim in claims[:3] for ref in _claim_refs(claim)],
                        expected_points=list(spec["points"]),
                        created_at=timestamp,
                        metadata={"prep_version_id": prep.prep_version_id, "job_id": prep.job_id},
                    )
                )
            )
        for index, requirement in enumerate(requirements, start=1):
            text = str(requirement.get("text", "")).strip()
            if not text:
                continue
            requirement_id = str(requirement.get("requirement_id") or requirement.get("atom_id") or f"req-{index}")
            source_type = QuestionSourceType.CAREER_GAP if requirement.get("gap") else QuestionSourceType.JOB_REQUIREMENT
            created.append(
                self.repository.save_question(
                    InterviewQuestion(
                        question_id=stable_id("question", prep.prep_version_id, requirement_id),
                        source_type=source_type,
                        category=str(requirement.get("category") or "Job requirement"),
                        difficulty=QuestionDifficulty.INTERMEDIATE,
                        prompt=(
                            f"你会怎样解释自己在“{text}”上的经验和边界？"
                            if source_type == QuestionSourceType.CAREER_GAP
                            else f"请结合可验证项目说明你如何满足：{text}"
                        ),
                        why_asked="直接对应目标岗位 requirement。",
                        job_requirement_refs=[requirement_id],
                        evidence_refs=[str(value) for value in requirement.get("evidence_refs", [])],
                        expected_points=["直接回答 requirement", "具体实现或知识", "证据或结果", "诚实边界"],
                        created_at=timestamp,
                        metadata={"prep_version_id": prep.prep_version_id, "job_id": prep.job_id},
                    )
                )
            )
        for index, claim in enumerate(claims[:12], start=1):
            created.append(
                self.repository.save_question(
                    InterviewQuestion(
                        question_id=stable_id("question", prep.prep_version_id, "claim", claim.claim_id),
                        source_type=QuestionSourceType.RESUME_PROJECT,
                        category=claim.category,
                        difficulty=QuestionDifficulty.ADVANCED,
                        prompt=f"围绕简历中的“{claim.canonical_claim}”，说明你的具体贡献、取舍、评测和限制。",
                        why_asked="核验当前投递简历版本中的个人 claim。",
                        resume_claim_refs=[claim.claim_id],
                        evidence_refs=_claim_refs(claim),
                        expected_points=["个人贡献", "技术取舍", "评测结果", "失败或限制"],
                        created_at=timestamp,
                        metadata={"prep_version_id": prep.prep_version_id, "job_id": prep.job_id},
                    )
                )
            )
        for question in created:
            self.repository.link_question(prep.prep_version_id, question.question_id)
        return created

    def start_mock(
        self,
        prep_version_id: str,
        *,
        action_id: str,
        mode: InterviewMode = InterviewMode.MOCK_INTERVIEW,
        targeted_retry: bool = False,
    ) -> MockInterviewSession:
        if mode == InterviewMode.QUICK_PREP:
            raise ValueError("QUICK_PREP does not create a mock session")
        existing_id = self.repository.existing_action(action_id, "start_mock")
        if existing_id is not None:
            return self.repository.get_session(existing_id)
        prep = self.repository.get_prep(prep_version_id)
        questions = self.repository.list_questions(prep_version_id)
        if mode == InterviewMode.PROJECT_DEEP_DIVE:
            questions = [value for value in questions if value.source_type == QuestionSourceType.RESUME_PROJECT]
        elif mode == InterviewMode.GAP_REVIEW:
            questions = [value for value in questions if value.source_type == QuestionSourceType.CAREER_GAP]
        if targeted_retry:
            open_categories = {
                weakness.category
                for weakness in self.repository.list_weaknesses(prep.application_id)
                if weakness.status != WeaknessStatus.RESOLVED
            }
            targeted = [value for value in questions if value.category in open_categories]
            questions = targeted or questions
        if not questions:
            raise ValueError("no questions available for selected interview mode")
        selected = questions[:12]
        session = MockInterviewSession(
            session_id=stable_id("mock", prep.application_id, action_id),
            application_id=prep.application_id,
            round_id=prep.interview_round_id,
            job_id=prep.job_id,
            resume_version_id=prep.resume_version_id,
            prep_version_id=prep.prep_version_id,
            mode=mode,
            status=SessionStatus.IN_PROGRESS,
            started_at=self._now(),
            question_ids=[value.question_id for value in selected],
            token_usage={
                "question_context_chars": sum(len(value.prompt) for value in selected),
                "question_estimated_tokens": max(1, sum(len(value.prompt) for value in selected) // 4),
            },
        )
        return self.repository.create_session(session, action_id=action_id)

    def submit_answer(
        self,
        session_id: str,
        *,
        question_id: str,
        answer: str,
        action_id: str,
    ) -> InterviewTurnRecord:
        existing_id = self.repository.existing_action(action_id, "submit_answer")
        if existing_id is not None:
            existing_session = self.repository.get_session(existing_id)
            existing_turn = next(
                (turn for turn in existing_session.turns if turn.turn_id == stable_id("turn", session_id, action_id)),
                None,
            )
            if existing_turn is None or existing_turn.question.question_id != question_id or existing_turn.user_answer != answer:
                raise ValueError("answer action idempotency conflict")
            return existing_turn
        session = self.repository.get_session(session_id)
        if session.status != SessionStatus.IN_PROGRESS:
            raise ValueError("mock session is not in progress")
        if question_id not in session.question_ids:
            raise ValueError("question is not part of the mock session")
        question = self.repository.get_question(question_id)
        claims = self.resume_repository.list_claims(session.resume_version_id)
        evaluation = evaluate_answer(question, answer, claims)
        ordinal = len(session.turns) + 1
        follow_up = self._follow_up(question, evaluation, session_id, ordinal)
        turn = InterviewTurnRecord(
            turn_id=stable_id("turn", session_id, action_id),
            session_id=session_id,
            ordinal=ordinal,
            question=question,
            user_answer=answer,
            evaluation=evaluation,
            follow_up=follow_up,
            created_at=self._now(),
            token_usage={
                "evaluation_context_chars": len(question.prompt) + len(answer),
                "evaluation_estimated_tokens": max(1, (len(question.prompt) + len(answer)) // 4),
                "follow_up_estimated_tokens": max(0, len(follow_up.prompt) // 4) if follow_up else 0,
            },
        )
        usage = _sum_usage(session.token_usage, turn.token_usage)
        updated = session.model_copy(update={"turns": [*session.turns, turn], "token_usage": usage})
        saved = self.repository.save_session(updated, action_id=action_id, kind="submit_answer")
        return saved.turns[-1]

    def complete_session(self, session_id: str, *, action_id: str) -> MockInterviewSession:
        existing_id = self.repository.existing_action(action_id, "complete_session")
        if existing_id is not None:
            existing = self.repository.get_session(existing_id)
            self._update_weaknesses(existing, action_id=action_id)
            return existing
        session = self.repository.get_session(session_id)
        if session.status == SessionStatus.COMPLETED:
            return session
        if not session.turns:
            raise ValueError("cannot complete an empty mock session")
        weak = sum(
            turn.evaluation.completeness != EvaluationLevel.GOOD
            or turn.evaluation.grounding == ClaimGrounding.UNSUPPORTED_CLAIM
            for turn in session.turns
        )
        summary = f"完成 {len(session.turns)} 题；{weak} 题需要继续复习。"
        completed = session.model_copy(
            update={"status": SessionStatus.COMPLETED, "completed_at": self._now(), "summary": summary}
        )
        saved = self.repository.save_session(completed, action_id=action_id, kind="complete_session")
        self._update_weaknesses(saved, action_id=action_id)
        return saved

    def update_weakness_status(
        self,
        weakness_id: str,
        *,
        status: WeaknessStatus,
        session_id: str,
        note: str,
        action_id: str,
    ) -> InterviewWeaknessSnapshot:
        existing_id = self.repository.existing_action(action_id, "save_weakness")
        if existing_id is not None:
            return self.repository.get_weakness(existing_id)
        value = self.repository.get_weakness(weakness_id)
        if value.status == status:
            return value
        allowed = {
            WeaknessStatus.OPEN: {WeaknessStatus.IMPROVING},
            WeaknessStatus.IMPROVING: {WeaknessStatus.OPEN, WeaknessStatus.RESOLVED},
            WeaknessStatus.RESOLVED: {WeaknessStatus.OPEN},
        }
        if status not in allowed[value.status]:
            raise ValueError("invalid weakness transition")
        updated = value.model_copy(
            update={
                "status": status,
                "history": [
                    *value.history,
                    WeaknessHistoryEvent(status=status, session_id=session_id, occurred_at=self._now(), note=note),
                ],
            }
        )
        application_id = self.repository.get_session(session_id).application_id
        return self.repository.save_weakness(application_id, updated, action_id=action_id)

    def review_queue(self, application_id: str | None = None) -> list[InterviewReviewItem]:
        weaknesses = [
            value
            for value in self.repository.list_weaknesses(application_id)
            if value.status != WeaknessStatus.RESOLVED
        ]
        grouped: dict[str, list[InterviewWeaknessSnapshot]] = defaultdict(list)
        for weakness in weaknesses:
            grouped[weakness.category].append(weakness)
        questions = self.repository.list_questions()
        values: list[InterviewReviewItem] = []
        for category, items in grouped.items():
            related_jobs = sorted(
                {
                    self._history_job_id(event.session_id)
                    for item in items
                    for event in item.history
                }
            )
            sessions = sorted({event.session_id for item in items for event in item.history})
            targeted = next(
                (
                    question.question_id
                    for question in questions
                    if question.category == category
                    and question.source_type != QuestionSourceType.FOLLOW_UP
                ),
                None,
            )
            severity = max({"LOW": 1, "MEDIUM": 2, "HIGH": 3}[item.severity.value] for item in items)
            values.append(
                InterviewReviewItem(
                    priority=severity * 100 + len(items),
                    topic=category,
                    reason=f"{len(items)} 个未解决 weakness；最近状态为 {items[-1].status.value}",
                    related_jobs=related_jobs,
                    source_sessions=sessions,
                    weakness_ids=[item.weakness_id for item in items],
                    targeted_question_id=targeted,
                )
            )
        values.sort(key=lambda item: (-item.priority, item.topic))
        return [item.model_copy(update={"priority": index}) for index, item in enumerate(values, start=1)]

    def _history_job_id(self, source_id: str) -> str:
        try:
            return self.repository.get_session(source_id).job_id
        except KeyError:
            return self.repository.get_real_interview(source_id).job_id

    def record_real_interview(
        self,
        *,
        application_id: str,
        round_id: str,
        action_id: str,
        occurred_at: datetime,
        questions: Sequence[RealInterviewQuestion],
        outcome: str | None = None,
        notes: str = "",
    ) -> RealInterviewRecord:
        existing_id = self.repository.existing_action(action_id, "record_real")
        if existing_id is not None:
            existing = self.repository.get_real_interview(existing_id)
            self._finalize_real_interview(existing, action_id)
            return existing
        application = self.application(application_id)
        if not application.job_id:
            raise ValueError("application is not linked to a job")
        round_value = self.repository.get_round(round_id)
        if round_value.application_id != application_id:
            raise ValueError("interview round belongs to another application")
        record = RealInterviewRecord(
            record_id=stable_id("real-interview", application_id, action_id),
            application_id=application_id,
            round_id=round_id,
            job_id=application.job_id,
            occurred_at=occurred_at,
            questions=list(questions),
            outcome=outcome,
            notes=notes,
            created_at=self._now(),
        )
        saved = self.repository.save_real_interview(record, action_id=action_id)
        self._finalize_real_interview(saved, action_id)
        return saved

    def _finalize_real_interview(self, saved: RealInterviewRecord, action_id: str) -> None:
        round_value = self.repository.get_round(saved.round_id)
        completed_round = round_value.model_copy(
            update={"status": InterviewRoundStatus.COMPLETED, "completed_at": saved.occurred_at}
        )
        self.repository.update_round(completed_round, action_id=f"{action_id}-round")
        for index, question in enumerate(saved.questions):
            if question.self_assessment == EvaluationLevel.WEAK:
                self._save_real_weakness(saved, question, index, action_id)

    def history(self, application_id: str) -> CopilotHistory:
        application = self.application(application_id)
        return CopilotHistory(
            application_id=application_id,
            stage=application.current_state,
            rounds=self.repository.list_rounds(application_id),
            prep_snapshots=self.repository.list_preps(application_id),
            mock_sessions=self.repository.list_sessions(application_id),
            real_interviews=self.repository.list_real_interviews(application_id),
            weaknesses=self.repository.list_weaknesses(application_id),
        )

    def dashboard(self, *, now: datetime | None = None, stale_days: int = 7) -> ApplicationDashboard:
        now = now or self._now()
        tracker = self.tracker_store.load(user_id=self.user_id)
        by_stage = Counter(value.current_state.value for value in tracker.applications)
        rounds = [round_value for app in tracker.applications for round_value in self.repository.list_rounds(app.id)]
        upcoming = sum(
            round_value.status == InterviewRoundStatus.PLANNED
            and round_value.scheduled_at is not None
            and round_value.scheduled_at >= now
            for round_value in rounds
        )
        waiting_states = {ApplicationStatus.APPLIED, ApplicationStatus.RESUME_SCREEN}
        waiting = sum(value.current_state in waiting_states for value in tracker.applications)
        stage_days = []
        for application in tracker.applications:
            if application.state_history:
                stage_days.append(max(0.0, (now - datetime.fromisoformat(application.state_history[-1].timestamp)).total_seconds() / 86400))
        families = Counter(value.tags[0] if value.tags and not value.tags[0].startswith("copilot-action:") else "OTHER" for value in tracker.applications)
        return ApplicationDashboard(
            total_applications=len(tracker.applications),
            by_stage=dict(by_stage),
            upcoming_interviews=upcoming,
            waiting_response=waiting,
            offers=by_stage[ApplicationStatus.OFFER.value] + by_stage[ApplicationStatus.ACCEPTED.value],
            rejections=by_stage[ApplicationStatus.REJECTED.value],
            withdrawn=by_stage[ApplicationStatus.WITHDRAWN.value],
            average_days_in_stage=(sum(stage_days) / len(stage_days) if stage_days else None),
            by_job_family=dict(families),
        )

    def inactive_applications(self, *, days: int = 7, now: datetime | None = None) -> list[ApplicationRecord]:
        cutoff = (now or self._now()) - timedelta(days=days)
        terminal = {
            ApplicationStatus.ACCEPTED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.ABANDONED,
            ApplicationStatus.CLOSED,
        }
        return [
            value
            for value in self.tracker_store.load(user_id=self.user_id).applications
            if value.current_state not in terminal
            and value.state_history
            and datetime.fromisoformat(value.state_history[-1].timestamp) <= cutoff
        ]

    def interviews_without_debrief(self) -> list[InterviewRound]:
        debriefed = {record.round_id for record in self.repository.list_real_interviews()}
        return [
            value
            for application in self.tracker_store.load(user_id=self.user_id).applications
            for value in self.repository.list_rounds(application.id)
            if value.status == InterviewRoundStatus.COMPLETED and value.round_id not in debriefed
        ]

    def analytics(self) -> InterviewAnalytics:
        sessions = self.repository.list_sessions()
        weaknesses = self.repository.list_weaknesses()
        categories = Counter(value.category for value in weaknesses)
        return InterviewAnalytics(
            mock_sessions=len(sessions),
            real_interview_records=len(self.repository.list_real_interviews()),
            questions_answered=sum(len(value.turns) for value in sessions),
            weakness_categories=dict(categories),
            repeated_weaknesses=sum(count > 1 for count in categories.values()),
            resolved_weaknesses=sum(value.status == WeaknessStatus.RESOLVED for value in weaknesses),
        )

    def _bound_resume(self, application: ApplicationRecord) -> ResumeVersion:
        link = self.resume_repository.application_link(application.id)
        if link is None:
            raise ValueError("application has no exact resume version link")
        if application.job_id != link.job_id:
            raise ValueError("application resume job mismatch")
        if application.resume_version_id and application.resume_version_id != link.resume_version_id:
            raise ValueError("application resume version drift")
        return self.resume_repository.get_version(link.resume_version_id)

    def _follow_up(
        self,
        question: InterviewQuestion,
        evaluation: AnswerEvaluation,
        session_id: str,
        ordinal: int,
    ) -> InterviewQuestion | None:
        if not evaluation.missing_points and not evaluation.unsupported_claims:
            return None
        missing = list(evaluation.missing_points[:3])
        if evaluation.unsupported_claims:
            missing.insert(0, "请区分通用知识与可验证的个人经历")
        reason = "回答仍缺少关键点" if missing else "回答包含未验证个人 claim"
        return self.repository.save_question(
            InterviewQuestion(
                question_id=stable_id("follow-up", session_id, ordinal, question.question_id),
                source_type=QuestionSourceType.FOLLOW_UP,
                category=question.category,
                difficulty=_next_difficulty(question.difficulty),
                prompt=f"请继续说明：{'；'.join(missing)}。",
                why_asked=reason,
                job_requirement_refs=question.job_requirement_refs,
                resume_claim_refs=question.resume_claim_refs,
                evidence_refs=question.evidence_refs,
                expected_points=missing or ["诚实边界"],
                created_at=self._now(),
                parent_question_id=question.question_id,
                missing_points=missing or ["诚实边界"],
                follow_up_reason=reason,
                metadata=question.metadata,
            )
        )

    def _update_weaknesses(self, session: MockInterviewSession, *, action_id: str) -> None:
        for turn in session.turns:
            evaluation = turn.evaluation
            if evaluation.completeness == EvaluationLevel.GOOD and evaluation.grounding != ClaimGrounding.UNSUPPORTED_CLAIM:
                continue
            weakness_action = f"{action_id}-weakness-{turn.ordinal}"
            if self.repository.existing_action(weakness_action, "save_weakness") is not None:
                continue
            category = turn.question.category
            existing = next(
                (
                    value
                    for value in reversed(self.repository.list_weaknesses(session.application_id))
                    if value.category == category and value.status != WeaknessStatus.RESOLVED
                ),
                None,
            )
            event = WeaknessHistoryEvent(
                status=WeaknessStatus.OPEN,
                session_id=session.session_id,
                occurred_at=self._now(),
                note="；".join(evaluation.feedback) or "回答需要补强",
            )
            if existing:
                updated = existing.model_copy(
                    update={
                        "supporting_turns": sorted({*existing.supporting_turns, turn.turn_id}),
                        "job_requirement_refs": sorted({*existing.job_requirement_refs, *turn.question.job_requirement_refs}),
                        "severity": max(existing.severity, _severity(evaluation), key=_severity_rank),
                        "status": WeaknessStatus.OPEN,
                        "history": [*existing.history, event],
                    }
                )
            else:
                updated = InterviewWeaknessSnapshot(
                    weakness_id=stable_id("weakness", session.application_id, category),
                    category=category,
                    description=_weakness_description(turn),
                    supporting_turns=[turn.turn_id],
                    job_requirement_refs=turn.question.job_requirement_refs,
                    severity=_severity(evaluation),
                    created_at=self._now(),
                    history=[event],
                )
            self.repository.save_weakness(
                session.application_id,
                updated,
                action_id=weakness_action,
            )

    def _save_real_weakness(
        self,
        record: RealInterviewRecord,
        question: RealInterviewQuestion,
        index: int,
        action_id: str,
    ) -> None:
        weakness_action = f"{action_id}-real-weakness-{index}"
        if self.repository.existing_action(weakness_action, "save_weakness") is not None:
            return
        category = "Real interview debrief"
        event = WeaknessHistoryEvent(
            status=WeaknessStatus.OPEN,
            session_id=record.record_id,
            occurred_at=self._now(),
            note=question.notes or "用户标记为未答好",
        )
        value = InterviewWeaknessSnapshot(
            weakness_id=stable_id("weakness", record.application_id, record.record_id, index),
            category=category,
            description=question.question,
            supporting_turns=[f"{record.record_id}:question:{index}"],
            job_requirement_refs=question.requirement_refs,
            severity=WeaknessSeverity.HIGH,
            created_at=self._now(),
            history=[event],
        )
        self.repository.save_weakness(
            record.application_id,
            value,
            action_id=weakness_action,
        )


def evaluate_answer(
    question: InterviewQuestion,
    answer: str,
    claims: Sequence[CandidateClaim],
) -> AnswerEvaluation:
    answer = normalize_text(answer).strip()
    if not answer:
        raise ValueError("answer must not be empty")
    supported = [claim for claim in claims if claim.verification_state == ClaimVerification.SUPPORTED]
    supported_text = "\n".join(claim.canonical_claim for claim in supported).casefold()
    supported_tech = {
        technology.casefold()
        for claim in supported
        for technology in claim.technologies
    } | {technology for technology in _TECHNOLOGIES if technology in supported_text}
    supported_numbers = {
        number
        for claim in supported
        for number in (*claim.numeric_values, *_NUMBER.findall(claim.canonical_claim))
    }
    personal = bool(_PERSONAL_EXPERIENCE.search(answer))
    answer_key = answer.casefold()
    mentioned_tech = {technology for technology in _TECHNOLOGIES if technology in answer_key}
    unsupported: list[UnsupportedClaim] = []
    if personal:
        for technology in sorted(mentioned_tech - supported_tech):
            unsupported.append(
                UnsupportedClaim(
                    text=technology,
                    kind="technology_experience",
                    reason="个人经历表述中的技术不在当前 ResumeVersion 的 supported claims 中。",
                )
            )
        if _PRODUCTION.search(answer) and not _PRODUCTION.search(supported_text):
            unsupported.append(
                UnsupportedClaim(
                    text="production scope",
                    kind="scope",
                    reason="生产环境范围没有可验证 Career Evidence。",
                )
            )
        if _OWNERSHIP.search(answer) and not _OWNERSHIP.search(supported_text):
            unsupported.append(
                UnsupportedClaim(
                    text="ownership scope",
                    kind="ownership",
                    reason="主导或责任范围没有出现在当前 ResumeVersion 的 supported claims 中。",
                )
            )
        for number in sorted(set(_NUMBER.findall(answer)) - supported_numbers):
            unsupported.append(
                UnsupportedClaim(
                    text=number,
                    kind="numeric",
                    reason="数字没有出现在当前 ResumeVersion 的 supported claims 中。",
                )
            )
    covered = [point for point in question.expected_points if _contains_point(answer, point)]
    missing = [point for point in question.expected_points if point not in covered]
    ratio = len(covered) / len(question.expected_points)
    completeness = EvaluationLevel.GOOD if ratio >= 0.75 else EvaluationLevel.PARTIAL if ratio >= 0.35 else EvaluationLevel.WEAK
    question_terms = _terms(question.prompt) - {"什么", "如何", "为什么", "说明", "please", "explain"}
    overlap = len(question_terms.intersection(_terms(answer)))
    relevance = EvaluationLevel.GOOD if overlap >= 2 or ratio > 0 else EvaluationLevel.PARTIAL if overlap else EvaluationLevel.WEAK
    specificity_signals = len(mentioned_tech) + len(_NUMBER.findall(answer)) + sum(term in answer_key for term in ("因为", "取舍", "trade-off", "失败", "限制"))
    specificity = EvaluationLevel.GOOD if specificity_signals >= 3 else EvaluationLevel.PARTIAL if specificity_signals else EvaluationLevel.WEAK
    structure = EvaluationLevel.GOOD if len(answer) >= 120 and sum(mark in answer for mark in ("首先", "其次", "最后", "1.", "2.")) >= 2 else EvaluationLevel.PARTIAL if len(answer) >= 50 else EvaluationLevel.WEAK
    if unsupported:
        grounding = ClaimGrounding.UNSUPPORTED_CLAIM
        factual = EvaluationLevel.WEAK
    elif personal:
        grounding = ClaimGrounding.SUPPORTED if supported else ClaimGrounding.UNSUPPORTED_CLAIM
        factual = EvaluationLevel.GOOD if supported else EvaluationLevel.WEAK
    elif mentioned_tech or question.source_type == QuestionSourceType.TECHNICAL:
        grounding = ClaimGrounding.TECHNICAL_KNOWLEDGE
        factual = EvaluationLevel.PARTIAL
    else:
        grounding = ClaimGrounding.NOT_APPLICABLE
        factual = EvaluationLevel.PARTIAL
    feedback = []
    if unsupported:
        feedback.append("区分通用技术知识与可验证的个人经历，删除或确认未支持 claim。")
    if missing:
        feedback.append(f"补充缺失点：{'、'.join(missing)}。")
    if specificity != EvaluationLevel.GOOD:
        feedback.append("增加具体设计、取舍、评测或限制，但不要新增未经验证的事实。")
    return AnswerEvaluation(
        factual_grounding=factual,
        relevance=relevance,
        completeness=completeness,
        specificity=specificity,
        structure=structure,
        grounding=grounding,
        covered_points=covered,
        missing_points=missing,
        unsupported_claims=unsupported,
        feedback=feedback,
        source_refs=sorted({*question.evidence_refs, *(ref for claim in supported for ref in _claim_refs(claim))}),
    )


def _claim_refs(claim: CandidateClaim) -> list[str]:
    return [binding.evidence_link.link_id for binding in claim.evidence]


def _next_difficulty(value: QuestionDifficulty) -> QuestionDifficulty:
    order = [
        QuestionDifficulty.BASIC,
        QuestionDifficulty.INTERMEDIATE,
        QuestionDifficulty.ADVANCED,
        QuestionDifficulty.CHALLENGE,
    ]
    return order[min(order.index(value) + 1, len(order) - 1)]


def _sum_usage(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    result = dict(left)
    for key, value in right.items():
        result[key] = result.get(key, 0) + int(value)
    return result


def _severity(value: AnswerEvaluation) -> WeaknessSeverity:
    if value.grounding == ClaimGrounding.UNSUPPORTED_CLAIM or value.completeness == EvaluationLevel.WEAK:
        return WeaknessSeverity.HIGH
    return WeaknessSeverity.MEDIUM


def _severity_rank(value: WeaknessSeverity) -> int:
    return {WeaknessSeverity.LOW: 1, WeaknessSeverity.MEDIUM: 2, WeaknessSeverity.HIGH: 3}[value]


def _weakness_description(turn: InterviewTurnRecord) -> str:
    if turn.evaluation.grounding == ClaimGrounding.UNSUPPORTED_CLAIM:
        return f"{turn.question.category} 回答包含未验证个人 claim"
    return f"{turn.question.category} 回答缺少：{'、'.join(turn.evaluation.missing_points)}"
