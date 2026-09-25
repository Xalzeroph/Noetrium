from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .contracts import HostOperatingSystem


class OperatingSystemRoute(Protocol):
    """Small capability route for host-dependent platform behavior."""

    @property
    def identity(self) -> HostOperatingSystem: ...

    @property
    def is_windows(self) -> bool: ...

    @property
    def is_posix(self) -> bool: ...

    def temporary_root(self) -> Path: ...

    def null_device(self) -> str: ...


__all__ = ["OperatingSystemRoute"]
