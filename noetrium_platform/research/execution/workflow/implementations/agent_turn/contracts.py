from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.participant.agent.api import AgentTurnResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonValue, OperationResult


@runtime_checkable
class AgentTurnOperationPort(Protocol):
    def agent_turn(
        self,
        task: object,
        input_payload: object,
        context: ExecutionContext,
    ) -> tuple[AgentTurnResult, tuple[OperationResult[JsonValue], ...]]: ...


__all__ = ["AgentTurnOperationPort"]
