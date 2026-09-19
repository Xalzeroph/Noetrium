from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.scope.path.api import is_absolute_target_path


@dataclass(frozen=True, slots=True)
class ArchiveMaterializationRequest:
    """Bounded request for atomically materializing one verified archive."""

    archive_path: str
    destination: str
    required_relative_paths: tuple[str, ...] = ()
    max_members: int = 200_000
    max_expanded_size: int = 4 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        if not is_absolute_target_path(self.archive_path):
            raise ValueError("archive materialization source must be absolute")
        if not is_absolute_target_path(self.destination):
            raise ValueError("archive materialization destination must be absolute")
        if self.max_members <= 0 or self.max_expanded_size <= 0:
            raise ValueError("archive materialization limits must be positive")
        if any(
            not value.strip()
            or value.startswith(("/", "\\"))
            or ".." in value.replace("\\", "/").split("/")
            for value in self.required_relative_paths
        ):
            raise ValueError("archive required paths must be safe relative paths")


@dataclass(frozen=True, slots=True)
class ArchiveMaterializationResult:
    destination: str
    top_level_directory: str
    tree_sha256: str
    file_count: int
    expanded_size: int


@dataclass(frozen=True, slots=True)
class MaterializedTreeInspection:
    tree_sha256: str
    file_count: int
    expanded_size: int


class ArchiveMaterializationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"archive materialization failed [{code}]: {message}")
        self.code = code


class ArchiveMaterializationPort(Protocol):
    def materialize(
        self,
        request: ArchiveMaterializationRequest,
    ) -> ArchiveMaterializationResult: ...


class MaterializedTreeInspectionPort(Protocol):
    def inspect(self, root: str) -> MaterializedTreeInspection: ...


__all__ = [
    "ArchiveMaterializationError",
    "ArchiveMaterializationPort",
    "ArchiveMaterializationRequest",
    "ArchiveMaterializationResult",
    "MaterializedTreeInspection",
    "MaterializedTreeInspectionPort",
]
