from __future__ import annotations

from pathlib import Path
import math
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
        if older_than_seconds is not None:
            if (
                type(older_than_seconds) not in {int, float}
                or not math.isfinite(float(older_than_seconds))
                or older_than_seconds < 0
            ):
                raise ValueError(
                    "older_than_seconds must be a finite non-negative number or None"
                )
        root = self._directories.root(kind)
        cutoff = (
            None
            if older_than_seconds is None
            else time.time() - float(older_than_seconds)
        )
        values: list[DirectoryCleanupCandidate] = []
        for path in sorted(root.iterdir()):
            try:
                identity = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            modified_at = identity.st_mtime
            if cutoff is not None and modified_at > cutoff:
                continue
            stats = self._inspector.entry_stats(path)
            try:
                after = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (
                identity.st_dev,
                identity.st_ino,
                identity.st_ctime_ns,
                identity.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_ctime_ns,
                after.st_mtime_ns,
            ):
                continue
            values.append(
                DirectoryCleanupCandidate(
                    path,
                    modified_at,
                    stats.files,
                    stats.directories,
                    stats.bytes,
                    identity.st_dev,
                    identity.st_ino,
                    identity.st_ctime_ns,
                )
            )
        return tuple(values)

    def clean(self, kind: ManagedDirectoryKind, *, older_than_seconds: float | None = None) -> tuple[Path, ...]:
        removed: list[Path] = []
        for candidate in self.clean_plan(kind, older_than_seconds=older_than_seconds):
            path = candidate.path
            try:
                current = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (
                current.st_dev != candidate.device
                or current.st_ino != candidate.inode
                or current.st_ctime_ns != candidate.change_time_ns
                or current.st_mtime != candidate.modified_at
            ):
                continue
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                continue
            removed.append(path)
        return tuple(removed)


__all__ = ["LocalDirectoryCleaner"]
