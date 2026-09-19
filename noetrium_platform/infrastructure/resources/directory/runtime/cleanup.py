from __future__ import annotations

from pathlib import Path
import shutil
import time

from noetrium_platform.infrastructure.resources.directory.api import DirectoryCleanupCandidate, DirectoryLayoutPort, ManagedDirectoryKind

from .inspection import LocalDirectoryInspector


class LocalDirectoryCleaner:
    """Explicit cleanup planning/execution for disposable cache/temp roots only."""

    def __init__(self, directories: DirectoryLayoutPort, inspector: LocalDirectoryInspector) -> None:
        self._directories = directories
        self._inspector = inspector

    def clean_plan(
        self,
        kind: ManagedDirectoryKind,
        *,
        older_than_seconds: float | None = None,
    ) -> tuple[DirectoryCleanupCandidate, ...]:
        if kind not in {ManagedDirectoryKind.CACHE, ManagedDirectoryKind.TEMP}:
            raise ValueError("automatic clean is restricted to cache/temp directories")
        root = self._directories.root(kind)
        cutoff = None if older_than_seconds is None else time.time() - older_than_seconds
        values: list[DirectoryCleanupCandidate] = []
        for path in sorted(root.iterdir()):
            try:
                modified_at = path.stat().st_mtime
            except FileNotFoundError:
                continue
            if cutoff is not None and modified_at > cutoff:
                continue
            stats = self._inspector.entry_stats(path)
            values.append(DirectoryCleanupCandidate(path, modified_at, stats.files, stats.directories, stats.bytes))
        return tuple(values)

    def clean(self, kind: ManagedDirectoryKind, *, older_than_seconds: float | None = None) -> tuple[Path, ...]:
        removed: list[Path] = []
        for candidate in self.clean_plan(kind, older_than_seconds=older_than_seconds):
            path = candidate.path
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            removed.append(path)
        return tuple(removed)


__all__ = ["LocalDirectoryCleaner"]
