from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.composition import environment_action_capability_payload
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext, JsonObject, JsonValue, canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import REACT_ALFWORLD_FIDELITY
from .semantics import normalize_model_action, visible_observation
from .trajectory import ReactAlfworldTranscript, ReactTrajectoryStep

_MODEL_AGENT_ID = "react.model"
_ENVIRONMENT_CAPABILITY_ID = "environment.act"
_ENVIRONMENT_ACTION_TYPE = "command"


@runtime_checkable
class ReactModelPort(Protocol):
    """Paper-owned generation seam; deployment/transport remains platform-owned."""

    def complete(self, prompt: str, context: ExecutionContext) -> str: ...


def _required_text(state: Mapping[str, JsonValue], key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str):
        raise ValueError(f"ReAct state requires text field: {key}")
    return value


def _required_int(state: Mapping[str, JsonValue], key: str) -> int:
    value = state.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f"ReAct state requires non-negative integer field: {key}")
    return value


def _trajectory_steps(state: Mapping[str, JsonValue]) -> tuple[ReactTrajectoryStep, ...]:
    raw = state.get("steps", ())
    if not isinstance(raw, tuple):
        raise TypeError("ReAct state steps must be a tuple")
    steps: list[ReactTrajectoryStep] = []
    for row in raw:
        if not isinstance(row, Mapping):
            raise TypeError("ReAct state step must be a mapping")
        action = row.get("action")
        observation = row.get("observation")
        if not isinstance(action, str) or not isinstance(observation, str):
            raise TypeError("ReAct state step requires action/observation text")
        steps.append(ReactTrajectoryStep(action, observation))
    return tuple(steps)


def _append_step(
    state: Mapping[str, JsonValue],
    *,
    action: str,
    observation: str,
) -> tuple[JsonObject, ...]:
    existing = tuple(
        {"action": step.action, "observation": step.observation}
        for step in _trajectory_steps(state)
    )
    return (*existing, {"action": action, "observation": observation})


def react_alfworld_initial_state(*, base_prompt: str, initial_observation: str) -> JsonObject:
    if not isinstance(base_prompt, str) or not base_prompt:
        raise ValueError("ReAct base_prompt is required")
    if not isinstance(initial_observation, str):
        raise TypeError("ReAct initial_observation must be text")
    return {
        "base_prompt": base_prompt,
        "initial_observation": initial_observation,
        "steps": (),
        "turn": 0,
        "pending_action": "",
        "last_observation": initial_observation,
        "success": False,
        "done": False,
    }


def _react_agent_view(request: MethodNodeRequest) -> JsonObject:
    """Project exactly the paper-visible ReAct transcript inputs."""

    return {
        "base_prompt": _required_text(request.state, "base_prompt"),
        "initial_observation": _required_text(request.state, "initial_observation"),
        "steps": tuple(
            {"action": step.action, "observation": step.observation}
            for step in _trajectory_steps(request.state)
        ),
        "turn": _required_int(request.state, "turn"),
        "last_observation": _required_text(request.state, "last_observation"),
    }


class ReactAlfworldAgentLoop:
    """ReAct model decision node; owns only paper prompt/action semantics."""

    def __init__(self, model: ReactModelPort) -> None:
        if not isinstance(model, ReactModelPort):
            raise TypeError("ReAct agent loop requires ReactModelPort")
        self._model = model

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id != _MODEL_AGENT_ID:
            raise ValueError(f"unexpected ReAct agent id: {request.agent_id}")
        transcript = ReactAlfworldTranscript(
            initial_observation=_required_text(request.view, "initial_observation"),
            steps=_trajectory_steps(request.view),
        )
        prompt = transcript.render(_required_text(request.view, "base_prompt"))
        action = normalize_model_action(self._model.complete(prompt, request.context))
        return MethodAgentResult(value=action, state_update={"pending_action": action})


def _prepare_environment(request: MethodNodeRequest) -> MethodNodeResult:
    action = normalize_model_action(_required_text(request.state, "pending_action"))
    envelope = environment_action_capability_payload(_ENVIRONMENT_ACTION_TYPE, {"text": action})
    return MethodNodeResult(
        value={"action": action},
        state_update=envelope,
    )


def _environment_observation(value: JsonValue) -> tuple[str, bool, bool]:
    if not isinstance(value, Mapping):
        raise TypeError("ReAct environment capability result must be a mapping")
    observation = value.get("observation")
    if not isinstance(observation, Mapping):
        raise TypeError("ReAct environment capability result requires observation")
    payload = observation.get("payload")
    if isinstance(payload, str):
        return payload, False, False
    if not isinstance(payload, Mapping):
        raise TypeError("ReAct ALFWorld observation payload must be text or mapping")
    text = payload.get("text", payload.get("observation"))
    if not isinstance(text, str):
        raise TypeError("ReAct ALFWorld observation payload requires text")
    info = payload.get("info", {})
    won = bool(info.get("won", False)) if isinstance(info, Mapping) else False
    done = bool(payload.get("done", won))
    return text, won, done


def _record_environment(request: MethodNodeRequest) -> MethodNodeResult:
    action = normalize_model_action(_required_text(request.state, "pending_action"))
    raw_observation, success, done = _environment_observation(request.previous_value)
    observation = visible_observation(action, raw_observation)
    turn = _required_int(request.state, "turn") + 1
    return MethodNodeResult(
        value={
            "action": action,
            "raw_environment_observation": raw_observation,
            "observation": observation,
            "turn": turn,
            "success": success,
            "done": done,
        },
        state_update={
            "steps": _append_step(request.state, action=action, observation=observation),
            "turn": turn,
            "last_observation": observation,
            "success": success,
            "done": done,
        },
    )


def _route_terminal(request: MethodNodeRequest) -> MethodNodeResult:
    turn = _required_int(request.state, "turn")
    success = request.state.get("success") is True
    done = request.state.get("done") is True
    terminal = done or turn >= REACT_ALFWORLD_FIDELITY.max_turns
    return MethodNodeResult(
        value={"terminal": terminal, "success": success, "turn": turn},
        next_node="return" if terminal else "model",
        checkpoint=True,
        checkpoint_value={"turn": turn, "success": success, "done": done},
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "success": request.state.get("success") is True,
            "turns": _required_int(request.state, "turn"),
            "last_observation": _required_text(request.state, "last_observation"),
            "steps": tuple(
                {"action": step.action, "observation": step.observation}
                for step in _trajectory_steps(request.state)
            ),
        }
    )


def build_react_alfworld_method_program() -> MethodProgram:
    """Compile the released ReAct ALFWorld loop into the universal MethodProgram ABI."""

    configuration: JsonObject = {
        "paper": "ReAct: Synergizing Reasoning and Acting in Language Models",
        "source_repository": REACT_ALFWORLD_FIDELITY.source.repository,
        "source_artifacts": REACT_ALFWORLD_FIDELITY.source.artifacts,
        "reference_model": REACT_ALFWORLD_FIDELITY.reference_model,
        "temperature": REACT_ALFWORLD_FIDELITY.temperature,
        "max_output_tokens": REACT_ALFWORLD_FIDELITY.max_output_tokens,
        "stop_sequences": REACT_ALFWORLD_FIDELITY.stop_sequences,
        "max_turns": REACT_ALFWORLD_FIDELITY.max_turns,
        "think_prefix": REACT_ALFWORLD_FIDELITY.think_prefix,
        "think_observation": REACT_ALFWORLD_FIDELITY.think_observation,
        "think_steps_environment": True,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="react-alfworld",
            implementation_version="paper-era-19c6bae5",
            abi_version="noetrium.method-machine.v1",
            schema_version="react-alfworld.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="model")
    builder.agent(
        "model",
        "react.model.generate",
        _MODEL_AGENT_ID,
        ("prepare_environment",),
        view_handler=_react_agent_view,
        max_visits=REACT_ALFWORLD_FIDELITY.max_turns,
    )
    builder.compute(
        "prepare_environment",
        "react.environment.prepare",
        _prepare_environment,
        ("environment",),
        max_visits=REACT_ALFWORLD_FIDELITY.max_turns,
    )
    builder.capability(
        "environment",
        "react.environment.act",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_environment",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=REACT_ALFWORLD_FIDELITY.max_turns,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_environment",
        "react.environment.record",
        _record_environment,
        ("terminal",),
        max_visits=REACT_ALFWORLD_FIDELITY.max_turns,
    )
    builder.route(
        "terminal",
        "react.terminal.route",
        _route_terminal,
        ("model", "return"),
        max_visits=REACT_ALFWORLD_FIDELITY.max_turns,
    )
    builder.return_node("return", "react.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=("react.trajectory", "environment.effect"),
        metric_names=("episode_success", "turn_count"),
        artifact_kinds=("react_trajectory",),
    )


REACT_ALFWORLD_METHOD_PROGRAM = build_react_alfworld_method_program()

__all__ = [
    "REACT_ALFWORLD_METHOD_PROGRAM",
    "ReactAlfworldAgentLoop",
    "ReactModelPort",
    "build_react_alfworld_method_program",
    "react_alfworld_initial_state",
]
