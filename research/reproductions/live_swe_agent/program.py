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
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, freeze_json, thaw_json

from collections.abc import Mapping, Sequence





from .fidelity import LIVE_SWE_AGENT_FIDELITY


_AGENT_ID = "live-swe-agent.worker"
_TOOL_REFLECTION_AGENT_ID = "live-swe-agent.tool-reflection"
_SOFTWARE_COMMAND_CAPABILITY = "software.command"
_HOST_MAX_TURNS = 512
_HOST_MAX_TOOL_CREATIONS = 128


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Live-SWE-agent {field} must be text")
    return value.strip()


def _count(state: Mapping[str, JsonValue], field: str) -> int:
    value = state.get(field, 0)
    if type(value) is not int or value < 0:
        raise ValueError(f"Live-SWE-agent {field} must be non-negative")
    return value


def _history(value: object) -> tuple[JsonObject, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError("Live-SWE-agent history must be a sequence")
    rows: list[JsonObject] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("Live-SWE-agent history rows must be mappings")
        rows.append(freeze_json(dict(row)))
    return tuple(rows)


def live_swe_agent_initial_state(
    *,
    task_instruction: str,
    initial_observation: str,
) -> JsonObject:
    return {
        "task_instruction": _text(task_instruction, "task_instruction"),
        "history": (
            {
                "role": "user",
                "kind": "observation",
                "content": _text(
                    initial_observation,
                    "initial_observation",
                    allow_empty=True,
                ),
            },
        ),
        "turn": 0,
        "command_count": 0,
        "tool_creation_count": 0,
        "pending_command": "",
        "pending_tool_spec": {},
        "last_observation": initial_observation,
        "submitted": False,
        "environment_done": False,
        "host_limit_reached": False,
    }


def _worker_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "live_worker",
        "task_instruction": request.state.get("task_instruction"),
        "history": _history(request.state.get("history", ())),
        "turn": _count(request.state, "turn"),
        "one_action_per_turn": LIVE_SWE_AGENT_FIDELITY.one_action_per_turn,
        "action_interface": LIVE_SWE_AGENT_FIDELITY.action_interface,
        "runtime_tool_creation": LIVE_SWE_AGENT_FIDELITY.runtime_tool_creation,
        "tool_creation_contract": {
            "requires_trajectory_reflection": (
                LIVE_SWE_AGENT_FIDELITY.trajectory_reflection_before_tool_creation
            ),
            "tool_kind": "python_cli",
        },
        "completion_command": LIVE_SWE_AGENT_FIDELITY.task_completion_command,
    }


def _prepare_worker_action(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if not isinstance(value, Mapping):
        raise TypeError("Live-SWE-agent worker result must be a mapping")
    discussion = _text(value.get("discussion", ""), "discussion", allow_empty=True)
    command_value = value.get("command")
    command = (
        command_value.strip()
        if isinstance(command_value, str) and command_value.strip()
        else ""
    )
    create_tool = value.get("create_tool") is True
    tool_spec = value.get("tool_spec", {})
    if create_tool:
        if not isinstance(tool_spec, Mapping) or not tool_spec:
            raise ValueError("Live-SWE-agent tool creation requires tool_spec")
        next_node = "tool_reflection"
    else:
        if not command:
            raise ValueError("Live-SWE-agent worker must emit one bash command")
        next_node = "software_command"

    history = _history(request.state.get("history", ()))
    return dict(
        value={
            "create_tool": create_tool,
            "command": command,
            "tool_spec": tool_spec,
        },
        state_update={
            "history": (
                *history,
                {
                    "role": "assistant",
                    "kind": "decision",
                    "discussion": discussion,
                    "command": command,
                    "create_tool": create_tool,
                    "tool_spec": tool_spec,
                },
            ),
            "pending_command": command,
            "pending_tool_spec": tool_spec if create_tool else {},
        },
        next_node=next_node,
    )


def _tool_reflection_view(request: MethodCall) -> JsonObject:
    return {
        "phase": "trajectory_reflection_before_tool_creation",
        "task_instruction": request.state.get("task_instruction"),
        "history": _history(request.state.get("history", ())),
        "requested_tool": request.state.get("pending_tool_spec", {}),
        "created_tool_contract": {
            "language": "python",
            "interface": "cli",
        },
        "instruction": (
            "Reflect on the trajectory and requested reusable operation, then emit "
            "one bash command that materializes the Python CLI tool in the task workspace."
        ),
    }


def _prepare_tool_creation(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, Mapping):
        command_value = value.get("command", value.get("bash"))
    else:
        command_value = value
    command = _text(command_value, "tool creation command")
    return dict(
        value={
            "command": command,
            "new_subshell": LIVE_SWE_AGENT_FIDELITY.environment_changes_are_new_subshell_per_action,
            "operation_kind": "runtime_tool_creation",
            "tool_kind": "python_cli",
        },
        state_update={"pending_command": command},
    )


def _prepare_command(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "command": _text(request.state.get("pending_command"), "pending_command"),
            "new_subshell": LIVE_SWE_AGENT_FIDELITY.environment_changes_are_new_subshell_per_action,
            "operation_kind": "task_action",
            "one_action_per_turn": LIVE_SWE_AGENT_FIDELITY.one_action_per_turn,
        }
    )


def _environment_result(value: JsonValue) -> tuple[str, bool, JsonValue]:
    result = thaw_json(value)
    if isinstance(result, str):
        return result, False, None
    if not isinstance(result, Mapping):
        return str(result), False, None
    text = ""
    for key in ("observation", "stdout", "content", "text"):
        candidate = result.get(key)
        if isinstance(candidate, str):
            text = candidate
            break
    done = result.get("done") is True
    artifact = result.get("artifact_reference", result.get("patch_reference"))
    return text, done, artifact


def _record_tool_creation(request: MethodCall) -> MethodNodeResult:
    observation, _done, artifact = _environment_result(request.previous_value)
    history = _history(request.state.get("history", ()))
    count = _count(request.state, "tool_creation_count") + 1
    row: JsonObject = {
        "role": "user",
        "kind": "tool_creation_observation",
        "content": observation,
        "tool_creation_index": count,
    }
    if artifact is not None:
        row["artifact_reference"] = artifact
    return dict(
        value={"tool_created": True, "observation": observation},
        state_update={
            "history": (*history, row),
            "tool_creation_count": count,
            "pending_tool_spec": {},
            "pending_command": "",
            "last_observation": observation,
        },
        next_node="worker",
        checkpoint=True,
        checkpoint_value={"tool_creation_count": count},
    )


def _record_command(request: MethodCall) -> MethodNodeResult:
    observation, done, artifact = _environment_result(request.previous_value)
    command = _text(request.state.get("pending_command"), "pending_command")
    history = _history(request.state.get("history", ()))
    turn = _count(request.state, "turn") + 1
    submitted = command == LIVE_SWE_AGENT_FIDELITY.task_completion_command
    row: JsonObject = {
        "role": "user",
        "kind": "observation",
        "content": observation,
    }
    update: dict[str, JsonValue] = {
        "history": (*history, row),
        "turn": turn,
        "command_count": _count(request.state, "command_count") + 1,
        "pending_command": "",
        "last_observation": observation,
        "submitted": submitted,
        "environment_done": done,
    }
    if artifact is not None:
        update["submission_artifact"] = artifact
    return dict(
        value={
            "turn": turn,
            "submitted": submitted,
            "environment_done": done,
            "observation": observation,
        },
        state_update=update,
        checkpoint=True,
        checkpoint_value={
            "turn": turn,
            "submitted": submitted,
            "environment_done": done,
        },
    )


def _route_terminal(request: MethodCall) -> MethodNodeResult:
    turn = _count(request.state, "turn")
    submitted = request.state.get("submitted") is True
    done = request.state.get("environment_done") is True
    host_limit = turn >= _HOST_MAX_TURNS
    return dict(
        value={
            "terminal": submitted or done or host_limit,
            "submitted": submitted,
            "environment_done": done,
            "host_limit_reached": host_limit,
        },
        state_update={"host_limit_reached": host_limit},
        next_node="return" if submitted or done or host_limit else "worker",
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    result: dict[str, JsonValue] = {
        "submitted": request.state.get("submitted") is True,
        "environment_done": request.state.get("environment_done") is True,
        "host_limit_reached": request.state.get("host_limit_reached") is True,
        "turn_count": _count(request.state, "turn"),
        "command_count": _count(request.state, "command_count"),
        "tool_creation_count": _count(request.state, "tool_creation_count"),
        "last_observation": request.state.get("last_observation", ""),
        "history": request.state.get("history", ()),
    }
    if "submission_artifact" in request.state:
        result["submission_artifact"] = request.state["submission_artifact"]
    return dict(value=result)


def build_live_swe_agent_method_program(method, ) -> None:
    f = LIVE_SWE_AGENT_FIDELITY
    configuration: JsonObject = {
        "release_tag": f.release_tag,
        "source_commit": f.audited_commit,
        "source_artifact": f.source_artifact,
        "base_scaffold": f.base_scaffold,
        "one_action_per_turn": f.one_action_per_turn,
        "action_interface": f.action_interface,
        "runtime_tool_creation": f.runtime_tool_creation,
        "trajectory_reflection_before_tool_creation": (
            f.trajectory_reflection_before_tool_creation
        ),
        "created_tools_are_python_cli_programs": f.created_tools_are_python_cli_programs,
        "environment_changes_are_new_subshell_per_action": (
            f.environment_changes_are_new_subshell_per_action
        ),
        "task_completion_command": f.task_completion_command,
        "terminal_completion_command_is_irreversible": (
            f.terminal_completion_command_is_irreversible
        ),
        "paper_default_step_limit": f.default_step_limit,
        "paper_default_cost_limit": f.default_cost_limit,
        "host_max_turns": _HOST_MAX_TURNS,
        "host_max_tool_creations": _HOST_MAX_TOOL_CREATIONS,
    }

    builder = method
    builder.agent(
        "worker",
        "live-swe-agent.worker",
        _AGENT_ID,
        ("prepare_worker_action",),
        view=_worker_view,
        max_visits=_HOST_MAX_TURNS + _HOST_MAX_TOOL_CREATIONS,
    )
    builder.route(
        "prepare_worker_action",
        "live-swe-agent.worker.record",
        _prepare_worker_action,
        ("tool_reflection", "software_command"),
        max_visits=_HOST_MAX_TURNS + _HOST_MAX_TOOL_CREATIONS,
    )
    builder.agent(
        "tool_reflection",
        "live-swe-agent.tool.reflect",
        _TOOL_REFLECTION_AGENT_ID,
        ("prepare_tool_creation",),
        view=_tool_reflection_view,
        max_visits=_HOST_MAX_TOOL_CREATIONS,
    )
    builder.compute(
        "prepare_tool_creation",
        "live-swe-agent.tool.prepare",
        _prepare_tool_creation,
        ("create_tool",),
        max_visits=_HOST_MAX_TOOL_CREATIONS,
    )
    builder.capability(
        "create_tool",
        "live-swe-agent.tool.create",
        _SOFTWARE_COMMAND_CAPABILITY,
        ("record_tool_creation",),
        effect='reconcilable',
        max_visits=_HOST_MAX_TOOL_CREATIONS,
        evidence=("live-swe-agent.tool-creation-effect",),
    )
    builder.route(
        "record_tool_creation",
        "live-swe-agent.tool.record",
        _record_tool_creation,
        ("worker",),
        max_visits=_HOST_MAX_TOOL_CREATIONS,
    )
    builder.compute(
        "software_command",
        "live-swe-agent.command.prepare",
        _prepare_command,
        ("execute_command",),
        max_visits=_HOST_MAX_TURNS,
    )
    builder.capability(
        "execute_command",
        "live-swe-agent.command.execute",
        _SOFTWARE_COMMAND_CAPABILITY,
        ("record_command",),
        effect='reconcilable',
        max_visits=_HOST_MAX_TURNS,
        evidence=("software.command.effect",),
    )
    builder.compute(
        "record_command",
        "live-swe-agent.command.record",
        _record_command,
        ("terminal",),
        max_visits=_HOST_MAX_TURNS,
    )
    builder.route(
        "terminal",
        "live-swe-agent.terminal.route",
        _route_terminal,
        ("worker", "return"),
        max_visits=_HOST_MAX_TURNS,
    )
    builder.return_node("return", "live-swe-agent.result", _return_result)
    builder.configure(configuration)
    builder.requires(*(_SOFTWARE_COMMAND_CAPABILITY,))
    builder.policy(
        execution='effect_recorded',
        evidence=(
            "live-swe-agent.trajectory",
            "live-swe-agent.tool-reflection",
            "live-swe-agent.tool-creation-effect",
            "software.command.effect",
            "model.invocation",
        ),
        metrics=(
            "task_resolved",
            "turn_count",
            "command_count",
            "tool_creation_count",
        ),
        artifacts=(
            "live_swe_agent_trajectory",
            "live_swe_agent_generated_tool",
            "prediction.patch",
        ),
    )
    return builder


METHOD_CONFIGURER = build_live_swe_agent_method_program
METHOD_ENTRYPOINT = "worker"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}


__all__ = [
    'build_live_swe_agent_method_program',
    'live_swe_agent_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]

METHOD_SPEC = {"method_id": 'live-swe-agent', "version": "paper-protocol", "semantic_contract": 'live-swe-agent' + ".method.v2", "entrypoint": METHOD_ENTRYPOINT}

__all__ = tuple(dict.fromkeys((*__all__, 'METHOD_SPEC')))
