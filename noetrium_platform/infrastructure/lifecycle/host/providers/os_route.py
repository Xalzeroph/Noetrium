from __future__ import annotations

import os
import platform
from pathlib import Path
import tempfile

from ..api import HostOperatingSystem, OperatingSystemFamily


def _family(system_name: str) -> OperatingSystemFamily:
    normalized = system_name.casefold()
    if normalized == "windows":
        return OperatingSystemFamily.WINDOWS
    if normalized == "linux":
        return OperatingSystemFamily.LINUX
    if normalized in {"darwin", "macos"}:
        return OperatingSystemFamily.DARWIN
    return OperatingSystemFamily.OTHER


class LocalOperatingSystemRoute:
    """Local provider for host identity and platform-owned OS conventions."""

    def __init__(self) -> None:
        system_name = platform.system() or os.name
        self._identity = HostOperatingSystem(
            family=_family(system_name),
            system_name=system_name,
            release=platform.release(),
            machine=platform.machine(),
        )

    @property
    def identity(self) -> HostOperatingSystem:
        return self._identity

    @property
    def is_windows(self) -> bool:
        return self._identity.family is OperatingSystemFamily.WINDOWS

    @property
    def is_posix(self) -> bool:
        return self._identity.family in {
            OperatingSystemFamily.LINUX,
            OperatingSystemFamily.DARWIN,
        }

    def temporary_root(self) -> Path:
        return Path(tempfile.gettempdir()).resolve()

    def null_device(self) -> str:
        return "NUL" if self.is_windows else "/dev/null"


__all__ = ["LocalOperatingSystemRoute"]
