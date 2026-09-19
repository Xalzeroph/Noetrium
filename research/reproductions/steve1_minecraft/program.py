from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
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

from .fidelity import STEVE1_REFERENCE_FIDELITY
from .source import STEVE1_AUDITED_COMMIT


_GOAL_ENCODER_AGENT_ID = "steve1.goal-encoder"
_CONTROLLER_AGENT_ID = "steve1.controller"
_ENVIRONMENT_CAPABILITY_ID = "environment.act"
_RAW_CONTROL_ACTION_TYPE = "minecraft_raw_control"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _mapping(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to object")
    return decoded


class Steve1PromptModality(StrEnum):
    TEXT = "text"
    VISUAL = "visual"


@dataclass(frozen=True, slots=True)
class Steve1GoalEmbedding:
    modality: Steve1PromptModality
    artifact_ref: str
    receipt: JsonValue = None
    embedding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.modality, Steve1PromptModality):
            raise TypeError("STEVE-1 goal modality is invalid")
        object.__setattr__(
            self,
            "artifact_ref",
            _text(self.artifact_ref, "STEVE-1 goal embedding artifact_ref"),
        )
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "embedding_digest",
            canonical_digest({
                "modality": self.modality.value,
                "artifact_ref": self.artifact_ref,
                "receipt": thaw_json(self.receipt),
            }),
        )


@dataclass(frozen=True, slots=True)
class Steve1ControlRequest:
    observation: JsonObject
    goal_embedding_ref: str
    controller_state_ref: str | None
    step_index: int
    cond_scale: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation",
            freeze_json(_mapping(self.observation, "STEVE-1 observation")),
        )
        object.__setattr__(
            self,
            "goal_embedding_ref",
            _text(self.goal_embedding_ref, "STEVE-1 goal_embedding_ref"),
        )
        if self.controller_state_ref is not None:
            object.__setattr__(
                self,
                "controller_state_ref",
                _text(
                    self.controller_state_ref,
                    "STEVE-1 controller_state_ref",
                ),
            )
        if type(self.step_index) is not int or self.step_index < 0:
            raise ValueError("STEVE-1 step_index must be non-negative")
        if isinstance(self.cond_scale, bool) or not isinstance(
            self.cond_scale,
            (int, float),
        ):
            raise TypeError("STEVE-1 cond_scale must be numeric")
        object.__setattr__(self, "cond_scale", float(self.cond_scale))


@dataclass(frozen=True, slots=True)
class Steve1ControlPrediction:
    controls: JsonObject
    next_controller_state_ref: str
    model_receipt: JsonValue = None
    prediction_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "controls",
            freeze_json(_mapping(self.controls, "STEVE-1 controls")),
        )
        object.__setattr__(
            self,
            "next_controller_state_ref",
            _text(
                self.next_controller_state_ref,
                "STEVE-1 next_controller_state_ref",
            ),
        )
        object.__setattr__(
            self,
            "model_receipt",
            freeze_json(self.model_receipt),
        )
        object.__setattr__(
            self,
            "prediction_digest",
            canonical_digest({
                "controls": thaw_json(self.controls),
                "next_controller_state_ref": self.next_controller_state_ref,
                "model_receipt": thaw_json(self.model_receipt),
            }),
        )


@runtime_checkable
class Steve1ControllerPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def encode_text(
        self,
        prompt: str,
        context: ExecutionContext,
    ) -> Steve1GoalEmbedding: ...

    def encode_visual(
        self,
        artifact_ref: str,
        context: ExecutionContext,
    ) -> Steve1GoalEmbedding: ...

    def act(
        self,
        request: Steve1ControlRequest,
        context: ExecutionContext,
    ) -> Steve1ControlPrediction: ...


class Steve1AgentLoop:
    def __init__(self, controller: Steve1ControllerPort) -> None:
        if not isinstance(controller, Steve1ControllerPort):
            raise TypeError("STEVE-1 loop requires Steve1ControllerPort")
        require_sha256(
            controller.identity_digest,
            "STEVE-1 controller identity_digest",
        )
        self._controller = controller

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "source_commit": STEVE1_AUDITED_COMMIT,
            "controller_identity_digest": self._controller.identity_digest,
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id == _GOAL_ENCODER_AGENT_ID:
            modality = Steve1PromptModality(
                _text(
                    request.view.get("prompt_modality"),
                    "STEVE-1 prompt modality",
                )
            )
            if modality is Steve1PromptModality.TEXT:
                embedding = self._controller.encode_text(
                    _text(
                        request.view.get("text_prompt"),
                        "STEVE-1 text prompt",
                    ),
                    request.context,
                )
            else:
                embedding = self._controller.encode_visual(
                    _text(
                        request.view.get("visual_prompt_artifact_ref"),
                        "STEVE-1 visual prompt artifact ref",
                    ),
                    request.context,
                )
            if not isinstance(embedding, Steve1GoalEmbedding):
                raise TypeError(
                    "STEVE-1 controller must return Steve1GoalEmbedding"
                )
            if embedding.modality is not modality:
                raise ValueError("STEVE-1 goal embedding modality drifted")
            return MethodAgentResult(
                value={
                    "goal_embedding_ref": embedding.artifact_ref,
                    "embedding_digest": embedding.embedding_digest,
                    "receipt": thaw_json(embedding.receipt),
                },
                state_update={
                    "goal_embedding_ref": embedding.artifact_ref,
                    "goal_embedding_digest": embedding.embedding_digest,
                    "goal_embedding_receipt": thaw_json(embedding.receipt),
                },
            )

        if request.agent_id != _CONTROLLER_AGENT_ID:
            raise ValueError(
                f"unexpected STEVE-1 agent id: {request.agent_id}"
            )
        state_ref = request.view.get("controller_state_ref")
        if state_ref is not None and type(state_ref) is not str:
            raise TypeError(
                "STEVE-1 controller_state_ref must be text or None"
            )
        prediction = self._controller.act(
            Steve1ControlRequest(
                observation=_mapping(
                    request.view.get("observation"),
                    "STEVE-1 controller observation",
                ),
                goal_embedding_ref=_text(
                    request.view.get("goal_embedding_ref"),
                    "STEVE-1 goal embedding ref",
                ),
                controller_state_ref=state_ref,
                step_index=request.view.get("step_index"),
                cond_scale=request.view.get("cond_scale"),
            ),
            request.context,
        )
        if not isinstance(prediction, Steve1ControlPrediction):
            raise TypeError(
                "STEVE-1 controller must return Steve1ControlPrediction"
            )
        return MethodAgentResult(
            value={
                "controls": thaw_json(prediction.controls),
                "next_controller_state_ref": (
                    prediction.next_controller_state_ref
                ),
                "prediction_digest": prediction.prediction_digest,
                "model_receipt": thaw_json(prediction.model_receipt),
            },
            state_update={
                "pending_controls": thaw_json(prediction.controls),
                "controller_state_ref": (
                    prediction.next_controller_state_ref
                ),
                "last_prediction_digest": prediction.prediction_digest,
                "last_model_receipt": thaw_json(prediction.model_receipt),
            },
        )


def steve1_initial_state(
    *,
    task_id: str,
    initial_observation: JsonObject,
    prompt_modality: Steve1PromptModality,
    text_prompt: str | None = None,
    visual_prompt_artifact_ref: str | None = None,
    max_steps: int | None = None,
) -> JsonObject:
    if not isinstance(prompt_modality, Steve1PromptModality):
        raise TypeError("STEVE-1 prompt_modality is invalid")
    if prompt_modality is Steve1PromptModality.TEXT:
        text_prompt = _text(text_prompt, "STEVE-1 text prompt")
        if visual_prompt_artifact_ref is not None:
            raise ValueError(
                "STEVE-1 text condition cannot carry visual prompt"
            )
        cond_scale = STEVE1_REFERENCE_FIDELITY.text_cond_scale
    else:
        visual_prompt_artifact_ref = _text(
            visual_prompt_artifact_ref,
            "STEVE-1 visual prompt artifact ref",
        )
        if text_prompt is not None:
            raise ValueError(
                "STEVE-1 visual condition cannot carry text prompt"
            )
        cond_scale = STEVE1_REFERENCE_FIDELITY.visual_cond_scale
    if max_steps is None:
        max_steps = STEVE1_REFERENCE_FIDELITY.released_runner_gameplay_length
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("STEVE-1 max_steps must be positive")
    return {
        "source_commit": STEVE1_AUDITED_COMMIT,
        "task_id": _text(task_id, "STEVE-1 task_id"),
        "prompt_modality": prompt_modality.value,
        "text_prompt": text_prompt,
        "visual_prompt_artifact_ref": visual_prompt_artifact_ref,
        "cond_scale": cond_scale,
        "goal_embedding_ref": None,
        "goal_embedding_digest": None,
        "goal_embedding_receipt": None,
        "observation": _mapping(
            initial_observation,
            "STEVE-1 initial observation",
        ),
        "controller_state_ref": None,
        "pending_controls": None,
        "last_prediction_digest": None,
        "last_model_receipt": None,
        "step_index": 0,
        "max_steps": max_steps,
        "last_reward": 0.0,
        "cumulative_reward": 0.0,
        "done": False,
        "success": False,
        "trajectory": (),
    }


def _goal_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "prompt_modality": request.state.get("prompt_modality"),
        "text_prompt": request.state.get("text_prompt"),
        "visual_prompt_artifact_ref": request.state.get(
            "visual_prompt_artifact_ref"
        ),
    }


def _policy_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "observation": _mapping(
            request.state.get("observation"),
            "STEVE-1 observation",
        ),
        "goal_embedding_ref": request.state.get("goal_embedding_ref"),
        "controller_state_ref": request.state.get("controller_state_ref"),
        "step_index": request.state.get("step_index"),
        "cond_scale": request.state.get("cond_scale"),
    }


def _prepare_environment(request: MethodNodeRequest) -> MethodNodeResult:
    controls = _mapping(
        request.state.get("pending_controls"),
        "STEVE-1 pending controls",
    )
    step_index = request.state.get("step_index")
    if type(step_index) is not int or step_index < 0:
        raise ValueError("STEVE-1 step_index is invalid")
    envelope = environment_action_capability_payload(
        _RAW_CONTROL_ACTION_TYPE,
        {
            "controls": controls,
            "step_index": step_index,
        },
    )
    return MethodNodeResult(
        value=envelope,
        state_update=envelope,
    )


def _environment_result(
    value: JsonValue,
) -> tuple[JsonObject, float, bool, bool, JsonValue]:
    result = _mapping(value, "STEVE-1 environment result")
    observation = _mapping(
        result.get("observation"),
        "STEVE-1 environment observation",
    )
    payload = _mapping(
        observation.get("payload"),
        "STEVE-1 observation payload",
    )
    frame_ref = _text(
        payload.get("frame_artifact_ref"),
        "STEVE-1 frame artifact ref",
    )
    state = _mapping(
        payload.get("state", {}),
        "STEVE-1 raw environment state",
    )
    reward = payload.get("reward", 0.0)
    if isinstance(reward, bool) or not isinstance(reward, (int, float)):
        raise TypeError("STEVE-1 reward must be numeric")
    done = payload.get("done", False)
    success = payload.get("success", False)
    if type(done) is not bool or type(success) is not bool:
        raise TypeError("STEVE-1 done/success must be booleans")
    return (
        {
            "frame_artifact_ref": frame_ref,
            "state": state,
        },
        float(reward),
        done,
        success,
        observation.get("generation"),
    )


def _record_environment(request: MethodNodeRequest) -> MethodNodeResult:
    observation, reward, done, success, generation = _environment_result(
        request.previous_value
    )
    step_index = request.state.get("step_index")
    if type(step_index) is not int or step_index < 0:
        raise ValueError("STEVE-1 step_index state is invalid")
    cumulative = request.state.get("cumulative_reward", 0.0)
    if isinstance(cumulative, bool) or not isinstance(
        cumulative,
        (int, float),
    ):
        raise TypeError("STEVE-1 cumulative_reward must be numeric")
    trajectory_value = request.state.get("trajectory", ())
    if not isinstance(trajectory_value, (tuple, list)):
        raise TypeError("STEVE-1 trajectory must be a sequence")
    rows = list(trajectory_value)
    rows.append({
        "step_index": step_index,
        "controls": _mapping(
            request.state.get("pending_controls"),
            "STEVE-1 controls",
        ),
        "controller_state_ref": request.state.get(
            "controller_state_ref"
        ),
        "prediction_digest": request.state.get(
            "last_prediction_digest"
        ),
        "reward": reward,
        "done": done,
        "success": success,
        "environment_generation": generation,
    })
    return MethodNodeResult(
        value={
            "step_index": step_index + 1,
            "reward": reward,
            "done": done,
            "success": success,
        },
        state_update={
            "observation": observation,
            "step_index": step_index + 1,
            "last_reward": reward,
            "cumulative_reward": float(cumulative) + reward,
            "done": done,
            "success": success,
            "trajectory": tuple(rows),
            "pending_controls": None,
        },
    )


def _route_terminal(request: MethodNodeRequest) -> MethodNodeResult:
    step = request.state.get("step_index")
    max_steps = request.state.get("max_steps")
    if type(step) is not int or type(max_steps) is not int:
        raise TypeError("STEVE-1 step budget state is invalid")
    done = request.state.get("done") is True
    exhausted = step >= max_steps
    return MethodNodeResult(
        value={
            "done": done,
            "success": request.state.get("success") is True,
            "step_index": step,
            "budget_exhausted": exhausted and not done,
        },
        next_node="return" if done or exhausted else "policy",
        checkpoint=True,
        checkpoint_value={
            "step_index": step,
            "controller_state_ref": request.state.get(
                "controller_state_ref"
            ),
            "done": done,
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    trajectory = request.state.get("trajectory", ())
    if not isinstance(trajectory, (tuple, list)):
        raise TypeError("STEVE-1 trajectory must be sequence")
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "prompt_modality": request.state.get("prompt_modality"),
            "goal_embedding_ref": request.state.get(
                "goal_embedding_ref"
            ),
            "success": request.state.get("success") is True,
            "done": request.state.get("done") is True,
            "steps": request.state.get("step_index"),
            "max_steps": request.state.get("max_steps"),
            "cumulative_reward": request.state.get(
                "cumulative_reward"
            ),
            "final_controller_state_ref": request.state.get(
                "controller_state_ref"
            ),
            "trajectory": tuple(trajectory),
        }
    )


def build_steve1_method_program() -> MethodProgram:
    fidelity = STEVE1_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "source_commit": STEVE1_AUDITED_COMMIT,
        "observation_family": fidelity.observation_family,
        "action_family": fidelity.action_family,
        "prompt_modalities": fidelity.prompt_modalities,
        "text_cond_scale": fidelity.text_cond_scale,
        "visual_cond_scale": fidelity.visual_cond_scale,
        "stochastic_policy_sampling": fidelity.stochastic_policy_sampling,
        "classifier_free_guidance": fidelity.classifier_free_guidance,
        "guidance_rule": fidelity.guidance_rule,
        "recurrent_state": "content-addressed-explicit-ref",
        "environment_capability": _ENVIRONMENT_CAPABILITY_ID,
        "environment_action_type": _RAW_CONTROL_ACTION_TYPE,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="steve-1",
            implementation_version=STEVE1_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="steve1.minecraft-control.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="encode_goal")
    builder.agent(
        "encode_goal",
        "steve1.goal.encode",
        _GOAL_ENCODER_AGENT_ID,
        ("policy",),
        view_handler=_goal_view,
        max_visits=1,
    )
    builder.agent(
        "policy",
        "steve1.policy.act",
        _CONTROLLER_AGENT_ID,
        ("prepare_environment",),
        view_handler=_policy_view,
        max_visits=4096,
    )
    builder.compute(
        "prepare_environment",
        "steve1.environment.prepare",
        _prepare_environment,
        ("environment",),
        max_visits=4096,
    )
    builder.capability(
        "environment",
        "steve1.minecraft.raw-control",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_environment",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=4096,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_environment",
        "steve1.environment.record",
        _record_environment,
        ("terminal",),
        max_visits=4096,
    )
    builder.route(
        "terminal",
        "steve1.terminal",
        _route_terminal,
        ("policy", "return"),
        max_visits=4096,
    )
    builder.return_node(
        "return",
        "steve1.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "steve1.goal-embedding",
            "steve1.controller-state",
            "steve1.raw-control-trajectory",
            "environment.effect",
        ),
        metric_names=(
            "episode_success",
            "episode_steps",
            "cumulative_reward",
        ),
        artifact_kinds=(
            "steve1_goal_embedding",
            "steve1_controller_state",
            "steve1_trajectory",
        ),
    )


STEVE1_METHOD_PROGRAM = build_steve1_method_program()


__all__ = [
    "STEVE1_METHOD_PROGRAM",
    "Steve1AgentLoop",
    "Steve1ControlPrediction",
    "Steve1ControlRequest",
    "Steve1ControllerPort",
    "Steve1GoalEmbedding",
    "Steve1PromptModality",
    "build_steve1_method_program",
    "steve1_initial_state",
]
