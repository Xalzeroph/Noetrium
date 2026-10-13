from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@runtime_checkable
class DiagnosticDegradationPort(Protocol):
    """Durable side-plane record for observability failures that must not alter primary truth."""

    def record(
        self,
        context: ExecutionContext,
        *,
        subsystem: str,
        stage: str,
        exc: BaseException,
        correlation_refs: tuple[str, ...] = (),
    ) -> str: ...


__all__ = ["DiagnosticDegradationPort"]
