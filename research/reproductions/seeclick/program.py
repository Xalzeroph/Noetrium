from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import JsonObject, canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

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


def _grounding_view(request: MethodNodeRequest) -> JsonObject:
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


def _record_grounding(request: MethodNodeRequest) -> MethodNodeResult:
    point = parse_seeclick_point(request.previous_value)
    count = request.state.get("model_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("SeeClick model_call_count must be non-negative")
    payload = point.as_payload()
    return MethodNodeResult(
        value={"point": payload},
        state_update={
            "predicted_point": payload,
            "model_call_count": count + 1,
        },
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "predicted_point": request.state.get("predicted_point", {}),
            "model_call_count": request.state.get("model_call_count", 0),
        }
    )


def build_seeclick_method_program() -> MethodProgram:
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
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="seeclick",
            implementation_version="acl-2024-final",
            abi_version="noetrium.method-machine.v1",
            schema_version="seeclick.gui-grounding.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="ground")
    builder.agent(
        "ground",
        "seeclick.gui-grounding.predict",
        _AGENT_ID,
        ("record",),
        view_handler=_grounding_view,
    )
    builder.compute(
        "record",
        "seeclick.gui-grounding.record",
        _record_grounding,
        ("return",),
    )
    builder.return_node("return", "seeclick.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.CHECKPOINTABLE,
        evidence_obligations=(
            "seeclick.screenshot-binding",
            "seeclick.grounding-prediction",
        ),
        metric_names=("grounding_accuracy", "model_call_count"),
        artifact_kinds=("seeclick_grounding_prediction",),
    )


SEECLICK_METHOD_PROGRAM = build_seeclick_method_program()

__all__ = [
    "SEECLICK_METHOD_PROGRAM",
    "build_seeclick_method_program",
    "seeclick_initial_state",
]
