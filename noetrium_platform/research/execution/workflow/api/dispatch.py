from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    ExecutionContext,
    OperationRequest,
    OperationResult,
    require_sha256,
)
from noetrium_platform.research.execution.operation.api import OperationEffectProfile

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class OperationEffectBinding:
    """Stable external-effect identity frozen before durable Operation execution."""

    profile: OperationEffectProfile
    effect_id: str
    request_id: str
    request_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile, OperationEffectProfile):
            raise TypeError("operation effect profile must be typed")
        if self.profile is OperationEffectProfile.NONE:
            raise ValueError("effect-free operation must not carry OperationEffectBinding")
        for value, field in (
            (self.effect_id, "effect_id"),
            (self.request_id, "request_id"),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"operation effect {field} must be non-empty")
        require_sha256(self.request_digest, "operation effect request_digest")


class OperationDispatchPort(Protocol):
    """Workflow-facing operation boundary independent of Study orchestration."""

    @property
    def identity_digest(self) -> str: ...

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
        effect_binding: OperationEffectBinding | None = None,
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
        effect_binding: OperationEffectBinding | None = None,
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


__all__ = ["OperationDispatchPort", "OperationEffectBinding", "OperationExecutionPort"]
