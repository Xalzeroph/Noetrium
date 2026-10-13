from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .contracts import Observation


@runtime_checkable
class EnvironmentResetPort(Protocol):
    """Reset one bound task/session to its frozen scientific initial state.

    Reset is task-local scientific control, not provider lifecycle authority.
    Implementations must preserve the bound task/source cut while returning a new
    authoritative observation for the initial state.
    """

    def reset(self, context: ExecutionContext) -> Observation: ...


__all__ = ["EnvironmentResetPort"]
