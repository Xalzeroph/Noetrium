from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonInput,
    JsonValue,
    OperationResult,
    require_sha256,
)


@dataclass(frozen=True, slots=True)
class TrialCycleExecution:
    context_text: str
    primary_result: object
    final_context: ExecutionContext
    operation_results: tuple[OperationResult[JsonValue], ...]


class ExecutionTrialProtocolKind(StrEnum):
    RUNTIME_PROGRAM = "runtime-program"


@runtime_checkable
class ExecutionTrialProtocolPort(Protocol):
    """Execution-owned trial protocol ABI consumed by Experimentation."""

    protocol_kind: ExecutionTrialProtocolKind
    protocol_id: str
    surface_id: str
    configuration_digest: str

    def run(
        self,
        surface: object,
        context: ExecutionContext,
        *,
        task: object,
        input_kind: str,
        input_payload: JsonInput,
    ) -> TrialCycleExecution: ...


def require_execution_trial_protocol(value: object) -> ExecutionTrialProtocolPort:
    if not isinstance(value, ExecutionTrialProtocolPort):
        raise TypeError("trial protocol must satisfy ExecutionTrialProtocolPort")
    if value.protocol_kind is not ExecutionTrialProtocolKind.RUNTIME_PROGRAM:
        raise TypeError(
            "trial protocol kind must be ExecutionTrialProtocolKind.RUNTIME_PROGRAM"
        )
    if type(value.protocol_id) is not str or not value.protocol_id.strip():
        raise ValueError("trial protocol_id must be stable non-empty text")
    if type(value.surface_id) is not str or not value.surface_id.strip():
        raise ValueError("trial surface_id must be stable non-empty text")
    require_sha256(
        value.configuration_digest,
        "execution trial protocol configuration_digest",
    )
    return value


__all__ = [
    "ExecutionTrialProtocolKind",
    "ExecutionTrialProtocolPort",
    "TrialCycleExecution",
    "require_execution_trial_protocol",
]
