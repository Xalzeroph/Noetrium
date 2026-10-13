from __future__ import annotations

from typing import Protocol

from .contracts import SubsystemSnapshot


class SubsystemStatusProbePort(Protocol):
    """Read-only projection from one subsystem into the shared status contract."""

    def snapshot(self) -> SubsystemSnapshot: ...


__all__ = ["SubsystemStatusProbePort"]
