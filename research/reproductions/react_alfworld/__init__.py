"""Matched-stack ReAct/ALFWorld downstream reproduction semantics.

This package owns only paper-specific scientific semantics. Noetrium owns the
method-machine lifecycle, model transport, environment lifecycle, Journal,
recovery, evidence and experiment execution.
"""
from .fidelity import REACT_ALFWORLD_FIDELITY, ReactAlfworldFidelity
from .program import ReactAlfworldAgentLoop, ReactModelPort, react_alfworld_initial_state, METHOD_SPEC, METHOD_CONFIGURER, METHOD_ENTRYPOINT, METHOD_CONFIGURER_ARGS, METHOD_CONFIGURER_KWARGS, configure_method
from .semantics import notebook_initial_observation, notebook_step_observation, ReactProtocolError, is_think_action, normalize_model_action, visible_observation
from .study import REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL, build_react_alfworld_released_study
from .trajectory import ReactAlfworldTranscript, ReactTrajectoryStep, render_react_alfworld_transcript
__all__ = ['notebook_initial_observation', 'notebook_step_observation', 'REACT_ALFWORLD_FIDELITY', 'REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL', 'ReactAlfworldAgentLoop', 'ReactAlfworldFidelity', 'ReactAlfworldTranscript', 'ReactModelPort', 'ReactProtocolError', 'ReactTrajectoryStep', 'build_react_alfworld_released_study', 'is_think_action', 'normalize_model_action', 'react_alfworld_initial_state', 'render_react_alfworld_transcript', 'visible_observation', 'METHOD_SPEC', 'METHOD_CONFIGURER', 'METHOD_ENTRYPOINT', 'METHOD_CONFIGURER_ARGS', 'METHOD_CONFIGURER_KWARGS', 'configure_method']
