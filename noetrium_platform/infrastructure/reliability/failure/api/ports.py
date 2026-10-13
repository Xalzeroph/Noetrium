from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .catalog import FailureSpec
from .reference import FailureReference
from noetrium_platform.foundation.kernel.unit import NoetriumUnit


class FailureLedgerPort(Protocol):
    """Minimal durable append-once authority used by non-forensic coordinators."""

    def append_failure_once(self, failure: NoetriumUnit) -> tuple[bool, str | None]: ...


@runtime_checkable
class FailureMaterializationPort(Protocol):
    """Adjacent-layer port for turning a primary exception into one failure identity."""

    def materialize(
        self,
        *,
        spec: FailureSpec,
        component_id: str,
        context: ExecutionContext,
        exc: BaseException,
        correlation_refs: tuple[str, ...] = (),
    ) -> FailureReference: ...


__all__ = ["FailureLedgerPort", "FailureMaterializationPort"]
