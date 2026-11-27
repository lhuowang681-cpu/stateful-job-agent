from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from job_agent.agent_runtime.contracts import AgentAction, ToolEffect
from job_agent.agent_runtime.policy import PolicyContext, PolicyEngine
from job_agent.interview.copilot_contracts import (
    ClaimGrounding,
    EvaluationLevel,
    InterviewMode,
    InterviewQuestion,
    InterviewRoundStatus,
    InterviewRoundType,
    QuestionDifficulty,
    QuestionSourceType,
    RealInterviewQuestion,
    SessionStatus,
    WeaknessStatus,
)
from job_agent.interview.copilot_repository import InterviewCopilotRepository
from job_agent.interview.copilot_service import ApplicationCopilotService, evaluate_answer
from job_agent.interview.copilot_tools import (
    APPLICATION_GET,
    APPLICATION_LIST,
    APPLICATION_SET_NEXT_ACTION,
    APPLICATION_UPDATE_STAGE,
    INTERVIEW_COMPLETE_SESSION,
    INTERVIEW_CREATE_PREP,
    INTERVIEW_GET_FEEDBACK,
    INTERVIEW_GET_HISTORY,
    INTERVIEW_GET_REVIEW_QUEUE,
    INTERVIEW_RECORD_REAL,
    INTERVIEW_START_MOCK,
    INTERVIEW_SUBMIT_ANSWER,
    build_interview_copilot_registry,
)
from job_agent.interview.evaluation import interview_eval_v1, run_deterministic_benchmark
from job_agent.resume.contracts import (
    ApplicationResumeLink,
    Resume,
    ResumeItem,
    ResumeSection,
    ResumeSourceType,
    ResumeVersion,
    ResumeVersionStatus,
    SectionKind,
    ClaimVerification,
)
from job_agent.resume.repository import ResumeRepository
from job_agent.schemas import ApplicationRecord, ApplicationStatus, TrackerEvent
from job_agent.tools.application_tracker import ApplicationTrackerStore


NOW = datetime(2026, 9, 21, 4, 0, tzinfo=UTC)


@pytest.fixture()
def copilot(tmp_path):
    tracker = ApplicationTrackerStore(tmp_path / "application-tracker.json", now=lambda: NOW)
    application = ApplicationRecord(
        id="app-001",
        job_id="job-agent-role",
        company="Example AI",
        title="Agent Engineer",
        city="杭州",
        source="referral",
        current_state=ApplicationStatus.FIRST_INTERVIEW,
        submitted_at=(NOW - timedelta(days=4)).isoformat(),
        state_history=[
            TrackerEvent(
                state=ApplicationStatus.FIRST_INTERVIEW,
                timestamp=(NOW - timedelta(days=2)).isoformat(),
                notes="First interview invitation",
            )
        ],
    )
    tracker.add_application(user_id="candidate", application=application, user_confirmed=True)

    resumes = ResumeRepository.open(tmp_path)
    resumes.save_resume(Resume(resume_id="resume-1", name="Candidate", created_at=NOW))
    version = ResumeVersion(
        resume_version_id="resume-version-1",
        resume_id="resume-1",
        version=1,
        target_job_id="job-agent-role",
        target_jd_snapshot_id="jd-1",
        target_jd_version=1,
        analysis_snapshot_id="analysis-1",
        created_at=NOW,
        source_type=ResumeSourceType.PLAIN_TEXT,
        status=ResumeVersionStatus.BASE,
        content_hash="a" * 64,
        raw_text="Built a governed Agent Runtime and evaluated dense retrieval.",
        sections=[
            ResumeSection(
                section_id="section-project",
                kind=SectionKind.PROJECT,
                title="Projects",
                order=0,
                items=[
                    ResumeItem(
                        item_id="item-job-agent",
                        section=SectionKind.PROJECT,
                        title="Job Agent",
                        original_text="Built a governed Agent Runtime.",
                        current_text="Built a governed Agent Runtime.",
                        order=0,
                    )
                ],
            )
        ],
    )
    resumes.save_version(version)
    resumes.link_application(
        ApplicationResumeLink(
            application_id="app-001",
            job_id="job-agent-role",
            resume_version_id=version.resume_version_id,
            linked_at=NOW,
        )
    )
    repository = InterviewCopilotRepository.open(tmp_path)
    service = ApplicationCopilotService(
        repository=repository,
        tracker_store=tracker,
        resume_repository=resumes,
        user_id="candidate",
        now=lambda: NOW,
    )
    service.bind_resume("app-001", resume_version_id=version.resume_version_id, action_id="bind-resume")
    yield service
    repository.close()
    resumes.close()


def _round_and_prep(service: ApplicationCopilotService):
    round_value = service.create_round(
        "app-001",
        action_id="round-1",
        round_type=InterviewRoundType.TECHNICAL,
        scheduled_at=NOW + timedelta(days=3),
        interviewer_role="Senior Agent Engineer",
    )
    prep = service.create_prep(
        application_id="app-001",
        round_id=round_value.round_id,
        action_id="prep-1",
        jd_snapshot_id="jd-1",
        jd_version=1,
        analysis_snapshot_id="analysis-1",
        requirements=[
            {
                "requirement_id": "req-runtime",
                "text": "Agent Runtime and tool governance",
                "category": "Tool governance",
                "strength": True,
                "evidence_refs": ["evidence:runtime"],
            },
            {
                "requirement_id": "req-k8s",
                "text": "Kubernetes production experience",
                "category": "Infrastructure",
                "gap": True,
            },
        ],
    )
    return round_value, prep


def test_application_lifecycle_round_and_exact_resume_binding_are_durable(copilot, tmp_path) -> None:
    round_value, prep = _round_and_prep(copilot)
    assert round_value.round_number == 1
    assert round_value.status == InterviewRoundStatus.PLANNED
    assert prep.application_id == "app-001"
    assert prep.interview_round_id == round_value.round_id
    assert prep.resume_version_id == "resume-version-1"
    assert prep.job_id == "job-agent-role"
    assert len(copilot.repository.list_questions(prep.prep_version_id)) >= 14
    assert all(question.why_asked for question in copilot.repository.list_questions(prep.prep_version_id))
    assert copilot.prep_is_stale(
        prep.prep_version_id,
        active_jd_snapshot_id="jd-2",
        active_analysis_snapshot_id="analysis-1",
        active_resume_version_id="resume-version-1",
    )

    restarted_repository = InterviewCopilotRepository.open(tmp_path)
    assert restarted_repository.get_round(round_value.round_id) == round_value
    assert restarted_repository.get_prep(prep.prep_version_id) == prep
    restarted_repository.close()


def test_round_and_session_mutations_are_idempotent(copilot) -> None:
    round_value, prep = _round_and_prep(copilot)
    duplicate_round = copilot.create_round(
        "app-001",
        action_id="round-1",
        round_type=InterviewRoundType.TECHNICAL,
        scheduled_at=NOW + timedelta(days=3),
    )
    assert duplicate_round.round_id == round_value.round_id
    session = copilot.start_mock(
        prep.prep_version_id,
        action_id="mock-1",
        mode=InterviewMode.PROJECT_DEEP_DIVE,
    )
    duplicate_session = copilot.start_mock(
        prep.prep_version_id,
        action_id="mock-1",
        mode=InterviewMode.PROJECT_DEEP_DIVE,
    )
    assert duplicate_session.session_id == session.session_id
    question_id = session.question_ids[0]
    answer = "我在生产环境部署了 Kubernetes，并把吞吐提升了 80%。"
    first = copilot.submit_answer(
        session.session_id,
        question_id=question_id,
        answer=answer,
        action_id="answer-1",
    )
    duplicate = copilot.submit_answer(
        session.session_id,
        question_id=question_id,
        answer=answer,
        action_id="answer-1",
    )
    assert duplicate == first
    assert len(copilot.repository.get_session(session.session_id).turns) == 1


def test_grounding_follow_up_completion_weakness_and_targeted_retry(copilot, tmp_path) -> None:
    _, prep = _round_and_prep(copilot)
    session = copilot.start_mock(
        prep.prep_version_id,
        action_id="mock-grounding",
        mode=InterviewMode.MOCK_INTERVIEW,
    )
    turn = copilot.submit_answer(
        session.session_id,
        question_id=session.question_ids[0],
        answer="我在生产环境部署了 Kubernetes，并把吞吐提升了 80%。",
        action_id="answer-grounding",
    )
    assert turn.evaluation.grounding == ClaimGrounding.UNSUPPORTED_CLAIM
    assert {value.kind for value in turn.evaluation.unsupported_claims} >= {"technology_experience", "scope", "numeric"}
    assert turn.follow_up is not None
    assert turn.follow_up.parent_question_id == turn.question.question_id
    assert turn.follow_up.missing_points

    completed = copilot.complete_session(session.session_id, action_id="complete-grounding")
    assert completed.status == SessionStatus.COMPLETED
    assert copilot.complete_session(session.session_id, action_id="complete-grounding") == completed
    weaknesses = copilot.repository.list_weaknesses("app-001")
    assert weaknesses and weaknesses[0].status == WeaknessStatus.OPEN
    assert len(weaknesses[0].history) == 1
    queue = copilot.review_queue("app-001")
    assert queue[0].source_sessions == [session.session_id]
    assert queue[0].targeted_question_id

    retry = copilot.start_mock(
        prep.prep_version_id,
        action_id="mock-targeted-retry",
        mode=InterviewMode.MOCK_INTERVIEW,
        targeted_retry=True,
    )
    assert retry.question_ids[0] == queue[0].targeted_question_id

    improving = copilot.update_weakness_status(
        weaknesses[0].weakness_id,
        status=WeaknessStatus.IMPROVING,
        session_id=session.session_id,
        note="Targeted retry started",
        action_id="weakness-improving",
    )
    assert improving.status == WeaknessStatus.IMPROVING
    assert copilot.update_weakness_status(
        weaknesses[0].weakness_id,
        status=WeaknessStatus.IMPROVING,
        session_id=session.session_id,
        note="Targeted retry started",
        action_id="weakness-improving",
    ) == improving
    resolved = copilot.update_weakness_status(
        weaknesses[0].weakness_id,
        status=WeaknessStatus.RESOLVED,
        session_id=retry.session_id,
        note="Covered all expected points",
        action_id="weakness-resolved",
    )
    assert resolved.status == WeaknessStatus.RESOLVED
    assert [event.status for event in resolved.history] == [
        WeaknessStatus.OPEN,
        WeaknessStatus.IMPROVING,
        WeaknessStatus.RESOLVED,
    ]

    restarted = InterviewCopilotRepository.open(tmp_path)
    assert restarted.get_session(session.session_id).summary
    assert restarted.list_weaknesses("app-001")[0].supporting_turns == [turn.turn_id]
    assert restarted.list_weaknesses("app-001")[0].status == WeaknessStatus.RESOLVED
    restarted.close()


def test_technical_knowledge_is_not_personal_experience() -> None:
    question = InterviewQuestion(
        question_id="q-rrf",
        source_type=QuestionSourceType.TECHNICAL,
        category="RAG",
        difficulty=QuestionDifficulty.BASIC,
        prompt="解释 RRF 是什么。",
        why_asked="检查技术基础",
        expected_points=["rank fusion", "reciprocal rank"],
        created_at=NOW,
    )
    evaluation = evaluate_answer(
        question,
        "RRF 是 reciprocal rank fusion，用不同检索器的 rank 做 rank fusion，不要求分数同尺度。",
        [],
    )
    assert evaluation.grounding == ClaimGrounding.TECHNICAL_KNOWLEDGE
    assert not evaluation.unsupported_claims

    ownership = evaluate_answer(
        question,
        "我主导了整个生产环境 RRF 系统。",
        [
            SimpleNamespace(
                canonical_claim="参与了本地 RAG 原型的实现。",
                technologies=["rag"],
                numeric_values=[],
                verification_state=ClaimVerification.SUPPORTED,
                evidence=[],
            )
        ],
    )
    assert {value.kind for value in ownership.unsupported_claims} >= {"ownership", "scope"}


def test_real_interview_debrief_history_dashboard_and_queries(copilot) -> None:
    round_value, _ = _round_and_prep(copilot)
    record = copilot.record_real_interview(
        application_id="app-001",
        round_id=round_value.round_id,
        action_id="real-1",
        occurred_at=NOW,
        questions=[
            RealInterviewQuestion(
                question="为什么不立即加 reranker？",
                self_assessment=EvaluationLevel.WEAK,
                requirement_refs=["req-runtime"],
                notes="没有解释错误分析。",
            )
        ],
        notes="User supplied debrief",
    )
    assert record.questions[0].question.startswith("为什么")
    assert copilot.repository.get_round(round_value.round_id).status == InterviewRoundStatus.COMPLETED
    history = copilot.history("app-001")
    assert history.real_interviews == [record]
    assert any(value.category == "Real interview debrief" for value in history.weaknesses)
    assert copilot.interviews_without_debrief() == []
    dashboard = copilot.dashboard(now=NOW)
    assert dashboard.total_applications == 1
    assert dashboard.by_stage[ApplicationStatus.FIRST_INTERVIEW.value] == 1
    assert copilot.analytics().real_interview_records == 1
    assert copilot.record_real_interview(
        application_id="app-001",
        round_id=round_value.round_id,
        action_id="real-1",
        occurred_at=NOW,
        questions=record.questions,
        notes="User supplied debrief",
    ) == record
    assert len(copilot.repository.list_real_interviews("app-001")) == 1


def test_application_transition_and_runtime_policy(copilot) -> None:
    tracker = copilot.tracker_store
    with pytest.raises(ValueError, match="invalid transition"):
        tracker.update_status(
            user_id="candidate",
            application_id="app-001",
            new_status=ApplicationStatus.OFFER,
            notes="invalid skip",
            user_confirmed=True,
        )
    registry = build_interview_copilot_registry(copilot)
    expected_names = {
        APPLICATION_LIST,
        APPLICATION_GET,
        APPLICATION_UPDATE_STAGE,
        APPLICATION_SET_NEXT_ACTION,
        INTERVIEW_CREATE_PREP,
        INTERVIEW_START_MOCK,
        INTERVIEW_SUBMIT_ANSWER,
        INTERVIEW_GET_FEEDBACK,
        INTERVIEW_COMPLETE_SESSION,
        INTERVIEW_RECORD_REAL,
        INTERVIEW_GET_REVIEW_QUEUE,
        INTERVIEW_GET_HISTORY,
    }
    assert set(registry.names()) == expected_names
    assert registry.get(APPLICATION_GET).spec.effect == ToolEffect.READ_ONLY
    assert registry.get(APPLICATION_UPDATE_STAGE).spec.effect == ToolEffect.LOCAL_STATE_MUTATION

    action = AgentAction(
        action_id="stage-action",
        tool_name=APPLICATION_UPDATE_STAGE,
        tool_arguments={"application_id": "app-001", "new_status": "second_interview"},
        expected_observation="updated application",
        progress_claim="update stage",
    )
    denied = PolicyEngine().authorize(
        action,
        registry.get(APPLICATION_UPDATE_STAGE).spec,
        PolicyContext(
            skill_allowed_tools=(APPLICATION_UPDATE_STAGE,),
            agent_allowed_tools=(APPLICATION_UPDATE_STAGE,),
            runtime_allowed_tools=(),
        ),
    )
    assert not denied.allowed and denied.reason_code == "runtime_tool_denied"
    waiting = PolicyEngine().authorize(
        action,
        registry.get(APPLICATION_UPDATE_STAGE).spec,
        PolicyContext(
            skill_allowed_tools=(APPLICATION_UPDATE_STAGE,),
            agent_allowed_tools=(APPLICATION_UPDATE_STAGE,),
            runtime_allowed_tools=(APPLICATION_UPDATE_STAGE,),
        ),
        session_id="session",
        run_id="run",
    )
    assert not waiting.allowed and waiting.reason_code == "approval_required"

    updated = copilot.set_next_action(
        "app-001",
        action_id="next-action",
        next_action="准备二面",
        due_at=(NOW + timedelta(days=2)).isoformat(),
    )
    assert updated.next_action == "准备二面"
    assert copilot.set_next_action(
        "app-001",
        action_id="next-action",
        next_action="准备二面",
        due_at=(NOW + timedelta(days=2)).isoformat(),
    ) == updated


def test_new_application_stages_remain_adjacent_and_queries_are_deterministic(tmp_path) -> None:
    tracker = ApplicationTrackerStore(tmp_path / "tracker.json", now=lambda: NOW)
    tracker.add_application(
        user_id="candidate",
        user_confirmed=True,
        application=ApplicationRecord(
            id="app-stage",
            job_id="job-stage",
            company="Example AI",
            title="Backend Engineer",
            current_state=ApplicationStatus.APPLIED,
            state_history=[TrackerEvent(state=ApplicationStatus.APPLIED, timestamp=(NOW - timedelta(days=8)).isoformat())],
        ),
    )
    for index, stage in enumerate(
        (
            ApplicationStatus.ONLINE_ASSESSMENT,
            ApplicationStatus.FIRST_INTERVIEW,
            ApplicationStatus.SECOND_INTERVIEW,
            ApplicationStatus.FINAL_INTERVIEW,
            ApplicationStatus.OFFER,
        )
    ):
        tracker.update_status(
            user_id="candidate",
            application_id="app-stage",
            new_status=stage,
            notes=stage.value,
            user_confirmed=True,
            action_id=f"stage-{index}",
        )
    application = tracker.load(user_id="candidate").applications[0]
    assert application.current_state == ApplicationStatus.OFFER
    assert [event.state for event in application.state_history] == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.ONLINE_ASSESSMENT,
        ApplicationStatus.FIRST_INTERVIEW,
        ApplicationStatus.SECOND_INTERVIEW,
        ApplicationStatus.FINAL_INTERVIEW,
        ApplicationStatus.OFFER,
    ]


def test_interview_eval_v1_has_36_cases_and_detects_hallucinated_experience() -> None:
    cases = interview_eval_v1()
    assert len(cases) == 36
    assert {value.case_id.rsplit("-", 1)[-1] for value in cases} == {"good", "partial", "unsupported"}
    metrics = run_deterministic_benchmark(cases)
    assert metrics.cases == 36
    assert metrics.unsupported_precision == 1.0
    assert metrics.unsupported_recall == 1.0
    assert metrics.missing_point_f1 >= 0.95
    assert metrics.follow_up_relevance >= 0.95
