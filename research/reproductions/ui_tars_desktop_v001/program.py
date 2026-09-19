from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
    environment_query_capability_payload,
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
    freeze_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import UI_TARS_DESKTOP_V001_FIDELITY
from .scaffold import (
    UiTarsDesktopV001Action,
    UiTarsDesktopV001Conversation,
    UiTarsDesktopV001LoopState,
    UiTarsDesktopV001Status,
    parse_ui_tars_desktop_v001_prediction,
    project_ui_tars_desktop_v001_vlm_view,
    ui_tars_desktop_v001_box_to_screen_point,
)

_AGENT_ID = "ui-tars.desktop-v001"
_QUERY_CAPABILITY = "environment.query"
_ACTION_CAPABILITY = "environment.act"
_HOST_MAX_ACTIONS_PER_PREDICTION = 64


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"UI-TARS {field} must be text")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"UI-TARS {field} must be integer >= {minimum}")
    return value


def _conversations(value: object) -> tuple[UiTarsDesktopV001Conversation, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("UI-TARS conversations must be a sequence")
    rows: list[UiTarsDesktopV001Conversation] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("UI-TARS conversation rows must be mappings")
        rows.append(
            UiTarsDesktopV001Conversation(
                _text(row.get("from_role"), "conversation role"),
                _text(row.get("value"), "conversation value", allow_empty=True),
            )
        )
    return tuple(rows)


def _conversation_rows(
    rows: Sequence[UiTarsDesktopV001Conversation],
) -> tuple[JsonObject, ...]:
    return tuple(
        {"from_role": row.from_role, "value": row.value}
        for row in rows
    )


def _images(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("UI-TARS images must be a sequence")
    rows = tuple(value)
    if any(not isinstance(row, str) or not row.strip() for row in rows):
        raise ValueError("UI-TARS images must be non-empty references")
    return rows


def _loop_state(state: Mapping[str, JsonValue]) -> UiTarsDesktopV001LoopState:
    raw = state.get("loop_status", UiTarsDesktopV001Status.INIT.value)
    try:
        status = UiTarsDesktopV001Status(str(raw))
    except ValueError as exc:
        raise ValueError("UI-TARS loop_status is invalid") from exc
    return UiTarsDesktopV001LoopState(
        loop_count=_integer(state.get("loop_count", 0), "loop_count"),
        snapshot_error_count=_integer(
            state.get("snapshot_error_count", 0),
            "snapshot_error_count",
        ),
        status=status,
    )


def _action_row(action: UiTarsDesktopV001Action) -> JsonObject:
    return {
        "reflection": action.reflection,
        "thought": action.thought,
        "action_type": action.action_type,
        "action_inputs": action.action_inputs,
    }


def _action(value: object) -> UiTarsDesktopV001Action:
    if not isinstance(value, Mapping):
        raise TypeError("UI-TARS pending action must be a mapping")
    raw_inputs = value.get("action_inputs", ())
    if not isinstance(raw_inputs, tuple):
        raise TypeError("UI-TARS pending action inputs must be a tuple")
    return UiTarsDesktopV001Action(
        reflection=_text(value.get("reflection", ""), "reflection", allow_empty=True),
        thought=_text(value.get("thought", ""), "thought", allow_empty=True),
        action_type=_text(value.get("action_type"), "action type"),
        action_inputs=raw_inputs,
    )


def ui_tars_desktop_v001_initial_state(*, task_instruction: str) -> JsonObject:
    instruction = _text(task_instruction, "task instruction")
    return {
        "task_instruction": instruction,
        "conversations": (
            {"from_role": "human", "value": instruction},
        ),
        "images": (),
        "loop_count": 0,
        "snapshot_error_count": 0,
        "loop_status": UiTarsDesktopV001Status.INIT.value,
        "snapshot_ref": "",
        "snapshot_width": 0,
        "snapshot_height": 0,
        "action_queue": (),
        "pending_action": None,
        "device_action_count": 0,
        "model_call_count": 0,
        "terminal_action": "",
        "last_device_observation": None,
    }


def _begin_iteration(request: MethodNodeRequest) -> MethodNodeResult:
    state = _loop_state(request.state)
    if state.status is UiTarsDesktopV001Status.INIT:
        state = state.start()
    state = state.begin_iteration()
    terminal = state.status is UiTarsDesktopV001Status.MAX_LOOP
    return MethodNodeResult(
        value={
            "loop_count": state.loop_count,
            "snapshot_error_count": state.snapshot_error_count,
            "status": state.status.value,
        },
        state_update={
            "loop_count": state.loop_count,
            "snapshot_error_count": state.snapshot_error_count,
            "loop_status": state.status.value,
            "terminal_action": (
                UI_TARS_DESKTOP_V001_FIDELITY.max_loop_action
                if terminal
                else request.state.get("terminal_action", "")
            ),
        },
        next_node="return" if terminal else "prepare_snapshot",
    )


def _prepare_snapshot(request: MethodNodeRequest) -> MethodNodeResult:
    del request
    return MethodNodeResult(
        value=environment_query_capability_payload(
            "state",
            {
                "view": "screen",
                "retry_count": UI_TARS_DESKTOP_V001_FIDELITY.screenshot_retry_count,
            },
        )
    )


def _snapshot(value: JsonValue) -> tuple[str, int, int] | None:
    if not isinstance(value, Mapping) or value.get("supported") is not True:
        return None
    payload = value.get("payload")
    observation = value.get("observation")
    if not isinstance(payload, Mapping) or not isinstance(observation, Mapping):
        return None

    width = payload.get("width")
    height = payload.get("height")
    if type(width) is not int or width <= 0 or type(height) is not int or height <= 0:
        observation_payload = observation.get("payload")
        if isinstance(observation_payload, Mapping):
            width = observation_payload.get("width")
            height = observation_payload.get("height")
    if type(width) is not int or width <= 0 or type(height) is not int or height <= 0:
        return None

    artifact_refs = observation.get("artifact_refs")
    snapshot_ref: str | None = None
    if isinstance(artifact_refs, tuple) and artifact_refs:
        candidate = artifact_refs[0]
        if isinstance(candidate, str) and candidate:
            snapshot_ref = candidate
    observation_payload = observation.get("payload")
    if snapshot_ref is None and isinstance(observation_payload, Mapping):
        candidate = observation_payload.get("screenshot_ref", observation_payload.get("image_ref"))
        if isinstance(candidate, str) and candidate:
            snapshot_ref = candidate
    if snapshot_ref is None:
        return None
    return snapshot_ref, width, height


def _record_snapshot(request: MethodNodeRequest) -> MethodNodeResult:
    resolved = _snapshot(request.previous_value)
    state = _loop_state(request.state)
    if resolved is None:
        state = state.record_invalid_snapshot()
        if state.snapshot_error_count >= UI_TARS_DESKTOP_V001_FIDELITY.screenshot_failure_limit:
            state = UiTarsDesktopV001LoopState(
                state.loop_count,
                state.snapshot_error_count,
                UiTarsDesktopV001Status.MAX_LOOP,
            )
        terminal = state.status is UiTarsDesktopV001Status.MAX_LOOP
        return MethodNodeResult(
            value={
                "snapshot_valid": False,
                "snapshot_error_count": state.snapshot_error_count,
            },
            state_update={
                "loop_count": state.loop_count,
                "snapshot_error_count": state.snapshot_error_count,
                "loop_status": state.status.value,
                "terminal_action": "error_env" if terminal else "",
            },
            next_node="return" if terminal else "begin_iteration",
        )

    snapshot_ref, width, height = resolved
    conversations = _conversations(request.state.get("conversations", ()))
    images = _images(request.state.get("images", ()))
    conversations = (
        *conversations,
        UiTarsDesktopV001Conversation(
            "human",
            UI_TARS_DESKTOP_V001_FIDELITY.image_placeholder,
        ),
    )
    images = (*images, snapshot_ref)
    return MethodNodeResult(
        value={
            "snapshot_valid": True,
            "snapshot_ref": snapshot_ref,
            "width": width,
            "height": height,
        },
        state_update={
            "conversations": _conversation_rows(conversations),
            "images": images,
            "snapshot_ref": snapshot_ref,
            "snapshot_width": width,
            "snapshot_height": height,
        },
        next_node="agent",
    )


def _agent_view(request: MethodNodeRequest) -> JsonObject:
    conversations = _conversations(request.state.get("conversations", ()))
    images = _images(request.state.get("images", ()))
    view = project_ui_tars_desktop_v001_vlm_view(
        conversations,
        images,
        max_images=UI_TARS_DESKTOP_V001_FIDELITY.max_retained_images,
    )
    return {
        "task_instruction": _text(
            request.state.get("task_instruction"),
            "task instruction",
        ),
        "conversations": _conversation_rows(view.conversations),
        "images": view.images,
        "snapshot_ref": _text(request.state.get("snapshot_ref"), "snapshot ref"),
        "snapshot_width": _integer(
            request.state.get("snapshot_width"),
            "snapshot width",
            minimum=1,
        ),
        "snapshot_height": _integer(
            request.state.get("snapshot_height"),
            "snapshot height",
            minimum=1,
        ),
        "loop_count": _integer(request.state.get("loop_count", 0), "loop count"),
    }


def _prediction(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        prediction = value.get("prediction")
        if isinstance(prediction, str):
            return prediction
    raise TypeError("UI-TARS agent result must be prediction text")


def _parse_prediction(request: MethodNodeRequest) -> MethodNodeResult:
    prediction = _prediction(request.previous_value)
    actions = parse_ui_tars_desktop_v001_prediction(prediction)
    conversations = _conversations(request.state.get("conversations", ()))
    conversations = (
        *conversations,
        UiTarsDesktopV001Conversation("gpt", prediction),
    )
    queue = tuple(_action_row(action) for action in actions)
    return MethodNodeResult(
        value={"action_count": len(queue)},
        state_update={
            "conversations": _conversation_rows(conversations),
            "action_queue": queue,
            "model_call_count": _integer(
                request.state.get("model_call_count", 0),
                "model_call_count",
            )
            + 1,
        },
        next_node="next_action" if queue else "begin_iteration",
    )


def _next_action(request: MethodNodeRequest) -> MethodNodeResult:
    queue = request.state.get("action_queue", ())
    if not isinstance(queue, tuple) or not queue:
        raise ValueError("UI-TARS next_action requires a non-empty action queue")
    action = _action(queue[0])
    remaining = queue[1:]
    terminal = action.action_type in UI_TARS_DESKTOP_V001_FIDELITY.terminal_actions
    is_wait = action.action_type == "wait"
    next_node = "return" if terminal else "record_wait" if is_wait else "prepare_device_action"
    return MethodNodeResult(
        value=_action_row(action),
        state_update={
            "pending_action": _action_row(action),
            "action_queue": remaining,
            "terminal_action": action.action_type if terminal else "",
        },
        next_node=next_node,
    )


def _point_payload(box: str, *, width: int, height: int) -> JsonObject:
    point = ui_tars_desktop_v001_box_to_screen_point(
        box,
        width=width,
        height=height,
        precision_factor=UI_TARS_DESKTOP_V001_FIDELITY.coordinate_factor,
    )
    return {"x": point.x, "y": point.y}


def _device_payload(action: UiTarsDesktopV001Action, *, width: int, height: int) -> JsonObject:
    values = dict(action.action_inputs)
    payload: dict[str, JsonValue] = {
        "reflection": action.reflection,
        "thought": action.thought,
    }
    if action.action_type in {"click", "left_double", "right_single"}:
        box = values.get("start_box")
        if not isinstance(box, str):
            raise ValueError(f"UI-TARS {action.action_type} requires start_box")
        payload.update(_point_payload(box, width=width, height=height))
    elif action.action_type == "drag":
        start = values.get("start_box")
        end = values.get("end_box")
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError("UI-TARS drag requires start_box and end_box")
        payload["start"] = _point_payload(start, width=width, height=height)
        payload["end"] = _point_payload(end, width=width, height=height)
    else:
        for name, value in action.action_inputs:
            payload[name] = value
    return payload


def _prepare_device_action(request: MethodNodeRequest) -> MethodNodeResult:
    action = _action(request.state.get("pending_action"))
    if action.action_type in UI_TARS_DESKTOP_V001_FIDELITY.terminal_actions or action.action_type == "wait":
        raise ValueError("UI-TARS non-device action reached device preparation")
    width = _integer(request.state.get("snapshot_width"), "snapshot width", minimum=1)
    height = _integer(request.state.get("snapshot_height"), "snapshot height", minimum=1)
    return MethodNodeResult(
        value=environment_action_capability_payload(
            action.action_type,
            _device_payload(action, width=width, height=height),
        )
    )


def _record_device_action(request: MethodNodeRequest) -> MethodNodeResult:
    count = _integer(
        request.state.get("device_action_count", 0),
        "device_action_count",
    ) + 1
    return MethodNodeResult(
        value=request.previous_value,
        state_update={
            "device_action_count": count,
            "last_device_observation": request.previous_value,
        },
        checkpoint=True,
        checkpoint_value={
            "loop_count": _integer(request.state.get("loop_count", 0), "loop_count"),
            "device_action_count": count,
        },
        next_node=(
            "next_action"
            if request.state.get("action_queue")
            else "begin_iteration"
        ),
    )


def _record_wait(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={"waited": True},
        next_node=(
            "next_action"
            if request.state.get("action_queue")
            else "begin_iteration"
        ),
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    terminal_action = _text(
        request.state.get("terminal_action", ""),
        "terminal action",
        allow_empty=True,
    )
    return MethodNodeResult(
        value={
            "finished": terminal_action == "finished",
            "terminal_action": terminal_action,
            "loop_count": _integer(request.state.get("loop_count", 0), "loop_count"),
            "device_action_count": _integer(
                request.state.get("device_action_count", 0),
                "device_action_count",
            ),
            "model_call_count": _integer(
                request.state.get("model_call_count", 0),
                "model_call_count",
            ),
            "snapshot_error_count": _integer(
                request.state.get("snapshot_error_count", 0),
                "snapshot_error_count",
            ),
            "final_snapshot_ref": request.state.get("snapshot_ref", ""),
        }
    )


def build_ui_tars_desktop_v001_method_program() -> MethodProgram:
    fidelity = UI_TARS_DESKTOP_V001_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "release_version": fidelity.release_version,
        "coordinate_factor": fidelity.coordinate_factor,
        "max_loop_count": fidelity.max_loop_count,
        "max_retained_images": fidelity.max_retained_images,
        "screenshot_retry_count": fidelity.screenshot_retry_count,
        "screenshot_failure_limit": fidelity.screenshot_failure_limit,
        "multiple_actions_per_prediction": fidelity.multiple_actions_per_prediction,
        "execution_uses_current_snapshot_geometry": (
            fidelity.execution_uses_current_snapshot_geometry
        ),
        "old_image_eviction_is_model_view_only": fidelity.old_image_eviction_is_model_view_only,
        "host_max_actions_per_prediction": _HOST_MAX_ACTIONS_PER_PREDICTION,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="ui-tars-desktop-v001",
            implementation_version=fidelity.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="ui-tars-desktop-v001.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    action_bound = fidelity.max_loop_count * _HOST_MAX_ACTIONS_PER_PREDICTION
    builder = MethodProgramBuilder(identity, entrypoint="begin_iteration")
    builder.route(
        "begin_iteration",
        "ui-tars.iteration.begin",
        _begin_iteration,
        ("prepare_snapshot", "return"),
        max_visits=fidelity.max_loop_count + fidelity.screenshot_failure_limit + 1,
    )
    builder.compute(
        "prepare_snapshot",
        "ui-tars.snapshot.prepare",
        _prepare_snapshot,
        ("snapshot_query",),
        max_visits=fidelity.max_loop_count + fidelity.screenshot_failure_limit,
    )
    builder.capability(
        "snapshot_query",
        "ui-tars.snapshot.query",
        _QUERY_CAPABILITY,
        ("record_snapshot",),
        effect_class=EffectClass.PURE,
        max_visits=fidelity.max_loop_count + fidelity.screenshot_failure_limit,
    )
    builder.compute(
        "record_snapshot",
        "ui-tars.snapshot.record",
        _record_snapshot,
        ("agent", "begin_iteration", "return"),
        max_visits=fidelity.max_loop_count + fidelity.screenshot_failure_limit,
    )
    builder.agent(
        "agent",
        "ui-tars.model.predict",
        _AGENT_ID,
        ("parse_prediction",),
        view_handler=_agent_view,
        max_visits=fidelity.max_loop_count,
    )
    builder.compute(
        "parse_prediction",
        "ui-tars.prediction.parse",
        _parse_prediction,
        ("next_action", "begin_iteration"),
        max_visits=fidelity.max_loop_count,
    )
    builder.route(
        "next_action",
        "ui-tars.action.route",
        _next_action,
        ("prepare_device_action", "record_wait", "return"),
        max_visits=action_bound,
    )
    builder.compute(
        "prepare_device_action",
        "ui-tars.action.prepare",
        _prepare_device_action,
        ("device_action",),
        max_visits=action_bound,
    )
    builder.capability(
        "device_action",
        "ui-tars.action.execute",
        _ACTION_CAPABILITY,
        ("record_device_action",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=action_bound,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_device_action",
        "ui-tars.action.record",
        _record_device_action,
        ("next_action", "begin_iteration"),
        max_visits=action_bound,
    )
    builder.compute(
        "record_wait",
        "ui-tars.wait.record",
        _record_wait,
        ("next_action", "begin_iteration"),
        max_visits=action_bound,
    )
    builder.return_node("return", "ui-tars.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_QUERY_CAPABILITY, _ACTION_CAPABILITY),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "ui-tars.model-view",
            "ui-tars.action-trajectory",
            "environment.observation",
            "environment.effect",
        ),
        metric_names=(
            "task_success",
            "loop_count",
            "device_action_count",
            "model_call_count",
            "snapshot_error_count",
        ),
        artifact_kinds=("ui_tars_trajectory", "gui_screenshot"),
    )


UI_TARS_DESKTOP_V001_METHOD_PROGRAM = build_ui_tars_desktop_v001_method_program()


__all__ = [
    "UI_TARS_DESKTOP_V001_METHOD_PROGRAM",
    "build_ui_tars_desktop_v001_method_program",
    "ui_tars_desktop_v001_initial_state",
]
