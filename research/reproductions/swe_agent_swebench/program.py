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
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, freeze_json

from collections.abc import Mapping, Sequence





from .aci import SweAgentTurn
from .fidelity import SWE_AGENT_PAPER_ERA_FIDELITY
from .history import project_paper_era_history

_AGENT_ID = "swe-agent.paper-era"
_SOFTWARE_COMMAND_CAPABILITY = "software.command"

# Bounded-host guard only. This is not presented as a paper claim.
_HOST_MAX_TURNS = 512


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"SWE-agent {field} must be text")
    return value


def _count(state: Mapping[str, JsonValue], field: str) -> int:
    value = state.get(field, 0)
    if type(value) is not int or value < 0:
        raise ValueError(f"SWE-agent {field} must be a non-negative integer")
    return value


def _history(value: object) -> tuple[JsonObject, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("SWE-agent history must be a sequence")
    rows: list[JsonObject] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("SWE-agent history rows must be mappings")
        role = row.get("role")
        message_type = row.get("message_type")
        content = row.get("content")
        if not isinstance(role, str) or not role:
            raise ValueError("SWE-agent history row requires role")
        if not isinstance(message_type, str) or not message_type:
            raise ValueError("SWE-agent history row requires message_type")
        if not isinstance(content, str):
            raise TypeError("SWE-agent history row content must be text")
        rows.append(freeze_json(dict(row)))
    return tuple(rows)


def swe_agent_paper_era_initial_state(
    *,
    task_instruction: str,
    initial_observation: str,
) -> JsonObject:
    instruction = _text(task_instruction, "task instruction")
    observation = _text(initial_observation, "initial observation", allow_empty=True)
    return {
        "task_instruction": instruction,
        "history": (
            {
                "role": "user",
                "message_type": "observation",
                "content": observation,
                "is_demo": False,
            },
        ),
        "turn": 0,
        "command_count": 0,
        "pending_command": "",
        "pending_discussion": "",
        "last_observation": observation,
        "submitted": False,
        "environment_done": False,
        "host_limit_reached": False,
    }


def _agent_view(request: MethodCall) -> JsonObject:
    history = _history(request.state.get("history", ()))
    projection = project_paper_era_history(history)
    return {
        "task_instruction": _text(request.state.get("task_instruction"), "task instruction"),
        "history": projection.records,
        "turn": _count(request.state, "turn"),
        "observation_history_limit": SWE_AGENT_PAPER_ERA_FIDELITY.history_observations_kept,
        "one_command_per_turn": SWE_AGENT_PAPER_ERA_FIDELITY.one_command_per_turn,
        "submit_command": SWE_AGENT_PAPER_ERA_FIDELITY.submit_command,
    }


def _agent_operation(value: JsonValue) -> SweAgentTurn:
    if not isinstance(value, Mapping):
        raise TypeError("SWE-agent model result must be a mapping")
    discussion = _text(value.get("discussion"), "discussion")
    command = _text(value.get("command"), "command")
    return SweAgentTurn(discussion, command)


def _prepare_command(request: MethodCall) -> MethodNodeResult:
    turn = _agent_operation(request.previous_value)
    history = _history(request.state.get("history", ()))
    assistant_row: JsonObject = {
        "role": "assistant",
        "message_type": "action",
        "content": turn.discussion,
        "command": turn.command,
        "is_demo": False,
    }
    return dict(
        value={"command": turn.command},
        state_update={
            "history": (*history, assistant_row),
            "pending_command": turn.command,
            "pending_discussion": turn.discussion,
        },
    )


def _observation(value: JsonValue) -> tuple[str, bool, JsonValue]:
    if isinstance(value, str):
        return value, False, None
    if not isinstance(value, Mapping):
        return str(value), False, None

    text: str | None = None
    for key in ("observation", "stdout", "content", "text"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            text = candidate
            break
    if text is None:
        text = str(value)

    done = value.get("done") is True
    artifact = value.get("artifact_reference", value.get("patch_reference"))
    return text, done, artifact


def _record_observation(request: MethodCall) -> MethodNodeResult:
    command = _text(request.state.get("pending_command"), "pending command")
    text, done, artifact = _observation(request.previous_value)
    history = _history(request.state.get("history", ()))
    observation_row: JsonObject = {
        "role": "user",
        "message_type": "observation",
        "content": text,
        "is_demo": False,
    }
    turn = _count(request.state, "turn") + 1
    submitted = command == SWE_AGENT_PAPER_ERA_FIDELITY.submit_command
    update: dict[str, JsonValue] = {
        "history": (*history, observation_row),
        "turn": turn,
        "command_count": _count(request.state, "command_count") + 1,
        "last_observation": text,
        "submitted": submitted,
        "environment_done": done,
    }
    if artifact is not None:
        update["submission_artifact"] = artifact
    return dict(
        value={
            "command": command,
            "observation": text,
            "turn": turn,
            "submitted": submitted,
            "environment_done": done,
        },
        state_update=update,
        checkpoint=True,
        checkpoint_value={
            "turn": turn,
            "command": command,
            "submitted": submitted,
            "environment_done": done,
        },
    )


def _route_terminal(request: MethodCall) -> MethodNodeResult:
    turn = _count(request.state, "turn")
    submitted = request.state.get("submitted") is True
    environment_done = request.state.get("environment_done") is True
    host_limit = turn >= _HOST_MAX_TURNS
    terminal = submitted or environment_done or host_limit
    return dict(
        value={
            "terminal": terminal,
            "submitted": submitted,
            "environment_done": environment_done,
            "host_limit_reached": host_limit,
            "turn": turn,
        },
        state_update={"host_limit_reached": host_limit},
        next_node="return" if terminal else "agent",
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    value: dict[str, JsonValue] = {
        "submitted": request.state.get("submitted") is True,
        "environment_done": request.state.get("environment_done") is True,
        "host_limit_reached": request.state.get("host_limit_reached") is True,
        "turn_count": _count(request.state, "turn"),
        "command_count": _count(request.state, "command_count"),
        "last_observation": _text(
            request.state.get("last_observation"),
            "last observation",
            allow_empty=True,
        ),
    }
    if "submission_artifact" in request.state:
        value["submission_artifact"] = request.state["submission_artifact"]
    return dict(value=value)


def build_swe_agent_paper_era_method_program(method, ) -> None:
    configuration: JsonObject = {
        "paper_era_commit": SWE_AGENT_PAPER_ERA_FIDELITY.audited_repository_commit,
        "parser": SWE_AGENT_PAPER_ERA_FIDELITY.parser,
        "file_window_lines": SWE_AGENT_PAPER_ERA_FIDELITY.file_window_lines,
        "file_window_overlap": SWE_AGENT_PAPER_ERA_FIDELITY.file_window_overlap,
        "history_observations_kept": SWE_AGENT_PAPER_ERA_FIDELITY.history_observations_kept,
        "one_command_per_turn": SWE_AGENT_PAPER_ERA_FIDELITY.one_command_per_turn,
        "wait_for_observation_after_command": (
            SWE_AGENT_PAPER_ERA_FIDELITY.wait_for_observation_after_command
        ),
        "submit_command": SWE_AGENT_PAPER_ERA_FIDELITY.submit_command,
        "host_max_turns": _HOST_MAX_TURNS,
    }

    builder = method
    builder.agent(
        "agent",
        "swe-agent.model.turn",
        _AGENT_ID,
        ("prepare_command",),
        view=_agent_view,
        max_visits=_HOST_MAX_TURNS,
    )
    builder.compute(
        "prepare_command",
        "swe-agent.command.prepare",
        _prepare_command,
        ("software_command",),
        max_visits=_HOST_MAX_TURNS,
    )
    builder.capability(
        "software_command",
        "swe-agent.command.execute",
        _SOFTWARE_COMMAND_CAPABILITY,
        ("record_observation",),
        effect='reconcilable',
        max_visits=_HOST_MAX_TURNS,
        evidence=("software.command.effect",),
    )
    builder.compute(
        "record_observation",
        "swe-agent.observation.record",
        _record_observation,
        ("terminal",),
        max_visits=_HOST_MAX_TURNS,
    )
    builder.route(
        "terminal",
        "swe-agent.terminal.route",
        _route_terminal,
        ("agent", "return"),
        max_visits=_HOST_MAX_TURNS,
    )
    builder.return_node("return", "swe-agent.result", _return_result)
    builder.configure(configuration)
    builder.requires(*(_SOFTWARE_COMMAND_CAPABILITY,))
    builder.policy(
        execution='effect_recorded',
        evidence=(
            "swe-agent.trajectory",
            "swe-agent.model-view",
            "software.command.effect",
        ),
        metrics=("task_resolved", "turn_count", "command_count"),
        artifacts=("swe_agent_trajectory", "prediction.patch"),
    )
    return builder


METHOD_CONFIGURER = build_swe_agent_paper_era_method_program
METHOD_ENTRYPOINT = "agent"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}


__all__ = [
    'build_swe_agent_paper_era_method_program',
    'swe_agent_paper_era_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]
