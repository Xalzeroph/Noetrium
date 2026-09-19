from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import COGAGENT_FIDELITY

_AGENT_ID = "cogagent.gui-policy"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"CogAgent {field} must be text")
    return value


def cogagent_initial_state(
    *,
    task_instruction: str,
    screenshot_ref: str,
    history: tuple[JsonObject, ...] = (),
    candidates: tuple[JsonObject, ...] = (),
) -> JsonObject:
    if type(history) is not tuple or any(not isinstance(row, Mapping) for row in history):
        raise TypeError("CogAgent history must be a tuple of objects")
    if type(candidates) is not tuple or any(not isinstance(row, Mapping) for row in candidates):
        raise TypeError("CogAgent candidates must be a tuple of objects")
    return {
        "task_instruction": _text(task_instruction, "task instruction"),
        "screenshot_ref": _text(screenshot_ref, "screenshot ref"),
        "history": history,
        "candidates": candidates,
        "prediction": {},
        "model_call_count": 0,
    }


def _policy_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task_instruction": request.state.get("task_instruction"),
        "screenshot_ref": request.state.get("screenshot_ref"),
        "history": request.state.get("history", ()),
        "candidates": request.state.get("candidates", ()),
        "input_representation": COGAGENT_FIDELITY.gui_input_representation,
        "paper_input_resolution": COGAGENT_FIDELITY.input_resolution,
        "operation_types": COGAGENT_FIDELITY.mind2web_operation_types,
        "output_schema": {
            "target": "GUI element prediction",
            "operation": "CLICK | TYPE | SELECT",
            "value": "optional operation value",
        },
    }


def _record_prediction(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if not isinstance(value, Mapping):
        raise TypeError("CogAgent GUI policy output must be an object")
    target = value.get("target", value.get("element"))
    if target is None:
        raise ValueError("CogAgent GUI prediction requires target")
    operation = _text(value.get("operation"), "operation").upper()
    if operation not in COGAGENT_FIDELITY.mind2web_operation_types:
        raise ValueError("CogAgent GUI prediction operation is outside paper action grammar")
    operation_value = value.get("value", "")
    if operation_value is None:
        operation_value = ""
    if type(operation_value) is not str:
        operation_value = str(operation_value)
    count = request.state.get("model_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("CogAgent model_call_count must be non-negative")
    prediction: JsonObject = {
        "target": target,
        "operation": operation,
        "value": operation_value,
    }
    return MethodNodeResult(
        value=prediction,
        state_update={
            "prediction": prediction,
            "model_call_count": count + 1,
        },
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "prediction": request.state.get("prediction", {}),
            "model_call_count": request.state.get("model_call_count", 0),
        }
    )


def build_cogagent_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "model_size_billion": COGAGENT_FIDELITY.model_parameters_billion,
        "visual_parameters_billion": COGAGENT_FIDELITY.visual_parameters_billion,
        "language_parameters_billion": COGAGENT_FIDELITY.language_parameters_billion,
        "input_resolution": COGAGENT_FIDELITY.input_resolution,
        "dual_resolution_vision": True,
        "gui_input_representation": COGAGENT_FIDELITY.gui_input_representation,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="cogagent",
            implementation_version="cvpr-2024-final",
            abi_version="noetrium.method-machine.v1",
            schema_version="cogagent.gui-policy.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="policy")
    builder.agent(
        "policy",
        "cogagent.gui-policy.predict",
        _AGENT_ID,
        ("record_prediction",),
        view_handler=_policy_view,
    )
    builder.compute(
        "record_prediction",
        "cogagent.gui-policy.record",
        _record_prediction,
        ("return",),
    )
    builder.return_node("return", "cogagent.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.CHECKPOINTABLE,
        evidence_obligations=(
            "cogagent.screenshot-binding",
            "cogagent.gui-prediction",
        ),
        metric_names=("step_success_rate", "model_call_count"),
        artifact_kinds=("cogagent_gui_prediction",),
    )


COGAGENT_METHOD_PROGRAM = build_cogagent_method_program()

__all__ = [
    "COGAGENT_METHOD_PROGRAM",
    "build_cogagent_method_program",
    "cogagent_initial_state",
]
