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
    freeze_json,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import HUGGINGGPT_FIDELITY
from .task_graph import build_hugginggpt_task

_PLANNER = "hugginggpt.controller.plan"
_SELECTOR = "hugginggpt.controller.select-model"
_AGGREGATOR = "hugginggpt.controller.aggregate"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"HuggingGPT {field} must be text")
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"HuggingGPT {field} must be a sequence")
    return tuple(value)


def hugginggpt_initial_state(*, instruction: str) -> JsonObject:
    return {
        "instruction": _text(instruction, "instruction"),
        "tasks": (),
        "completed_task_ids": (),
        "results": (),
        "selected_task_id": None,
        "selected_capability_id": "",
        "expert_call_count": 0,
        "response": "",
    }


def _planning_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "instruction": _text(request.state.get("instruction"), "instruction"),
        "stage": "task_planning",
        "dependency_marker": HUGGINGGPT_FIDELITY.dependency_marker,
        "output_schema": {
            "tasks": (
                "sequence of {task_id:int, task:str, args:object}; "
                "dependency args reference <GENERATED>-N"
            )
        },
    }


def _record_plan(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if not isinstance(value, Mapping):
        raise TypeError("HuggingGPT planner output must be an object")
    raw_tasks = _sequence(value.get("tasks", ()), "planned tasks")
    normalized = []
    seen: set[int] = set()
    for raw in raw_tasks:
        if not isinstance(raw, Mapping):
            raise TypeError("HuggingGPT planned task must be an object")
        task_id = raw.get("task_id")
        if type(task_id) is not int or task_id < 0 or task_id in seen:
            raise ValueError("HuggingGPT planned task ids must be unique non-negative integers")
        seen.add(task_id)
        args = raw.get("args", {})
        if not isinstance(args, Mapping):
            raise TypeError("HuggingGPT planned task args must be an object")
        typed = build_hugginggpt_task(
            task_id=task_id,
            task=_text(raw.get("task"), "planned task"),
            args={str(key): str(item) for key, item in args.items()},
        )
        normalized.append({
            "task_id": typed.task_id,
            "task": typed.task,
            "args": typed.args,
            "dependencies": typed.dependencies,
        })
    if not normalized:
        raise ValueError("HuggingGPT planner must produce at least one subtask")
    normalized.sort(key=lambda row: int(row["task_id"]))
    return MethodNodeResult(
        value={"task_count": len(normalized)},
        state_update={"tasks": tuple(normalized)},
        next_node="select_next",
    )


def _completed_ids(request: MethodNodeRequest) -> tuple[int, ...]:
    rows = _sequence(request.state.get("completed_task_ids", ()), "completed task ids")
    if any(type(row) is not int or row < 0 for row in rows):
        raise TypeError("HuggingGPT completed task ids must be non-negative integers")
    return tuple(int(row) for row in rows)


def _task_rows(request: MethodNodeRequest) -> tuple[Mapping[str, object], ...]:
    rows = _sequence(request.state.get("tasks", ()), "tasks")
    if any(not isinstance(row, Mapping) for row in rows):
        raise TypeError("HuggingGPT tasks must be objects")
    return tuple(row for row in rows if isinstance(row, Mapping))


def _select_next(request: MethodNodeRequest) -> MethodNodeResult:
    tasks = _task_rows(request)
    completed = set(_completed_ids(request))
    pending = [row for row in tasks if int(row["task_id"]) not in completed]
    if not pending:
        return MethodNodeResult(value={"done": True}, next_node="aggregate")
    ready = [
        row
        for row in pending
        if set(int(dep) for dep in row.get("dependencies", ())).issubset(completed)
    ]
    if not ready:
        raise RuntimeError("HuggingGPT task graph has unresolved dependency cycle")
    selected = min(ready, key=lambda row: int(row["task_id"]))
    return MethodNodeResult(
        value={"selected_task_id": int(selected["task_id"])},
        state_update={
            "selected_task_id": int(selected["task_id"]),
            "selected_capability_id": "",
        },
        next_node="select_model",
    )


def _selected_task(request: MethodNodeRequest) -> Mapping[str, object]:
    task_id = request.state.get("selected_task_id")
    if type(task_id) is not int:
        raise ValueError("HuggingGPT selected_task_id is missing")
    for row in _task_rows(request):
        if int(row["task_id"]) == task_id:
            return row
    raise ValueError("HuggingGPT selected task is not in task graph")


def _selection_view(request: MethodNodeRequest) -> JsonObject:
    task = _selected_task(request)
    return {
        "instruction": request.state.get("instruction"),
        "stage": "model_selection",
        "task": freeze_json(task),
        "selection_basis": HUGGINGGPT_FIDELITY.model_selection_basis,
    }


def _record_selection(
    allowed_capabilities: tuple[str, ...],
):
    allowed = set(allowed_capabilities)

    def record(request: MethodNodeRequest) -> MethodNodeResult:
        value = request.previous_value
        if isinstance(value, str):
            capability_id = value
        elif isinstance(value, Mapping):
            capability_id = value.get("capability_id", value.get("model_id", ""))
        else:
            raise TypeError("HuggingGPT model selection must be text or object")
        capability_id = _text(capability_id, "selected capability")
        if capability_id not in allowed:
            raise ValueError("HuggingGPT selected model escaped expert capability closure")
        return MethodNodeResult(
            value={"capability_id": capability_id},
            state_update={"selected_capability_id": capability_id},
            next_node="prepare_execution",
        )

    return record


def _results_map(request: MethodNodeRequest) -> dict[int, JsonValue]:
    rows = _sequence(request.state.get("results", ()), "results")
    result: dict[int, JsonValue] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("HuggingGPT result rows must be objects")
        task_id = row.get("task_id")
        if type(task_id) is not int:
            raise TypeError("HuggingGPT result task_id must be integer")
        result[task_id] = row.get("result")
    return result


def _prepare_execution(request: MethodNodeRequest) -> MethodNodeResult:
    task = _selected_task(request)
    results = _results_map(request)
    dependencies = tuple(int(dep) for dep in task.get("dependencies", ()))
    return MethodNodeResult(
        value={
            "task_id": int(task["task_id"]),
            "task": task["task"],
            "args": task.get("args", ()),
            "dependency_results": tuple(
                {"task_id": dep, "result": results[dep]}
                for dep in dependencies
            ),
        }
    )


def _expert_target(request: MethodNodeRequest) -> str:
    return _text(
        request.state.get("selected_capability_id"),
        "selected capability",
    )


def _record_execution(request: MethodNodeRequest) -> MethodNodeResult:
    task = _selected_task(request)
    task_id = int(task["task_id"])
    rows = list(_sequence(request.state.get("results", ()), "results"))
    rows.append({"task_id": task_id, "result": thaw_json(request.previous_value)})
    completed = (*_completed_ids(request), task_id)
    count = request.state.get("expert_call_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("HuggingGPT expert_call_count must be non-negative")
    return MethodNodeResult(
        value={"task_id": task_id, "completed": True},
        state_update={
            "results": tuple(rows),
            "completed_task_ids": completed,
            "expert_call_count": count + 1,
        },
        next_node="select_next",
        checkpoint=True,
        checkpoint_value={
            "completed_task_ids": completed,
            "expert_call_count": count + 1,
        },
    )


def _aggregate_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "instruction": request.state.get("instruction"),
        "stage": "response_generation",
        "results": request.state.get("results", ()),
        "aggregation_order": HUGGINGGPT_FIDELITY.response_aggregation_order,
    }


def _record_response(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        response = value
    elif isinstance(value, Mapping):
        response = value.get("response", value.get("text", ""))
    else:
        raise TypeError("HuggingGPT response generation must return text or object")
    response = _text(response, "response")
    return MethodNodeResult(
        value={"response": response},
        state_update={"response": response},
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "response": request.state.get("response", ""),
            "subtask_count": len(_task_rows(request)),
            "expert_call_count": request.state.get("expert_call_count", 0),
            "completed_task_ids": request.state.get("completed_task_ids", ()),
            "results": request.state.get("results", ()),
        }
    )


def build_hugginggpt_method_program(
    expert_capability_ids: tuple[str, ...],
) -> MethodProgram:
    if type(expert_capability_ids) is not tuple or not expert_capability_ids:
        raise ValueError("HuggingGPT requires non-empty expert capability closure")
    if any(type(row) is not str or not row.strip() for row in expert_capability_ids):
        raise ValueError("HuggingGPT expert capabilities must be canonical text")
    if len(expert_capability_ids) != len(set(expert_capability_ids)):
        raise ValueError("HuggingGPT expert capability closure must be unique")

    configuration: JsonObject = {
        "source_commit": HUGGINGGPT_FIDELITY.source_commit,
        "stages": tuple(stage.value for stage in HUGGINGGPT_FIDELITY.stages),
        "expert_capability_ids": expert_capability_ids,
        "dependency_marker": HUGGINGGPT_FIDELITY.dependency_marker,
        "ready_task_policy": "dependency-ready/task-id-order",
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="hugginggpt",
            implementation_version=HUGGINGGPT_FIDELITY.source_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="hugginggpt.neurips2023.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="plan")
    builder.agent(
        "plan",
        "hugginggpt.task-planning",
        _PLANNER,
        ("record_plan",),
        view_handler=_planning_view,
    )
    builder.compute(
        "record_plan",
        "hugginggpt.task-planning.record",
        _record_plan,
        ("select_next",),
    )
    builder.route(
        "select_next",
        "hugginggpt.task-execution.ready-set",
        _select_next,
        ("select_model", "aggregate"),
        max_visits=4096,
    )
    builder.agent(
        "select_model",
        "hugginggpt.model-selection",
        _SELECTOR,
        ("record_selection",),
        view_handler=_selection_view,
        max_visits=4096,
    )
    builder.compute(
        "record_selection",
        "hugginggpt.model-selection.record",
        _record_selection(expert_capability_ids),
        ("prepare_execution",),
        max_visits=4096,
    )
    builder.compute(
        "prepare_execution",
        "hugginggpt.task-execution.prepare",
        _prepare_execution,
        ("execute",),
        max_visits=4096,
    )
    builder.dynamic_capability(
        "execute",
        "hugginggpt.task-execution.expert-model",
        expert_capability_ids,
        _expert_target,
        ("record_execution",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=4096,
        evidence_obligations=("hugginggpt.expert-execution",),
    )
    builder.compute(
        "record_execution",
        "hugginggpt.task-execution.record",
        _record_execution,
        ("select_next",),
        max_visits=4096,
    )
    builder.agent(
        "aggregate",
        "hugginggpt.response-generation",
        _AGGREGATOR,
        ("record_response",),
        view_handler=_aggregate_view,
    )
    builder.compute(
        "record_response",
        "hugginggpt.response-generation.record",
        _record_response,
        ("return",),
    )
    builder.return_node("return", "hugginggpt.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=expert_capability_ids,
        execution_class=MethodExecutionClass.CHECKPOINTABLE,
        evidence_obligations=(
            "hugginggpt.task-plan",
            "hugginggpt.model-selection",
            "hugginggpt.expert-execution",
            "hugginggpt.response",
        ),
        metric_names=(
            "task_success",
            "subtask_count",
            "expert_call_count",
            "model_call_count",
        ),
        artifact_kinds=("hugginggpt_execution_trace",),
    )


__all__ = ["build_hugginggpt_method_program", "hugginggpt_initial_state"]
