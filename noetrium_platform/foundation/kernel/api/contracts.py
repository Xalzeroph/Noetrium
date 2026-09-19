from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    platform_id: str
    version: str

    def __post_init__(self) -> None:
        if not self.platform_id.strip():
            raise ValueError("platform_id must be non-empty")
        if not self.version.strip():
            raise ValueError("version must be non-empty")


@dataclass(frozen=True, slots=True)
class PlatformManifest:
    identity: PlatformIdentity
    systems: tuple[str, ...]
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if not self.systems:
            raise ValueError("platform must declare systems")
