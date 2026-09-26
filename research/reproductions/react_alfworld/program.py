from __future__ import annotations
from research.reproductions._support import AgentLoopResult
from research.reproductions._support import JsonObject, JsonValue, canonical_digest
from collections.abc import Mapping
from typing import Protocol, runtime_checkable
from .fidelity import REACT_ALFWORLD_FIDELITY
from .semantics import normalize_model_action, visible_observation
from .trajectory import ReactAlfworldTranscript, ReactTrajectoryStep
_MODEL_AGENT_ID = 'react.model'
_ENVIRONMENT_CAPABILITY_ID = 'environment.act'
_ENVIRONMENT_ACTION_TYPE = 'command'

@runtime_checkable
class ReactModelPort(Protocol):
    """Paper-owned generation seam; deployment/transport remains platform-owned."""

    def complete(self, prompt: str, context: object) -> str:
        ...

def _required_text(state: Mapping[str, JsonValue], key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str):
        raise ValueError(f'ReAct state requires text field: {key}')
    return value

def _required_int(state: Mapping[str, JsonValue], key: str) -> int:
    value = state.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f'ReAct state requires non-negative integer field: {key}')
    return value

def _trajectory_steps(state: Mapping[str, JsonValue]) -> tuple[ReactTrajectoryStep, ...]:
    raw = state.get('steps', ())
    if not isinstance(raw, tuple):
        raise TypeError('ReAct state steps must be a tuple')
    steps: list[ReactTrajectoryStep] = []
    for row in raw:
        if not isinstance(row, Mapping):
            raise TypeError('ReAct state step must be a mapping')
        action = row.get('action')
        observation = row.get('observation')
        if not isinstance(action, str) or not isinstance(observation, str):
            raise TypeError('ReAct state step requires action/observation text')
        steps.append(ReactTrajectoryStep(action, observation))
    return tuple(steps)

def _append_step(state: Mapping[str, JsonValue], *, action: str, observation: str) -> tuple[JsonObject, ...]:
    existing = tuple(({'action': step.action, 'observation': step.observation} for step in _trajectory_steps(state)))
    return (*existing, {'action': action, 'observation': observation})

def react_alfworld_initial_state(*, base_prompt: str, initial_observation: str) -> JsonObject:
    if not isinstance(base_prompt, str) or not base_prompt:
        raise ValueError('ReAct base_prompt is required')
    if not isinstance(initial_observation, str):
        raise TypeError('ReAct initial_observation must be text')
    return {'base_prompt': base_prompt, 'initial_observation': initial_observation, 'steps': (), 'turn': 0, 'pending_action': '', 'last_observation': initial_observation, 'success': False, 'done': False}

def _react_agent_view(request: object) -> JsonObject:
    """Project exactly the paper-visible ReAct transcript inputs."""
    return {'base_prompt': _required_text(request.state, 'base_prompt'), 'initial_observation': _required_text(request.state, 'initial_observation'), 'steps': tuple(({'action': step.action, 'observation': step.observation} for step in _trajectory_steps(request.state))), 'turn': _required_int(request.state, 'turn'), 'last_observation': _required_text(request.state, 'last_observation')}

class ReactAlfworldAgentLoop:
    """ReAct model decision node; owns only paper prompt/action semantics."""

    def __init__(self, model: ReactModelPort) -> None:
        if not isinstance(model, ReactModelPort):
            raise TypeError('ReAct agent loop requires ReactModelPort')
        self._model = model

    def run(self, request: object) -> MethodAgentResult:
        if request.agent_id != _MODEL_AGENT_ID:
            raise ValueError(f'unexpected ReAct agent id: {request.agent_id}')
        transcript = ReactAlfworldTranscript(initial_observation=_required_text(request.view, 'initial_observation'), steps=_trajectory_steps(request.view))
        prompt = transcript.render(_required_text(request.view, 'base_prompt'))
        action = normalize_model_action(self._model.complete(prompt, request.context))
        return AgentLoopResult(value=action, state_update={'pending_action': action})

def _prepare_environment(request: object) -> MethodNodeResult:
    action = normalize_model_action(_required_text(request.state, 'pending_action'))
    envelope = request.environment_action(_ENVIRONMENT_ACTION_TYPE, {'text': action})
    return request.transition(value=envelope, state_update=envelope)

def _environment_observation(value: JsonValue) -> tuple[str, bool, bool]:
    if not isinstance(value, Mapping):
        raise TypeError('ReAct environment capability result must be a mapping')
    observation = value.get('observation')
    if not isinstance(observation, Mapping):
        raise TypeError('ReAct environment capability result requires observation')
    payload = observation.get('payload')
    if isinstance(payload, str):
        return (payload, False, False)
    if not isinstance(payload, Mapping):
        raise TypeError('ReAct ALFWorld observation payload must be text or mapping')
    text = payload.get('text', payload.get('observation'))
    if not isinstance(text, str):
        raise TypeError('ReAct ALFWorld observation payload requires text')
    info = payload.get('info', {})
    won = bool(info.get('won', False)) if isinstance(info, Mapping) else False
    done = bool(payload.get('done', won))
    return (text, won, done)

def _record_environment(request: object) -> MethodNodeResult:
    action = normalize_model_action(_required_text(request.state, 'pending_action'))
    (raw_observation, success, done) = _environment_observation(request.previous_value)
    observation = visible_observation(action, raw_observation)
    turn = _required_int(request.state, 'turn') + 1
    return request.transition(value={'action': action, 'raw_environment_observation': raw_observation, 'observation': observation, 'turn': turn, 'success': success, 'done': done}, state_update={'steps': _append_step(request.state, action=action, observation=observation), 'turn': turn, 'last_observation': observation, 'success': success, 'done': done})

def _route_terminal(request: object) -> MethodNodeResult:
    turn = _required_int(request.state, 'turn')
    success = request.state.get('success') is True
    done = request.state.get('done') is True
    terminal = done or turn >= REACT_ALFWORLD_FIDELITY.max_turns
    return request.transition(value={'terminal': terminal, 'success': success, 'turn': turn}, next_node='return' if terminal else 'model', checkpoint=True, checkpoint_value={'turn': turn, 'success': success, 'done': done})

def _return_result(request: object) -> MethodNodeResult:
    return request.transition(value={'success': request.state.get('success') is True, 'turns': _required_int(request.state, 'turn'), 'last_observation': _required_text(request.state, 'last_observation'), 'steps': tuple(({'action': step.action, 'observation': step.observation} for step in _trajectory_steps(request.state)))})

def configure_method(method):
    """Compile the released ReAct ALFWorld loop into the universal MethodProgram ABI."""
    configuration: JsonObject = {'paper': 'ReAct: Synergizing Reasoning and Acting in Language Models', 'source_repository': REACT_ALFWORLD_FIDELITY.source.repository, 'source_artifacts': REACT_ALFWORLD_FIDELITY.source.artifacts, 'reference_model': REACT_ALFWORLD_FIDELITY.reference_model, 'temperature': REACT_ALFWORLD_FIDELITY.temperature, 'max_output_tokens': REACT_ALFWORLD_FIDELITY.max_output_tokens, 'stop_sequences': REACT_ALFWORLD_FIDELITY.stop_sequences, 'max_turns': REACT_ALFWORLD_FIDELITY.max_turns, 'think_prefix': REACT_ALFWORLD_FIDELITY.think_prefix, 'think_observation': REACT_ALFWORLD_FIDELITY.think_observation, 'think_steps_environment': True}
    method.agent('model', 'react.model.generate', _MODEL_AGENT_ID, ('prepare_environment',), view=_react_agent_view, max_visits=REACT_ALFWORLD_FIDELITY.max_turns)
    method.compute('prepare_environment', 'react.environment.prepare', _prepare_environment, ('environment',), max_visits=REACT_ALFWORLD_FIDELITY.max_turns)
    method.capability('environment', 'react.environment.act', _ENVIRONMENT_CAPABILITY_ID, ('record_environment',), effect='reconcilable', max_visits=REACT_ALFWORLD_FIDELITY.max_turns, evidence=('environment.effect',))
    method.compute('record_environment', 'react.environment.record', _record_environment, ('terminal',), max_visits=REACT_ALFWORLD_FIDELITY.max_turns)
    method.route('terminal', 'react.terminal.route', _route_terminal, ('model', 'return'), max_visits=REACT_ALFWORLD_FIDELITY.max_turns)
    method.return_node('return', 'react.result', _return_result)
    method.configure(configuration)
    method.requires(_ENVIRONMENT_CAPABILITY_ID)
    method.policy(execution='effect_recorded', evidence=('react.trajectory', 'environment.effect'), metrics=('episode_success', 'turn_count'), artifacts=('react_trajectory',))
    return method
METHOD_SPEC = {'method_id': 'react-alfworld', 'version': 'paper-era-19c6bae5', 'semantic_contract': 'react-alfworld.method.v1', 'entrypoint': 'model'}
METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = 'model'
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}
__all__ = ['ReactAlfworldAgentLoop', 'ReactModelPort', 'react_alfworld_initial_state', 'METHOD_SPEC', 'METHOD_CONFIGURER', 'METHOD_ENTRYPOINT', 'METHOD_CONFIGURER_ARGS', 'METHOD_CONFIGURER_KWARGS', 'configure_method']
