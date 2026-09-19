from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

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
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import WEBVOYAGER_FIDELITY

_POLICY_AGENT = "webvoyager.policy"
_ENVIRONMENT_ACTION_CAPABILITY = "environment.act"
_ACTION_RE = re.compile(r"^([A-Za-z]+)(?:\s*\[(.*?)\])?$")


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"WebVoyager {field} must be text")
    return value


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"WebVoyager {field} must be a sequence")
    return tuple(value)


def webvoyager_initial_state(
    *,
    task_id: str,
    instruction: str,
    start_url: str,
    observation: JsonObject,
) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "instruction": _text(instruction, "instruction"),
        "start_url": _text(start_url, "start_url"),
        "observation": observation,
        "recent_image_refs": (),
        "step": 0,
        "last_thought": "",
        "last_action": "",
        "last_environment_result": {},
        "answer": "",
        "terminated": False,
    }


def _policy_view(request: MethodNodeRequest) -> JsonObject:
    step = request.state.get("step", 0)
    if type(step) is not int or step < 0:
        raise ValueError("WebVoyager step must be non-negative")
    images = _sequence(
        request.state.get("recent_image_refs", ()),
        "recent_image_refs",
    )
    return {
        "task_id": request.state.get("task_id"),
        "instruction": request.state.get("instruction"),
        "start_url": request.state.get("start_url"),
        "observation_mode": WEBVOYAGER_FIDELITY.observation_mode,
        "observation": request.state.get("observation", {}),
        "recent_image_refs": images[-WEBVOYAGER_FIDELITY.max_attached_images :],
        "step": step,
        "max_iterations": WEBVOYAGER_FIDELITY.max_iterations,
        "action_grammar": WEBVOYAGER_FIDELITY.action_grammar,
        "strict_thought_action_format": (
            WEBVOYAGER_FIDELITY.strict_thought_action_format
        ),
        "one_action_per_iteration": WEBVOYAGER_FIDELITY.one_action_per_iteration,
        "numerical_element_grounding": (
            WEBVOYAGER_FIDELITY.numerical_element_grounding
        ),
    }


def _decode_policy(value: JsonValue) -> tuple[str, str]:
    if isinstance(value, Mapping):
        thought = value.get("thought", value.get("Thought", ""))
        action = value.get("action", value.get("Action", ""))
        return (
            _text(thought, "thought", allow_empty=True),
            _text(action, "action"),
        )
    if not isinstance(value, str):
        raise TypeError("WebVoyager policy output must be text or object")
    thought = ""
    action = ""
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("thought:"):
            thought = stripped.split(":", 1)[1].strip()
        elif stripped.lower().startswith("action:"):
            action = stripped.split(":", 1)[1].strip()
    if not action:
        raise ValueError("WebVoyager policy output requires Action")
    return thought, action


def _parse_action(action: str) -> JsonObject:
    match = _ACTION_RE.fullmatch(action.strip())
    if match is None:
        raise ValueError("WebVoyager action does not match released grammar")
    kind = match.group(1)
    payload = "" if match.group(2) is None else match.group(2).strip()
    if kind not in WEBVOYAGER_FIDELITY.action_grammar:
        raise ValueError(f"unsupported WebVoyager action: {kind}")
    if kind in {"Click", "Type"} and not payload:
        raise ValueError(f"WebVoyager {kind} requires an argument")
    if kind == "Click":
        first = payload.split(",", 1)[0].strip()
        if not first.isdigit():
            raise ValueError("WebVoyager Click requires numerical element grounding")
    return {
        "kind": kind,
        "argument": payload,
        "terminal": kind == "ANSWER",
    }


def _record_policy(request: MethodNodeRequest) -> MethodNodeResult:
    thought, action_text = _decode_policy(request.previous_value)
    action = _parse_action(action_text)
    step = request.state.get("step", 0)
    if type(step) is not int or step < 0:
        raise ValueError("WebVoyager step must be non-negative")
    if action["terminal"] is True:
        answer = _text(action["argument"], "answer")
        return MethodNodeResult(
            value={"thought": thought, "action": action_text, "answer": answer},
            state_update={
                "last_thought": thought,
                "last_action": action_text,
                "answer": answer,
                "terminated": True,
            },
            next_node="return",
        )
    if step >= WEBVOYAGER_FIDELITY.max_iterations:
        return MethodNodeResult(
            value={"budget_exhausted": True},
            state_update={"terminated": True},
            next_node="return",
        )
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "action": action,
            "wait_seconds": WEBVOYAGER_FIDELITY.wait_seconds,
            "type_action_auto_enter": WEBVOYAGER_FIDELITY.type_action_auto_enter,
        },
        state_update={
            "last_thought": thought,
            "last_action": action_text,
        },
        next_node="act",
    )


def _record_environment(request: MethodNodeRequest) -> MethodNodeResult:
    result = thaw_json(request.previous_value)
    if not isinstance(result, Mapping):
        raise TypeError("WebVoyager environment result must be an object")
    step = request.state.get("step", 0)
    if type(step) is not int or step < 0:
        raise ValueError("WebVoyager step must be non-negative")
    next_step = step + 1
    observation = result.get("observation", result)
    image_refs = list(
        _sequence(
            request.state.get("recent_image_refs", ()),
            "recent_image_refs",
        )
    )
    image_ref = result.get("image_ref")
    if isinstance(image_ref, str) and image_ref.strip():
        image_refs.append(image_ref)
    image_refs = image_refs[-WEBVOYAGER_FIDELITY.max_attached_images :]
    exhausted = next_step >= WEBVOYAGER_FIDELITY.max_iterations
    return MethodNodeResult(
        value={
            "step": next_step,
            "observation": observation,
            "budget_exhausted": exhausted,
        },
        state_update={
            "step": next_step,
            "observation": observation,
            "recent_image_refs": tuple(image_refs),
            "last_environment_result": result,
            "terminated": exhausted,
        },
        next_node="return" if exhausted else "policy",
        checkpoint=True,
        checkpoint_value={
            "step": next_step,
            "last_action": request.state.get("last_action", ""),
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "answer": request.state.get("answer", ""),
            "terminated": request.state.get("terminated") is True,
            "step_count": request.state.get("step", 0),
            "last_action": request.state.get("last_action", ""),
            "last_environment_result": request.state.get(
                "last_environment_result",
                {},
            ),
        }
    )


def build_webvoyager_method_program() -> MethodProgram:
    fidelity = WEBVOYAGER_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "observation_mode": fidelity.observation_mode,
        "text_only_alternative": fidelity.text_only_alternative,
        "action_grammar": fidelity.action_grammar,
        "max_iterations": fidelity.max_iterations,
        "max_attached_images": fidelity.max_attached_images,
        "strict_thought_action_format": fidelity.strict_thought_action_format,
        "numerical_element_grounding": fidelity.numerical_element_grounding,
        "wait_seconds": fidelity.wait_seconds,
        "type_action_auto_enter": fidelity.type_action_auto_enter,
        "environment_action_capability": _ENVIRONMENT_ACTION_CAPABILITY,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="webvoyager",
            implementation_version=fidelity.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="webvoyager.acl2024.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="policy")
    builder.agent(
        "policy",
        "webvoyager.policy",
        _POLICY_AGENT,
        ("record_policy",),
        view_handler=_policy_view,
        max_visits=fidelity.max_iterations + 1,
    )
    builder.route(
        "record_policy",
        "webvoyager.policy.record",
        _record_policy,
        ("act", "return"),
        max_visits=fidelity.max_iterations + 1,
    )
    builder.capability(
        "act",
        "webvoyager.environment.act",
        _ENVIRONMENT_ACTION_CAPABILITY,
        ("record_environment",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=fidelity.max_iterations,
        evidence_obligations=("webvoyager.environment-effect",),
    )
    builder.route(
        "record_environment",
        "webvoyager.environment.record",
        _record_environment,
        ("policy", "return"),
        max_visits=fidelity.max_iterations,
        evidence_obligations=("webvoyager.observation",),
    )
    builder.return_node("return", "webvoyager.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_ACTION_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "webvoyager.model-visible-observation",
            "webvoyager.environment-effect",
            "webvoyager.observation",
            "webvoyager.answer",
        ),
        metric_names=(
            "task_success",
            "step_count",
            "model_call_count",
        ),
        artifact_kinds=(
            "webvoyager_trajectory",
            "webvoyager_screenshot",
        ),
    )


WEBVOYAGER_METHOD_PROGRAM = build_webvoyager_method_program()

__all__ = [
    "WEBVOYAGER_METHOD_PROGRAM",
    "build_webvoyager_method_program",
    "webvoyager_initial_state",
]
