from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from noetrium_platform.foundation.scope.api import ScopeIdentity

from .contracts import (
    DirectoryCleanupCandidate,
    DirectoryContentStats,
    DirectoryEntryStats,
    DirectoryLayout,
    DirectoryOverview,
    DirectoryUsage,
    ManagedDirectoryKind,
    WorkspaceAllocation,
)


class DirectoryLayoutPort(Protocol):
    @property
    def layout(self) -> DirectoryLayout: ...
    def ensure_layout(self) -> DirectoryLayout: ...
    def root(self, kind: ManagedDirectoryKind) -> Path: ...


class WorkspaceManagementPort(Protocol):
    def allocate_workspace(
        self,
        workspace_id: str,
        *,
        scope: ScopeIdentity,
        category: str = "default",
        owner: str | None = None,
        note: str | None = None,
    ) -> WorkspaceAllocation: ...
    def list_workspaces(self, *, scope: ScopeIdentity | None = None, category: str | None = None) -> tuple[WorkspaceAllocation, ...]: ...
    def remove_workspace(self, workspace_id: str, *, scope: ScopeIdentity, category: str = "default") -> bool: ...


class DirectoryInspectionPort(Protocol):
    def usage(self, kind: ManagedDirectoryKind) -> DirectoryUsage: ...
    def overview(self, kind: ManagedDirectoryKind) -> DirectoryOverview: ...
    def content_stats(self, kind: ManagedDirectoryKind) -> DirectoryContentStats: ...
    def entries(self, kind: ManagedDirectoryKind, *, limit: int | None = None) -> tuple[DirectoryEntryStats, ...]: ...


class DirectoryCleanupPort(Protocol):
    def clean_plan(self, kind: ManagedDirectoryKind, *, older_than_seconds: float | None = None) -> tuple[DirectoryCleanupCandidate, ...]: ...
    def clean(self, kind: ManagedDirectoryKind, *, older_than_seconds: float | None = None) -> tuple[Path, ...]: ...


@dataclass(frozen=True, slots=True)
class DirectoryManagementAuthorities:
    layout: DirectoryLayoutPort
    workspaces: WorkspaceManagementPort
    inspection: DirectoryInspectionPort
    cleanup: DirectoryCleanupPort


__all__ = [
    "DirectoryCleanupPort",
    "DirectoryInspectionPort",
    "DirectoryLayoutPort",
    "DirectoryManagementAuthorities",
    "WorkspaceManagementPort",
]
