from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from noetrium_platform.foundation.scope.api import ScopeIdentity




class WorkspaceMetadataFailureCode(StrEnum):
    DOCUMENT_INTEGRITY = "document-integrity"
    PAYLOAD_SHAPE = "payload-shape"
    IDENTITY_MISMATCH = "identity-mismatch"


class WorkspaceMetadataError(RuntimeError):
    """Machine-classified durable workspace metadata failure."""

    def __init__(self, code: WorkspaceMetadataFailureCode) -> None:
        self.code = code
        super().__init__(f"workspace metadata failure: {code.value}")

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        return (f"resource-workspace-metadata:{self.code.value}",)


class ManagedDirectoryKind(StrEnum):
    RELEASES = "releases"
    RUNTIME = "runtime"
    STATE = "state"
    LOGS = "logs"
    MODEL_ARTIFACTS = "model_artifacts"
    PYTHON_ENVIRONMENTS = "python_environments"
    CACHE = "cache"
    TEMP = "temp"
    LOCKS = "locks"
    WORKSPACES = "workspaces"


@dataclass(frozen=True, slots=True)
class DirectoryLayout:
    releases: Path
    runtime: Path
    state: Path
    logs: Path
    model_artifacts: Path
    python_environments: Path
    cache: Path
    temp: Path
    locks: Path
    workspaces: Path

    def path_for(self, kind: ManagedDirectoryKind) -> Path:
        return getattr(self, kind.value)

    def entries(self) -> tuple[tuple[ManagedDirectoryKind, Path], ...]:
        return tuple((kind, self.path_for(kind)) for kind in ManagedDirectoryKind)


@dataclass(frozen=True, slots=True)
class WorkspaceAllocation:
    workspace_id: str
    scope: ScopeIdentity
    category: str
    path: Path
    owner: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DirectoryContentStats:
    path: Path
    files: int
    directories: int
    bytes: int


@dataclass(frozen=True, slots=True)
class DirectoryUsage:
    path: Path
    total_bytes: int
    used_bytes: int
    free_bytes: int


@dataclass(frozen=True, slots=True)
class DirectoryOverview:
    path: Path
    top_level_entries: int
    total_bytes: int
    used_bytes: int
    free_bytes: int


@dataclass(frozen=True, slots=True)
class DirectoryEntryStats:
    path: Path
    files: int
    directories: int
    bytes: int


@dataclass(frozen=True, slots=True)
class DirectoryCleanupCandidate:
    path: Path
    modified_at: float
    files: int
    directories: int
    bytes: int


__all__ = [
    "DirectoryCleanupCandidate",
    "DirectoryContentStats",
    "DirectoryEntryStats",
    "DirectoryLayout",
    "DirectoryOverview",
    "DirectoryUsage",
    "ManagedDirectoryKind",
    "WorkspaceAllocation",
    "WorkspaceMetadataError",
    "WorkspaceMetadataFailureCode",
]
