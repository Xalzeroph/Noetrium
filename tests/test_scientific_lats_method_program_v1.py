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
from research.reproductions.lats_webshop import (
    LATS_WEBSHOP_METHOD_PROGRAM,
    lats_webshop_initial_state,
)


class _Models:
    def __init__(self) -> None:
        self.policy_calls = 0
        self.value_calls = 0
        self.reflection_calls = 0

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id == "lats.policy":
            self.policy_calls += 1
            count = request.view["sample_count"]
            prefix = "expand" if request.view["phase"] == "expansion" else "rollout"
            return MethodAgentResult(
                value={"actions": tuple(f"{prefix}-{i}" for i in range(count))}
            )

        if request.agent_id == "lats.value":
            self.value_calls += 1
            count = len(request.view["candidates"])
            if self.value_calls == 1:
                values = tuple(1.0 if i == 0 else 0.1 for i in range(count))
            else:
                values = tuple(0.1 for _ in range(count))
            return MethodAgentResult(value={"values": values})

        self.reflection_calls += 1
        return MethodAgentResult(value={"reflections": ("avoid partial path",)})


class _Environment:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.branch_calls = 0

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id not in {"environment.reset", "environment.branch-state"}:
            raise KeyError(capability_id)
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            EffectClass.IDEMPOTENT,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id == "environment.reset":
            self.reset_calls += 1
            return CapabilityResult(
                request.capability_id,
                {"observation": "Find the requested product."},
            )

        self.branch_calls += 1
        payload = request.payload
        assert payload["operation"] == "fork_action"
        action = payload["action"]["payload"]["text"]
        is_rollout = action.startswith("rollout")
        success = is_rollout and action == "rollout-0"
        return CapabilityResult(
            request.capability_id,
            {
                "operation": "fork_action",
                "action_payload": {"text": action},
                "observation": {
                    "payload": {
                        "text": "success" if success else f"obs:{action}",
                        "reward": 1.0 if success else 0.0,
                        "done": success,
                    }
                },
                "branch_id": payload["child_branch_id"],
                "source_cut_id": f"cut:{payload['child_branch_id']}",
                "proof": "portable_branch_state_digest_equality",
            },
        )


def test_lats_method_program_preserves_expand_value_rollout_search_semantics() -> None:
    models = _Models()
    environment = _Environment()
    result = UniversalMethodMachine(max_steps=512).run(
        LATS_WEBSHOP_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            ExecutionContext("lats-run", "trace", "span", task_id="webshop:1"),
            capabilities=environment,
            agent_loop=models,
        ),
        initial_state=lats_webshop_initial_state(
            task_id="webshop:1",
            source_cut_id="webshop:initial",
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["reward"] == 1.0
    assert result.value["task_success"] is True
    assert environment.reset_calls == 1
    # Root expansion is 5 * 2 and rollout expansion is 5.
    assert environment.branch_calls == 15
    assert models.policy_calls == 2
    assert models.value_calls == 2
    assert models.reflection_calls == 0


def test_lats_method_program_declares_branch_search_not_linear_act() -> None:
    program = LATS_WEBSHOP_METHOD_PROGRAM
    assert program.required_capabilities == (
        "environment.reset",
        "environment.branch-state",
    )
    assert "environment.act" not in program.required_capabilities
    assert program.configuration["max_iterations"] == 30
    assert program.configuration["max_tree_depth"] == 15
    assert program.configuration["root_expansion_multiplier"] == 2
    assert program.configuration["rollout_candidate_count"] == 5
    assert program.configuration["unique_failed_trajectory_limit"] == 3
