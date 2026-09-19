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
    freeze_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import REFLEXION_ALFWORLD_FIDELITY
from .memory import ReflexionTaskState
from .semantics import (
    accept_action_candidate,
    render_reflection_prompt,
    render_task_prompt,
)

_ACTION_AGENT_ID = "reflexion.action"
_REFLECTION_AGENT_ID = "reflexion.reflection"
_ACTION_CAPABILITY = "environment.act"
_RESET_CAPABILITY = "environment.reset"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Reflexion {field} must be text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Reflexion {field} must be a non-negative integer")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"Reflexion {field} must be a sequence")
    return tuple(_text(item, field) for item in value)


def reflexion_alfworld_initial_state(
    *,
    task_id: str,
    base_prompt: str,
    initial_observation: str,
    reflection_examples: str,
) -> JsonObject:
    state = ReflexionTaskState(_text(task_id, "task_id"))
    return {
        "task_id": state.task_id,
        "base_prompt": _text(base_prompt, "base prompt"),
        "initial_observation": _text(
            initial_observation,
            "initial observation",
            allow_empty=True,
        ),
        "reflection_examples": _text(
            reflection_examples,
            "reflection examples",
        ),
        "reflections": state.reflections,
        "completed_trials": 0,
        "solved": False,
        "trial_turn": 0,
        "candidate_attempt": 0,
        "trial_log": "",
        "last_action": "",
        "last_observation": initial_observation,
    }


def _task_state(state: Mapping[str, JsonValue]) -> ReflexionTaskState:
    return ReflexionTaskState(
        _text(state.get("task_id"), "task_id"),
        reflections=_strings(state.get("reflections", ()), "reflections"),
        solved=state.get("solved") is True,
        completed_trials=_integer(state.get("completed_trials", 0), "completed_trials"),
    )


def _start_trial(request: MethodNodeRequest) -> MethodNodeResult:
    state = _task_state(request.state)
    if state.solved or state.completed_trials >= REFLEXION_ALFWORLD_FIDELITY.max_trials:
        return MethodNodeResult(value={"terminal": True}, next_node="return")
    prompt = render_task_prompt(
        _text(request.state.get("base_prompt"), "base prompt"),
        _text(
            request.state.get("initial_observation"),
            "initial observation",
            allow_empty=True,
        ),
        state,
    )
    return MethodNodeResult(
        value={"trial": state.completed_trials + 1},
        state_update={
            "trial_turn": 0,
            "candidate_attempt": 0,
            "trial_log": prompt,
            "last_action": "",
            "last_observation": request.state.get("initial_observation", ""),
        },
        next_node="action",
    )


def _action_view(request: MethodNodeRequest) -> JsonObject:
    attempt = _integer(request.state.get("candidate_attempt", 0), "candidate_attempt")
    return {
        "trial": _integer(request.state.get("completed_trials", 0), "completed_trials") + 1,
        "turn": _integer(request.state.get("trial_turn", 0), "trial_turn"),
        "candidate_attempt": attempt,
        "temperature": REFLEXION_ALFWORLD_FIDELITY.action_temperature(attempt),
        "stop_sequences": REFLEXION_ALFWORLD_FIDELITY.action_stop_sequences,
        "max_output_tokens": REFLEXION_ALFWORLD_FIDELITY.action_max_output_tokens,
        "trajectory": _text(
            request.state.get("trial_log", ""),
            "trial log",
            allow_empty=True,
        ),
        "reflections": _task_state(request.state).visible_reflections,
    }


def _action_text(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        candidate = value.get("action", value.get("text"))
        if isinstance(candidate, str):
            return candidate
    raise TypeError("Reflexion action model result must contain action text")


def _validate_action(request: MethodNodeRequest) -> MethodNodeResult:
    raw = _action_text(request.previous_value)
    admitted = accept_action_candidate(raw)
    attempt = _integer(request.state.get("candidate_attempt", 0), "candidate_attempt")
    if admitted is None:
        next_attempt = attempt + 1
        if next_attempt >= REFLEXION_ALFWORLD_FIDELITY.action_candidate_attempts:
            raise RuntimeError("Reflexion action candidate retry budget exhausted")
        return MethodNodeResult(
            value={"accepted": False, "attempt": next_attempt},
            state_update={"candidate_attempt": next_attempt},
            next_node="action",
        )
    return MethodNodeResult(
        value={"action": admitted},
        state_update={
            "candidate_attempt": 0,
            "last_action": admitted,
        },
        next_node=(
            "record_think"
            if admitted.lower().startswith(REFLEXION_ALFWORLD_FIDELITY.think_prefix)
            else "prepare_action"
        ),
    )


def _append_turn_log(
    state: Mapping[str, JsonValue],
    *,
    action: str,
    observation: str,
) -> str:
    prefix = _text(state.get("trial_log", ""), "trial log", allow_empty=True)
    return f"{prefix}\n> {action}\n{observation}"


def _next_after_turn(
    request: MethodNodeRequest,
    *,
    observation: str,
    success: bool,
    terminal: bool,
) -> MethodNodeResult:
    action = _text(request.state.get("last_action"), "last action")
    turn = _integer(request.state.get("trial_turn", 0), "trial_turn") + 1
    trial_log = _append_turn_log(
        request.state,
        action=action,
        observation=observation,
    )
    exhausted = turn >= REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial
    if success:
        before = _task_state(request.state)
        after = before.complete_trial(success=True)
        return MethodNodeResult(
            value={"success": True, "turn": turn},
            state_update={
                "trial_turn": turn,
                "trial_log": trial_log,
                "last_observation": observation,
                "completed_trials": after.completed_trials,
                "solved": True,
            },
            next_node="return",
            checkpoint=True,
            checkpoint_value={
                "trial": after.completed_trials,
                "turn": turn,
                "success": True,
            },
        )
    if terminal or exhausted:
        return MethodNodeResult(
            value={"success": False, "turn": turn},
            state_update={
                "trial_turn": turn,
                "trial_log": trial_log,
                "last_observation": observation,
            },
            next_node="complete_failed_trial",
        )
    return MethodNodeResult(
        value={"success": False, "turn": turn},
        state_update={
            "trial_turn": turn,
            "trial_log": trial_log,
            "last_observation": observation,
        },
        next_node="action",
    )


def _record_think(request: MethodNodeRequest) -> MethodNodeResult:
    return _next_after_turn(
        request,
        observation=REFLEXION_ALFWORLD_FIDELITY.think_observation,
        success=False,
        terminal=False,
    )


def _prepare_action(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value=environment_action_capability_payload(
            "command",
            {"text": _text(request.state.get("last_action"), "last action")},
        )
    )


def _environment_outcome(value: JsonValue) -> tuple[str, bool, bool]:
    candidate: object = value
    if isinstance(value, Mapping):
        observation = value.get("observation")
        if isinstance(observation, Mapping) and "payload" in observation:
            candidate = observation["payload"]
        elif "payload" in value and not isinstance(value.get("payload"), bool):
            candidate = value["payload"]

    if isinstance(candidate, str):
        return candidate, False, False
    if not isinstance(candidate, Mapping):
        return str(candidate), False, False

    text = ""
    for key in ("text", "observation", "message", "content"):
        row = candidate.get(key)
        if isinstance(row, str):
            text = row
            break
    if not text:
        text = str(dict(candidate))

    reward = candidate.get("reward")
    success = (
        candidate.get("success") is True
        or candidate.get("won") is True
        or (
            isinstance(reward, (int, float))
            and not isinstance(reward, bool)
            and float(reward) > 0.0
        )
    )
    terminal = (
        success
        or candidate.get("done") is True
        or candidate.get("terminal") is True
    )
    return text, success, terminal


def _record_action(request: MethodNodeRequest) -> MethodNodeResult:
    observation, success, terminal = _environment_outcome(request.previous_value)
    return _next_after_turn(
        request,
        observation=observation,
        success=success,
        terminal=terminal,
    )


def _complete_failed_trial(request: MethodNodeRequest) -> MethodNodeResult:
    before = _task_state(request.state)
    after = before.complete_trial(success=False)
    update = {
        "completed_trials": after.completed_trials,
        "solved": False,
    }
    if after.completed_trials >= REFLEXION_ALFWORLD_FIDELITY.max_trials:
        return MethodNodeResult(
            value={"trials_exhausted": True},
            state_update=update,
            next_node="return",
            checkpoint=True,
            checkpoint_value={
                "trial": after.completed_trials,
                "success": False,
            },
        )
    return MethodNodeResult(
        value={"trials_exhausted": False},
        state_update=update,
        next_node="reflection",
        checkpoint=True,
        checkpoint_value={
            "trial": after.completed_trials,
            "success": False,
        },
    )


def _reflection_view(request: MethodNodeRequest) -> JsonObject:
    state = _task_state(request.state)
    return {
        "trial": state.completed_trials,
        "temperature": REFLEXION_ALFWORLD_FIDELITY.reflection_temperature,
        "max_output_tokens": REFLEXION_ALFWORLD_FIDELITY.reflection_max_output_tokens,
        "prompt": render_reflection_prompt(
            failed_trial_log=_text(request.state.get("trial_log"), "trial log"),
            state=state,
            few_shot_examples=_text(
                request.state.get("reflection_examples"),
                "reflection examples",
            ),
        ),
        "visible_reflections": state.visible_reflections,
    }


def _reflection_text(value: JsonValue) -> str:
    if isinstance(value, str):
        return _text(value, "reflection")
    if isinstance(value, Mapping):
        candidate = value.get("reflection", value.get("plan", value.get("text")))
        if isinstance(candidate, str):
            return _text(candidate, "reflection")
    raise TypeError("Reflexion reflection model result must contain reflection text")


def _record_reflection(request: MethodNodeRequest) -> MethodNodeResult:
    state = _task_state(request.state)
    reflected = state.append_reflection(_reflection_text(request.previous_value))
    return MethodNodeResult(
        value={"reflection_count": len(reflected.reflections)},
        state_update={"reflections": reflected.reflections},
        next_node="reset",
    )


def _reset_payload(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "task_id": _text(request.state.get("task_id"), "task_id"),
            "next_trial": _integer(
                request.state.get("completed_trials", 0),
                "completed_trials",
            )
            + 1,
        }
    )


def _record_reset(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value=request.previous_value,
        next_node="start_trial",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    state = _task_state(request.state)
    return MethodNodeResult(
        value={
            "task_id": state.task_id,
            "success": state.solved,
            "completed_trials": state.completed_trials,
            "first_success_trial": state.completed_trials if state.solved else None,
            "trials_used": state.completed_trials,
            "reflections": state.reflections,
            "visible_reflections": state.visible_reflections,
        }
    )


def build_reflexion_alfworld_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "max_trials": REFLEXION_ALFWORLD_FIDELITY.max_trials,
        "max_turns_per_trial": REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial,
        "action_candidate_attempts": REFLEXION_ALFWORLD_FIDELITY.action_candidate_attempts,
        "action_temperature_step": REFLEXION_ALFWORLD_FIDELITY.action_temperature_step,
        "reflection_temperature": REFLEXION_ALFWORLD_FIDELITY.reflection_temperature,
        "reflection_memory_window": REFLEXION_ALFWORLD_FIDELITY.reflection_memory_window,
        "think_prefix": REFLEXION_ALFWORLD_FIDELITY.think_prefix,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="reflexion",
            implementation_version=REFLEXION_ALFWORLD_FIDELITY.source.commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="reflexion.alfworld.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    max_action_calls = (
        REFLEXION_ALFWORLD_FIDELITY.max_trials
        * REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial
        * REFLEXION_ALFWORLD_FIDELITY.action_candidate_attempts
    )
    max_turns = (
        REFLEXION_ALFWORLD_FIDELITY.max_trials
        * REFLEXION_ALFWORLD_FIDELITY.max_turns_per_trial
    )
    builder = MethodProgramBuilder(identity, entrypoint="start_trial")
    builder.route("start_trial", "reflexion.trial.start", _start_trial, ("action", "return"), max_visits=REFLEXION_ALFWORLD_FIDELITY.max_trials + 1)
    builder.agent("action", "reflexion.action.generate", _ACTION_AGENT_ID, ("validate_action",), view_handler=_action_view, max_visits=max_action_calls)
    builder.route("validate_action", "reflexion.action.validate", _validate_action, ("action", "record_think", "prepare_action"), max_visits=max_action_calls)
    builder.compute("prepare_action", "reflexion.action.prepare", _prepare_action, ("environment",), max_visits=max_turns)
    builder.capability("environment", "reflexion.environment.act", _ACTION_CAPABILITY, ("record_action",), effect_class=EffectClass.RECONCILABLE, max_visits=max_turns, evidence_obligations=("environment.action.effect",))
    builder.route("record_action", "reflexion.observation.record", _record_action, ("action", "complete_failed_trial", "return"), max_visits=max_turns)
    builder.route("record_think", "reflexion.think.record", _record_think, ("action", "complete_failed_trial", "return"), max_visits=max_turns)
    builder.route("complete_failed_trial", "reflexion.trial.complete", _complete_failed_trial, ("reflection", "return"), max_visits=REFLEXION_ALFWORLD_FIDELITY.max_trials)
    builder.agent("reflection", "reflexion.reflection.generate", _REFLECTION_AGENT_ID, ("record_reflection",), view_handler=_reflection_view, max_visits=REFLEXION_ALFWORLD_FIDELITY.max_trials - 1)
    builder.compute("record_reflection", "reflexion.reflection.record", _record_reflection, ("prepare_reset",), max_visits=REFLEXION_ALFWORLD_FIDELITY.max_trials - 1)
    builder.compute("prepare_reset", "reflexion.environment.reset.prepare", _reset_payload, ("reset",), max_visits=REFLEXION_ALFWORLD_FIDELITY.max_trials - 1)
    builder.capability("reset", "reflexion.environment.reset", _RESET_CAPABILITY, ("record_reset",), effect_class=EffectClass.IDEMPOTENT, max_visits=REFLEXION_ALFWORLD_FIDELITY.max_trials - 1)
    builder.compute("record_reset", "reflexion.environment.reset.record", _record_reset, ("start_trial",), max_visits=REFLEXION_ALFWORLD_FIDELITY.max_trials - 1)
    builder.return_node("return", "reflexion.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ACTION_CAPABILITY, _RESET_CAPABILITY),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "reflexion.trajectory",
            "reflexion.reflection-memory",
            "environment.action.effect",
        ),
        metric_names=("task_success", "first_success_trial", "trials_used"),
        artifact_kinds=("reflexion_trajectory", "reflexion_reflection_memory"),
    )


REFLEXION_ALFWORLD_METHOD_PROGRAM = build_reflexion_alfworld_method_program()

__all__ = [
    "REFLEXION_ALFWORLD_METHOD_PROGRAM",
    "build_reflexion_alfworld_method_program",
    "reflexion_alfworld_initial_state",
]
