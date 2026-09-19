from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.evidence.artifact.content.api import TensorContentRef
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import (
    VIMA_EVAL_PARTITIONS,
    VIMA_REFERENCE_FIDELITY,
    VIMA_TASKS,
)
from .policy import (
    VIMA_POLICY_AGENT_ID,
    VimaActionBounds,
)
from .source import (
    VIMA_BENCH_AUDITED_COMMIT,
    VIMA_POLICY_AUDITED_COMMIT,
)


_ENVIRONMENT_CAPABILITY_ID = "environment.act"
_ENVIRONMENT_ACTION_TYPE = "embodied_action"

_PROMPT_TOKEN_SCHEMA = "vima.prompt-token.tensor.v1"
_PROMPT_MASK_SCHEMA = "vima.prompt-mask.tensor.v1"
_OBSERVATION_TOKEN_SCHEMA = "vima.observation-token.tensor.v1"
_OBSERVATION_MASK_SCHEMA = "vima.observation-mask.tensor.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _tensor_ref(
    value: object,
    *,
    schema_id: str,
    field_name: str,
) -> TensorContentRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a tensor reference")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    ref = TensorContentRef.from_payload(decoded)
    if ref.schema_id != schema_id:
        raise ValueError(f"{field_name} tensor schema drifted")
    return ref


def _ref_tuple(
    value: object,
    *,
    schema_id: str,
    field_name: str,
) -> tuple[JsonObject, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(
        _tensor_ref(
            item,
            schema_id=schema_id,
            field_name=field_name,
        ).payload()
        for item in value
    )


def vima_initial_state(
    *,
    task_id: str,
    evaluation_partition: str,
    seed: int,
    oracle_max_steps: int,
    prompt_token_ref: TensorContentRef,
    prompt_mask_ref: TensorContentRef,
    initial_observation_token_ref: TensorContentRef,
    initial_observation_mask_ref: TensorContentRef,
    action_bounds: VimaActionBounds,
) -> JsonObject:
    task_id = _text(task_id, "VIMA task_id")
    if task_id not in VIMA_TASKS:
        raise ValueError(f"unknown VIMA-Bench task: {task_id}")
    partition = _text(
        evaluation_partition,
        "VIMA evaluation_partition",
    )
    if partition not in VIMA_EVAL_PARTITIONS:
        raise ValueError(
            f"unknown VIMA-Bench partition: {partition}"
        )
    if type(seed) is not int:
        raise TypeError("VIMA benchmark seed must be an integer")
    max_steps = (
        _positive_int(
            oracle_max_steps,
            "VIMA oracle_max_steps",
        )
        + VIMA_REFERENCE_FIDELITY.episode_bonus_steps
    )

    refs = (
        (
            prompt_token_ref,
            _PROMPT_TOKEN_SCHEMA,
            "VIMA prompt_token_ref",
        ),
        (
            prompt_mask_ref,
            _PROMPT_MASK_SCHEMA,
            "VIMA prompt_mask_ref",
        ),
        (
            initial_observation_token_ref,
            _OBSERVATION_TOKEN_SCHEMA,
            "VIMA initial observation token ref",
        ),
        (
            initial_observation_mask_ref,
            _OBSERVATION_MASK_SCHEMA,
            "VIMA initial observation mask ref",
        ),
    )
    for ref, schema_id, field_name in refs:
        if not isinstance(ref, TensorContentRef):
            raise TypeError(f"{field_name} must be TensorContentRef")
        if ref.schema_id != schema_id:
            raise ValueError(f"{field_name} schema drifted")
    if not isinstance(action_bounds, VimaActionBounds):
        raise TypeError(
            "VIMA initial state requires VimaActionBounds"
        )

    return {
        "policy_source_commit": VIMA_POLICY_AUDITED_COMMIT,
        "benchmark_source_commit": VIMA_BENCH_AUDITED_COMMIT,
        "task_id": task_id,
        "evaluation_partition": partition,
        "seed": seed,
        "max_steps": max_steps,
        "prompt_token_ref": prompt_token_ref.payload(),
        "prompt_mask_ref": prompt_mask_ref.payload(),
        "observation_token_refs": (
            initial_observation_token_ref.payload(),
        ),
        "observation_mask_refs": (
            initial_observation_mask_ref.payload(),
        ),
        "action_token_refs": (),
        "action_bounds": action_bounds.payload(),
        "step_index": 0,
        "pending_action": None,
        "pending_discrete_action": None,
        "last_policy_request_digest": None,
        "last_model_receipt": None,
        "done": False,
        "success": False,
        "last_reward": None,
        "last_environment_generation": None,
    }


def _agent_view(request: MethodNodeRequest) -> JsonObject:
    state = request.state
    prompt_token = _tensor_ref(
        state.get("prompt_token_ref"),
        schema_id=_PROMPT_TOKEN_SCHEMA,
        field_name="VIMA prompt_token_ref",
    )
    prompt_mask = _tensor_ref(
        state.get("prompt_mask_ref"),
        schema_id=_PROMPT_MASK_SCHEMA,
        field_name="VIMA prompt_mask_ref",
    )
    observation_tokens = _ref_tuple(
        state.get("observation_token_refs", ()),
        schema_id=_OBSERVATION_TOKEN_SCHEMA,
        field_name="VIMA observation_token_refs",
    )
    observation_masks = _ref_tuple(
        state.get("observation_mask_refs", ()),
        schema_id=_OBSERVATION_MASK_SCHEMA,
        field_name="VIMA observation_mask_refs",
    )
    action_tokens = _ref_tuple(
        state.get("action_token_refs", ()),
        schema_id="vima.action-token.tensor.v1",
        field_name="VIMA action_token_refs",
    )
    step_index = state.get("step_index")
    if type(step_index) is not int or step_index < 0:
        raise ValueError("VIMA step_index state is invalid")
    bounds = VimaActionBounds.from_payload(
        state.get("action_bounds")
    )
    return {
        "prompt_token_ref": prompt_token.payload(),
        "prompt_mask_ref": prompt_mask.payload(),
        "observation_token_refs": observation_tokens,
        "observation_mask_refs": observation_masks,
        "action_token_refs": action_tokens,
        "action_bounds": bounds.payload(),
        "step_index": step_index,
    }


def _prepare_environment(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    action = request.state.get("pending_action")
    if not isinstance(action, Mapping):
        raise TypeError(
            "VIMA policy must produce pending_action before environment step"
        )
    envelope = environment_action_capability_payload(
        _ENVIRONMENT_ACTION_TYPE,
        {
            "action": thaw_json(action),
            "task_id": _text(
                request.state.get("task_id"),
                "VIMA task_id",
            ),
            "step_index": request.state.get("step_index"),
        },
    )
    return MethodNodeResult(
        value={
            "action": thaw_json(action),
            "step_index": request.state.get("step_index"),
        },
        state_update=envelope,
    )


def _environment_observation(
    value: JsonValue,
) -> tuple[
    TensorContentRef,
    TensorContentRef,
    bool,
    bool,
    JsonValue,
    str | None,
]:
    if not isinstance(value, Mapping):
        raise TypeError(
            "VIMA environment capability result must be an object"
        )
    observation = value.get("observation")
    if not isinstance(observation, Mapping):
        raise TypeError(
            "VIMA environment result requires observation"
        )
    payload = observation.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError(
            "VIMA environment observation payload must be an object"
        )
    token_ref = _tensor_ref(
        payload.get("vima_observation_token_ref"),
        schema_id=_OBSERVATION_TOKEN_SCHEMA,
        field_name="VIMA environment observation token ref",
    )
    mask_ref = _tensor_ref(
        payload.get("vima_observation_mask_ref"),
        schema_id=_OBSERVATION_MASK_SCHEMA,
        field_name="VIMA environment observation mask ref",
    )
    done = payload.get("done", False)
    success = payload.get("success", False)
    if type(done) is not bool or type(success) is not bool:
        raise TypeError(
            "VIMA environment done/success must be booleans"
        )
    reward = payload.get("reward")
    generation = observation.get("generation")
    if generation is not None and (
        type(generation) is not str or not generation.strip()
    ):
        raise TypeError(
            "VIMA environment generation must be text or None"
        )
    return (
        token_ref,
        mask_ref,
        done,
        success,
        reward,
        generation,
    )


def _record_environment(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    (
        token_ref,
        mask_ref,
        done,
        success,
        reward,
        generation,
    ) = _environment_observation(request.previous_value)

    observation_tokens = list(
        _ref_tuple(
            request.state.get("observation_token_refs", ()),
            schema_id=_OBSERVATION_TOKEN_SCHEMA,
            field_name="VIMA observation_token_refs",
        )
    )
    observation_masks = list(
        _ref_tuple(
            request.state.get("observation_mask_refs", ()),
            schema_id=_OBSERVATION_MASK_SCHEMA,
            field_name="VIMA observation_mask_refs",
        )
    )
    observation_tokens.append(token_ref.payload())
    observation_masks.append(mask_ref.payload())

    step_index = request.state.get("step_index")
    if type(step_index) is not int or step_index < 0:
        raise ValueError("VIMA step_index state is invalid")
    step_index += 1

    return MethodNodeResult(
        value={
            "step_index": step_index,
            "done": done,
            "success": success,
            "reward": reward,
            "observation_token_digest": token_ref.tensor_digest,
            "observation_mask_digest": mask_ref.tensor_digest,
            "environment_generation": generation,
        },
        state_update={
            "observation_token_refs": tuple(observation_tokens),
            "observation_mask_refs": tuple(observation_masks),
            "step_index": step_index,
            "done": done,
            "success": success,
            "last_reward": reward,
            "last_environment_generation": generation,
        },
    )


def _route_terminal(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    step_index = request.state.get("step_index")
    max_steps = request.state.get("max_steps")
    if type(step_index) is not int or step_index < 0:
        raise ValueError("VIMA step_index state is invalid")
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("VIMA max_steps state is invalid")
    done = request.state.get("done") is True
    success = request.state.get("success") is True
    budget_exhausted = step_index >= max_steps
    terminal = done or budget_exhausted
    return MethodNodeResult(
        value={
            "terminal": terminal,
            "done": done,
            "success": success,
            "budget_exhausted": budget_exhausted,
            "step_index": step_index,
            "max_steps": max_steps,
        },
        next_node="return" if terminal else "policy",
        checkpoint=True,
        checkpoint_value={
            "step_index": step_index,
            "success": success,
            "done": done,
            "max_steps": max_steps,
        },
    )


def _return_result(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    observation_tokens = _ref_tuple(
        request.state.get("observation_token_refs", ()),
        schema_id=_OBSERVATION_TOKEN_SCHEMA,
        field_name="VIMA observation_token_refs",
    )
    action_tokens = _ref_tuple(
        request.state.get("action_token_refs", ()),
        schema_id="vima.action-token.tensor.v1",
        field_name="VIMA action_token_refs",
    )
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "evaluation_partition": request.state.get(
                "evaluation_partition"
            ),
            "seed": request.state.get("seed"),
            "success": request.state.get("success") is True,
            "done": request.state.get("done") is True,
            "steps": request.state.get("step_index"),
            "max_steps": request.state.get("max_steps"),
            "observation_count": len(observation_tokens),
            "action_count": len(action_tokens),
            "last_reward": request.state.get("last_reward"),
            "last_environment_generation": request.state.get(
                "last_environment_generation"
            ),
            "last_observation_token_digest": (
                observation_tokens[-1]["tensor_digest"]
                if observation_tokens
                and isinstance(observation_tokens[-1], Mapping)
                else None
            ),
        }
    )


def build_vima_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "paper": "VIMA: Robot Manipulation with Multimodal Prompts",
        "policy_source_commit": VIMA_POLICY_AUDITED_COMMIT,
        "benchmark_source_commit": VIMA_BENCH_AUDITED_COMMIT,
        "prompt_io": "interleaved-text-object-tokens",
        "observation_io": "object-centric-front+top+ee",
        "history": "autoregressive-observation-action-interleave",
        "position_bins": VIMA_REFERENCE_FIDELITY.pose_position_bins,
        "rotation_bins": VIMA_REFERENCE_FIDELITY.pose_rotation_bins,
        "episode_budget": "oracle_max_steps+2",
        "environment_capability": _ENVIRONMENT_CAPABILITY_ID,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="vima-embodied",
            implementation_version=VIMA_POLICY_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="vima.embodied.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(
        identity,
        entrypoint="policy",
    )
    builder.agent(
        "policy",
        "vima.policy.predict",
        VIMA_POLICY_AGENT_ID,
        ("prepare_environment",),
        view_handler=_agent_view,
    )
    builder.compute(
        "prepare_environment",
        "vima.environment.prepare",
        _prepare_environment,
        ("environment",),
    )
    builder.capability(
        "environment",
        "vima.environment.act",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_environment",),
        effect_class=EffectClass.RECONCILABLE,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_environment",
        "vima.environment.record",
        _record_environment,
        ("terminal",),
    )
    builder.route(
        "terminal",
        "vima.terminal.route",
        _route_terminal,
        ("policy", "return"),
    )
    builder.return_node(
        "return",
        "vima.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "vima.prompt.content",
            "vima.observation.content",
            "vima.action-token.content",
            "environment.effect",
            "vima.trajectory",
        ),
        metric_names=(
            "episode_success",
            "episode_steps",
        ),
        artifact_kinds=(
            "vima_multimodal_prompt",
            "vima_embodied_trajectory",
        ),
    )


VIMA_METHOD_PROGRAM = build_vima_method_program()


__all__ = [
    "VIMA_METHOD_PROGRAM",
    "build_vima_method_program",
    "vima_initial_state",
]
