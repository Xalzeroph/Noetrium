from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import (
    UniversalMethodMachine,
)
from noetrium_platform.research.provenance import MethodSourceLaneKind
from noetrium_platform.research.reproduction import ReproductionAssetKind

from research.reproductions.optimus2_minecraft.definition import REPRODUCTION
from research.reproductions.optimus2_minecraft.fidelity import (
    OPTIMUS2_REFERENCE_FIDELITY,
)
from research.reproductions.optimus2_minecraft.program import (
    OPTIMUS2_METHOD_PROGRAM,
    optimus2_method_initial_state,
)
from research.reproductions.optimus2_minecraft.source import (
    OPTIMUS2_PAPER_REPOSITORY,
)


class _Agents:
    def __init__(self) -> None:
        self.planner_calls = 0
        self.policy_histories: list[tuple] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id == "optimus2.planner":
            self.planner_calls += 1
            return MethodAgentResult(
                value={"subgoals": ("chop a tree to get logs",)}
            )
        if request.agent_id == "optimus2.goap-policy":
            history = tuple(
                request.view["goal_observation_action_history"]
            )
            self.policy_histories.append(history)
            call = len(self.policy_histories)
            return MethodAgentResult(
                value={
                    "action": {
                        "keyboard": (
                            ("forward",) if call == 1 else ("attack",)
                        ),
                        "mouse": (1.0, 0.0),
                    }
                }
            )
        raise AssertionError(
            f"unexpected Optimus-2 agent: {request.agent_id}"
        )


class _Environment:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "environment.act"
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            effect_class=EffectClass.RECONCILABLE,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        assert isinstance(request.payload, Mapping)
        call = len(self.requests)
        payload = {
            "environment_steps": 1,
            "subgoal_success": call == 2,
            "task_success": False,
            "game_over": False,
            "observation": {"frame": call},
            "provider_receipt": {"call": call},
        }
        digest = capability_request_digest(request)
        return CapabilityResult(
            capability_id="environment.act",
            payload=payload,
            generation=f"optimus2-env-{call}",
            effect=EffectReceipt(
                effect_id=f"optimus2-effect-{call}",
                request_digest=digest,
                effect_class=EffectClass.RECONCILABLE,
                certainty=EffectCertainty.EFFECT_CONFIRMED,
            ),
            request_digest=digest,
        )


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="optimus2-method-run",
        trace_id="optimus2-trace",
        span_id="optimus2-span",
        task_id="chop-tree",
    )


def test_optimus2_cvpr2025_fidelity_freezes_goap_architecture() -> None:
    fidelity = OPTIMUS2_REFERENCE_FIDELITY

    assert fidelity.venue == "CVPR 2025"
    assert fidelity.official_repository_contains_executable_code is False
    assert fidelity.high_level_planner == "multimodal_large_language_model"
    assert fidelity.low_level_policy == (
        "goal_observation_action_conditioned_policy"
    )
    assert fidelity.goap_action_guided_behavior_encoder is True
    assert fidelity.goap_action_observation_causal_modeling is True
    assert fidelity.goap_historical_observation_action_interaction is True
    assert fidelity.goap_fixed_length_behavior_tokens is True
    assert fidelity.goap_language_behavior_alignment is True
    assert fidelity.goap_autoregressive_action_prediction is True
    assert fidelity.mgoa_video_count == 25_000
    assert fidelity.mgoa_atomic_task_count == 8
    assert fidelity.mgoa_goal_observation_action_pairs_approx == 30_000_000


def test_optimus2_reproduction_is_explicitly_independent_reconstruction() -> None:
    assert OPTIMUS2_PAPER_REPOSITORY.kind is MethodSourceLaneKind.PAPER_PROVENANCE
    assert OPTIMUS2_PAPER_REPOSITORY.executable is False
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    assert REPRODUCTION.primary_executable == (
        "research/reproductions/optimus2_minecraft/program.py"
    )
    kinds = tuple(row.kind for row in REPRODUCTION.assets)
    assert ReproductionAssetKind("method_program") in kinds
    assert any(
        "independent reconstruction" in row.description
        for row in REPRODUCTION.deltas
    )


def test_optimus2_method_program_preserves_planner_goap_split() -> None:
    program = OPTIMUS2_METHOD_PROGRAM
    assert program.required_capabilities == ("environment.act",)
    assert tuple(node.node_id for node in program.graph.nodes) == (
        "planner",
        "record_plan",
        "select_subgoal",
        "goap_policy",
        "record_policy_action",
        "prepare_environment",
        "execute_environment",
        "record_environment",
        "return",
    )


def test_optimus2_goap_receives_growing_goal_observation_action_history() -> None:
    agents = _Agents()
    environment = _Environment()

    result = UniversalMethodMachine(max_steps=100).run(
        OPTIMUS2_METHOD_PROGRAM,
        runtime=MethodRuntimeContext(
            _context(),
            capabilities=environment,
            agent_loop=agents,
        ),
        initial_state=optimus2_method_initial_state(
            task_id="chop-tree",
            instruction="chop a tree to get logs",
            initial_observation={"frame": 0},
            max_environment_steps=20,
            max_policy_steps_per_subgoal=10,
        ),
    )

    assert result.status is MethodRunStatus.SUCCEEDED, (
        result.failure_code,
        result.failure_phase,
        result.failure,
        result.diagnostics,
    )
    assert result.value["success"] is True
    assert result.value["completed_subgoals"] == 1
    assert result.value["environment_steps"] == 2
    assert len(result.value["goal_observation_action_history"]) == 2
    assert agents.planner_calls == 1
    assert len(agents.policy_histories) == 2
    assert agents.policy_histories[0] == ()
    assert len(agents.policy_histories[1]) == 1
    assert len(environment.requests) == 2
