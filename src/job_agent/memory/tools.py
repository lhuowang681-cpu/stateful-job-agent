from __future__ import annotations

from pydantic import Field

from job_agent.agent_runtime.contracts import ToolContext, ToolEffect
from job_agent.agent_runtime.tool_registry import ToolRegistry
from job_agent.memory.user_state_store import UserStateStore
from job_agent.schemas import StrictModel


UPDATE_JOB_LOCATION_PREFERENCE_TOOL = "memory.update_job_location_preference"


class UpdateJobLocationPreferenceInput(StrictModel):
    add_acceptable_cities: list[str] = Field(default_factory=list)
    replace_preferred_city: str | None = None
    statement: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class UpdateJobLocationPreferenceOutput(StrictModel):
    user_state_version: int = Field(ge=1)
    preferred_city: str | None = None
    acceptable_cities: list[str] = Field(default_factory=list)
    memory_id: str = Field(min_length=1)
    superseded_memory_id: str | None = None
    changed: bool


def build_memory_tool_registry(
    store: UserStateStore,
    *,
    user_id: str,
) -> ToolRegistry:
    registry = ToolRegistry()

    def update_location(
        value: UpdateJobLocationPreferenceInput,
        context: ToolContext,
    ) -> UpdateJobLocationPreferenceOutput:
        result = store.update_job_location_preference(
            user_id=user_id,
            add_acceptable_cities=value.add_acceptable_cities,
            replace_preferred_city=value.replace_preferred_city,
            statement=value.statement,
            idempotency_key=value.idempotency_key,
        )
        return UpdateJobLocationPreferenceOutput(
            user_state_version=result.state.version,
            preferred_city=result.state.preferences.get("preferred_city"),
            acceptable_cities=list(
                result.state.preferences.get("acceptable_cities", [])
            ),
            memory_id=result.memory.memory_id,
            superseded_memory_id=result.superseded_memory_id,
            changed=result.changed,
        )

    registry.register(
        name=UPDATE_JOB_LOCATION_PREFERENCE_TOOL,
        description=(
            "Persist an explicit user-stated job-location preference update, "
            "preserving supersession history."
        ),
        input_model=UpdateJobLocationPreferenceInput,
        output_model=UpdateJobLocationPreferenceOutput,
        handler=update_location,
        effect=ToolEffect.LOCAL_STATE_MUTATION,
        idempotent=True,
    )
    return registry
