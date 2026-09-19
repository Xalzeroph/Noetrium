from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    ExecutionContext,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import MINEDOJO_REFERENCE_FIDELITY
from .source import MINECLIP_AUDITED_COMMIT


_MINEAGENT_AGENT_ID = "minedojo.mineagent"
_ENVIRONMENT_CAPABILITY_ID = "environment.act"
_ENVIRONMENT_ACTION_TYPE = "minecraft_action"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _mapping(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _raw_action(value: object) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise TypeError("MineAgent raw action must be a sequence")
    action = tuple(value)
    dims = MINEDOJO_REFERENCE_FIDELITY.mineagent_actor_action_dims
    if len(action) != len(dims):
        raise ValueError("MineAgent raw action dimension drifted")
    for index, (item, dim) in enumerate(zip(action, dims)):
        if type(item) is not int or not 0 <= item < dim:
            raise ValueError(
                f"MineAgent action component {index} must be in [0, {dim})"
            )
    return action


def project_mineagent_demo_action(
    raw_action: Sequence[int],
) -> tuple[int, ...]:
    """Project the six actor dimensions to released demo env action.

    The source condition
        if action[-1] != 0 or action[-1] != 1 or action[-1] != 3:
    is always true.  Therefore the sixth actor dimension is always replaced by
    zero before two trailing zeros are appended.
    """

    action = list(_raw_action(raw_action))
    action[-1] = 0
    action.extend(
        MINEDOJO_REFERENCE_FIDELITY.mineagent_demo_appends_action_suffix
    )
    projected = tuple(action)
    if len(projected) != (
        MINEDOJO_REFERENCE_FIDELITY.mineagent_demo_environment_action_dims
    ):
        raise RuntimeError("MineAgent projected action dimension drifted")
    return projected


@dataclass(frozen=True, slots=True)
class MineAgentPolicyRequest:
    observation: JsonObject
    task_prompt: str
    step_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.observation, Mapping):
            raise TypeError("MineAgent observation must be an object")
        object.__setattr__(self, "observation", freeze_json(self.observation))
        object.__setattr__(
            self,
            "task_prompt",
            _text(self.task_prompt, "MineAgent task_prompt"),
        )
        if type(self.step_index) is not int or self.step_index < 0:
            raise ValueError("MineAgent step_index must be non-negative")


@dataclass(frozen=True, slots=True)
class MineAgentPolicyPrediction:
    raw_action: tuple[int, ...]
    model_receipt: JsonValue = None
    prediction_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_action", _raw_action(self.raw_action))
        object.__setattr__(self, "model_receipt", freeze_json(self.model_receipt))
        object.__setattr__(
            self,
            "prediction_digest",
            canonical_digest({
                "raw_action": self.raw_action,
                "model_receipt": self.model_receipt,
            }),
        )


@runtime_checkable
class MineAgentPolicyPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def predict(
        self,
        request: MineAgentPolicyRequest,
        context: ExecutionContext,
    ) -> MineAgentPolicyPrediction: ...


class MineAgentPolicyAgentLoop:
    def __init__(self, policy: MineAgentPolicyPort) -> None:
        if not isinstance(policy, MineAgentPolicyPort):
            raise TypeError("MineAgent loop requires MineAgentPolicyPort")
        require_sha256(
            policy.identity_digest,
            "MineAgent policy identity_digest",
        )
        self._policy = policy

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "agent": _MINEAGENT_AGENT_ID,
            "source_commit": MINECLIP_AUDITED_COMMIT,
            "policy_identity_digest": self._policy.identity_digest,
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id != _MINEAGENT_AGENT_ID:
            raise ValueError(
                f"unexpected MineAgent agent id: {request.agent_id}"
            )
        observation = _mapping(
            request.view.get("observation"),
            "MineAgent observation",
        )
        step_index = request.view.get("step_index")
        if type(step_index) is not int or step_index < 0:
            raise ValueError("MineAgent step_index view is invalid")
        prediction = self._policy.predict(
            MineAgentPolicyRequest(
                observation=observation,
                task_prompt=_text(
                    request.view.get("task_prompt"),
                    "MineAgent task_prompt",
                ),
                step_index=step_index,
            ),
            request.context,
        )
        if not isinstance(prediction, MineAgentPolicyPrediction):
            raise TypeError(
                "MineAgent policy must return MineAgentPolicyPrediction"
            )
        return MethodAgentResult(
            value={
                "raw_action": prediction.raw_action,
                "prediction_digest": prediction.prediction_digest,
                "model_receipt": thaw_json(prediction.model_receipt),
            },
            state_update={
                "pending_raw_action": prediction.raw_action,
                "last_prediction_digest": prediction.prediction_digest,
                "last_model_receipt": thaw_json(prediction.model_receipt),
            },
        )


def mineagent_initial_state(
    *,
    task_id: str,
    task_prompt: str,
    initial_observation: JsonObject,
    max_steps: int,
) -> JsonObject:
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("MineAgent max_steps must be positive")
    return {
        "source_commit": MINECLIP_AUDITED_COMMIT,
        "task_id": _text(task_id, "MineAgent task_id"),
        "task_prompt": _text(task_prompt, "MineAgent task_prompt"),
        "observation": _mapping(
            initial_observation,
            "MineAgent initial_observation",
        ),
        "step_index": 0,
        "max_steps": max_steps,
        "pending_raw_action": None,
        "pending_environment_action": None,
        "last_prediction_digest": None,
        "last_model_receipt": None,
        "last_reward": 0.0,
        "cumulative_reward": 0.0,
        "done": False,
        "success": False,
        "trajectory": (),
    }


def _agent_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task_id": _text(
            request.state.get("task_id"),
            "MineAgent task_id",
        ),
        "task_prompt": _text(
            request.state.get("task_prompt"),
            "MineAgent task_prompt",
        ),
        "observation": _mapping(
            request.state.get("observation", {}),
            "MineAgent observation",
        ),
        "step_index": request.state.get("step_index"),
    }


def _prepare_environment(request: MethodNodeRequest) -> MethodNodeResult:
    raw = _raw_action(request.state.get("pending_raw_action"))
    projected = project_mineagent_demo_action(raw)
    step_index = request.state.get("step_index")
    if type(step_index) is not int or step_index < 0:
        raise ValueError("MineAgent step_index state is invalid")
    envelope = environment_action_capability_payload(
        _ENVIRONMENT_ACTION_TYPE,
        {
            "task_id": _text(
                request.state.get("task_id"),
                "MineAgent task_id",
            ),
            "step_index": step_index,
            "raw_action": raw,
            "action": projected,
        },
    )
    return MethodNodeResult(
        value=envelope,
        state_update={
            **envelope,
            "pending_environment_action": projected,
        },
    )


def _environment_result(
    value: JsonValue,
) -> tuple[JsonObject, float, bool, bool, JsonValue]:
    result = _mapping(value, "MineAgent environment result")
    observation = result.get("observation")
    if not isinstance(observation, Mapping):
        raise TypeError(
            "MineAgent environment result requires observation"
        )
    payload = observation.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError(
            "MineAgent environment observation requires payload"
        )
    next_observation = payload.get("mineagent_observation")
    if not isinstance(next_observation, Mapping):
        raise TypeError(
            "MineAgent environment payload requires mineagent_observation"
        )
    reward = payload.get("reward", 0.0)
    if (
        isinstance(reward, bool)
        or not isinstance(reward, (int, float))
    ):
        raise TypeError("MineAgent environment reward must be numeric")
    done = payload.get("done", False)
    success = payload.get("success", False)
    if type(done) is not bool or type(success) is not bool:
        raise TypeError("MineAgent done/success must be booleans")
    return (
        _mapping(next_observation, "MineAgent next observation"),
        float(reward),
        done,
        success,
        observation.get("generation"),
    )


def _record_environment(request: MethodNodeRequest) -> MethodNodeResult:
    observation, reward, done, success, generation = _environment_result(
        request.previous_value
    )
    raw = _raw_action(request.state.get("pending_raw_action"))
    projected = tuple(
        int(value)
        for value in _raw_projected_action(
            request.state.get("pending_environment_action")
        )
    )
    step_index = request.state.get("step_index")
    if type(step_index) is not int or step_index < 0:
        raise ValueError("MineAgent step_index state is invalid")
    cumulative = request.state.get("cumulative_reward", 0.0)
    if isinstance(cumulative, bool) or not isinstance(
        cumulative, (int, float)
    ):
        raise TypeError("MineAgent cumulative_reward must be numeric")

    rows_raw = request.state.get("trajectory", ())
    if not isinstance(rows_raw, (tuple, list)):
        raise TypeError("MineAgent trajectory must be a sequence")
    rows = list(rows_raw)
    rows.append({
        "step_index": step_index,
        "raw_action": raw,
        "environment_action": projected,
        "reward": reward,
        "done": done,
        "success": success,
        "environment_generation": generation,
        "prediction_digest": request.state.get(
            "last_prediction_digest"
        ),
    })

    return MethodNodeResult(
        value={
            "step_index": step_index + 1,
            "reward": reward,
            "done": done,
            "success": success,
            "environment_generation": generation,
        },
        state_update={
            "observation": observation,
            "step_index": step_index + 1,
            "last_reward": reward,
            "cumulative_reward": float(cumulative) + reward,
            "done": done,
            "success": success,
            "trajectory": tuple(rows),
            "pending_raw_action": None,
            "pending_environment_action": None,
        },
    )


def _raw_projected_action(value: object) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise TypeError(
            "MineAgent projected environment action must be a sequence"
        )
    rows = tuple(value)
    if len(rows) != (
        MINEDOJO_REFERENCE_FIDELITY.mineagent_demo_environment_action_dims
    ):
        raise ValueError(
            "MineAgent projected environment action dimension drifted"
        )
    if any(type(item) is not int for item in rows):
        raise TypeError(
            "MineAgent projected environment action must be integer-valued"
        )
    return rows


def _route_terminal(request: MethodNodeRequest) -> MethodNodeResult:
    step = request.state.get("step_index")
    max_steps = request.state.get("max_steps")
    if type(step) is not int or step < 0:
        raise ValueError("MineAgent step_index state is invalid")
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("MineAgent max_steps state is invalid")
    done = request.state.get("done") is True
    exhausted = step >= max_steps
    return MethodNodeResult(
        value={
            "done": done,
            "success": request.state.get("success") is True,
            "step_index": step,
            "max_steps": max_steps,
            "budget_exhausted": exhausted and not done,
        },
        next_node="return" if done or exhausted else "policy",
        checkpoint=True,
        checkpoint_value={
            "step_index": step,
            "done": done,
            "success": request.state.get("success") is True,
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    trajectory = request.state.get("trajectory", ())
    if not isinstance(trajectory, (tuple, list)):
        raise TypeError("MineAgent trajectory must be a sequence")
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "success": request.state.get("success") is True,
            "done": request.state.get("done") is True,
            "steps": request.state.get("step_index"),
            "max_steps": request.state.get("max_steps"),
            "cumulative_reward": request.state.get(
                "cumulative_reward"
            ),
            "trajectory": tuple(trajectory),
        }
    )


def build_mineagent_method_program() -> MethodProgram:
    fidelity = MINEDOJO_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "source_commit": MINECLIP_AUDITED_COMMIT,
        "policy": "mineagent",
        "deterministic_eval": fidelity.mineagent_deterministic_eval_uses_mode,
        "actor_action_dims": fidelity.mineagent_actor_action_dims,
        "demo_environment_action_dims": (
            fidelity.mineagent_demo_environment_action_dims
        ),
        "demo_forces_sixth_action_zero": (
            fidelity.mineagent_demo_forces_sixth_action_zero
        ),
        "demo_action_suffix": fidelity.mineagent_demo_appends_action_suffix,
        "environment_capability": _ENVIRONMENT_CAPABILITY_ID,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="minedojo-mineagent",
            implementation_version=MINECLIP_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="minedojo.mineagent.control.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="policy")
    builder.agent(
        "policy",
        "minedojo.mineagent.predict",
        _MINEAGENT_AGENT_ID,
        ("prepare_environment",),
        view_handler=_agent_view,
        max_visits=4096,
    )
    builder.compute(
        "prepare_environment",
        "minedojo.mineagent.prepare-action",
        _prepare_environment,
        ("environment",),
        max_visits=4096,
    )
    builder.capability(
        "environment",
        "minedojo.minecraft.act",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_environment",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=4096,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_environment",
        "minedojo.mineagent.record-environment",
        _record_environment,
        ("terminal",),
        max_visits=4096,
    )
    builder.route(
        "terminal",
        "minedojo.mineagent.terminal",
        _route_terminal,
        ("policy", "return"),
        max_visits=4096,
    )
    builder.return_node(
        "return",
        "minedojo.mineagent.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "minedojo.mineagent.policy",
            "minedojo.minecraft.trajectory",
            "environment.effect",
        ),
        metric_names=(
            "episode_success",
            "episode_steps",
            "cumulative_reward",
        ),
        artifact_kinds=("minedojo_mineagent_trajectory",),
    )


MINEAGENT_METHOD_PROGRAM = build_mineagent_method_program()


__all__ = [
    "MINEAGENT_METHOD_PROGRAM",
    "MineAgentPolicyAgentLoop",
    "MineAgentPolicyPort",
    "MineAgentPolicyPrediction",
    "MineAgentPolicyRequest",
    "build_mineagent_method_program",
    "mineagent_initial_state",
    "project_mineagent_demo_action",
]
