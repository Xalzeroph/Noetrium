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
from research.reproductions._support import JsonObject, canonical_digest

from collections.abc import Mapping




from .fidelity import SEECLICK_FIDELITY
from .grounding import parse_seeclick_point

_AGENT_ID = "seeclick.gui-grounding"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"SeeClick {field} must be non-empty text")
    return value


def seeclick_initial_state(*, instruction: str, screenshot_ref: str) -> JsonObject:
    return {
        "instruction": _text(instruction, "instruction"),
        "screenshot_ref": _text(screenshot_ref, "screenshot ref"),
        "predicted_point": {},
        "model_call_count": 0,
    }


def _grounding_view(request: MethodCall) -> JsonObject:
    return {
        "instruction": request.state.get("instruction"),
        "screenshot_ref": request.state.get("screenshot_ref"),
        "task": "text_2_point",
        "coordinate_system": {
            "minimum": SEECLICK_FIDELITY.coordinate_min,
            "maximum": SEECLICK_FIDELITY.coordinate_max,
            "precision_decimals": SEECLICK_FIDELITY.coordinate_precision_decimals,
        },
        "input_representation": "screenshot-only",
    }


def _record_grounding(request: MethodCall) -> MethodNodeResult:
    point = parse_seeclick_point(request.previous_value)
    count = request.state.get("model_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("SeeClick model_call_count must be non-negative")
    payload = point.as_payload()
    return dict(
        value={"point": payload},
        state_update={
            "predicted_point": payload,
            "model_call_count": count + 1,
        },
        next_node="return",
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "predicted_point": request.state.get("predicted_point", {}),
            "model_call_count": request.state.get("model_call_count", 0),
        }
    )


def build_seeclick_method_program(method, ) -> None:
    configuration: JsonObject = {
        "base_model": SEECLICK_FIDELITY.base_model,
        "coordinate_range": (
            SEECLICK_FIDELITY.coordinate_min,
            SEECLICK_FIDELITY.coordinate_max,
        ),
        "coordinate_precision_decimals": (
            SEECLICK_FIDELITY.coordinate_precision_decimals
        ),
        "grounding_task": "text_2_point",
        "screenshots_only_for_agent": SEECLICK_FIDELITY.screenshots_only_for_agent,
    }

    builder = method
    builder.agent(
        "ground",
        "seeclick.gui-grounding.predict",
        _AGENT_ID,
        ("record",),
        view=_grounding_view,
    )
    builder.compute(
        "record",
        "seeclick.gui-grounding.record",
        _record_grounding,
        ("return",),
    )
    builder.return_node("return", "seeclick.result", _return_result)
    builder.configure(configuration)
    builder.policy(
        execution='checkpointable',
        evidence=(
            "seeclick.screenshot-binding",
            "seeclick.grounding-prediction",
        ),
        metrics=("grounding_accuracy", "model_call_count"),
        artifacts=("seeclick_grounding_prediction",),
    )
    return builder


METHOD_CONFIGURER = build_seeclick_method_program
METHOD_ENTRYPOINT = "ground"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = [
    'build_seeclick_method_program',
    'seeclick_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]
