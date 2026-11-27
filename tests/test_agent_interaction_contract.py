from __future__ import annotations

from datetime import timezone

import pytest
from pydantic import Field, ValidationError

from job_agent.agent_runtime import (
    AgentAction,
    AgentFinish,
    AgentInputRequest,
    AgentLoop,
    AgentLoopConfig,
    AgentLoopTerminationReason,
    AgentObservation,
    AgentObservationOutcome,
    AgentRunStatus,
    AgentTurn,
    AgentBudget,
    BudgetManager,
    BudgetProfile,
    PolicyContext,
    PolicyEngine,
    ScriptedAgentModel,
    ToolContext,
    ToolEffect,
    ToolRegistry,
    UserInputRequest,
    VerificationResult,
    parse_agent_decision,
)
from job_agent.schemas import StrictModel


class EchoInput(StrictModel):
    value: str = Field(min_length=1)


class EchoOutput(StrictModel):
    value: str


class AcceptFinishVerifier:
    def verify(self, finish, *, goal, steps):
        return VerificationResult(
            passed=True,
            reason_code="complete",
            feedback="complete",
            evidence_refs=["contract:test"],
        )


def _action(action_id: str = "action-1", value: str = "job-1") -> AgentAction:
    return AgentAction(
        action_id=action_id,
        tool_name="career.echo",
        tool_arguments={"value": value},
        expected_observation="structured echo result",
        progress_claim="execute governed capability",
    )


def _finish() -> AgentFinish:
    return AgentFinish(
        result={"response": "Done."},
        completion_evidence=["contract:test"],
        confidence=1.0,
    )


def test_agent_turn_is_a_small_session_scoped_input_contract() -> None:
    turn = AgentTurn(
        turn_id="turn-1",
        session_id="session-1",
        user_input="这个岗位怎么样？",
    )

    assert turn.created_at.tzinfo == timezone.utc
    assert set(turn.model_dump()) == {
        "turn_id",
        "session_id",
        "user_input",
        "created_at",
    }


def test_finish_is_valid_and_rejects_an_empty_response_payload() -> None:
    assert parse_agent_decision(_finish().model_dump()).kind == "finish"

    with pytest.raises(ValidationError):
        AgentFinish(
            result={},
            completion_evidence=["contract:test"],
            confidence=1.0,
        )


def test_input_request_is_valid_and_rejects_an_empty_prompt() -> None:
    decision = AgentInputRequest(
        request=UserInputRequest(
            request_id="request-1",
            prompt="你指的是 Agent Intern 还是 AI Infra Intern？",
            reason="ambiguous_job_reference",
            choices=["Agent Intern", "AI Infra Intern"],
        ),
        progress_claim="clarify the job reference",
    )

    assert parse_agent_decision(decision.model_dump()).kind == "input_request"
    assert decision.request.reason == "ambiguous_job_reference"

    with pytest.raises(ValidationError):
        UserInputRequest(request_id="request-2", prompt="")


def test_action_union_uses_the_runtime_action_schema() -> None:
    decision = parse_agent_decision(_action().model_dump())

    assert isinstance(decision, AgentAction)
    assert decision.tool_name == "career.echo"

    with pytest.raises(ValidationError):
        parse_agent_decision(
            {
                "kind": "action",
                "action_id": "action-2",
                "tool_name": "career.echo",
                "tool_arguments": {},
            }
        )


def test_unknown_decision_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_agent_decision({"kind": "execute_python", "command": "do_work()"})


def test_loop_config_enforces_a_positive_step_budget() -> None:
    assert AgentLoopConfig().max_steps == 8
    assert AgentLoopConfig(max_steps=1).max_steps == 1

    with pytest.raises(ValidationError):
        AgentLoopConfig(max_steps=0)


def test_observation_expresses_success_and_failure_without_tracebacks() -> None:
    success = AgentObservation(
        action_id="action-1",
        tool_name="career.echo",
        outcome=AgentObservationOutcome.SUCCEEDED,
        result={"value": "job-1"},
    )
    failure = AgentObservation(
        action_id="action-2",
        tool_name="career.echo",
        outcome=AgentObservationOutcome.FAILED,
        error_summary="tool input was invalid",
    )

    assert success.result == {"value": "job-1"}
    assert failure.error_summary == "tool input was invalid"

    with pytest.raises(ValidationError):
        AgentObservation(
            action_id="action-3",
            tool_name="career.echo",
            outcome=AgentObservationOutcome.FAILED,
        )


def test_observation_represents_runtime_wait_states() -> None:
    approval = AgentObservation(
        action_id="action-1",
        tool_name="application.update_stage",
        outcome=AgentObservationOutcome.WAITING_FOR_APPROVAL,
        approval_required=True,
    )
    user_input = AgentObservation(
        action_id="action-2",
        tool_name="application.lookup",
        outcome=AgentObservationOutcome.WAITING_FOR_USER,
        user_input_required=True,
    )

    assert approval.approval_required is True
    assert user_input.user_input_required is True


def test_termination_reason_contract_is_small_and_explicit() -> None:
    assert {reason.value for reason in AgentLoopTerminationReason} == {
        "finished",
        "waiting_for_user",
        "waiting_for_approval",
        "step_budget_exhausted",
        "fatal_error",
    }


@pytest.mark.parametrize(
    ("user_input", "decision"),
    [
        ("这个岗位怎么样？", _action("analyze-1")),
        ("这个还行，记一下。", _action("track-1")),
        (
            "上次那个岗位。",
            AgentInputRequest(
                request=UserInputRequest(
                    request_id="clarify-1",
                    prompt="你指的是 Agent Intern 还是 AI Infra Intern？",
                    reason="ambiguous_job_reference",
                    choices=["Agent Intern", "AI Infra Intern"],
                ),
                progress_claim="clarify the job reference",
            ),
        ),
        ("谢谢，先这样。", _finish()),
    ],
)
def test_future_interaction_scenarios_are_contract_expressible(
    user_input: str,
    decision,
) -> None:
    turn = AgentTurn(
        turn_id=f"turn-{decision.kind}",
        session_id="session-1",
        user_input=user_input,
    )

    assert turn.user_input == user_input
    assert parse_agent_decision(decision.model_dump()).kind == decision.kind


def test_agent_action_executes_through_the_existing_governed_runtime() -> None:
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(
        name="career.echo",
        description="Echo deterministic contract data",
        input_model=EchoInput,
        output_model=EchoOutput,
        handler=lambda value, context: calls.append(value.value)
        or EchoOutput(value=value.value),
        effect=ToolEffect.READ_ONLY,
    )
    action = _action()
    loop = AgentLoop(
        agent_id="interaction-contract-agent",
        model=ScriptedAgentModel([action, _finish()]),
        registry=registry,
        policy=PolicyEngine(),
        policy_context=PolicyContext(
            skill_allowed_tools=("career.echo",),
            agent_allowed_tools=("career.echo",),
            runtime_allowed_tools=("career.echo",),
        ),
        budget=BudgetManager(AgentBudget.for_profile(BudgetProfile.QUICK)),
        verifier=AcceptFinishVerifier(),
    )

    result = loop.run(
        session_id="session-1",
        run_id="run-1",
        goal={"task": "contract compatibility"},
        tool_context=ToolContext(
            session_id="session-1",
            run_id="run-1",
            agent_id="interaction-contract-agent",
            workspace_root="fixtures/workspace",
        ),
    )

    assert result.state.status == AgentRunStatus.COMPLETED
    assert calls == ["job-1"]
