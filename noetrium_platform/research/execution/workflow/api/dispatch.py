from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, ExecutionContext, OperationRequest, OperationResult

T = TypeVar("T")
R = TypeVar("R")


class OperationDispatchPort(Protocol):
    """Workflow-facing operation boundary independent of Study orchestration."""

    def dispatch(
        self,
        *,
        root_context: ExecutionContext,
        operation_id: str,
        operation_type: str,
        target: ComponentIdentity,
        payload: T,
        payload_schema: str,
        handler: Callable[[OperationRequest[T]], R],
        digest_output: bool = True,
        effect_projector=None,
        idempotency_key: str | None = None,
    ) -> OperationResult[R]: ...

    def require(self, result: OperationResult[R]) -> R: ...

    async def dispatch_async(
        self,
        *,
        root_context: ExecutionContext,
        operation_id: str,
        operation_type: str,
        target: ComponentIdentity,
        payload: T,
        payload_schema: str,
        handler: Callable[[OperationRequest[T]], R],
        digest_output: bool = True,
        effect_projector=None,
        idempotency_key: str | None = None,
    ) -> OperationResult[R]: ...


class OperationExecutionPort(Protocol):
    """Narrow backend boundary used only by durable operation ownership wrappers."""

    def execute(
        self,
        *,
        root_context: ExecutionContext,
        operation_id: str,
        operation_type: str,
        target: ComponentIdentity,
        payload: T,
        payload_schema: str,
        handler: Callable[[OperationRequest[T]], R],
        digest_output: bool = True,
        effect_projector=None,
        idempotency_key: str | None = None,
    ) -> OperationResult[R]: ...


__all__ = ["OperationDispatchPort", "OperationExecutionPort"]
