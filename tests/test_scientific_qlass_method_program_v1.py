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
from research.reproductions.qlass_alfworld import (
    QLASS_ALFWORLD_METHOD_PROGRAM,
    qlass_alfworld_initial_state,
)


class _Models:
    def __init__(self) -> None:
        self.policy_calls = 0
        self.q_calls = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id == "qlass.sft-policy":
            self.policy_calls += 1
            candidate_index = request.view["candidate_index"]
            assert request.view["disable_perturbation"] is True
            return MethodAgentResult(
                value={"action": "open fridge" if candidate_index == 0 else "open cabinet"}
            )

        assert request.agent_id == "qlass.q-net"
        self.q_calls += 1
        assert len(request.view["candidates"]) == 2
        return MethodAgentResult(value={"scores": (0.2, 0.9)})


class _Environment:
    def __init__(self) -> None:
        self.resets = 0
        self.branch_requests = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id == "environment.reset":
            effect = EffectClass.IDEMPOTENT
        elif capability_id == "environment.branch-state":
            effect = EffectClass.IDEMPOTENT
        else:
            raise KeyError(capability_id)
        return CapabilityDescriptor(capability_id, "1", "json", "json", effect)

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id == "environment.reset":
            self.resets += 1
            return CapabilityResult(
                request.capability_id,
                {"history": ({"from": "human", "content": "initial observation"},)},
            )

        payload = request.payload
        self.branch_requests.append(payload)
        assert payload["operation"] == "replay_action"
        assert payload["committed_actions"] == ()
        action = payload["action"]["payload"]["text"]
        success = action == "open cabinet"
        return CapabilityResult(
            request.capability_id,
            {
                "operation": "replay_action",
                "action_payload": {"text": action},
                "observation": {
                    "payload": {
                        "history": (
                            {"from": "human", "content": "initial observation"},
                            {"from": "gpt", "content": action},
                            {
                                "from": "human",
                                "content": "success" if success else "not yet",
                            },
                        ),
                        "text": "success" if success else "not yet",
                        "reward": 1.0 if success else 0.0,
                        "finished": success,
                    }
                },
                "proof": "fresh_open_plus_ordered_prefix_replay",
            },
        )


def test_qlass_method_program_runs_three_reset_replay_best_of_n_trajectories() -> None:
    models = _Models()
    environment = _Environment()
    result = UniversalMethodMachine(max_steps=256).run(
        QLASS_ALFWORLD_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("qlass-run", "trace", "span", task_id="alfworld:dev:1"),
            capabilities=environment,
            agent_loop=models,
        ),
        initial_state=qlass_alfworld_initial_state(
            task_id="alfworld:dev:1",
            source_cut_id="alfworld:dev:initial",
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["trajectory_count"] == 3
    assert result.value["trajectory_rewards"] == (1.0, 1.0, 1.0)
    assert result.value["trajectory_successes"] == (True, True, True)
    assert result.value["first_trajectory_success"] is True
    assert result.value["committed_turns"] == 3
    assert environment.resets == 3
    assert len(environment.branch_requests) == 6
    assert models.policy_calls == 6
    assert models.q_calls == 3


def test_qlass_method_program_declares_reset_replay_not_linear_environment_act() -> None:
    program = QLASS_ALFWORLD_METHOD_PROGRAM
    assert program.required_capabilities == (
        "environment.reset",
        "environment.branch-state",
    )
    assert "environment.act" not in program.required_capabilities
    assert program.configuration["best_of_n"] == 2
    assert program.configuration["trajectories_per_task"] == 3
    assert program.configuration["max_turns_per_trajectory"] == 40
    assert (
        program.configuration["branch_strategy"]
        == "reset_and_replay_committed_action_history"
    )
