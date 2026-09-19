from __future__ import annotations

from pathlib import Path
import shutil

from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryContentStats,
    DirectoryEntryStats,
    DirectoryLayoutPort,
    DirectoryOverview,
    DirectoryUsage,
    ManagedDirectoryKind,
)


class LocalDirectoryInspector:
    """Read-only directory capacity/content view."""

    def __init__(self, directories: DirectoryLayoutPort) -> None:
        self._directories = directories

    def usage(self, kind: ManagedDirectoryKind) -> DirectoryUsage:
        path = self._directories.root(kind)
        total, used, free = shutil.disk_usage(path)
        return DirectoryUsage(path, total, used, free)

    def overview(self, kind: ManagedDirectoryKind) -> DirectoryOverview:
        path = self._directories.root(kind)
        total, used, free = shutil.disk_usage(path)
        return DirectoryOverview(path, sum(1 for _ in path.iterdir()), total, used, free)

    def content_stats(self, kind: ManagedDirectoryKind) -> DirectoryContentStats:
        root = self._directories.root(kind)
        stats = self.entry_stats(root, count_root_directory=False)
        return DirectoryContentStats(root, stats.files, stats.directories, stats.bytes)

    def entries(self, kind: ManagedDirectoryKind, *, limit: int | None = None) -> tuple[DirectoryEntryStats, ...]:
        root = self._directories.root(kind)
        values = [self.entry_stats(path) for path in root.iterdir()]
        values.sort(key=lambda value: (-value.bytes, value.path.name))
        return tuple(values if limit is None else values[: max(0, limit)])

    @staticmethod
    def entry_stats(path: Path, *, count_root_directory: bool = True) -> DirectoryEntryStats:
        if path.is_file():
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                size = 0
            return DirectoryEntryStats(path, 1, 0, size)
        files = 0
        directories = 1 if count_root_directory else 0
        total_bytes = 0
        for child in path.rglob("*"):
            if child.is_dir():
                directories += 1
            elif child.is_file():
                files += 1
                try:
                    total_bytes += child.stat().st_size
                except FileNotFoundError:
                    continue
        return DirectoryEntryStats(path, files, directories, total_bytes)


__all__ = ["LocalDirectoryInspector"]
