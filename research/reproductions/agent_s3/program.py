from __future__ import annotations

from research.reproductions._support import (
    JsonObject,
    JsonValue,
    MethodCall,
    canonical_digest,
    freeze_json,
    method_event,
    require_sha256,
    thaw_json,
)
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, thaw_json

from collections.abc import Mapping, Sequence





from .context import (
    AgentS3GeneratorTurn,
    AgentS3ReflectionTurn,
    project_agent_s3_context,
)
from .fidelity import AGENT_S3_FIDELITY


_REFLECTION_AGENT = "agent-s3.reflection"
_WORKER_AGENT = "agent-s3.worker"
_CODE_AGENT = "agent-s3.code-agent"
_ENVIRONMENT_ACTION_CAPABILITY = "environment.act"
_HOST_SAFETY_MAX_TURNS = 256


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Agent S3 {field} must be text")
    return value.strip()


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"Agent S3 {field} must be a sequence")
    return tuple(value)


def _model_text(value: object, field: str) -> str:
    if isinstance(value, str):
        return _text(value, field)
    if not isinstance(value, Mapping):
        raise TypeError(f"Agent S3 {field} must be text or mapping")
    for key in ("content", "text", "response", "action", "command"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise ValueError(f"Agent S3 {field} has no textual content")


def _generator_turns(state: Mapping[str, JsonValue]) -> tuple[AgentS3GeneratorTurn, ...]:
    rows = _sequence(state.get("generator_turns", ()), "generator_turns")
    result: list[AgentS3GeneratorTurn] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("Agent S3 generator turn state must be mappings")
        result.append(
            AgentS3GeneratorTurn(
                user_text=_text(row.get("user_text"), "generator user_text", allow_empty=True),
                assistant_text=_text(
                    row.get("assistant_text"),
                    "generator assistant_text",
                    allow_empty=True,
                ),
                screenshot_ref=(
                    row.get("screenshot_ref")
                    if isinstance(row.get("screenshot_ref"), str)
                    and row.get("screenshot_ref", "").strip()
                    else None
                ),
            )
        )
    return tuple(result)


def _reflection_turns(state: Mapping[str, JsonValue]) -> tuple[AgentS3ReflectionTurn, ...]:
    rows = _sequence(state.get("reflection_turns", ()), "reflection_turns")
    result: list[AgentS3ReflectionTurn] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("Agent S3 reflection turn state must be mappings")
        result.append(
            AgentS3ReflectionTurn(
                text=_text(row.get("text"), "reflection text"),
                screenshot_ref=(
                    row.get("screenshot_ref")
                    if isinstance(row.get("screenshot_ref"), str)
                    and row.get("screenshot_ref", "").strip()
                    else None
                ),
            )
        )
    return tuple(result)


def _projected_context(request: MethodCall):
    return project_agent_s3_context(
        generator_turns=_generator_turns(request.state),
        reflection_turns=_reflection_turns(request.state),
        engine_type=_text(request.state.get("engine_type"), "engine_type"),
        max_trajectory_length=AGENT_S3_FIDELITY.default_max_trajectory_length,
    )


def agent_s3_initial_state(
    *,
    task_id: str,
    instruction: str,
    engine_type: str,
    observation: JsonObject,
) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "instruction": _text(instruction, "instruction"),
        "engine_type": _text(engine_type, "engine_type"),
        "observation": observation,
        "generator_turns": (),
        "reflection_turns": (),
        "iteration": 0,
        "pending_action": "",
        "pending_code_request": "",
        "last_environment_result": {},
        "model_call_count": 0,
        "device_action_count": 0,
        "terminated": False,
        "success": False,
    }


def _reflection_view(request: MethodCall) -> JsonObject:
    view = _projected_context(request)
    return {
        "phase": "trajectory_reflection",
        "task_id": request.state.get("task_id"),
        "instruction": request.state.get("instruction"),
        "observation": request.state.get("observation", {}),
        "generator_turns": tuple(
            {
                "user_text": row.user_text,
                "assistant_text": row.assistant_text,
                "screenshot_ref": row.screenshot_ref,
            }
            for row in view.generator_turns
        ),
        "reflection_turns": tuple(
            {"text": row.text, "screenshot_ref": row.screenshot_ref}
            for row in view.reflection_turns
        ),
        "runtime_tool_creation": AGENT_S3_FIDELITY.runtime_tool_creation,
        "trajectory_reflection_before_tool_creation": (
            AGENT_S3_FIDELITY.trajectory_reflection_before_tool_creation
        ),
    }


def _record_reflection(request: MethodCall) -> MethodNodeResult:
    text = _model_text(request.previous_value, "reflection response")
    rows = list(_sequence(request.state.get("reflection_turns", ()), "reflection_turns"))
    observation = request.state.get("observation", {})
    screenshot_ref = (
        observation.get("image_ref")
        if isinstance(observation, Mapping)
        and isinstance(observation.get("image_ref"), str)
        and observation.get("image_ref", "").strip()
        else None
    )
    rows.append({"text": text, "screenshot_ref": screenshot_ref})
    count = request.state.get("model_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Agent S3 model_call_count must be non-negative")
    return dict(
        value={"reflection": text},
        state_update={
            "reflection_turns": tuple(rows),
            "model_call_count": count + 1,
        },
    )


def _worker_view(request: MethodCall) -> JsonObject:
    view = _projected_context(request)
    latest_reflection = (
        view.reflection_turns[-1].text if view.reflection_turns else ""
    )
    return {
        "phase": "single_worker_policy",
        "task_id": request.state.get("task_id"),
        "instruction": request.state.get("instruction"),
        "observation": request.state.get("observation", {}),
        "latest_reflection": latest_reflection,
        "generator_turns": tuple(
            {
                "user_text": row.user_text,
                "assistant_text": row.assistant_text,
                "screenshot_ref": row.screenshot_ref,
            }
            for row in view.generator_turns
        ),
        "one_action_per_turn": AGENT_S3_FIDELITY.one_action_per_turn,
        "action_interface": AGENT_S3_FIDELITY.action_interface,
        "code_agent_available": AGENT_S3_FIDELITY.runtime_tool_creation,
        "code_agent_languages": AGENT_S3_FIDELITY.code_agent_languages,
    }


def _record_worker(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    use_code_agent = False
    code_request = ""
    if isinstance(value, Mapping):
        action = value.get("action", value.get("command"))
        action_text = _text(action, "worker action") if isinstance(action, str) else ""
        use_code_agent = value.get("use_code_agent") is True
        request_text = value.get("code_request")
        if isinstance(request_text, str) and request_text.strip():
            code_request = request_text.strip()
    else:
        action_text = _model_text(value, "worker response")
    if use_code_agent:
        if not code_request:
            code_request = action_text
        next_node = "code_agent"
        pending_action = ""
    else:
        if not action_text:
            raise ValueError("Agent S3 worker must emit one action")
        next_node = "act"
        pending_action = action_text

    count = request.state.get("model_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Agent S3 model_call_count must be non-negative")
    return dict(
        value={
            "use_code_agent": use_code_agent,
            "action": pending_action,
            "code_request": code_request,
        },
        state_update={
            "pending_action": pending_action,
            "pending_code_request": code_request,
            "model_call_count": count + 1,
        },
        next_node=next_node,
    )


def _code_agent_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "bounded_code_agent",
        "task_id": request.state.get("task_id"),
        "instruction": request.state.get("instruction"),
        "request": _text(
            request.state.get("pending_code_request"),
            "pending_code_request",
        ),
        "languages": AGENT_S3_FIDELITY.code_agent_languages,
        "budget": AGENT_S3_FIDELITY.code_agent_budget,
        "output_contract": "single bash action or generated Python CLI invocation",
    }


def _record_code_agent(request: MethodCall) -> MethodNodeResult:
    action = _model_text(request.previous_value, "code-agent response")
    count = request.state.get("model_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Agent S3 model_call_count must be non-negative")
    return dict(
        value={"action": action},
        state_update={
            "pending_action": action,
            "pending_code_request": "",
            "model_call_count": count + 1,
        },
    )


def _prepare_action(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "task_id": request.state.get("task_id"),
            "interface": AGENT_S3_FIDELITY.action_interface,
            "action": _text(request.state.get("pending_action"), "pending_action"),
            "one_action_per_turn": AGENT_S3_FIDELITY.one_action_per_turn,
        }
    )


def _record_environment(request: MethodCall) -> MethodNodeResult:
    result = thaw_json(request.previous_value)
    if not isinstance(result, Mapping):
        raise TypeError("Agent S3 environment result must be an object")
    iteration = request.state.get("iteration", 0)
    actions = request.state.get("device_action_count", 0)
    if type(iteration) is not int or iteration < 0:
        raise ValueError("Agent S3 iteration must be non-negative")
    if type(actions) is not int or actions < 0:
        raise ValueError("Agent S3 device_action_count must be non-negative")

    action = _text(request.state.get("pending_action"), "pending_action")
    observation = result.get("observation", result)
    image_ref = result.get("image_ref")
    rows = list(_sequence(request.state.get("generator_turns", ()), "generator_turns"))
    rows.append(
        {
            "user_text": _text(
                str(request.state.get("instruction", "")),
                "instruction",
            ),
            "assistant_text": action,
            "screenshot_ref": (
                image_ref
                if isinstance(image_ref, str) and image_ref.strip()
                else None
            ),
        }
    )
    success = result.get("success") is True
    terminated = (
        result.get("done") is True
        or result.get("terminated") is True
        or success
        or action.strip() == AGENT_S3_FIDELITY.task_completion_command
    )
    next_iteration = iteration + 1
    return dict(
        value={
            "iteration": next_iteration,
            "success": success,
            "terminated": terminated,
            "observation": observation,
        },
        state_update={
            "generator_turns": tuple(rows),
            "observation": observation,
            "last_environment_result": result,
            "iteration": next_iteration,
            "device_action_count": actions + 1,
            "pending_action": "",
            "terminated": terminated,
            "success": success,
        },
        next_node="return" if terminated else "reflection",
        checkpoint=True,
        checkpoint_value={
            "iteration": next_iteration,
            "success": success,
            "terminated": terminated,
        },
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "task_id": request.state.get("task_id"),
            "success": request.state.get("success") is True,
            "terminated": request.state.get("terminated") is True,
            "iteration": request.state.get("iteration", 0),
            "model_call_count": request.state.get("model_call_count", 0),
            "device_action_count": request.state.get("device_action_count", 0),
            "last_environment_result": request.state.get("last_environment_result", {}),
            "generator_turns": request.state.get("generator_turns", ()),
            "reflection_turns": request.state.get("reflection_turns", ()),
        }
    )


def build_agent_s3_method_program(method, ) -> None:
    f = AGENT_S3_FIDELITY
    configuration: JsonObject = {
        "repository": f.repository,
        "release": f.release,
        "release_commit": f.release_commit,
        "agent_source": f.agent_source,
        "worker_source": f.worker_source,
        "code_agent_source": f.code_agent_source,
        "grounding_source": f.grounding_source,
        "hierarchy_enabled": f.hierarchy_enabled,
        "default_max_trajectory_length": f.default_max_trajectory_length,
        "default_reflection_enabled": f.default_reflection_enabled,
        "long_context_engine_types": f.long_context_engine_types,
        "runtime_tool_creation": True,
        "code_agent_budget": f.code_agent_budget,
        "code_agent_languages": f.code_agent_languages,
        "host_safety_max_turns": _HOST_SAFETY_MAX_TURNS,
    }

    builder = method
    builder.agent(
        "reflection",
        "agent-s3.trajectory.reflect",
        _REFLECTION_AGENT,
        ("record_reflection",),
        view=_reflection_view,
        max_visits=_HOST_SAFETY_MAX_TURNS,
    )
    builder.compute(
        "record_reflection",
        "agent-s3.trajectory.reflect.record",
        _record_reflection,
        ("worker",),
        max_visits=_HOST_SAFETY_MAX_TURNS,
    )
    builder.agent(
        "worker",
        "agent-s3.worker",
        _WORKER_AGENT,
        ("record_worker",),
        view=_worker_view,
        max_visits=_HOST_SAFETY_MAX_TURNS,
    )
    builder.route(
        "record_worker",
        "agent-s3.worker.record",
        _record_worker,
        ("code_agent", "act"),
        max_visits=_HOST_SAFETY_MAX_TURNS,
    )
    builder.agent(
        "code_agent",
        "agent-s3.code-agent",
        _CODE_AGENT,
        ("record_code_agent",),
        view=_code_agent_view,
        max_visits=f.code_agent_budget,
    )
    builder.compute(
        "record_code_agent",
        "agent-s3.code-agent.record",
        _record_code_agent,
        ("act",),
        max_visits=f.code_agent_budget,
    )
    builder.compute(
        "act",
        "agent-s3.action.prepare",
        _prepare_action,
        ("environment",),
        max_visits=_HOST_SAFETY_MAX_TURNS,
    )
    builder.capability(
        "environment",
        "agent-s3.environment.act",
        _ENVIRONMENT_ACTION_CAPABILITY,
        ("record_environment",),
        effect='reconcilable',
        max_visits=_HOST_SAFETY_MAX_TURNS,
        evidence=("agent-s3.environment-effect",),
    )
    builder.route(
        "record_environment",
        "agent-s3.environment.record",
        _record_environment,
        ("reflection", "return"),
        max_visits=_HOST_SAFETY_MAX_TURNS,
    )
    builder.return_node("return", "agent-s3.result", _return_result)
    builder.configure(configuration)
    builder.requires(*(_ENVIRONMENT_ACTION_CAPABILITY,))
    builder.policy(
        execution='effect_recorded',
        evidence=(
            "agent-s3.context-projection",
            "agent-s3.reflection",
            "agent-s3.environment-effect",
            "agent-s3.trajectory",
            "model.invocation",
        ),
        metrics=(
            "task_success",
            "model_call_count",
            "device_action_count",
            "iteration_count",
        ),
        artifacts=(
            "agent_s3_trajectory",
            "agent_s3_reflection",
            "agent_s3_screenshot",
        ),
    )
    return builder


METHOD_CONFIGURER = build_agent_s3_method_program
METHOD_ENTRYPOINT = "reflection"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}


__all__ = [
    'agent_s3_initial_state',
    'build_agent_s3_method_program',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]

METHOD_SPEC = {"method_id": 'agent-s3', "version": "paper-protocol", "semantic_contract": 'agent-s3' + ".method.v2", "entrypoint": METHOD_ENTRYPOINT}

__all__ = tuple(dict.fromkeys((*__all__, 'METHOD_SPEC')))
