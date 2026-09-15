"""Matched-stack ReAct/ALFWorld downstream reproduction semantics.

This package owns only paper-specific scientific semantics. Noetrium owns the
agent loop, model transport, environment lifecycle, Journal, recovery,
evidence and experiment execution.
"""

from .fidelity import REACT_ALFWORLD_FIDELITY, ReactAlfworldFidelity
from .semantics import (
    ReactProtocolError,
    is_think_action,
    normalize_model_action,
    visible_observation,
)
from .trajectory import ReactAlfworldTranscript, render_react_alfworld_transcript

__all__ = [
    "REACT_ALFWORLD_FIDELITY",
    "ReactAlfworldFidelity",
    "ReactAlfworldTranscript",
    "ReactProtocolError",
    "is_think_action",
    "normalize_model_action",
    "render_react_alfworld_transcript",
    "visible_observation",
]
