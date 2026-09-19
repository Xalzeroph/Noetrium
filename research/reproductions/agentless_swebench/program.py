from __future__ import annotations

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

from .fidelity import AGENTLESS_FIDELITY

_FILE_LOCALIZER = "agentless.localization.files"
_SYMBOL_LOCALIZER = "agentless.localization.symbols"
_EDIT_LOCALIZER = "agentless.localization.edits"
_REPAIR_MODEL = "agentless.repair"
_VALIDATION_PLANNER = "agentless.validation.plan"
_RERANK_MODEL = "agentless.validation.rerank"
_SOFTWARE_COMMAND_CAPABILITY = "software.command"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Agentless {field} must be text")
    return value


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"Agentless {field} must be a sequence")
    return tuple(value)


def _mapping(value: object, field: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Agentless {field} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"Agentless {field} must decode to an object")
    return decoded


def agentless_initial_state(
    *,
    instance_id: str,
    issue: str,
    repository_structure: JsonObject,
) -> JsonObject:
    return {
        "instance_id": _text(instance_id, "instance_id"),
        "issue": _text(issue, "issue"),
        "repository_structure": repository_structure,
        "localized_files": (),
        "localized_symbols": (),
        "edit_locations": (),
        "candidate_patches": (),
        "validation_plan": {},
        "validation_result": {},
        "selected_patch": "",
        "model_call_count": 0,
        "validation_count": 0,
    }


def _model_count(request: MethodNodeRequest) -> int:
    value = request.state.get("model_call_count", 0)
    if type(value) is not int or value < 0:
        raise ValueError("Agentless model_call_count must be non-negative")
    return value


def _files_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "instance_id": request.state.get("instance_id"),
        "issue": request.state.get("issue"),
        "repository_structure": request.state.get("repository_structure", {}),
        "objective": "localize likely faulty files only",
        "next_stage_is_fixed": "class_or_function_localization",
    }


def _record_files(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    raw = value.get("files", ()) if isinstance(value, Mapping) else value
    files = tuple(_text(row, "localized file") for row in _sequence(raw, "files"))
    if not files:
        raise ValueError("Agentless file localization returned no files")
    return MethodNodeResult(
        value={"files": files},
        state_update={
            "localized_files": files,
            "model_call_count": _model_count(request) + 1,
        },
    )


def _symbols_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "issue": request.state.get("issue"),
        "localized_files": request.state.get("localized_files", ()),
        "repository_structure": request.state.get("repository_structure", {}),
        "objective": "localize relevant classes or functions within selected files",
        "next_stage_is_fixed": "fine_grained_edit_localization",
    }


def _record_symbols(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    raw = value.get("symbols", ()) if isinstance(value, Mapping) else value
    symbols = tuple(_text(row, "localized symbol") for row in _sequence(raw, "symbols"))
    if not symbols:
        raise ValueError("Agentless symbol localization returned no symbols")
    return MethodNodeResult(
        value={"symbols": symbols},
        state_update={
            "localized_symbols": symbols,
            "model_call_count": _model_count(request) + 1,
        },
    )


def _edits_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "issue": request.state.get("issue"),
        "localized_files": request.state.get("localized_files", ()),
        "localized_symbols": request.state.get("localized_symbols", ()),
        "objective": "identify fine-grained edit locations; do not choose tools",
        "next_stage_is_fixed": "repair",
    }


def _record_edits(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    raw = value.get("edit_locations", ()) if isinstance(value, Mapping) else value
    edits = tuple(_text(row, "edit location") for row in _sequence(raw, "edit locations"))
    if not edits:
        raise ValueError("Agentless edit localization returned no locations")
    return MethodNodeResult(
        value={"edit_locations": edits},
        state_update={
            "edit_locations": edits,
            "model_call_count": _model_count(request) + 1,
        },
    )


def _repair_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "instance_id": request.state.get("instance_id"),
        "issue": request.state.get("issue"),
        "localized_files": request.state.get("localized_files", ()),
        "localized_symbols": request.state.get("localized_symbols", ()),
        "edit_locations": request.state.get("edit_locations", ()),
        "objective": "sample multiple candidate patches in simple diff form",
        "next_stage_is_fixed": "patch_validation",
    }


def _record_repairs(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    raw = value.get("candidate_patches", ()) if isinstance(value, Mapping) else value
    patches = tuple(_text(row, "candidate patch") for row in _sequence(raw, "candidate patches"))
    if not patches:
        raise ValueError("Agentless repair returned no candidate patches")
    return MethodNodeResult(
        value={"candidate_patches": patches},
        state_update={
            "candidate_patches": patches,
            "model_call_count": _model_count(request) + 1,
        },
    )


def _validation_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "instance_id": request.state.get("instance_id"),
        "issue": request.state.get("issue"),
        "candidate_patches": request.state.get("candidate_patches", ()),
        "objective": (
            "select regression tests and generate a reproduction test for fixed "
            "validation; do not choose arbitrary future actions"
        ),
        "required_outputs": (
            "commands",
            "reproduction_test",
            "candidate_patch_order",
        ),
    }


def _prepare_validation(request: MethodNodeRequest) -> MethodNodeResult:
    plan = _mapping(request.previous_value, "validation plan")
    commands = _sequence(plan.get("commands", ()), "validation commands")
    if not commands:
        raise ValueError("Agentless validation plan requires commands")
    for command in commands:
        _text(command, "validation command")
    return MethodNodeResult(
        value={
            "commands": commands,
            "reproduction_test": plan.get("reproduction_test", ""),
            "candidate_patches": request.state.get("candidate_patches", ()),
            "execution_mode": "fixed_validation_batch",
        },
        state_update={
            "validation_plan": plan,
            "model_call_count": _model_count(request) + 1,
        },
    )


def _record_validation(request: MethodNodeRequest) -> MethodNodeResult:
    result = _mapping(request.previous_value, "validation result")
    count = request.state.get("validation_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Agentless validation_count must be non-negative")
    return MethodNodeResult(
        value=result,
        state_update={
            "validation_result": result,
            "validation_count": count + 1,
        },
    )


def _rerank_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "issue": request.state.get("issue"),
        "candidate_patches": request.state.get("candidate_patches", ()),
        "validation_plan": request.state.get("validation_plan", {}),
        "validation_result": request.state.get("validation_result", {}),
        "objective": "rerank validated patches and select exactly one final patch",
    }


def _record_selection(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        patch = value
    elif isinstance(value, Mapping):
        patch = value.get("selected_patch", value.get("patch", ""))
    else:
        raise TypeError("Agentless rerank output must be text or object")
    patch = _text(patch, "selected patch")
    return MethodNodeResult(
        value={"selected_patch": patch},
        state_update={
            "selected_patch": patch,
            "model_call_count": _model_count(request) + 1,
        },
        next_node="return",
        checkpoint=True,
        checkpoint_value={
            "selected_patch_digest": canonical_digest(patch),
            "validation_count": request.state.get("validation_count", 0),
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    patch = _text(request.state.get("selected_patch"), "selected patch")
    return MethodNodeResult(
        value={
            "instance_id": request.state.get("instance_id"),
            "selected_patch": patch,
            "localized_files": request.state.get("localized_files", ()),
            "localized_symbols": request.state.get("localized_symbols", ()),
            "edit_locations": request.state.get("edit_locations", ()),
            "candidate_patch_count": len(
                _sequence(
                    request.state.get("candidate_patches", ()),
                    "candidate patches",
                )
            ),
            "validation_count": request.state.get("validation_count", 0),
            "model_call_count": request.state.get("model_call_count", 0),
        }
    )


def build_agentless_method_program() -> MethodProgram:
    f = AGENTLESS_FIDELITY
    configuration: JsonObject = {
        "source_commit": f.audited_commit,
        "release": f.release,
        "stages": f.stages,
        "localization_levels": f.localization_levels,
        "autonomous_agent_loop": f.autonomous_agent_loop,
        "model_selects_next_tool_action": f.model_selects_next_tool_action,
        "samples_multiple_candidate_patches": f.samples_multiple_candidate_patches,
        "selects_regression_tests": f.selects_regression_tests,
        "generates_reproduction_tests": f.generates_reproduction_tests,
        "reranks_with_validation_results": f.reranks_with_validation_results,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="agentless",
            implementation_version=f.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="agentless.fse2025.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="localize_files")
    builder.agent(
        "localize_files",
        "agentless.localization.files",
        _FILE_LOCALIZER,
        ("record_files",),
        view_handler=_files_view,
    )
    builder.compute(
        "record_files",
        "agentless.localization.files.record",
        _record_files,
        ("localize_symbols",),
    )
    builder.agent(
        "localize_symbols",
        "agentless.localization.symbols",
        _SYMBOL_LOCALIZER,
        ("record_symbols",),
        view_handler=_symbols_view,
    )
    builder.compute(
        "record_symbols",
        "agentless.localization.symbols.record",
        _record_symbols,
        ("localize_edits",),
    )
    builder.agent(
        "localize_edits",
        "agentless.localization.edits",
        _EDIT_LOCALIZER,
        ("record_edits",),
        view_handler=_edits_view,
    )
    builder.compute(
        "record_edits",
        "agentless.localization.edits.record",
        _record_edits,
        ("repair",),
    )
    builder.agent(
        "repair",
        "agentless.repair.sample",
        _REPAIR_MODEL,
        ("record_repairs",),
        view_handler=_repair_view,
    )
    builder.compute(
        "record_repairs",
        "agentless.repair.record",
        _record_repairs,
        ("validation_plan",),
    )
    builder.agent(
        "validation_plan",
        "agentless.validation.plan",
        _VALIDATION_PLANNER,
        ("prepare_validation",),
        view_handler=_validation_view,
    )
    builder.compute(
        "prepare_validation",
        "agentless.validation.prepare",
        _prepare_validation,
        ("validate",),
    )
    builder.capability(
        "validate",
        "agentless.validation.execute",
        _SOFTWARE_COMMAND_CAPABILITY,
        ("record_validation",),
        effect_class=EffectClass.RECONCILABLE,
        evidence_obligations=("agentless.validation-effect",),
    )
    builder.compute(
        "record_validation",
        "agentless.validation.record",
        _record_validation,
        ("rerank",),
    )
    builder.agent(
        "rerank",
        "agentless.validation.rerank",
        _RERANK_MODEL,
        ("record_selection",),
        view_handler=_rerank_view,
    )
    builder.compute(
        "record_selection",
        "agentless.validation.select",
        _record_selection,
        ("return",),
    )
    builder.return_node("return", "agentless.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_SOFTWARE_COMMAND_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "agentless.localization",
            "agentless.candidate-patches",
            "agentless.validation-effect",
            "agentless.patch-selection",
        ),
        metric_names=(
            "task_resolved",
            "model_call_count",
            "validation_count",
        ),
        artifact_kinds=(
            "prediction.patch",
            "agentless_localization",
            "agentless_validation",
        ),
    )


AGENTLESS_METHOD_PROGRAM = build_agentless_method_program()

__all__ = [
    "AGENTLESS_METHOD_PROGRAM",
    "agentless_initial_state",
    "build_agentless_method_program",
]
