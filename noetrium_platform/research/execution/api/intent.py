from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.research.execution.command.api import ExecutionCommand
from noetrium_platform.research.execution.operation.api import (
    EffectId,
    OperationEffectProfile,
    OperationId,
    OperationSnapshot,
)


def _optional_effect_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text when present")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ExecutionOperationIntent:
    """Parent-level binding of one durable command intent to one stable operation identity."""

    command: ExecutionCommand
    operation_id: OperationId
    parent_operation_id: OperationId | None = None
    effect_profile: OperationEffectProfile = OperationEffectProfile.NONE
    effect_id: EffectId | None = None
    effect_request_id: str | None = None
    effect_request_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.command, ExecutionCommand):
            raise TypeError("execution intent command must be ExecutionCommand")
        if not isinstance(self.operation_id, OperationId):
            raise TypeError("execution intent operation_id must be OperationId")
        if self.parent_operation_id == self.operation_id:
            raise ValueError("execution operation cannot be its own parent")
        request_id = _optional_effect_text(self.effect_request_id, "effect_request_id")
        request_digest = _optional_effect_text(self.effect_request_digest, "effect_request_digest")
        if self.effect_profile is OperationEffectProfile.NONE:
            if self.effect_id is not None or request_id is not None or request_digest is not None:
                raise ValueError("effect-free execution intent cannot carry external effect identity")
        elif self.effect_id is None or request_id is None or request_digest is None:
            raise ValueError("effectful execution intent requires effect_id/request_id/request_digest")
        object.__setattr__(self, "effect_request_id", request_id)
        object.__setattr__(self, "effect_request_digest", request_digest)


@dataclass(frozen=True, slots=True)
class ExecutionIntentReceipt:
    command: ExecutionCommand
    operation: OperationSnapshot
    command_created: bool
    operation_created: bool


class ExecutionIntentPort(Protocol):
    def submit(self, intent: ExecutionOperationIntent) -> ExecutionIntentReceipt: ...


__all__ = ["ExecutionIntentPort", "ExecutionIntentReceipt", "ExecutionOperationIntent"]
