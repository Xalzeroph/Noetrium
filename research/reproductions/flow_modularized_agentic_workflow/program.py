from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchMachineBatchItem,
    ChildResearchMachineBatchPort,
    ChildResearchMachineBatchRequest,
    ChildResearchMachineRequest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .aov import (
    flow_all_completed,
    flow_merge_refinement,
    flow_ready_task_ids,
    flow_select_candidate,
    normalize_flow_workflow,
)
from .fidelity import FLOW_FIDELITY
from .subtask import flow_subtask_initial_data

_INITIAL_WORKFLOW_AGENT = "flow.workflow-initializer"
_SUBTASK_AGENT = "flow.subtask-executor"
_VALIDATOR_AGENT = "flow.subtask-validator"
_REFINER_AGENT = "flow.workflow-refiner"
_SUMMARY_AGENT = "flow.summary"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Flow {field} must be text")
    return value if allow_empty else value.strip()


def _mapping(value: object, field: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Flow {field} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"Flow {field} must decode to an object")
    return decoded


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"Flow {field} must be a sequence")
    return tuple(value)


def flow_initial_state(*, task_id: str, overall_task: str) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "overall_task": _text(overall_task, "overall_task"),
        "initial_candidates": (),
        "workflow": {},
        "candidate_scores": (),
        "candidate_selected_index": -1,
        "current_task_id": "",
        "pending_task_result": None,
        "pending_ready_task_ids": (),
        "batch_sequence": 0,
        "completed_since_refine": 0,
        "refinement_count": 0,
        "total_task_executions": 0,
        "ready_set_batches": (),
        "summary": "",
        "terminated_with_incomplete_tasks": False,
    }


def _initial_view(request: MethodNodeRequest) -> JsonObject:
    candidates = _sequence(
        request.state.get("initial_candidates", ()),
        "initial_candidates",
    )
    return {
        "overall_task": request.state.get("overall_task"),
        "candidate_index": len(candidates),
        "candidate_count": FLOW_FIDELITY.candidate_graphs,
        "workflow_graph": FLOW_FIDELITY.workflow_graph,
        "required_task_fields": FLOW_FIDELITY.task_fields,
        "instruction": (
            "Generate one modular Activity-on-Vertex workflow. Minimize unnecessary "
            "dependencies, maximize useful independent subtasks, and assign a role "
            "to every subtask. Return a workflow object keyed by task id."
        ),
    }


def _record_initial_candidate(request: MethodNodeRequest) -> MethodNodeResult:
    candidates = list(
        _sequence(
            request.state.get("initial_candidates", ()),
            "initial_candidates",
        )
    )
    candidate = normalize_flow_workflow(request.previous_value)
    candidates.append(candidate)
    complete = len(candidates) >= FLOW_FIDELITY.candidate_graphs
    return MethodNodeResult(
        value={
            "candidate_index": len(candidates) - 1,
            "candidate_count": len(candidates),
        },
        state_update={"initial_candidates": tuple(candidates)},
        next_node="select_initial" if complete else "initial_workflow",
    )


def _select_initial(request: MethodNodeRequest) -> MethodNodeResult:
    candidates = _sequence(
        request.state.get("initial_candidates", ()),
        "initial_candidates",
    )
    if len(candidates) != FLOW_FIDELITY.candidate_graphs:
        raise ValueError("Flow initial candidate cardinality drifted")
    normalized = tuple(normalize_flow_workflow(row) for row in candidates)
    index, scores = flow_select_candidate(normalized)
    selected = normalized[index]
    return MethodNodeResult(
        value={
            "selected_index": index,
            "scores": scores,
            "task_count": len(selected),
        },
        state_update={
            "workflow": selected,
            "candidate_scores": scores,
            "candidate_selected_index": index,
        },
        next_node="route",
        checkpoint=True,
        checkpoint_value={
            "phase": "initial-workflow-selected",
            "selected_index": index,
            "scores": scores,
        },
    )


def _terminal_failure(workflow: Mapping[str, JsonValue]) -> bool:
    return any(
        raw["status"] == "failed"
        and int(raw.get("validation_attempts", 0))
        >= FLOW_FIDELITY.max_validation_iterations
        for raw in workflow.values()
    )


def _route(request: MethodNodeRequest) -> MethodNodeResult:
    workflow = normalize_flow_workflow(request.state.get("workflow", {}))
    if flow_all_completed(workflow):
        return MethodNodeResult(
            value={"completed": True},
            next_node="summary",
        )

    refinements = request.state.get("refinement_count", 0)
    completed_since = request.state.get("completed_since_refine", 0)
    if type(refinements) is not int or refinements < 0:
        raise ValueError("Flow refinement_count must be non-negative")
    if type(completed_since) is not int or completed_since < 0:
        raise ValueError("Flow completed_since_refine must be non-negative")

    terminal_failure = _terminal_failure(workflow)
    should_refine = (
        completed_since >= FLOW_FIDELITY.refine_threshold
        or terminal_failure
    )
    if should_refine and refinements < FLOW_FIDELITY.max_refine_iterations:
        return MethodNodeResult(
            value={
                "refinement_requested": True,
                "completed_since_refine": completed_since,
                "refinement_count": refinements,
            },
            next_node="refine",
        )
    if terminal_failure and refinements >= FLOW_FIDELITY.max_refine_iterations:
        return MethodNodeResult(
            value={
                "completed": False,
                "terminal_validation_failure": True,
                "refinement_budget_exhausted": True,
            },
            state_update={"terminated_with_incomplete_tasks": True},
            next_node="summary",
        )

    ready = flow_ready_task_ids(workflow)
    if not ready:
        return MethodNodeResult(
            value={
                "completed": False,
                "stalled": True,
                "refinement_budget_exhausted": (
                    refinements >= FLOW_FIDELITY.max_refine_iterations
                ),
            },
            state_update={"terminated_with_incomplete_tasks": True},
            next_node="summary",
        )

    return MethodNodeResult(
        value={
            "ready_task_ids": ready,
            "paper_semantics": "execute-ready-set-concurrently",
            "execution_projection": "child-research-machine-batch",
        },
        state_update={
            "pending_ready_task_ids": ready,
        },
        next_node="execute_ready_set",
    )


def _execute_ready_set(request: MethodNodeRequest) -> MethodNodeResult:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError(
            "Flow concurrent ready-set execution requires child ResearchMachines"
        )
    if not isinstance(request.child_machines, ChildResearchMachineBatchPort):
        raise RuntimeError(
            "Flow requires a batch-capable child ResearchMachine executor"
        )

    workflow = normalize_flow_workflow(request.state.get("workflow", {}))
    ready = tuple(
        _text(row, "ready task id")
        for row in _sequence(
            request.state.get("pending_ready_task_ids", ()),
            "pending_ready_task_ids",
        )
    )
    expected = flow_ready_task_ids(workflow)
    if ready != expected:
        raise ValueError("Flow ready-set identity drifted before batch execution")
    sequence = request.state.get("batch_sequence", 0)
    if type(sequence) is not int or sequence < 0:
        raise ValueError("Flow batch_sequence must be non-negative")
    workflow_digest = canonical_digest(workflow)
    selection_digest = canonical_digest({
        "schema": "flow.ready-set-selection.v1",
        "workflow_digest": workflow_digest,
        "ready_task_ids": ready,
        "batch_sequence": sequence,
    })

    items = []
    for task_id in ready:
        task = workflow[task_id]
        parent_context = tuple(
            {
                "task_id": parent,
                "objective": workflow[parent]["objective"],
                "data": workflow[parent]["data"],
            }
            for parent in task["prev"]
            if workflow[parent]["status"] == "completed"
        )
        initial_data = flow_subtask_initial_data(
            task_id=task_id,
            overall_task=_text(
                request.state.get("overall_task"),
                "overall_task",
            ),
            objective=_text(task["objective"], "task objective"),
            assigned_role=_text(task["agent"], "task agent"),
            output_format=_text(
                task["output_format"],
                "task output_format",
                allow_empty=True,
            ),
            parent_context=parent_context,
            history=tuple(task["history"]),
        )
        child_machine_id = (
            f"{request.parent_machine_id}:flow-subtask:{sequence}:{task_id}"
        )
        child_request = ChildResearchMachineRequest(
            host_id="flow.subtask",
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "paper": "Flow ICLR 2025",
                "fidelity_digest": FLOW_FIDELITY.fidelity_digest,
                "workflow_digest": workflow_digest,
                "selection_digest": selection_digest,
                "batch_sequence": sequence,
                "task_id": task_id,
                "task_digest": canonical_digest(task),
            },
            initial_data=initial_data,
            failure_policy=ChildFailurePolicy.COLLECT,
            command_id_prefix=(
                f"{request.parent_machine_id}:flow:{sequence}:{task_id}"
            ),
        )
        items.append(
            ChildResearchMachineBatchItem(
                participant_id=f"{task['agent_id']}::{task_id}",
                request=child_request,
            )
        )

    batch_request = ChildResearchMachineBatchRequest(
        batch_id=f"flow-ready-set:{sequence}",
        parent_machine_id=request.parent_machine_id,
        selection_digest=selection_digest,
        items=tuple(items),
        require_concurrent=True,
    )
    batch = request.child_machines.execute_batch(batch_request)

    updated = dict(thaw_json(workflow))
    completed = 0
    executions = 0
    for task_id, child in zip(ready, batch.executions, strict=True):
        result = _mapping(child.result, f"subtask result {task_id}")
        row = dict(updated[task_id])
        attempts = result.get("validation_attempts", 0)
        if type(attempts) is not int or attempts < 1:
            raise ValueError("Flow child validation_attempts must be positive")
        executions += attempts
        valid = result.get("valid") is True and child.status.value == "completed"
        row["validation_attempts"] = attempts
        row["history"] = result.get("history", row.get("history", ()))
        if valid:
            row["status"] = "completed"
            row["data"] = result.get("result")
            completed += 1
        else:
            row["status"] = "failed"
            row["data"] = None
        updated[task_id] = row

    updated_workflow = normalize_flow_workflow(updated)
    completed_since = request.state.get("completed_since_refine", 0)
    total_executions = request.state.get("total_task_executions", 0)
    if type(completed_since) is not int or completed_since < 0:
        raise ValueError("Flow completed_since_refine must be non-negative")
    if type(total_executions) is not int or total_executions < 0:
        raise ValueError("Flow total_task_executions must be non-negative")
    batch_rows = tuple(
        _sequence(
            request.state.get("ready_set_batches", ()),
            "ready_set_batches",
        )
    ) + ({
        "batch_sequence": sequence,
        "ready_set": ready,
        "selection_digest": selection_digest,
        "batch_request_digest": batch_request.request_digest,
        "batch_execution_digest": batch.execution_digest,
        "mode": batch.mode.value,
        "mechanics_evidence_digests": batch.evidence_digests,
        "child_machine_ids": tuple(
            row.child_machine_id for row in batch.links
        ),
    },)
    return MethodNodeResult(
        value={
            "ready_task_ids": ready,
            "completed_count": completed,
            "batch_execution_digest": batch.execution_digest,
            "mode": batch.mode.value,
        },
        state_update={
            "workflow": updated_workflow,
            "pending_ready_task_ids": (),
            "batch_sequence": sequence + 1,
            "completed_since_refine": completed_since + completed,
            "total_task_executions": total_executions + executions,
            "ready_set_batches": batch_rows,
        },
        next_node="route",
        checkpoint=True,
        checkpoint_value={
            "phase": "ready-set-batch-complete",
            "batch_sequence": sequence,
            "selection_digest": selection_digest,
            "batch_execution_digest": batch.execution_digest,
        },
        child_links=batch.links,
        events=(
            MethodEvent(
                "flow.ready-set.batch",
                {
                    "batch_sequence": sequence,
                    "ready_task_ids": ready,
                    "selection_digest": selection_digest,
                    "batch_execution_digest": batch.execution_digest,
                    "mode": batch.mode.value,
                    "mechanics_evidence_digests": batch.evidence_digests,
                },
            ),
        ),
    )


def _task_view(request: MethodNodeRequest) -> JsonObject:
    workflow = normalize_flow_workflow(request.state.get("workflow", {}))
    task_id = _text(request.state.get("current_task_id"), "current_task_id")
    task = workflow.get(task_id)
    if not isinstance(task, Mapping):
        raise KeyError(task_id)
    context = tuple(
        {
            "task_id": parent,
            "objective": workflow[parent]["objective"],
            "data": workflow[parent]["data"],
        }
        for parent in task["prev"]
        if workflow[parent]["status"] == "completed"
    )
    return {
        "overall_task": request.state.get("overall_task"),
        "task_id": task_id,
        "objective": task["objective"],
        "assigned_role": task["agent"],
        "output_format": task["output_format"],
        "completed_parent_context": context,
        "history": task["history"],
        "instruction": (
            "Execute this subtask as the assigned role. Return the concrete result "
            "needed by downstream subtasks."
        ),
    }


def _record_task_result(request: MethodNodeRequest) -> MethodNodeResult:
    count = request.state.get("total_task_executions", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Flow total_task_executions must be non-negative")
    return MethodNodeResult(
        value={"task_executed": request.state.get("current_task_id")},
        state_update={
            "pending_task_result": freeze_json(request.previous_value),
            "total_task_executions": count + 1,
        },
        next_node="validate",
    )


def _validation_view(request: MethodNodeRequest) -> JsonObject:
    workflow = normalize_flow_workflow(request.state.get("workflow", {}))
    task_id = _text(request.state.get("current_task_id"), "current_task_id")
    task = workflow.get(task_id)
    if not isinstance(task, Mapping):
        raise KeyError(task_id)
    return {
        "overall_task": request.state.get("overall_task"),
        "task_id": task_id,
        "objective": task["objective"],
        "result": request.state.get("pending_task_result"),
        "previous_history": task["history"],
        "validation_attempt": int(task.get("validation_attempts", 0)) + 1,
        "max_validation_iterations": FLOW_FIDELITY.max_validation_iterations,
        "instruction": (
            "Determine whether all requirements of this subtask are fulfilled. "
            "Return {valid: bool, feedback: text}."
        ),
    }


def _validation_result(value: JsonValue) -> tuple[bool, str]:
    if not isinstance(value, Mapping):
        raise TypeError("Flow validator output must be an object")
    valid = value.get("valid")
    if type(valid) is not bool:
        raise TypeError("Flow validator valid must be boolean")
    feedback = value.get("feedback", "")
    return valid, _text(str(feedback), "validation feedback", allow_empty=True)


def _record_validation(request: MethodNodeRequest) -> MethodNodeResult:
    workflow = dict(
        thaw_json(
            normalize_flow_workflow(request.state.get("workflow", {}))
        )
    )
    task_id = _text(request.state.get("current_task_id"), "current_task_id")
    task = workflow.get(task_id)
    if not isinstance(task, dict):
        raise KeyError(task_id)
    valid, feedback = _validation_result(request.previous_value)
    attempts = int(task.get("validation_attempts", 0)) + 1
    history = list(task.get("history", ()))
    history.append({
        "attempt": attempts,
        "result": thaw_json(request.state.get("pending_task_result")),
        "feedback": feedback,
        "valid": valid,
    })
    task["validation_attempts"] = attempts
    task["history"] = tuple(history)
    if valid:
        task["status"] = "completed"
        task["data"] = thaw_json(request.state.get("pending_task_result"))
    else:
        task["status"] = "failed"
        task["data"] = None
    workflow[task_id] = task
    workflow = normalize_flow_workflow(workflow)

    completed_since = request.state.get("completed_since_refine", 0)
    if type(completed_since) is not int or completed_since < 0:
        raise ValueError("Flow completed_since_refine must be non-negative")
    if valid:
        completed_since += 1

    return MethodNodeResult(
        value={
            "task_id": task_id,
            "valid": valid,
            "validation_attempt": attempts,
            "feedback": feedback,
        },
        state_update={
            "workflow": workflow,
            "pending_task_result": None,
            "completed_since_refine": completed_since,
        },
        next_node="route",
        checkpoint=True,
        checkpoint_value={
            "task_id": task_id,
            "valid": valid,
            "validation_attempt": attempts,
            "completed_since_refine": completed_since,
        },
    )


def _refine_view(request: MethodNodeRequest) -> JsonObject:
    workflow = normalize_flow_workflow(request.state.get("workflow", {}))
    return {
        "final_goal": request.state.get("overall_task"),
        "workflow": workflow,
        "refinement_count": request.state.get("refinement_count", 0),
        "completed_since_refine": request.state.get("completed_since_refine", 0),
        "instruction": (
            "Review completed task outputs and the whole AOV. Remove redundant "
            "tasks, add missing tasks, clarify objectives, reassign roles, and "
            "reorganize dependencies to improve parallel execution. Return an "
            "updated workflow object, or an empty object when no change is needed."
        ),
    }


def _record_refinement(request: MethodNodeRequest) -> MethodNodeResult:
    current = normalize_flow_workflow(request.state.get("workflow", {}))
    raw = request.previous_value
    if not isinstance(raw, Mapping):
        raise TypeError("Flow refinement output must be an object")
    decoded = thaw_json(raw)
    if not decoded:
        updated = current
        changed = False
    else:
        proposed = decoded.get("workflow", decoded)
        if not isinstance(proposed, Mapping) or not proposed:
            raise ValueError("Flow refinement workflow must be a non-empty object")
        updated = flow_merge_refinement(current, proposed)
        changed = canonical_digest(updated) != canonical_digest(current)

    count = request.state.get("refinement_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Flow refinement_count must be non-negative")
    count += 1
    return MethodNodeResult(
        value={
            "refinement_count": count,
            "changed": changed,
            "task_count": len(updated),
        },
        state_update={
            "workflow": updated,
            "refinement_count": count,
            "completed_since_refine": 0,
            "current_task_id": "",
        },
        next_node="route",
        checkpoint=True,
        checkpoint_value={
            "phase": "workflow-refinement",
            "refinement_count": count,
            "workflow_digest": canonical_digest(updated),
        },
    )


def _summary_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "overall_task": request.state.get("overall_task"),
        "workflow": normalize_flow_workflow(request.state.get("workflow", {})),
        "terminated_with_incomplete_tasks": (
            request.state.get("terminated_with_incomplete_tasks") is True
        ),
        "instruction": (
            "Synthesize the final deliverable from completed subtask outputs. "
            "Do not hide incomplete or failed subtasks."
        ),
    }


def _record_summary(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        summary = value
    elif isinstance(value, Mapping):
        summary = value.get("summary", value.get("text", ""))
    else:
        raise TypeError("Flow summary output must be text or object")
    summary = _text(summary, "summary")
    return MethodNodeResult(
        value={"summary": summary},
        state_update={"summary": summary},
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    workflow = normalize_flow_workflow(request.state.get("workflow", {}))
    completed = tuple(
        task_id
        for task_id, row in workflow.items()
        if row["status"] == "completed"
    )
    incomplete = tuple(
        task_id
        for task_id, row in workflow.items()
        if row["status"] != "completed"
    )
    return MethodNodeResult(
        value={
            "summary": request.state.get("summary", ""),
            "completed_task_ids": completed,
            "incomplete_task_ids": incomplete,
            "task_success": not incomplete,
            "refinement_count": request.state.get("refinement_count", 0),
            "task_execution_count": request.state.get("total_task_executions", 0),
            "initial_candidate_scores": request.state.get("candidate_scores", ()),
            "initial_candidate_selected_index": request.state.get(
                "candidate_selected_index",
                -1,
            ),
            "ready_set_batches": request.state.get(
                "ready_set_batches",
                (),
            ),
        }
    )


def build_flow_method_program() -> MethodProgram:
    fidelity = FLOW_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "workflow_graph": fidelity.workflow_graph,
        "candidate_graphs": fidelity.candidate_graphs,
        "initial_candidate_selection": fidelity.initial_candidate_selection,
        "refine_threshold": fidelity.refine_threshold,
        "max_refine_iterations": fidelity.max_refine_iterations,
        "max_validation_iterations": fidelity.max_validation_iterations,
        "paper_ready_set_execution": "concurrent",
        "current_execution_projection": "child_research_machine_batch",
        "batch_execution_contract": "noetrium.child-research-machine-batch-request.v1",
        "refinement_strategy": "wait-for-active-batch-then-update",
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="flow-modularized-agentic-workflow",
            implementation_version=fidelity.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="flow.iclr2025.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="initial_workflow")
    builder.agent(
        "initial_workflow",
        "flow.workflow.generate-candidate",
        _INITIAL_WORKFLOW_AGENT,
        ("record_initial_candidate",),
        view_handler=_initial_view,
        max_visits=fidelity.candidate_graphs,
    )
    builder.route(
        "record_initial_candidate",
        "flow.workflow.record-candidate",
        _record_initial_candidate,
        ("initial_workflow", "select_initial"),
        max_visits=fidelity.candidate_graphs,
    )
    builder.compute(
        "select_initial",
        "flow.workflow.select-initial",
        _select_initial,
        ("route",),
    )
    builder.route(
        "route",
        "flow.workflow.route",
        _route,
        ("execute_ready_set", "refine", "summary"),
        max_visits=512,
    )
    builder.compute(
        "execute_ready_set",
        "flow.ready-set.execute-batch",
        _execute_ready_set,
        ("route",),
        max_visits=256,
        evidence_obligations=(
            "flow.ready-set-selection",
            "flow.concurrent-batch-evidence",
            "flow.child-machine-cuts",
        ),
    )
    builder.agent(
        "refine",
        "flow.workflow.refine",
        _REFINER_AGENT,
        ("record_refinement",),
        view_handler=_refine_view,
        max_visits=fidelity.max_refine_iterations,
    )
    builder.compute(
        "record_refinement",
        "flow.workflow.refinement-record",
        _record_refinement,
        ("route",),
        max_visits=fidelity.max_refine_iterations,
    )
    builder.agent(
        "summary",
        "flow.summary",
        _SUMMARY_AGENT,
        ("record_summary",),
        view_handler=_summary_view,
    )
    builder.compute(
        "record_summary",
        "flow.summary.record",
        _record_summary,
        ("return",),
    )
    builder.return_node("return", "flow.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.CHECKPOINTABLE,
        evidence_obligations=(
            "flow.initial-workflow-candidates",
            "flow.workflow-selection-metrics",
            "flow.ready-set-selection",
            "flow.concurrent-batch-evidence",
            "flow.child-machine-cuts",
            "flow.subtask-history",
            "flow.validation",
            "flow.workflow-refinement",
            "flow.final-summary",
        ),
        metric_names=(
            "task_success",
            "human_rating",
            "subtask_count",
            "refinement_count",
            "task_execution_count",
        ),
        artifact_kinds=(
            "flow_initial_workflows",
            "flow_workflow_trace",
            "flow_final_output",
        ),
    )


FLOW_METHOD_PROGRAM = build_flow_method_program()

__all__ = [
    "FLOW_METHOD_PROGRAM",
    "build_flow_method_program",
    "flow_initial_state",
]
