from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
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
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchMachineExecution,
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

from .fidelity import OPTIMUS1_REFERENCE_FIDELITY
from .memory import (
    OPTIMUS1_MEMORY_PROGRAM,
    optimus1_memory_initial_data,
)
from .source import OPTIMUS1_PAPER_ERA_COMMIT


_RETRIEVAL_AGENT_ID = "optimus1.retrieval"
_PLANNER_AGENT_ID = "optimus1.planner"
_REFLECTOR_AGENT_ID = "optimus1.reflector"
_ENVIRONMENT_CAPABILITY = "environment.act"
_MEMORY_HOST_ID = "optimus1.hybrid-multimodal-memory"
_REFLECTION_INTERVAL_STEPS = 1200


def _text(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    result = value.strip()
    if not result and not allow_empty:
        raise ValueError(f"{field_name} must be non-empty")
    return result


def _object(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _sequence(value: object, field_name: str) -> tuple[JsonValue, ...]:
    decoded = thaw_json(value)
    if isinstance(decoded, (str, bytes, bytearray)) or not isinstance(
        decoded,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(decoded)


def _plan_rows(value: object, field_name: str) -> tuple[JsonObject, ...]:
    rows = _sequence(value, field_name)
    result: list[JsonObject] = []
    for row in rows:
        item = _object(row, field_name)
        _text(item.get("task"), f"{field_name} task")
        goal = item.get("goal")
        if isinstance(goal, (str, bytes, bytearray)) or not isinstance(
            goal,
            Sequence,
        ):
            raise TypeError(f"{field_name} goal must be a sequence")
        if not tuple(goal):
            raise ValueError(f"{field_name} goal must not be empty")
        result.append(item)
    return tuple(result)


def optimus1_method_initial_state(
    *,
    task_id: str,
    task: str,
    initial_observation: JsonObject | None = None,
    max_environment_steps: int = 24000,
) -> JsonObject:
    if type(max_environment_steps) is not int or max_environment_steps < 1:
        raise ValueError("Optimus-1 max_environment_steps must be positive")
    return {
        "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
        "task_id": _text(task_id, "Optimus-1 task_id"),
        "task": _text(task, "Optimus-1 task"),
        "observation": (
            {}
            if initial_observation is None
            else dict(initial_observation)
        ),
        "goal": "",
        "visual_info": "",
        "environment": "none",
        "plan": (),
        "plan_index": 0,
        "current_plan": None,
        "memory_example": None,
        "craft_graph": "",
        "environment_steps": 0,
        "max_environment_steps": max_environment_steps,
        "task_success": False,
        "game_over": False,
        "outcome": None,
        "trajectory": (),
        "replan_count": 0,
        "reflection_count": 0,
        "last_execution": {},
        "last_error_info": "",
        "last_missing_materials": {},
        "before_artifact_ref": "",
        "after_artifact_ref": "",
        "video_artifact_ref": None,
        "memory_plan_digest": None,
        "memory_write_digest": None,
    }


def _retrieval_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "goal-and-visual-retrieval",
        "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
        "task": request.state.get("task"),
        "observation": request.state.get("observation", {}),
        "required_output": {
            "goal": "text",
            "visual_info": "text",
            "environment": "text",
        },
    }


def _record_retrieval(request: MethodNodeRequest) -> MethodNodeResult:
    value = _object(
        request.previous_value,
        "Optimus-1 retrieval result",
    )
    goal = _text(value.get("goal"), "Optimus-1 inferred goal")
    visual = _text(
        value.get("visual_info", ""),
        "Optimus-1 visual info",
        allow_empty=True,
    )
    environment = _text(
        value.get("environment", "none"),
        "Optimus-1 environment",
    )
    return MethodNodeResult(
        value={
            "goal": goal,
            "visual_info": visual,
            "environment": environment,
        },
        state_update={
            "goal": goal,
            "visual_info": visual,
            "environment": environment,
        },
        next_node="load_memory",
    )


def _require_child(request: MethodNodeRequest) -> None:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError(
            "Optimus-1 requires journal-backed child MemoryMachine execution"
        )


def _memory_step(
    request: MethodNodeRequest,
    *,
    kind: str,
    payload: JsonObject,
    suffix: str,
) -> ChildResearchMachineExecution:
    _require_child(request)
    child_machine_id = (
        f"{request.parent_machine_id}:optimus1-hybrid-memory"
    )
    child = request.child_machines.step_once(
        ChildResearchMachineRequest(
            host_id=_MEMORY_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
                "program_digest": OPTIMUS1_MEMORY_PROGRAM.program_digest,
                "child_registry_identity_digest": (
                    request.child_machines.identity_digest
                ),
            },
            initial_data=optimus1_memory_initial_data(),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload={
                "event": {
                    "kind": kind,
                    "payload": payload,
                    "source": "optimus1-method",
                }
            },
            command_id_prefix=(
                f"{child_machine_id}:{suffix}:"
                f"{request.node_id}:{request.visit}"
            ),
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError(
            "Optimus-1 child MemoryMachine returned invalid execution"
        )
    if child.status.value != "runnable":
        raise RuntimeError(
            "Optimus-1 child MemoryMachine stopped unexpectedly: "
            f"{child.status.value}"
        )
    if not isinstance(child.result, Mapping):
        raise TypeError(
            "Optimus-1 child MemoryMachine result must be an object"
        )
    return child


def _child_result(
    child: ChildResearchMachineExecution,
) -> JsonObject:
    return _object(child.result, "Optimus-1 memory result")


def _load_memory(request: MethodNodeRequest) -> MethodNodeResult:
    task = _text(request.state.get("task"), "Optimus-1 task")
    goal = _text(request.state.get("goal"), "Optimus-1 goal")
    plan_child = _memory_step(
        request,
        kind="optimus1.memory.retrieve-plan",
        payload={"task": task},
        suffix="plan-retrieval",
    )
    graph_child = _memory_step(
        request,
        kind="optimus1.memory.retrieve-graph",
        payload={"goal": goal, "number": 1},
        suffix="graph-retrieval",
    )
    plan_result = _child_result(plan_child)
    graph_result = _child_result(graph_child)
    record = plan_result.get("record")
    exact = plan_result.get("has_done") is True
    exact_plan: tuple[JsonObject, ...] = ()
    if exact and isinstance(record, Mapping):
        exact_plan = _plan_rows(
            record.get("planning", ()),
            "Optimus-1 exact memory plan",
        )
    graph = _text(
        graph_result.get("graph", ""),
        "Optimus-1 craft graph",
        allow_empty=True,
    )
    return MethodNodeResult(
        value={
            "plan_found": plan_result.get("found") is True,
            "exact_plan": exact,
            "graph": graph,
        },
        state_update={
            "memory_example": (
                None if not isinstance(record, Mapping) else dict(record)
            ),
            "craft_graph": graph,
            "plan": exact_plan,
            "plan_index": 0,
            "memory_plan_digest": (
                None
                if not isinstance(record, Mapping)
                else record.get("record_digest")
            ),
        },
        next_node="route_plan_source",
        child_links=(plan_child.link, graph_child.link),
        events=(
            MethodEvent(
                "optimus1.memory.loaded",
                {
                    "plan_found": plan_result.get("found") is True,
                    "exact_plan": exact,
                    "graph_empty": not bool(graph),
                },
            ),
        ),
    )


def _route_plan_source(request: MethodNodeRequest) -> MethodNodeResult:
    plan = _plan_rows(
        request.state.get("plan", ()),
        "Optimus-1 plan",
    )
    return MethodNodeResult(
        value={"reused_exact_plan": bool(plan)},
        next_node="select_subgoal" if plan else "planner",
    )


def _planner_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "knowledge-guided-planning",
        "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
        "task": request.state.get("task"),
        "observation": request.state.get("observation", {}),
        "visual_info": request.state.get("visual_info", ""),
        "environment": request.state.get("environment", "none"),
        "craft_graph": request.state.get("craft_graph", ""),
        "memory_example": request.state.get("memory_example"),
        "required_output": {
            "planning": (
                "ordered sequence of {task: text, goal: [item, number]}"
            ),
        },
    }


def _record_plan(request: MethodNodeRequest) -> MethodNodeResult:
    value = _object(
        request.previous_value,
        "Optimus-1 planner result",
    )
    plan = _plan_rows(
        value.get("planning", ()),
        "Optimus-1 planner output",
    )
    if not plan:
        raise ValueError("Optimus-1 planner returned an empty plan")
    return MethodNodeResult(
        value={"plan_step_count": len(plan)},
        state_update={
            "plan": plan,
            "plan_index": 0,
            "current_plan": None,
        },
        next_node="select_subgoal",
        events=(
            MethodEvent(
                "optimus1.plan.generated",
                {
                    "plan_step_count": len(plan),
                    "plan_digest": canonical_digest(plan),
                },
            ),
        ),
    )


def _operation(task: str) -> str:
    token = task.strip().lower().split(" ", 1)[0]
    if "create" in task.lower():
        return "craft"
    if "smelt" in task.lower():
        return "smelt"
    return token


def _select_subgoal(request: MethodNodeRequest) -> MethodNodeResult:
    plan = _plan_rows(
        request.state.get("plan", ()),
        "Optimus-1 plan",
    )
    index = request.state.get("plan_index", 0)
    if type(index) is not int or index < 0:
        raise ValueError("Optimus-1 plan_index is invalid")
    if request.state.get("game_over") is True:
        return MethodNodeResult(
            value={"outcome": "failed", "reason": "game_over"},
            state_update={"outcome": "failed"},
            next_node="persist_plan",
        )
    if request.state.get("task_success") is True or index >= len(plan):
        return MethodNodeResult(
            value={"outcome": "success", "plan_index": index},
            state_update={
                "outcome": "success",
                "task_success": True,
            },
            next_node="persist_plan",
        )
    current = plan[index]
    task = _text(
        current.get("task"),
        "Optimus-1 current subgoal task",
    )
    op = _operation(task)
    helper_mode = op in {"craft", "smelt", "equip"}
    return MethodNodeResult(
        value={
            "plan_index": index,
            "task": task,
            "goal": current.get("goal"),
            "controller_mode": "helper" if helper_mode else "steve1",
        },
        state_update={"current_plan": current},
        next_node=(
            "prepare_helper" if helper_mode else "prepare_controller"
        ),
    )


def _controller_envelope(
    request: MethodNodeRequest,
    *,
    mode: str,
) -> JsonObject:
    current = _object(
        request.state.get("current_plan"),
        "Optimus-1 current plan",
    )
    return environment_action_capability_payload(
        (
            "optimus1.helper-subgoal"
            if mode == "helper"
            else "optimus1.steve1-subgoal"
        ),
        {
            "mode": mode,
            "task_id": request.state.get("task_id"),
            "task": current.get("task"),
            "goal": current.get("goal"),
            "observation": request.state.get("observation", {}),
            "environment_steps": request.state.get(
                "environment_steps",
                0,
            ),
            "controller_checkpoint": (
                OPTIMUS1_REFERENCE_FIDELITY
                .official_release_controller_checkpoint
            ),
        },
    )


def _prepare_helper(request: MethodNodeRequest) -> MethodNodeResult:
    envelope = _controller_envelope(request, mode="helper")
    return MethodNodeResult(value=envelope, state_update=envelope)


def _prepare_controller(request: MethodNodeRequest) -> MethodNodeResult:
    envelope = _controller_envelope(request, mode="steve1")
    return MethodNodeResult(value=envelope, state_update=envelope)


def _execution_result(value: JsonValue) -> JsonObject:
    result = _object(value, "Optimus-1 environment result")
    observation = result.get("observation")
    if isinstance(observation, Mapping):
        payload = observation.get("payload")
        if isinstance(payload, Mapping):
            execution = payload.get("optimus1_controller")
            if isinstance(execution, Mapping):
                return _object(
                    execution,
                    "Optimus-1 controller execution",
                )
    nested = result.get("optimus1_controller")
    if isinstance(nested, Mapping):
        return _object(
            nested,
            "Optimus-1 controller execution",
        )
    return result


def _trajectory(
    request: MethodNodeRequest,
    execution: Mapping[str, JsonValue],
    *,
    mode: str,
    total_steps: int,
) -> tuple[JsonObject, ...]:
    rows = [
        _object(row, "Optimus-1 trajectory")
        for row in _sequence(
            request.state.get("trajectory", ()),
            "Optimus-1 trajectory",
        )
    ]
    current = _object(
        request.state.get("current_plan"),
        "Optimus-1 current plan",
    )
    rows.append(
        {
            "plan_index": request.state.get("plan_index", 0),
            "task": current.get("task"),
            "goal": current.get("goal"),
            "controller_mode": mode,
            "environment_steps": execution.get("environment_steps", 1),
            "total_environment_steps": total_steps,
            "subgoal_success": execution.get(
                "subgoal_success",
                execution.get("current_task_finish", False),
            ),
            "task_success": execution.get("task_success", False),
            "game_over": execution.get("game_over", False),
            "error_info": execution.get("error_info", ""),
            "provider_receipt": execution.get("provider_receipt"),
        }
    )
    return tuple(rows)


def _record_execution(
    request: MethodNodeRequest,
    *,
    mode: str,
) -> MethodNodeResult:
    execution = _execution_result(request.previous_value)
    consumed = request.state.get("environment_steps", 0)
    if type(consumed) is not int or consumed < 0:
        raise ValueError("Optimus-1 environment_steps state is invalid")
    delta = execution.get("environment_steps", execution.get("steps", 1))
    if type(delta) is not int or delta < 1:
        raise ValueError(
            "Optimus-1 controller environment_steps must be positive"
        )
    total = consumed + delta
    limit = request.state.get("max_environment_steps")
    if type(limit) is not int or limit < 1:
        raise ValueError(
            "Optimus-1 max_environment_steps state is invalid"
        )
    subgoal_success = execution.get(
        "subgoal_success",
        execution.get("current_task_finish", False),
    )
    task_success = execution.get("task_success", False)
    game_over = execution.get("game_over", False)
    if any(
        type(value) is not bool
        for value in (subgoal_success, task_success, game_over)
    ):
        raise TypeError("Optimus-1 execution flags must be booleans")
    if total >= limit:
        game_over = True
    error_info = _text(
        execution.get("error_info", ""),
        "Optimus-1 error_info",
        allow_empty=True,
    )
    if mode == "helper" and "time" in error_info.lower():
        game_over = True
    observation = execution.get(
        "observation",
        request.state.get("observation", {}),
    )
    if not isinstance(observation, Mapping):
        raise TypeError("Optimus-1 observation must be an object")
    missing = execution.get("missing_materials", {})
    if not isinstance(missing, Mapping):
        missing = {}
    before_ref = execution.get("before_artifact_ref", "")
    after_ref = execution.get("after_artifact_ref", "")
    video_ref = execution.get(
        "video_artifact_ref",
        request.state.get("video_artifact_ref"),
    )
    before_ref = (
        ""
        if before_ref is None
        else _text(
            before_ref,
            "Optimus-1 before artifact ref",
            allow_empty=True,
        )
    )
    after_ref = (
        ""
        if after_ref is None
        else _text(
            after_ref,
            "Optimus-1 after artifact ref",
            allow_empty=True,
        )
    )
    prior_bucket = consumed // _REFLECTION_INTERVAL_STEPS
    current_bucket = total // _REFLECTION_INTERVAL_STEPS
    reflection_due = (
        mode == "steve1"
        and total > 0
        and current_bucket > prior_bucket
        and not subgoal_success
        and not task_success
        and not game_over
    )
    index = request.state.get("plan_index", 0)
    if type(index) is not int or index < 0:
        raise ValueError("Optimus-1 plan_index state is invalid")
    next_index = index + 1 if subgoal_success else index
    update: JsonObject = {
        "observation": dict(observation),
        "environment_steps": total,
        "plan_index": next_index,
        "task_success": task_success,
        "game_over": game_over,
        "last_execution": execution,
        "last_error_info": error_info,
        "last_missing_materials": dict(missing),
        "before_artifact_ref": before_ref,
        "after_artifact_ref": after_ref,
        "video_artifact_ref": video_ref,
        "trajectory": _trajectory(
            request,
            execution,
            mode=mode,
            total_steps=total,
        ),
    }
    if task_success or game_over:
        next_node = "persist_plan"
        update["outcome"] = "success" if task_success else "failed"
    elif subgoal_success:
        next_node = "select_subgoal"
    elif mode == "helper" and error_info:
        next_node = "prepare_replan_context"
    elif reflection_due:
        next_node = "prepare_reflection"
    else:
        next_node = (
            "prepare_helper" if mode == "helper" else "prepare_controller"
        )
    return MethodNodeResult(
        value={
            "controller_mode": mode,
            "subgoal_success": subgoal_success,
            "task_success": task_success,
            "game_over": game_over,
            "environment_steps": total,
            "reflection_due": reflection_due,
        },
        state_update=update,
        next_node=next_node,
        checkpoint=True,
        checkpoint_value={
            "plan_index": next_index,
            "environment_steps": total,
            "task_success": task_success,
            "game_over": game_over,
        },
    )


def _record_helper(request: MethodNodeRequest) -> MethodNodeResult:
    return _record_execution(request, mode="helper")


def _record_controller(request: MethodNodeRequest) -> MethodNodeResult:
    return _record_execution(request, mode="steve1")


def _prepare_reflection(request: MethodNodeRequest) -> MethodNodeResult:
    current = _object(
        request.state.get("current_plan"),
        "Optimus-1 current plan",
    )
    child = _memory_step(
        request,
        kind="optimus1.memory.retrieve-reflection",
        payload={
            "task": current.get("task"),
            "environment": request.state.get("environment", "none"),
        },
        suffix="reflection-retrieval",
    )
    result = _child_result(child)
    return MethodNodeResult(
        value=result,
        state_update={"reflection_examples": result},
        next_node="reflector",
        child_links=(child.link,),
    )


def _reflector_view(request: MethodNodeRequest) -> JsonObject:
    current = _object(
        request.state.get("current_plan"),
        "Optimus-1 current plan",
    )
    return {
        "phase": "experience-driven-reflection",
        "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
        "task": current.get("task"),
        "goal": current.get("goal"),
        "environment": request.state.get("environment", "none"),
        "observation": request.state.get("observation", {}),
        "environment_steps": request.state.get("environment_steps", 0),
        "examples": request.state.get("reflection_examples", {}),
        "required_output": {
            "category": ("done", "continue", "replan"),
            "environment": "text",
        },
        "released_control_semantics": (
            "record-reflection-without-control-branch"
        ),
    }


def _record_reflection(request: MethodNodeRequest) -> MethodNodeResult:
    value = _object(
        request.previous_value,
        "Optimus-1 reflection result",
    )
    category = _text(
        value.get("category"),
        "Optimus-1 reflection category",
    )
    if category not in (
        OPTIMUS1_REFERENCE_FIDELITY.amep_reflection_labels
    ):
        raise ValueError("Optimus-1 reflection category drifted")
    environment = _text(
        value.get(
            "environment",
            request.state.get("environment", "none"),
        ),
        "Optimus-1 reflection environment",
    )
    before_ref = _text(
        request.state.get("before_artifact_ref", ""),
        "Optimus-1 before artifact ref",
        allow_empty=True,
    )
    after_ref = _text(
        request.state.get("after_artifact_ref", ""),
        "Optimus-1 after artifact ref",
        allow_empty=True,
    )
    child_links = ()
    record_digest = None
    if before_ref and after_ref:
        current = _object(
            request.state.get("current_plan"),
            "Optimus-1 current plan",
        )
        child = _memory_step(
            request,
            kind="optimus1.memory.write-reflection",
            payload={
                "task": current.get("task"),
                "environment": environment,
                "category": category,
                "before_artifact_ref": before_ref,
                "after_artifact_ref": after_ref,
            },
            suffix="reflection-write",
        )
        child_links = (child.link,)
        record_digest = _child_result(child).get("record_digest")
    count = request.state.get("reflection_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Optimus-1 reflection_count is invalid")
    return MethodNodeResult(
        value={
            "category": category,
            "record_digest": record_digest,
            "control_effect": "none-in-paper-era-release",
        },
        state_update={
            "environment": environment,
            "reflection_count": count + 1,
        },
        next_node="prepare_controller",
        child_links=child_links,
        events=(
            MethodEvent(
                "optimus1.reflection.recorded",
                {
                    "category": category,
                    "control_effect": "none-in-paper-era-release",
                },
            ),
        ),
    )


def _prepare_replan_context(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    current = _object(
        request.state.get("current_plan"),
        "Optimus-1 current plan",
    )
    task = _text(
        current.get("task"),
        "Optimus-1 current task",
    )
    error_info = _text(
        request.state.get("last_error_info"),
        "Optimus-1 replan error",
    )
    example_child = _memory_step(
        request,
        kind="optimus1.memory.retrieve-replan",
        payload={"task": task, "error_info": error_info},
        suffix="replan-retrieval",
    )
    example = _child_result(example_child)
    materials = request.state.get("last_missing_materials", {})
    if not isinstance(materials, Mapping):
        materials = {}
    graph_parts: list[str] = []
    graph_links = []
    if materials:
        items = tuple(
            (str(item), int(number))
            for item, number in materials.items()
            if isinstance(number, int) and not isinstance(number, bool)
            and number > 0
        )
    else:
        goal = current.get("goal", ())
        goal_rows = _sequence(goal, "Optimus-1 current goal")
        items = (
            (str(goal_rows[0]), int(goal_rows[1]))
            if len(goal_rows) >= 2
            and isinstance(goal_rows[1], int)
            and not isinstance(goal_rows[1], bool)
            else (str(goal_rows[0]), 1)
        ,)
    for index, (item, number) in enumerate(items):
        graph_child = _memory_step(
            request,
            kind="optimus1.memory.retrieve-graph",
            payload={"goal": item, "number": number},
            suffix=f"replan-graph-{index}",
        )
        graph_result = _child_result(graph_child)
        graph_parts.append(
            _text(
                graph_result.get("graph", ""),
                "Optimus-1 replan graph",
                allow_empty=True,
            )
        )
        graph_links.append(graph_child.link)
    return MethodNodeResult(
        value={
            "error_info": error_info,
            "example": example,
            "graph_summary": "\n".join(
                part for part in graph_parts if part
            ),
        },
        state_update={
            "replan_example": example,
            "replan_graph_summary": "\n".join(
                part for part in graph_parts if part
            ),
        },
        next_node="replan",
        child_links=(example_child.link, *graph_links),
    )


def _replan_view(request: MethodNodeRequest) -> JsonObject:
    current = _object(
        request.state.get("current_plan"),
        "Optimus-1 current plan",
    )
    return {
        "phase": "failure-conditioned-replan",
        "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
        "task": current.get("task"),
        "error_info": request.state.get("last_error_info", ""),
        "observation": request.state.get("observation", {}),
        "memory_example": request.state.get("replan_example"),
        "craft_graph": request.state.get(
            "replan_graph_summary",
            "",
        ),
        "required_output": {
            "planning": (
                "ordered replacement sequence of "
                "{task: text, goal: [item, number]}"
            ),
        },
    }


def _record_replan(request: MethodNodeRequest) -> MethodNodeResult:
    value = _object(
        request.previous_value,
        "Optimus-1 replan result",
    )
    new_rows = list(
        _plan_rows(
            value.get("planning", ()),
            "Optimus-1 replan output",
        )
    )
    if not new_rows:
        raise ValueError("Optimus-1 replan returned no steps")
    plan = list(
        _plan_rows(
            request.state.get("plan", ()),
            "Optimus-1 plan",
        )
    )
    index = request.state.get("plan_index", 0)
    if type(index) is not int or not 0 <= index < len(plan):
        raise ValueError("Optimus-1 replan plan_index is invalid")
    current = plan[index]
    current_task = _text(
        current.get("task"),
        "Optimus-1 current task",
    )
    if _text(
        new_rows[-1].get("task"),
        "Optimus-1 replan final task",
    ) != current_task:
        new_rows.append(current)
    updated = (*plan[:index], *new_rows, *plan[index + 1 :])
    error_info = _text(
        request.state.get("last_error_info"),
        "Optimus-1 replan error",
    )
    child = _memory_step(
        request,
        kind="optimus1.memory.write-replan",
        payload={
            "task": current_task,
            "error_info": error_info,
            "planning": tuple(new_rows),
        },
        suffix="replan-write",
    )
    count = request.state.get("replan_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("Optimus-1 replan_count is invalid")
    return MethodNodeResult(
        value={
            "inserted_steps": len(new_rows),
            "plan_step_count": len(updated),
        },
        state_update={
            "plan": updated,
            "current_plan": None,
            "replan_count": count + 1,
        },
        next_node="select_subgoal",
        child_links=(child.link,),
        events=(
            MethodEvent(
                "optimus1.plan.replanned",
                {
                    "inserted_steps": len(new_rows),
                    "replan_count": count + 1,
                },
            ),
        ),
    )


def _persist_plan(request: MethodNodeRequest) -> MethodNodeResult:
    plan = _plan_rows(
        request.state.get("plan", ()),
        "Optimus-1 final plan",
    )
    status = (
        "success"
        if request.state.get("outcome") == "success"
        else "failed"
    )
    child = _memory_step(
        request,
        kind="optimus1.memory.write-plan",
        payload={
            "task": request.state.get("task"),
            "environment": request.state.get("environment", "none"),
            "visual_info": request.state.get("visual_info", ""),
            "goal": request.state.get("goal"),
            "planning": plan,
            "status": status,
            "steps": request.state.get("environment_steps", 0),
            "video_artifact_ref": request.state.get(
                "video_artifact_ref"
            ),
        },
        suffix="plan-write",
    )
    result = _child_result(child)
    return MethodNodeResult(
        value=result,
        state_update={
            "memory_write_digest": result.get("record_digest"),
        },
        next_node="return",
        child_links=(child.link,),
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    plan = _plan_rows(
        request.state.get("plan", ()),
        "Optimus-1 plan",
    )
    trajectory = tuple(
        _object(row, "Optimus-1 trajectory")
        for row in _sequence(
            request.state.get("trajectory", ()),
            "Optimus-1 trajectory",
        )
    )
    outcome = request.state.get("outcome")
    if outcome not in {"success", "failed"}:
        outcome = (
            "success"
            if request.state.get("task_success") is True
            else "failed"
        )
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "success": outcome == "success",
            "outcome": outcome,
            "environment_steps": request.state.get(
                "environment_steps",
                0,
            ),
            "completed_plan_steps": request.state.get(
                "plan_index",
                0,
            ),
            "plan_step_count": len(plan),
            "reflection_count": request.state.get(
                "reflection_count",
                0,
            ),
            "replan_count": request.state.get("replan_count", 0),
            "memory_program_digest": OPTIMUS1_MEMORY_PROGRAM.program_digest,
            "memory_plan_digest": request.state.get(
                "memory_plan_digest"
            ),
            "memory_write_digest": request.state.get(
                "memory_write_digest"
            ),
            "trajectory": trajectory,
        }
    )


def build_optimus1_method_program() -> MethodProgram:
    fidelity = OPTIMUS1_REFERENCE_FIDELITY
    configuration: JsonObject = {
        "source_commit": OPTIMUS1_PAPER_ERA_COMMIT,
        "memory_program_digest": OPTIMUS1_MEMORY_PROGRAM.program_digest,
        "hybrid_memory_components": ("HDKG", "AMEP"),
        "planner": "knowledge-guided",
        "reflector": "experience-driven",
        "action_controller": fidelity.action_controller,
        "reflection_interval_environment_steps": (
            _REFLECTION_INTERVAL_STEPS
        ),
        "reflection_labels": fidelity.amep_reflection_labels,
        "released_reflection_control": (
            "record-only; parsed replan_type is not consumed by main.py"
        ),
        "craft_smelt_equip_failure_replan": True,
        "final_plan_memory_write": True,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="optimus1-minecraft-agent",
            implementation_version=OPTIMUS1_PAPER_ERA_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="optimus1.minecraft.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="retrieval")
    builder.agent(
        "retrieval",
        "optimus1.goal-visual-retrieval",
        _RETRIEVAL_AGENT_ID,
        ("record_retrieval",),
        view_handler=_retrieval_view,
    )
    builder.compute(
        "record_retrieval",
        "optimus1.retrieval.record",
        _record_retrieval,
        ("load_memory",),
    )
    builder.compute(
        "load_memory",
        "optimus1.memory.load",
        _load_memory,
        ("route_plan_source",),
        evidence_obligations=("optimus1.memory.child-cuts",),
    )
    builder.route(
        "route_plan_source",
        "optimus1.plan.source",
        _route_plan_source,
        ("planner", "select_subgoal"),
    )
    builder.agent(
        "planner",
        "optimus1.planner.knowledge-guided",
        _PLANNER_AGENT_ID,
        ("record_plan",),
        view_handler=_planner_view,
        max_visits=256,
    )
    builder.compute(
        "record_plan",
        "optimus1.plan.record",
        _record_plan,
        ("select_subgoal",),
        max_visits=256,
    )
    builder.route(
        "select_subgoal",
        "optimus1.plan.select-subgoal",
        _select_subgoal,
        ("prepare_helper", "prepare_controller", "persist_plan"),
        max_visits=8192,
    )
    builder.compute(
        "prepare_helper",
        "optimus1.helper.prepare",
        _prepare_helper,
        ("execute_helper",),
        max_visits=8192,
    )
    builder.capability(
        "execute_helper",
        "optimus1.minecraft.helper-execute",
        _ENVIRONMENT_CAPABILITY,
        ("record_helper",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=8192,
        evidence_obligations=("environment.effect",),
    )
    builder.route(
        "record_helper",
        "optimus1.helper.record",
        _record_helper,
        (
            "prepare_helper",
            "select_subgoal",
            "prepare_replan_context",
            "persist_plan",
        ),
        max_visits=8192,
    )
    builder.compute(
        "prepare_controller",
        "optimus1.steve1.prepare",
        _prepare_controller,
        ("execute_controller",),
        max_visits=32768,
    )
    builder.capability(
        "execute_controller",
        "optimus1.minecraft.steve1-execute",
        _ENVIRONMENT_CAPABILITY,
        ("record_controller",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=32768,
        evidence_obligations=("environment.effect",),
    )
    builder.route(
        "record_controller",
        "optimus1.steve1.record",
        _record_controller,
        (
            "prepare_controller",
            "select_subgoal",
            "prepare_reflection",
            "persist_plan",
        ),
        max_visits=32768,
    )
    builder.compute(
        "prepare_reflection",
        "optimus1.memory.prepare-reflection",
        _prepare_reflection,
        ("reflector",),
        max_visits=64,
    )
    builder.agent(
        "reflector",
        "optimus1.reflector.experience-driven",
        _REFLECTOR_AGENT_ID,
        ("record_reflection",),
        view_handler=_reflector_view,
        max_visits=64,
    )
    builder.compute(
        "record_reflection",
        "optimus1.reflection.record",
        _record_reflection,
        ("prepare_controller",),
        max_visits=64,
    )
    builder.compute(
        "prepare_replan_context",
        "optimus1.replan.prepare",
        _prepare_replan_context,
        ("replan",),
        max_visits=256,
    )
    builder.agent(
        "replan",
        "optimus1.planner.failure-replan",
        _PLANNER_AGENT_ID,
        ("record_replan",),
        view_handler=_replan_view,
        max_visits=256,
    )
    builder.compute(
        "record_replan",
        "optimus1.replan.record",
        _record_replan,
        ("select_subgoal",),
        max_visits=256,
    )
    builder.compute(
        "persist_plan",
        "optimus1.memory.persist-plan",
        _persist_plan,
        ("return",),
        evidence_obligations=("optimus1.memory.child-cut",),
    )
    builder.return_node(
        "return",
        "optimus1.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "optimus1.memory.child-cuts",
            "optimus1.minecraft.trajectory",
            "optimus1.reflection.trajectory",
            "environment.effect",
        ),
        metric_names=(
            "task_success",
            "environment_steps",
            "reflection_count",
            "replan_count",
        ),
        artifact_kinds=(
            "optimus1_plan_memory",
            "optimus1_reflection_memory",
            "optimus1_replan_memory",
            "optimus1_minecraft_trajectory",
        ),
    )


OPTIMUS1_METHOD_PROGRAM = build_optimus1_method_program()


__all__ = [
    "OPTIMUS1_METHOD_PROGRAM",
    "build_optimus1_method_program",
    "optimus1_method_initial_state",
]
