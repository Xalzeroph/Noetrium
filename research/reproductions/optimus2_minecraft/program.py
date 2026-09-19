from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import OPTIMUS2_REFERENCE_FIDELITY
from .source import OPTIMUS2_PAPER_REPOSITORY_COMMIT


_PLANNER_AGENT_ID = "optimus2.planner"
_GOAP_AGENT_ID = "optimus2.goap-policy"
_ENVIRONMENT_CAPABILITY = "environment.act"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field} must be text")
    result = value.strip()
    if not result and not allow_empty:
        raise ValueError(f"{field} must be non-empty")
    return result


def _object(value: object, field: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field} must decode to object")
    return decoded


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    decoded = thaw_json(value)
    if isinstance(decoded, (str, bytes, bytearray)) or not isinstance(
        decoded,
        Sequence,
    ):
        raise TypeError(f"{field} must be a sequence")
    return tuple(decoded)


def _subgoals(value: object) -> tuple[str, ...]:
    return tuple(
        _text(row, "Optimus-2 subgoal")
        for row in _sequence(value, "Optimus-2 subgoals")
    )


def optimus2_method_initial_state(
    *,
    task_id: str,
    instruction: str,
    initial_observation: JsonObject | None = None,
    max_environment_steps: int = 12000,
    max_policy_steps_per_subgoal: int = 3000,
) -> JsonObject:
    if type(max_environment_steps) is not int or max_environment_steps < 1:
        raise ValueError("Optimus-2 max_environment_steps must be positive")
    if (
        type(max_policy_steps_per_subgoal) is not int
        or max_policy_steps_per_subgoal < 1
    ):
        raise ValueError(
            "Optimus-2 max_policy_steps_per_subgoal must be positive"
        )
    return {
        "paper_repository_commit": OPTIMUS2_PAPER_REPOSITORY_COMMIT,
        "task_id": _text(task_id, "Optimus-2 task_id"),
        "instruction": _text(instruction, "Optimus-2 instruction"),
        "observation": (
            {}
            if initial_observation is None
            else dict(initial_observation)
        ),
        "subgoals": (),
        "subgoal_index": 0,
        "current_subgoal": "",
        "policy_step": 0,
        "environment_steps": 0,
        "max_environment_steps": max_environment_steps,
        "max_policy_steps_per_subgoal": max_policy_steps_per_subgoal,
        "history": (),
        "pending_action": None,
        "task_success": False,
        "game_over": False,
        "outcome": None,
    }


def _planner_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "high-level-multimodal-planning",
        "paper_repository_commit": OPTIMUS2_PAPER_REPOSITORY_COMMIT,
        "instruction": request.state.get("instruction"),
        "observation": request.state.get("observation", {}),
        "required_output": {
            "subgoals": "ordered sequence of natural-language subgoals"
        },
    }


def _record_plan(request: MethodNodeRequest) -> MethodNodeResult:
    value = _object(request.previous_value, "Optimus-2 planner result")
    subgoals = _subgoals(value.get("subgoals", ()))
    if not subgoals:
        raise ValueError("Optimus-2 planner returned no subgoals")
    return MethodNodeResult(
        value={"subgoal_count": len(subgoals)},
        state_update={
            "subgoals": subgoals,
            "subgoal_index": 0,
            "current_subgoal": "",
            "policy_step": 0,
        },
        next_node="select_subgoal",
        events=(
            MethodEvent(
                "optimus2.plan.generated",
                {
                    "subgoal_count": len(subgoals),
                    "plan_digest": canonical_digest(subgoals),
                },
            ),
        ),
    )


def _select_subgoal(request: MethodNodeRequest) -> MethodNodeResult:
    subgoals = _subgoals(request.state.get("subgoals", ()))
    index = request.state.get("subgoal_index", 0)
    if type(index) is not int or index < 0:
        raise ValueError("Optimus-2 subgoal_index is invalid")
    if request.state.get("game_over") is True:
        return MethodNodeResult(
            value={"outcome": "failed"},
            state_update={"outcome": "failed"},
            next_node="return",
        )
    if request.state.get("task_success") is True or index >= len(subgoals):
        return MethodNodeResult(
            value={"outcome": "success"},
            state_update={
                "outcome": "success",
                "task_success": True,
            },
            next_node="return",
        )
    current = subgoals[index]
    return MethodNodeResult(
        value={"subgoal_index": index, "subgoal": current},
        state_update={
            "current_subgoal": current,
            "policy_step": 0,
        },
        next_node="goap_policy",
    )


def _goap_view(request: MethodNodeRequest) -> JsonObject:
    history = _sequence(
        request.state.get("history", ()),
        "Optimus-2 GOA history",
    )
    return {
        "phase": "goal-observation-action-policy",
        "paper_repository_commit": OPTIMUS2_PAPER_REPOSITORY_COMMIT,
        "goal": request.state.get("current_subgoal"),
        "instruction": request.state.get("instruction"),
        "observation": request.state.get("observation", {}),
        "goal_observation_action_history": history,
        "policy_step": request.state.get("policy_step", 0),
        "architecture": {
            "action_guided_behavior_encoder": True,
            "fixed_length_behavior_tokens": True,
            "language_behavior_alignment": True,
            "autoregressive_action_prediction": True,
        },
        "required_output": {
            "action": "Minecraft action object",
        },
    }


def _record_policy_action(request: MethodNodeRequest) -> MethodNodeResult:
    value = _object(request.previous_value, "Optimus-2 GOAP result")
    action = value.get("action")
    if not isinstance(action, Mapping):
        raise TypeError("Optimus-2 GOAP action must be an object")
    step = request.state.get("policy_step", 0)
    if type(step) is not int or step < 0:
        raise ValueError("Optimus-2 policy_step is invalid")
    return MethodNodeResult(
        value={"action": dict(action), "policy_step": step},
        state_update={"pending_action": dict(action)},
        next_node="prepare_environment",
    )


def _prepare_environment(request: MethodNodeRequest) -> MethodNodeResult:
    action = request.state.get("pending_action")
    if not isinstance(action, Mapping):
        raise TypeError("Optimus-2 pending_action must be an object")
    envelope = environment_action_capability_payload(
        "optimus2.goap-action",
        {
            "task_id": request.state.get("task_id"),
            "instruction": request.state.get("instruction"),
            "subgoal": request.state.get("current_subgoal"),
            "policy_step": request.state.get("policy_step", 0),
            "action": dict(action),
        },
    )
    return MethodNodeResult(value=envelope, state_update=envelope)


def _execution(value: JsonValue) -> JsonObject:
    result = _object(value, "Optimus-2 environment result")
    observation = result.get("observation")
    if isinstance(observation, Mapping):
        payload = observation.get("payload")
        if isinstance(payload, Mapping):
            nested = payload.get("optimus2_goap")
            if isinstance(nested, Mapping):
                return _object(nested, "Optimus-2 GOAP execution")
    nested = result.get("optimus2_goap")
    if isinstance(nested, Mapping):
        return _object(nested, "Optimus-2 GOAP execution")
    return result


def _record_environment(request: MethodNodeRequest) -> MethodNodeResult:
    execution = _execution(request.previous_value)
    delta = execution.get("environment_steps", execution.get("steps", 1))
    if type(delta) is not int or delta < 1:
        raise ValueError("Optimus-2 environment_steps must be positive")
    consumed = request.state.get("environment_steps", 0)
    if type(consumed) is not int or consumed < 0:
        raise ValueError("Optimus-2 environment_steps state is invalid")
    total = consumed + delta
    limit = request.state.get("max_environment_steps")
    if type(limit) is not int or limit < 1:
        raise ValueError("Optimus-2 max_environment_steps state is invalid")
    policy_step = request.state.get("policy_step", 0)
    policy_limit = request.state.get("max_policy_steps_per_subgoal")
    if (
        type(policy_step) is not int
        or policy_step < 0
        or type(policy_limit) is not int
        or policy_limit < 1
    ):
        raise ValueError("Optimus-2 policy counters are invalid")
    policy_step += 1

    subgoal_success = execution.get("subgoal_success", False)
    task_success = execution.get("task_success", False)
    game_over = execution.get("game_over", False)
    if any(
        type(flag) is not bool
        for flag in (subgoal_success, task_success, game_over)
    ):
        raise TypeError("Optimus-2 execution flags must be booleans")
    if total >= limit:
        game_over = True
    if policy_step >= policy_limit and not subgoal_success:
        game_over = True

    observation = execution.get(
        "observation",
        request.state.get("observation", {}),
    )
    if not isinstance(observation, Mapping):
        raise TypeError("Optimus-2 observation must be an object")
    pending_action = _object(
        request.state.get("pending_action"),
        "Optimus-2 pending action",
    )
    history = [
        _object(row, "Optimus-2 GOA history")
        for row in _sequence(
            request.state.get("history", ()),
            "Optimus-2 GOA history",
        )
    ]
    history.append(
        {
            "goal": request.state.get("current_subgoal"),
            "observation_before": request.state.get("observation", {}),
            "action": pending_action,
            "observation_after": dict(observation),
            "provider_receipt": execution.get("provider_receipt"),
        }
    )

    index = request.state.get("subgoal_index", 0)
    if type(index) is not int or index < 0:
        raise ValueError("Optimus-2 subgoal_index state is invalid")
    next_index = index + 1 if subgoal_success else index
    update: JsonObject = {
        "observation": dict(observation),
        "history": tuple(history),
        "environment_steps": total,
        "policy_step": policy_step,
        "subgoal_index": next_index,
        "task_success": task_success,
        "game_over": game_over,
        "pending_action": None,
    }
    if task_success:
        update["outcome"] = "success"
        next_node = "return"
    elif game_over:
        update["outcome"] = "failed"
        next_node = "return"
    elif subgoal_success:
        next_node = "select_subgoal"
    else:
        next_node = "goap_policy"

    return MethodNodeResult(
        value={
            "subgoal_success": subgoal_success,
            "task_success": task_success,
            "game_over": game_over,
            "environment_steps": total,
            "policy_step": policy_step,
        },
        state_update=update,
        next_node=next_node,
        checkpoint=True,
        checkpoint_value={
            "subgoal_index": next_index,
            "policy_step": policy_step,
            "environment_steps": total,
        },
        events=(
            MethodEvent(
                "optimus2.goap.step-recorded",
                {
                    "subgoal_index": index,
                    "subgoal_success": subgoal_success,
                    "task_success": task_success,
                    "environment_steps": total,
                },
            ),
        ),
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    subgoals = _subgoals(request.state.get("subgoals", ()))
    history = _sequence(
        request.state.get("history", ()),
        "Optimus-2 GOA history",
    )
    outcome = request.state.get("outcome")
    if outcome not in {"success", "failed"}:
        outcome = (
            "success"
            if request.state.get("task_success") is True
            else "failed"
        )
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "success": outcome == "success",
            "outcome": outcome,
            "subgoal_count": len(subgoals),
            "completed_subgoals": request.state.get("subgoal_index", 0),
            "environment_steps": request.state.get("environment_steps", 0),
            "goal_observation_action_history": history,
        }
    )


def build_optimus2_method_program() -> MethodProgram:
    fidelity = OPTIMUS2_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "paper_repository_commit": OPTIMUS2_PAPER_REPOSITORY_COMMIT,
        "source_lane": "paper-authoritative-independent-reconstruction",
        "high_level_planner": fidelity.high_level_planner,
        "low_level_policy": fidelity.low_level_policy,
        "goap_action_guided_behavior_encoder": (
            fidelity.goap_action_guided_behavior_encoder
        ),
        "goap_fixed_length_behavior_tokens": (
            fidelity.goap_fixed_length_behavior_tokens
        ),
        "goap_language_behavior_alignment": (
            fidelity.goap_language_behavior_alignment
        ),
        "goap_autoregressive_action_prediction": (
            fidelity.goap_autoregressive_action_prediction
        ),
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="optimus2-minecraft-agent",
            implementation_version="independent-cvpr2025-v1",
            abi_version="noetrium.method-machine.v1",
            schema_version="optimus2.minecraft.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="planner")
    builder.agent(
        "planner",
        "optimus2.planner.multimodal",
        _PLANNER_AGENT_ID,
        ("record_plan",),
        view_handler=_planner_view,
    )
    builder.compute(
        "record_plan",
        "optimus2.plan.record",
        _record_plan,
        ("select_subgoal",),
    )
    builder.route(
        "select_subgoal",
        "optimus2.plan.select-subgoal",
        _select_subgoal,
        ("goap_policy", "return"),
        max_visits=4096,
    )
    builder.agent(
        "goap_policy",
        "optimus2.goap.predict-action",
        _GOAP_AGENT_ID,
        ("record_policy_action",),
        view_handler=_goap_view,
        max_visits=32768,
    )
    builder.compute(
        "record_policy_action",
        "optimus2.goap.record-action",
        _record_policy_action,
        ("prepare_environment",),
        max_visits=32768,
    )
    builder.compute(
        "prepare_environment",
        "optimus2.environment.prepare",
        _prepare_environment,
        ("execute_environment",),
        max_visits=32768,
    )
    builder.capability(
        "execute_environment",
        "optimus2.minecraft.execute",
        _ENVIRONMENT_CAPABILITY,
        ("record_environment",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=32768,
        evidence_obligations=("environment.effect",),
    )
    builder.route(
        "record_environment",
        "optimus2.environment.record",
        _record_environment,
        ("goap_policy", "select_subgoal", "return"),
        max_visits=32768,
    )
    builder.return_node("return", "optimus2.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "optimus2.planner.trajectory",
            "optimus2.goap.trajectory",
            "environment.effect",
        ),
        metric_names=(
            "task_success",
            "environment_steps",
            "completed_subgoals",
        ),
        artifact_kinds=(
            "optimus2_goal_observation_action_trajectory",
        ),
    )


OPTIMUS2_METHOD_PROGRAM = build_optimus2_method_program()


__all__ = [
    "OPTIMUS2_METHOD_PROGRAM",
    "build_optimus2_method_program",
    "optimus2_method_initial_state",
]
