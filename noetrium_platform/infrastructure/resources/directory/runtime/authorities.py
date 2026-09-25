from __future__ import annotations

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout, DirectoryManagementAuthorities

from .cleanup import LocalDirectoryCleaner
from .inspection import LocalDirectoryInspector
from .layout import LocalDirectoryLayout
from .workspaces import LocalWorkspaceManager


def build_local_directory_authorities(layout: DirectoryLayout) -> DirectoryManagementAuthorities:
    layout_runtime = LocalDirectoryLayout(layout)
    layout_runtime.ensure_layout()
    inspector = LocalDirectoryInspector(layout_runtime)
    return DirectoryManagementAuthorities(
        layout=layout_runtime,
        workspaces=LocalWorkspaceManager(layout_runtime),
        inspection=inspector,
        cleanup=LocalDirectoryCleaner(layout_runtime, inspector),
    )


__all__ = ["build_local_directory_authorities"]
