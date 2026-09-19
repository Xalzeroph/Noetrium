from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.reproductions.reflexion_alfworld import (
    REFLEXION_ALFWORLD_METHOD_PROGRAM,
    reflexion_alfworld_initial_state,
)


class _Agents:
    def __init__(self) -> None:
        self.action_calls = 0
        self.reflection_calls = 0
        self.action_views = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id == "reflexion.reflection":
            self.reflection_calls += 1
            assert request.view["trial"] == 1
            assert "New plan:" in request.view["prompt"]
            return MethodAgentResult(
                value={"reflection": "Search the cabinet before retrying."}
            )

        assert request.agent_id == "reflexion.action"
        self.action_calls += 1
        self.action_views.append(request.view)
        if self.action_calls == 1:
            assert request.view["reflections"] == ()
            return MethodAgentResult(value={"action": "open fridge"})
        assert request.view["reflections"] == (
            "Search the cabinet before retrying.",
        )
        return MethodAgentResult(value={"action": "open cabinet"})


class _Environment:
    def __init__(self) -> None:
        self.actions = []
        self.resets = 0

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id == "environment.act":
            effect = EffectClass.RECONCILABLE
        elif capability_id == "environment.reset":
            effect = EffectClass.IDEMPOTENT
        else:
            raise KeyError(capability_id)
        return CapabilityDescriptor(capability_id, "1", "json", "json", effect)

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id == "environment.reset":
            self.resets += 1
            assert request.payload["next_trial"] == 2
            return CapabilityResult(request.capability_id, {"reset": True})

        command = request.payload["payload"]["text"]
        self.actions.append(command)
        if len(self.actions) == 1:
            payload = {
                "observation": {
                    "payload": {
                        "text": "Nothing useful here.",
                        "done": True,
                        "success": False,
                    }
                }
            }
        else:
            payload = {
                "observation": {
                    "payload": {
                        "text": "Task completed.",
                        "done": True,
                        "success": True,
                        "reward": 1.0,
                    }
                }
            }
        return CapabilityResult(request.capability_id, payload)


def test_reflexion_method_program_restarts_failed_trial_with_verbal_memory() -> None:
    agents = _Agents()
    environment = _Environment()
    result = UniversalMethodMachine(max_steps=256).run(
        REFLEXION_ALFWORLD_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("reflexion-run", "trace", "span", task_id="alfworld:1"),
            capabilities=environment,
            agent_loop=agents,
        ),
        initial_state=reflexion_alfworld_initial_state(
            task_id="alfworld:1",
            base_prompt="Solve the task.",
            initial_observation="You are in a room.",
            reflection_examples="Failure -> inspect before repeating.",
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["success"] is True
    assert result.value["completed_trials"] == 2
    assert result.value["first_success_trial"] == 2
    assert result.value["trials_used"] == 2
    assert result.value["visible_reflections"] == (
        "Search the cabinet before retrying.",
    )
    assert environment.actions == ["open fridge", "open cabinet"]
    assert environment.resets == 1
    assert agents.reflection_calls == 1


def test_reflexion_method_program_declares_exact_cross_trial_requirements() -> None:
    program = REFLEXION_ALFWORLD_METHOD_PROGRAM
    assert program.required_capabilities == (
        "environment.act",
        "environment.reset",
    )
    assert program.metric_names == (
        "task_success",
        "first_success_trial",
        "trials_used",
    )
    assert program.configuration["max_trials"] == 10
    assert program.configuration["max_turns_per_trial"] == 49
    assert program.configuration["reflection_memory_window"] == 3
