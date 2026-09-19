"""Pure checkpoint capture-trigger policy.

This module decides only *when to request* a checkpoint. It never decides
whether a snapshot is authoritative or resumable; that remains a Machine
Journal/checkpoint-manifest responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math

from noetrium_platform.foundation.kernel.kernel import canonical_digest


class CheckpointTriggerKind(StrEnum):
    MANUAL = "manual"
    TURNS = "turns"
    TOKENS = "tokens"
    ELAPSED_SECONDS = "elapsed_seconds"


@dataclass(frozen=True, slots=True)
class CheckpointTrigger:
    kind: CheckpointTriggerKind
    threshold: int | float | None = None
    trigger_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CheckpointTriggerKind):
            raise TypeError("checkpoint trigger kind must be CheckpointTriggerKind")
        if self.kind is CheckpointTriggerKind.MANUAL:
            if self.threshold is not None:
                raise ValueError("manual checkpoint trigger cannot have a threshold")
        elif self.kind in {CheckpointTriggerKind.TURNS, CheckpointTriggerKind.TOKENS}:
            if type(self.threshold) is not int or self.threshold <= 0:
                raise ValueError(
                    f"{self.kind.value} checkpoint threshold must be a positive integer"
                )
        else:
            if (
                isinstance(self.threshold, bool)
                or not isinstance(self.threshold, (int, float))
                or not math.isfinite(float(self.threshold))
                or self.threshold <= 0
            ):
                raise ValueError(
                    "elapsed checkpoint threshold must be finite and positive"
                )
        object.__setattr__(
            self,
            "trigger_digest",
            canonical_digest(
                {
                    "kind": self.kind.value,
                    "threshold": self.threshold,
                }
            ),
        )

    @classmethod
    def manual(cls) -> "CheckpointTrigger":
        return cls(CheckpointTriggerKind.MANUAL)

    @classmethod
    def every_turns(cls, turns: int) -> "CheckpointTrigger":
        return cls(CheckpointTriggerKind.TURNS, turns)

    @classmethod
    def every_tokens(cls, tokens: int) -> "CheckpointTrigger":
        return cls(CheckpointTriggerKind.TOKENS, tokens)

    @classmethod
    def every_seconds(cls, seconds: float) -> "CheckpointTrigger":
        return cls(CheckpointTriggerKind.ELAPSED_SECONDS, seconds)


@dataclass(frozen=True, slots=True)
class CheckpointCapturePolicy:
    triggers: tuple[CheckpointTrigger, ...]
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.triggers) is not tuple or any(
            type(row) is not CheckpointTrigger for row in self.triggers
        ):
            raise TypeError("checkpoint capture policy triggers must be typed")
        if not self.triggers:
            raise ValueError("checkpoint capture policy requires at least one trigger")
        ordered = tuple(sorted(self.triggers, key=lambda row: row.kind.value))
        kinds = tuple(row.kind for row in ordered)
        if len(kinds) != len(set(kinds)):
            raise ValueError("checkpoint capture policy trigger kinds must be unique")
        object.__setattr__(self, "triggers", ordered)
        object.__setattr__(
            self,
            "policy_digest",
            canonical_digest(tuple(row.trigger_digest for row in ordered)),
        )

    def should_request(
        self,
        *,
        turns_since_checkpoint: int = 0,
        tokens_since_checkpoint: int = 0,
        elapsed_seconds: float = 0.0,
        manual: bool = False,
    ) -> bool:
        if type(turns_since_checkpoint) is not int or turns_since_checkpoint < 0:
            raise ValueError("turns_since_checkpoint must be a non-negative integer")
        if type(tokens_since_checkpoint) is not int or tokens_since_checkpoint < 0:
            raise ValueError("tokens_since_checkpoint must be a non-negative integer")
        if (
            isinstance(elapsed_seconds, bool)
            or not isinstance(elapsed_seconds, (int, float))
            or not math.isfinite(float(elapsed_seconds))
            or elapsed_seconds < 0
        ):
            raise ValueError("elapsed_seconds must be finite and non-negative")
        if type(manual) is not bool:
            raise TypeError("manual must be boolean")

        for trigger in self.triggers:
            if trigger.kind is CheckpointTriggerKind.MANUAL and manual:
                return True
            if (
                trigger.kind is CheckpointTriggerKind.TURNS
                and turns_since_checkpoint >= trigger.threshold
            ):
                return True
            if (
                trigger.kind is CheckpointTriggerKind.TOKENS
                and tokens_since_checkpoint >= trigger.threshold
            ):
                return True
            if (
                trigger.kind is CheckpointTriggerKind.ELAPSED_SECONDS
                and elapsed_seconds >= trigger.threshold
            ):
                return True
        return False


__all__ = [
    "CheckpointCapturePolicy",
    "CheckpointTrigger",
    "CheckpointTriggerKind",
]
