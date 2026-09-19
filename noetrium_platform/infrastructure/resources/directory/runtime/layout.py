from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout, ManagedDirectoryKind


class LocalDirectoryLayout:
    """Explicit local directory-layout authority."""

    def __init__(self, layout: DirectoryLayout) -> None:
        self._layout = layout

    @property
    def layout(self) -> DirectoryLayout:
        return self._layout

    def ensure_layout(self) -> DirectoryLayout:
        for _, path in self._layout.entries():
            path.mkdir(parents=True, exist_ok=True)
        return self._layout

    def root(self, kind: ManagedDirectoryKind) -> Path:
        path = self._layout.path_for(kind)
        path.mkdir(parents=True, exist_ok=True)
        return path


__all__ = ["LocalDirectoryLayout"]
