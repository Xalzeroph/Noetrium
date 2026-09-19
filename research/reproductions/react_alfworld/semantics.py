from __future__ import annotations

from .fidelity import REACT_ALFWORLD_FIDELITY


class ReactProtocolError(ValueError):
    """The model/environment exchange no longer matches ReAct fidelity."""


def normalize_model_action(text: str) -> str:
    """Accept exactly one non-empty model line.

    The original run used a newline stop sequence. Silently taking the first
    line from a multi-line provider response would hide transport drift, so a
    matched reproduction fails closed instead.
    """

    if not isinstance(text, str):
        raise TypeError("ReAct model action must be text")
    normalized = text.strip()
    if not normalized:
        raise ReactProtocolError("ReAct model action is empty")
    if "\n" in normalized or "\r" in normalized:
        raise ReactProtocolError("ReAct model action must contain exactly one line")
    return normalized


def is_think_action(action: str) -> bool:
    action = normalize_model_action(action)
    return action.startswith(REACT_ALFWORLD_FIDELITY.think_prefix)


def visible_observation(action: str, environment_observation: str) -> str:
    action = normalize_model_action(action)
    if not isinstance(environment_observation, str):
        raise TypeError("ReAct environment observation must be text")
    if is_think_action(action):
        return REACT_ALFWORLD_FIDELITY.think_observation
    return environment_observation


__all__ = [
    "ReactProtocolError",
    "is_think_action",
    "normalize_model_action",
    "visible_observation",
]
