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

from .fidelity import JARVIS1_REFERENCE_FIDELITY
from .memory import (
    JARVIS1_MEMORY_PROGRAM,
    jarvis1_memory_initial_data,
)
from .source import JARVIS1_PUBLIC_EXECUTABLE_COMMIT


_MEMORY_HOST_ID = "jarvis1.multimodal-memory"
_CONTROLLER_CAPABILITY = "jarvis1.controller.execute"

_PUBLIC_MEMORY_MODE = "public-fixed-memory"
_PAPER_MULTIMODAL_MODE = "paper-semantic-multimodal"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _object(value: object, field_name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _rows(value: object, field_name: str) -> tuple[JsonObject, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(_object(row, field_name) for row in value)


def jarvis1_method_initial_state(
    *,
    task_id: str,
    instruction: str,
    initial_agent_state: JsonObject,
    memory_mode: str = _PUBLIC_MEMORY_MODE,
    visual_artifact_refs: tuple[str, ...] = (),
    max_environment_steps: int = 11999,
) -> JsonObject:
    if memory_mode not in {_PUBLIC_MEMORY_MODE, _PAPER_MULTIMODAL_MODE}:
        raise ValueError("JARVIS-1 memory_mode is invalid")
    if type(max_environment_steps) is not int or max_environment_steps < 1:
        raise ValueError("JARVIS-1 max_environment_steps must be positive")
    if type(visual_artifact_refs) is not tuple or any(
        type(row) is not str or not row.strip()
        for row in visual_artifact_refs
    ):
        raise TypeError("JARVIS-1 visual_artifact_refs must be text tuple")
    return {
        "public_executable_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
        "task_id": _text(task_id, "JARVIS-1 task_id"),
        "instruction": _text(instruction, "JARVIS-1 instruction"),
        "memory_mode": memory_mode,
        "visual_artifact_refs": visual_artifact_refs,
        "agent_state": _object(
            initial_agent_state,
            "JARVIS-1 initial agent state",
        ),
        "plan": (),
        "plan_index": 0,
        "current_step": None,
        "memory_record_digest": None,
        "memory_operation_digest": None,
        "environment_steps": 0,
        "max_environment_steps": max_environment_steps,
        "controller_attempt_count": 0,
        "task_success": False,
        "outcome": None,
        "trajectory": (),
    }


def _require_child(request: MethodNodeRequest) -> None:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError(
            "JARVIS-1 MethodProgram requires child MemoryMachine execution"
        )


def _memory_step(
    request: MethodNodeRequest,
) -> ChildResearchMachineExecution:
    _require_child(request)
    mode = request.state.get("memory_mode")
    if mode == _PUBLIC_MEMORY_MODE:
        kind = "jarvis1.memory.lookup-exact"
        payload: JsonObject = {
            "task_id": _text(
                request.state.get("task_id"),
                "JARVIS-1 task_id",
            ),
        }
    elif mode == _PAPER_MULTIMODAL_MODE:
        state = _object(
            request.state.get("agent_state", {}),
            "JARVIS-1 agent state",
        )
        inventory = state.get("inventory", {})
        if not isinstance(inventory, Mapping):
            inventory = {}
        refs = request.state.get("visual_artifact_refs", ())
        if isinstance(refs, (str, bytes, bytearray)) or not isinstance(
            refs,
            Sequence,
        ):
            raise TypeError(
                "JARVIS-1 visual_artifact_refs state must be a sequence"
            )
        kind = "jarvis1.memory.retrieve-multimodal"
        payload = {
            "instruction": _text(
                request.state.get("instruction"),
                "JARVIS-1 instruction",
            ),
            "visual_artifact_refs": tuple(
                _text(row, "JARVIS-1 visual artifact ref")
                for row in refs
            ),
            "inventory": dict(inventory),
        }
    else:
        raise ValueError("JARVIS-1 memory mode state drifted")

    child_machine_id = f"{request.parent_machine_id}:jarvis1-memory"
    child = request.child_machines.step_once(
        ChildResearchMachineRequest(
            host_id=_MEMORY_HOST_ID,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "public_source_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
                "program_digest": JARVIS1_MEMORY_PROGRAM.program_digest,
                "memory_mode": mode,
                "child_registry_identity_digest": (
                    request.child_machines.identity_digest
                ),
            },
            initial_data=jarvis1_memory_initial_data(),
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload={
                "event": {
                    "kind": kind,
                    "payload": payload,
                    "source": "jarvis1-method",
                }
            },
            command_id_prefix=(
                f"{child_machine_id}:lookup:"
                f"{request.node_id}:{request.visit}"
            ),
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError("JARVIS-1 memory child returned invalid execution")
    if child.status.value != "runnable":
        raise RuntimeError(
            "JARVIS-1 memory child stopped unexpectedly: "
            f"{child.status.value}"
        )
    if not isinstance(child.result, Mapping):
        raise TypeError("JARVIS-1 memory child result must be an object")
    return child


def _extract_plan(
    result: Mapping[str, JsonValue],
    mode: str,
) -> tuple[tuple[JsonObject, ...], str | None]:
    if mode == _PUBLIC_MEMORY_MODE:
        if result.get("found") is not True:
            raise RuntimeError(
                "JARVIS-1 public offline lane has no fixed-memory plan; "
                "the public source raises NotImplementedError because online "
                "planning is unreleased"
            )
        record = _object(
            result.get("record"),
            "JARVIS-1 fixed-memory record",
        )
        return (
            _rows(record.get("plan", ()), "JARVIS-1 fixed-memory plan"),
            (
                None
                if result.get("record_digest") is None
                else _text(
                    result.get("record_digest"),
                    "JARVIS-1 record digest",
                )
            ),
        )

    candidates = _rows(
        result.get("candidates", ()),
        "JARVIS-1 multimodal retrieval candidates",
    )
    if not candidates:
        raise RuntimeError(
            "JARVIS-1 multimodal retrieval returned no plan candidate"
        )
    record = _object(
        candidates[0].get("record"),
        "JARVIS-1 multimodal memory record",
    )
    digest = record.get("record_digest")
    return (
        _rows(record.get("plan", ()), "JARVIS-1 retrieved plan"),
        None if digest is None else _text(
            digest,
            "JARVIS-1 retrieved record digest",
        ),
    )


def _lookup_plan(request: MethodNodeRequest) -> MethodNodeResult:
    child = _memory_step(request)
    result = _object(child.result, "JARVIS-1 memory result")
    mode = _text(
        request.state.get("memory_mode"),
        "JARVIS-1 memory mode",
    )
    plan, record_digest = _extract_plan(result, mode)
    if not plan:
        raise RuntimeError("JARVIS-1 fixed/retrieved plan must not be empty")
    return MethodNodeResult(
        value={
            "memory_mode": mode,
            "plan_step_count": len(plan),
            "record_digest": record_digest,
            "memory_operation_digest": result.get("operation_digest"),
        },
        state_update={
            "plan": plan,
            "plan_index": 0,
            "current_step": None,
            "memory_record_digest": record_digest,
            "memory_operation_digest": result.get("operation_digest"),
        },
        next_node="select_step",
        child_links=(child.link,),
        events=(
            MethodEvent(
                "jarvis1.memory.plan-loaded",
                {
                    "memory_mode": mode,
                    "plan_step_count": len(plan),
                    "record_digest": record_digest,
                },
            ),
        ),
    )


def _select_step(request: MethodNodeRequest) -> MethodNodeResult:
    if request.state.get("task_success") is True:
        return MethodNodeResult(
            value={"outcome": "success"},
            state_update={"outcome": "success"},
            next_node="return",
        )
    plan = _rows(request.state.get("plan", ()), "JARVIS-1 plan")
    index = request.state.get("plan_index")
    if type(index) is not int or index < 0:
        raise ValueError("JARVIS-1 plan_index is invalid")
    if index >= len(plan):
        return MethodNodeResult(
            value={"outcome": "plan_error", "plan_index": index},
            state_update={"outcome": "plan_error"},
            next_node="return",
        )
    current = plan[index]
    return MethodNodeResult(
        value={
            "plan_index": index,
            "goal": current.get("goal"),
            "type": current.get("type"),
            "text": current.get("text"),
        },
        state_update={"current_step": current},
        next_node="prepare_controller",
    )


def _prepare_controller(request: MethodNodeRequest) -> MethodNodeResult:
    step = _object(
        request.state.get("current_step"),
        "JARVIS-1 current plan step",
    )
    index = request.state.get("plan_index")
    if type(index) is not int or index < 0:
        raise ValueError("JARVIS-1 plan_index state is invalid")
    envelope = {
        "task_id": _text(
            request.state.get("task_id"),
            "JARVIS-1 task_id",
        ),
        "plan_index": index,
        "goal": _object(step.get("goal"), "JARVIS-1 subgoal"),
        "skill_type": _text(
            step.get("type"),
            "JARVIS-1 skill type",
        ),
        "text": _text(step.get("text"), "JARVIS-1 skill text"),
        "agent_state": _object(
            request.state.get("agent_state", {}),
            "JARVIS-1 agent state",
        ),
        "controller_timeout": (
            JARVIS1_REFERENCE_FIDELITY.steve1_text_controller_timeout
        ),
        "target_reward": (
            JARVIS1_REFERENCE_FIDELITY.steve1_target_reward
        ),
    }
    return MethodNodeResult(
        value=envelope,
        state_update={"pending_controller_request": envelope},
        next_node="execute_skill",
    )


def _record_skill(request: MethodNodeRequest) -> MethodNodeResult:
    result = _object(
        request.previous_value,
        "JARVIS-1 controller result",
    )
    subgoal_success = result.get("subgoal_success", False)
    task_success = result.get("task_success", False)
    if type(subgoal_success) is not bool or type(task_success) is not bool:
        raise TypeError(
            "JARVIS-1 controller success fields must be booleans"
        )
    delta = result.get("environment_steps", 0)
    if type(delta) is not int or delta < 0:
        raise ValueError(
            "JARVIS-1 controller environment_steps must be non-negative"
        )
    consumed = request.state.get("environment_steps", 0)
    limit = request.state.get("max_environment_steps")
    attempts = request.state.get("controller_attempt_count", 0)
    index = request.state.get("plan_index")
    if (
        type(consumed) is not int
        or consumed < 0
        or type(limit) is not int
        or limit < 1
        or type(attempts) is not int
        or attempts < 0
        or type(index) is not int
        or index < 0
    ):
        raise ValueError("JARVIS-1 execution counters are invalid")
    next_consumed = consumed + delta
    next_attempts = attempts + 1
    agent_state = _object(
        result.get("agent_state", request.state.get("agent_state", {})),
        "JARVIS-1 controller agent_state",
    )

    trajectory_value = request.state.get("trajectory", ())
    if isinstance(trajectory_value, (str, bytes, bytearray)) or not isinstance(
        trajectory_value,
        Sequence,
    ):
        raise TypeError("JARVIS-1 trajectory must be a sequence")
    trajectory = list(trajectory_value)
    trajectory.append({
        "attempt": next_attempts,
        "plan_index": index,
        "subgoal_success": subgoal_success,
        "task_success": task_success,
        "environment_steps": delta,
        "total_environment_steps": next_consumed,
        "controller_receipt": result.get("controller_receipt"),
    })

    next_index = index + 1 if subgoal_success else index
    timeout = next_consumed > limit
    if task_success:
        outcome = "success"
        next_node = "return"
    elif timeout:
        outcome = "timeout"
        next_node = "return"
    elif subgoal_success:
        outcome = None
        next_node = "select_step"
    else:
        outcome = None
        next_node = "prepare_controller"

    update: JsonObject = {
        "agent_state": agent_state,
        "environment_steps": next_consumed,
        "controller_attempt_count": next_attempts,
        "plan_index": next_index,
        "task_success": task_success,
        "trajectory": tuple(trajectory),
        "outcome": outcome,
    }
    return MethodNodeResult(
        value={
            "subgoal_success": subgoal_success,
            "task_success": task_success,
            "environment_steps": next_consumed,
            "plan_index": next_index,
            "outcome": outcome,
        },
        state_update=update,
        next_node=next_node,
        checkpoint=True,
        checkpoint_value={
            "plan_index": next_index,
            "environment_steps": next_consumed,
            "task_success": task_success,
        },
        events=(
            MethodEvent(
                "jarvis1.controller.attempt-recorded",
                {
                    "attempt": next_attempts,
                    "plan_index": index,
                    "subgoal_success": subgoal_success,
                    "task_success": task_success,
                    "environment_steps": next_consumed,
                },
            ),
        ),
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    outcome = request.state.get("outcome")
    if outcome not in {"success", "timeout", "plan_error"}:
        outcome = "success" if request.state.get("task_success") is True else (
            "plan_error"
        )
    trajectory = request.state.get("trajectory", ())
    if isinstance(trajectory, (str, bytes, bytearray)) or not isinstance(
        trajectory,
        Sequence,
    ):
        raise TypeError("JARVIS-1 trajectory must be a sequence")
    return MethodNodeResult(
        value={
            "task_id": request.state.get("task_id"),
            "memory_mode": request.state.get("memory_mode"),
            "outcome": outcome,
            "success": outcome == "success",
            "plan_step_count": len(
                _rows(request.state.get("plan", ()), "JARVIS-1 plan")
            ),
            "completed_plan_steps": request.state.get("plan_index", 0),
            "controller_attempt_count": request.state.get(
                "controller_attempt_count",
                0,
            ),
            "environment_steps": request.state.get("environment_steps", 0),
            "memory_record_digest": request.state.get(
                "memory_record_digest"
            ),
            "memory_operation_digest": request.state.get(
                "memory_operation_digest"
            ),
            "trajectory": tuple(trajectory),
        }
    )


def build_jarvis1_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "public_source_commit": JARVIS1_PUBLIC_EXECUTABLE_COMMIT,
        "memory_program_digest": JARVIS1_MEMORY_PROGRAM.program_digest,
        "public_memory_mode": _PUBLIC_MEMORY_MODE,
        "paper_multimodal_mode": _PAPER_MULTIMODAL_MODE,
        "public_missing_plan_behavior": "fail-closed-online-planner-unreleased",
        "controller_capability": _CONTROLLER_CAPABILITY,
        "controller_timeout": (
            JARVIS1_REFERENCE_FIDELITY.steve1_text_controller_timeout
        ),
        "controller_target_reward": (
            JARVIS1_REFERENCE_FIDELITY.steve1_target_reward
        ),
        "loop_semantics": (
            "retry-current-subgoal-until-monitor-success",
            "advance-plan-index-on-subgoal-success",
            "terminate-on-task-success",
            "terminate-on-environment-step-limit",
        ),
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="jarvis1-hierarchical-minecraft-agent",
            implementation_version=JARVIS1_PUBLIC_EXECUTABLE_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="jarvis1.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="lookup_plan")
    builder.compute(
        "lookup_plan",
        "jarvis1.memory.load-plan",
        _lookup_plan,
        ("select_step",),
        evidence_obligations=("jarvis1.memory.child-cut",),
    )
    builder.route(
        "select_step",
        "jarvis1.plan.select-step",
        _select_step,
        ("prepare_controller", "return"),
        max_visits=4096,
    )
    builder.compute(
        "prepare_controller",
        "jarvis1.controller.prepare",
        _prepare_controller,
        ("execute_skill",),
        max_visits=4096,
    )
    builder.capability(
        "execute_skill",
        "jarvis1.controller.execute",
        _CONTROLLER_CAPABILITY,
        ("record_skill",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=4096,
        evidence_obligations=("jarvis1.controller.effect",),
    )
    builder.route(
        "record_skill",
        "jarvis1.controller.record",
        _record_skill,
        ("prepare_controller", "select_step", "return"),
        max_visits=4096,
    )
    builder.return_node(
        "return",
        "jarvis1.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(_CONTROLLER_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "jarvis1.memory.child-cut",
            "jarvis1.controller.effect",
            "jarvis1.plan-trajectory",
        ),
        metric_names=(
            "task_success",
            "environment_steps",
            "controller_attempt_count",
            "completed_plan_steps",
        ),
        artifact_kinds=(
            "jarvis1_memory_record",
            "jarvis1_multimodal_memory_evidence",
            "jarvis1_controller_trajectory",
        ),
    )


JARVIS1_METHOD_PROGRAM = build_jarvis1_method_program()


__all__ = [
    "JARVIS1_METHOD_PROGRAM",
    "build_jarvis1_method_program",
    "jarvis1_method_initial_state",
]
