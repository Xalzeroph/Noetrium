from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OperatingSystemFamily(StrEnum):
    WINDOWS = "windows"
    LINUX = "linux"
    DARWIN = "darwin"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class HostOperatingSystem:
    """Stable host identity used to select OS providers."""

    family: OperatingSystemFamily
    system_name: str
    release: str
    machine: str


__all__ = ["HostOperatingSystem", "OperatingSystemFamily"]
