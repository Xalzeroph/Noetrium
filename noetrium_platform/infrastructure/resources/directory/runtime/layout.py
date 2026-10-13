from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout, ManagedDirectoryKind


def standard_local_directory_layout(root: Path) -> DirectoryLayout:
    """Canonical local platform directory tree under one root."""

    if not isinstance(root, Path):
        raise TypeError("local directory root must be pathlib.Path")
    base = root.expanduser().absolute()
    if base.exists() and (base.is_symlink() or not base.is_dir()):
        raise ValueError("local directory root must be a real directory")
    return DirectoryLayout(
        releases=base / "releases",
        runtime=base / "runtime",
        state=base / "state",
        logs=base / "logs",
        model_artifacts=base / "model-artifacts",
        python_environments=base / "python-environments",
        cache=base / "cache",
        temp=base / "temp",
        locks=base / "locks",
        workspaces=base / "workspaces",
    )


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


__all__ = ["LocalDirectoryLayout", "standard_local_directory_layout"]
