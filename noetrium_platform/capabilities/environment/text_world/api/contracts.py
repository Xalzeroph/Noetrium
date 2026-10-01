from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json, thaw_json


class TextWorldActionKind(StrEnum):
    COMMAND = "command"
    SPEAK = "speak"
    LOOK = "look"
    INVENTORY = "inventory"


@dataclass(frozen=True, slots=True)
class TextWorldContextPolicy:
    """Bounds for model-visible textual world state and recent trajectory."""

    max_observation_chars: int = 16_000
    max_history_turns: int = 8
    include_last_action_feedback: bool = True

    def __post_init__(self) -> None:
        if type(self.max_observation_chars) is not int or self.max_observation_chars < 1_000:
            raise ValueError("text-world max_observation_chars is invalid")
        if type(self.max_history_turns) is not int or self.max_history_turns < 0:
            raise ValueError("text-world max_history_turns is invalid")
        if type(self.include_last_action_feedback) is not bool:
            raise TypeError(
                "text-world include_last_action_feedback must be boolean"
            )

    def record(self) -> dict[str, JsonValue]:
        return {
            "max_observation_chars": self.max_observation_chars,
            "max_history_turns": self.max_history_turns,
            "include_last_action_feedback": self.include_last_action_feedback,
        }


@dataclass(frozen=True, slots=True)
class TextWorldEnvironmentSpec:
    environment_id: str
    revision: str
    turn_based: bool = True
    action_vocabulary: tuple[TextWorldActionKind, ...] = ()
    metadata: dict[str, JsonValue] = field(default_factory=dict)
    context_policy: TextWorldContextPolicy = field(default_factory=TextWorldContextPolicy)

    def __post_init__(self) -> None:
        if not self.environment_id.strip() or not self.revision.strip():
            raise ValueError("text-world environment identity is required")
        if not isinstance(self.turn_based, bool):
            raise TypeError("text-world turn_based flag must be boolean")
        if any(not isinstance(item, TextWorldActionKind) for item in self.action_vocabulary):
            raise TypeError("text-world actions must use TextWorldActionKind")
        if len(self.action_vocabulary) != len(set(self.action_vocabulary)):
            raise ValueError("text-world actions must be unique")
        object.__setattr__(self, "metadata", freeze_json(self.metadata or {}))

    @property
    def spec_digest(self) -> str:
        return canonical_digest({
            "environment_id": self.environment_id, "revision": self.revision,
            "turn_based": self.turn_based,
            "action_vocabulary": [item.value for item in self.action_vocabulary],
            "metadata": thaw_json(self.metadata),
            "context_policy": self.context_policy.record(),
        })


__all__ = ["TextWorldActionKind", "TextWorldContextPolicy", "TextWorldEnvironmentSpec"]
