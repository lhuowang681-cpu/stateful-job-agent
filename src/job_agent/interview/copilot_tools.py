from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from job_agent.agent_runtime.contracts import ToolContext, ToolEffect
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.schemas import ApplicationRecord, ApplicationStatus, StrictModel

from .copilot_contracts import (
    AnswerEvaluation,
    CopilotHistory,
    InterviewMode,
    InterviewPrepSnapshot,
    InterviewReviewItem,
    InterviewRound,
    InterviewRoundType,
    InterviewTurnRecord,
    MockInterviewSession,
    RealInterviewQuestion,
    RealInterviewRecord,
)
from .copilot_service import ApplicationCopilotService


APPLICATION_LIST = "application.list"
APPLICATION_GET = "application.get"
APPLICATION_UPDATE_STAGE = "application.update_stage"
APPLICATION_SET_NEXT_ACTION = "application.set_next_action"
INTERVIEW_CREATE_PREP = "interview.create_prep"
INTERVIEW_START_MOCK = "interview.start_mock"
INTERVIEW_SUBMIT_ANSWER = "interview.submit_answer"
INTERVIEW_GET_FEEDBACK = "interview.get_feedback"
INTERVIEW_COMPLETE_SESSION = "interview.complete_session"
INTERVIEW_RECORD_REAL = "interview.record_real"
INTERVIEW_GET_REVIEW_QUEUE = "interview.get_review_queue"
INTERVIEW_GET_HISTORY = "interview.get_history"


class EmptyInput(StrictModel):
    pass


class ApplicationListOutput(StrictModel):
    applications: list[ApplicationRecord]


class ApplicationGetInput(StrictModel):
    application_id: str = Field(min_length=1)


class ApplicationGetOutput(StrictModel):
    application: ApplicationRecord
    rounds: list[InterviewRound] = Field(default_factory=list)


class ApplicationStageInput(StrictModel):
    application_id: str
    new_status: ApplicationStatus
    expected_revision: int = Field(ge=0)
    action_id: str = Field(min_length=1)
    notes: str = ""
    create_round_type: InterviewRoundType | None = None
    scheduled_at: datetime | None = None


class ApplicationStageOutput(StrictModel):
    application: ApplicationRecord
    tracker_revision: int
    interview_round: InterviewRound | None = None


class NextActionInput(StrictModel):
    application_id: str
    action_id: str
    next_action: str = Field(min_length=1)
    due_at: str | None = None


class RequirementInput(StrictModel):
    requirement_id: str
    text: str
    category: str = "Job requirement"
    strength: bool = False
    gap: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class CreatePrepInput(StrictModel):
    application_id: str
    round_id: str
    action_id: str
    jd_snapshot_id: str
    jd_version: int = Field(ge=1)
    analysis_snapshot_id: str
    requirements: list[RequirementInput] = Field(min_length=1)
    mode: InterviewMode = InterviewMode.QUICK_PREP


class StartMockInput(StrictModel):
    prep_version_id: str
    action_id: str
    mode: InterviewMode = InterviewMode.MOCK_INTERVIEW
    targeted_retry: bool = False


class SubmitAnswerInput(StrictModel):
    session_id: str
    question_id: str
    answer: str = Field(min_length=1)
    action_id: str


class GetFeedbackInput(StrictModel):
    session_id: str
    turn_id: str | None = None


class FeedbackOutput(StrictModel):
    evaluations: list[AnswerEvaluation]
    turns: list[InterviewTurnRecord]


class CompleteSessionInput(StrictModel):
    session_id: str
    action_id: str


class RecordRealInput(StrictModel):
    application_id: str
    round_id: str
    action_id: str
    occurred_at: datetime
    questions: list[RealInterviewQuestion] = Field(min_length=1)
    outcome: str | None = None
    notes: str = ""


class ReviewQueueInput(StrictModel):
    application_id: str | None = None


class ReviewQueueOutput(StrictModel):
    items: list[InterviewReviewItem]


def build_interview_copilot_registry(service: ApplicationCopilotService) -> ToolRegistry:
    registry = ToolRegistry()

    def list_applications(_: EmptyInput, context: ToolContext) -> ApplicationListOutput:
        context.ensure_active()
        tracker = service.tracker_store.load(user_id=service.user_id)
        return ApplicationListOutput(applications=tracker.applications)

    def get_application(value: ApplicationGetInput, context: ToolContext) -> ApplicationGetOutput:
        context.ensure_active()
        return ApplicationGetOutput(
            application=service.application(value.application_id),
            rounds=service.repository.list_rounds(value.application_id),
        )

    def update_stage(value: ApplicationStageInput, context: ToolContext) -> ApplicationStageOutput:
        context.ensure_active()
        tracker = service.tracker_store.load(user_id=service.user_id)
        current = service.application(value.application_id)
        already_applied = f"copilot-action:{value.action_id}" in current.tags
        if tracker.revision != value.expected_revision and not already_applied:
            raise ValueError("stale tracker revision")
        updated = service.tracker_store.update_status(
            user_id=service.user_id,
            application_id=value.application_id,
            new_status=value.new_status,
            notes=value.notes,
            user_confirmed=True,
            timestamp=service.tracker_store.current_timestamp(),
            action_id=value.action_id,
        )
        round_value = None
        if value.create_round_type is not None:
            round_value = service.create_round(
                value.application_id,
                action_id=f"{value.action_id}-round",
                round_type=value.create_round_type,
                scheduled_at=value.scheduled_at,
                notes=value.notes,
            )
        revision = service.tracker_store.load(user_id=service.user_id).revision
        return ApplicationStageOutput(
            application=updated,
            tracker_revision=revision,
            interview_round=round_value,
        )

    def set_next_action(value: NextActionInput, context: ToolContext) -> ApplicationRecord:
        context.ensure_active()
        return service.set_next_action(
            value.application_id,
            action_id=value.action_id,
            next_action=value.next_action,
            due_at=value.due_at,
        )

    def create_prep(value: CreatePrepInput, context: ToolContext) -> InterviewPrepSnapshot:
        context.ensure_active()
        return service.create_prep(
            application_id=value.application_id,
            round_id=value.round_id,
            action_id=value.action_id,
            jd_snapshot_id=value.jd_snapshot_id,
            jd_version=value.jd_version,
            analysis_snapshot_id=value.analysis_snapshot_id,
            requirements=[item.model_dump(mode="json") for item in value.requirements],
            mode=value.mode,
        )

    def start_mock(value: StartMockInput, context: ToolContext) -> MockInterviewSession:
        context.ensure_active()
        return service.start_mock(
            value.prep_version_id,
            action_id=value.action_id,
            mode=value.mode,
            targeted_retry=value.targeted_retry,
        )

    def submit_answer(value: SubmitAnswerInput, context: ToolContext) -> InterviewTurnRecord:
        context.ensure_active()
        return service.submit_answer(
            value.session_id,
            question_id=value.question_id,
            answer=value.answer,
            action_id=value.action_id,
        )

    def get_feedback(value: GetFeedbackInput, context: ToolContext) -> FeedbackOutput:
        context.ensure_active()
        turns = service.repository.get_session(value.session_id).turns
        if value.turn_id:
            turns = [turn for turn in turns if turn.turn_id == value.turn_id]
        return FeedbackOutput(evaluations=[turn.evaluation for turn in turns], turns=turns)

    def complete_session(value: CompleteSessionInput, context: ToolContext) -> MockInterviewSession:
        context.ensure_active()
        return service.complete_session(value.session_id, action_id=value.action_id)

    def record_real(value: RecordRealInput, context: ToolContext) -> RealInterviewRecord:
        context.ensure_active()
        return service.record_real_interview(
            application_id=value.application_id,
            round_id=value.round_id,
            action_id=value.action_id,
            occurred_at=value.occurred_at,
            questions=value.questions,
            outcome=value.outcome,
            notes=value.notes,
        )

    def review_queue(value: ReviewQueueInput, context: ToolContext) -> ReviewQueueOutput:
        context.ensure_active()
        return ReviewQueueOutput(items=service.review_queue(value.application_id))

    def history(value: ApplicationGetInput, context: ToolContext) -> CopilotHistory:
        context.ensure_active()
        return service.history(value.application_id)

    specs: tuple[tuple[str, str, type[StrictModel], type[StrictModel], Any, ToolEffect], ...] = (
        (APPLICATION_LIST, "List canonical applications and current stages.", EmptyInput, ApplicationListOutput, list_applications, ToolEffect.READ_ONLY),
        (APPLICATION_GET, "Get one canonical application and its interview rounds.", ApplicationGetInput, ApplicationGetOutput, get_application, ToolEffect.READ_ONLY),
        (APPLICATION_UPDATE_STAGE, "Apply one legal application stage transition and optionally create its interview round.", ApplicationStageInput, ApplicationStageOutput, update_stage, ToolEffect.LOCAL_STATE_MUTATION),
        (APPLICATION_SET_NEXT_ACTION, "Set the deterministic next action for one application.", NextActionInput, ApplicationRecord, set_next_action, ToolEffect.LOCAL_STATE_MUTATION),
        (INTERVIEW_CREATE_PREP, "Create an immutable prep snapshot bound to exact job, JD, analysis, round, and resume versions.", CreatePrepInput, InterviewPrepSnapshot, create_prep, ToolEffect.LOCAL_STATE_MUTATION),
        (INTERVIEW_START_MOCK, "Start a durable job-specific mock interview session.", StartMockInput, MockInterviewSession, start_mock, ToolEffect.LOCAL_STATE_MUTATION),
        (INTERVIEW_SUBMIT_ANSWER, "Persist and evaluate one answer with grounding checks and a linked follow-up.", SubmitAnswerInput, InterviewTurnRecord, submit_answer, ToolEffect.LOCAL_STATE_MUTATION),
        (INTERVIEW_GET_FEEDBACK, "Read structured answer feedback from a durable mock session.", GetFeedbackInput, FeedbackOutput, get_feedback, ToolEffect.READ_ONLY),
        (INTERVIEW_COMPLETE_SESSION, "Complete a mock session and derive durable weakness state.", CompleteSessionInput, MockInterviewSession, complete_session, ToolEffect.LOCAL_STATE_MUTATION),
        (INTERVIEW_RECORD_REAL, "Record a user-supplied real interview debrief and its weak answers.", RecordRealInput, RealInterviewRecord, record_real, ToolEffect.LOCAL_STATE_MUTATION),
        (INTERVIEW_GET_REVIEW_QUEUE, "Get prioritized open interview weaknesses and targeted retry questions.", ReviewQueueInput, ReviewQueueOutput, review_queue, ToolEffect.READ_ONLY),
        (INTERVIEW_GET_HISTORY, "Get cross-session interview history for one application.", ApplicationGetInput, CopilotHistory, history, ToolEffect.READ_ONLY),
    )
    for name, description, input_model, output_model, handler, effect in specs:
        registry.register(
            name=name,
            description=description,
            input_model=input_model,
            output_model=output_model,
            handler=handler,
            effect=effect,
            idempotent=True,
        )
    return registry
