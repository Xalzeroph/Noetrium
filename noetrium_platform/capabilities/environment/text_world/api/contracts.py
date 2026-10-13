from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from noetrium_platform.capabilities.environment.api.semantics import (
    environment_capabilities,
    environment_unit,
    require_environment_unit,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


class TextWorldActionKind(StrEnum):
    COMMAND = "command"
    SPEAK = "speak"
    LOOK = "look"
    INVENTORY = "inventory"


def text_world_context_policy(
    *,
    max_observation_chars: int = 16_000,
    max_history_turns: int = 8,
    include_last_action_feedback: bool = True,
) -> Mapping[str, JsonValue]:
    if type(max_observation_chars) is not int or max_observation_chars < 1_000:
        raise ValueError("text-world max_observation_chars is invalid")
    if type(max_history_turns) is not int or max_history_turns < 0:
        raise ValueError("text-world max_history_turns is invalid")
    if type(include_last_action_feedback) is not bool:
        raise TypeError("text-world include_last_action_feedback must be boolean")
    return freeze_json({
        "max_observation_chars": max_observation_chars,
        "max_history_turns": max_history_turns,
        "include_last_action_feedback": include_last_action_feedback,
    })


def text_world_environment_unit(
    environment_id: str,
    revision: str,
    *,
    turn_based: bool = True,
    action_vocabulary: tuple[TextWorldActionKind, ...] = (),
    metadata: Mapping[str, JsonValue] | None = None,
    context_policy: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    if type(turn_based) is not bool:
        raise TypeError("text-world turn_based flag must be boolean")
    if type(action_vocabulary) is not tuple or any(
        not isinstance(item, TextWorldActionKind) for item in action_vocabulary
    ):
        raise TypeError("text-world actions must use TextWorldActionKind tuple")
    if len(action_vocabulary) != len(set(action_vocabulary)):
        raise ValueError("text-world actions must be unique")
    policy = (
        text_world_context_policy()
        if context_policy is None
        else freeze_json(context_policy)
    )
    return environment_unit(
        environment_id,
        category="text_world",
        revision=revision,
        capabilities=tuple(item.value for item in action_vocabulary) or ("observe",),
        parameters={
            "turn_based": turn_based,
            "metadata": freeze_json({} if metadata is None else metadata),
            "context_policy": policy,
        },
    )


def require_text_world_environment(value: NoetriumUnit) -> NoetriumUnit:
    value = require_environment_unit(value)
    if value.parameters["category"] != "text_world":
        raise TypeError("text-world environment Unit must have category='text_world'")
    return value


def text_world_environment_context_policy(
    value: NoetriumUnit,
) -> Mapping[str, JsonValue]:
    return require_text_world_environment(value).parameters["context_policy"]


def text_world_environment_actions(
    value: NoetriumUnit,
) -> tuple[TextWorldActionKind, ...]:
    return tuple(
        TextWorldActionKind(item)
        for item in environment_capabilities(require_text_world_environment(value))
        if item in {kind.value for kind in TextWorldActionKind}
    )


__all__ = [
    "TextWorldActionKind",
    "require_text_world_environment",
    "text_world_context_policy",
    "text_world_environment_actions",
    "text_world_environment_context_policy",
    "text_world_environment_unit",
]
