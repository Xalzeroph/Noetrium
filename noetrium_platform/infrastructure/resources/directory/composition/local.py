from __future__ import annotations

from noetrium_platform.infrastructure.resources.authority.api import ResourceAuthorityPort
from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryLayout,
    DirectoryManagementAuthorities,
    ManagedDirectoryKind,
)
from noetrium_platform.infrastructure.resources.directory.providers import (
    WorkspacePhysicalProvider,
)
from noetrium_platform.infrastructure.resources.directory.runtime import (
    LocalDirectoryCleaner,
    LocalDirectoryInspector,
    LocalDirectoryLayout,
    LocalWorkspaceManager,
)


def build_local_directory_authorities(
    layout: DirectoryLayout,
    resource_authority: ResourceAuthorityPort,
) -> DirectoryManagementAuthorities:
    layout_runtime = LocalDirectoryLayout(layout)
    layout_runtime.ensure_layout()
    inspector = LocalDirectoryInspector(layout_runtime)
    provider = WorkspacePhysicalProvider(
        layout_runtime.root(ManagedDirectoryKind.WORKSPACES)
    )
    return DirectoryManagementAuthorities(
        layout=layout_runtime,
        workspaces=LocalWorkspaceManager(
            layout_runtime,
            resource_authority,
            provider,
        ),
        inspection=inspector,
        cleanup=LocalDirectoryCleaner(layout_runtime, inspector),
    )


__all__ = ["build_local_directory_authorities"]
