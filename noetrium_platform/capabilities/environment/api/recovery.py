from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EnvironmentRecoverySession(Protocol):
    """Session-bound recovery checkpoint seam.

    These payloads restore the same logical session. They are not portable
    scientific search-branch state.
    """

    def checkpoint(self) -> bytes: ...

    def restore(self, payload: bytes) -> None: ...


__all__ = ["EnvironmentRecoverySession"]
