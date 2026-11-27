from __future__ import annotations

from typing import Any

from pydantic import Field

from job_agent.agent_runtime.contracts import ToolContext, ToolEffect
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.career.durable import DurableCareerRepository
from job_agent.memory.contracts import ApplicationTrackerStore
from job_agent.schemas import StrictModel


READ_CAREER_STATE_TOOL = "career.read_durable_state"


class ReadCareerStateInput(StrictModel):
    job_id: str = Field(min_length=1)


class CurrentApplicationState(StrictModel):
    application_id: str = Field(min_length=1)
    current_stage: str = Field(min_length=1)
    state_history: list[dict[str, Any]] = Field(default_factory=list)
    tracker_revision: int = Field(ge=0)
    source: str = Field(min_length=1)


class ReadCareerStateOutput(StrictModel):
    job: dict[str, Any]
    latest_jd: dict[str, Any] | None = None
    latest_analysis: dict[str, Any] | None = None
    application: CurrentApplicationState | None = None
    latest_interview_prep: dict[str, Any] | None = None


def build_durable_career_registry(
    repository: DurableCareerRepository,
    tracker_store: ApplicationTrackerStore,
    *,
    user_id: str,
) -> ToolRegistry:
    registry = ToolRegistry()

    def read_state(
        value: ReadCareerStateInput,
        context: ToolContext,
    ) -> ReadCareerStateOutput:
        state = repository.get_state(value.job_id)
        application = None
        if state.application_link is not None:
            tracker = tracker_store.load(user_id=user_id)
            record = next(
                (
                    item
                    for item in tracker.applications
                    if item.id == state.application_link.application_id
                ),
                None,
            )
            if record is None:
                raise ValueError("linked application is missing from canonical tracker")
            application = CurrentApplicationState(
                application_id=record.id,
                current_stage=record.current_state.value,
                state_history=[
                    event.model_dump(mode="json") for event in record.state_history
                ],
                tracker_revision=tracker.revision,
                source=record.source or "application_tracker",
            )
        return ReadCareerStateOutput(
            job=state.job.model_dump(mode="json"),
            latest_jd=(
                state.latest_jd.model_dump(mode="json")
                if state.latest_jd is not None
                else None
            ),
            latest_analysis=(
                state.latest_analysis.model_dump(mode="json")
                if state.latest_analysis is not None
                else None
            ),
            application=application,
            latest_interview_prep=(
                state.latest_interview_prep.model_dump(mode="json")
                if state.latest_interview_prep is not None
                else None
            ),
        )

    registry.register(
        name=READ_CAREER_STATE_TOOL,
        description=(
            "Read a durable job, its latest JD and analysis, the live canonical "
            "application stage, and latest interview preparation metadata."
        ),
        input_model=ReadCareerStateInput,
        output_model=ReadCareerStateOutput,
        handler=read_state,
        effect=ToolEffect.READ_ONLY,
        idempotent=True,
        requires_approval=False,
    )
    return registry
