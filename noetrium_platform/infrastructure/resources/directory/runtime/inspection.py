from __future__ import annotations

from pathlib import Path
import os
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

    @staticmethod
    def _inode_capacity(path: Path) -> tuple[int | None, int | None]:
        try:
            stat = os.statvfs(path)
        except OSError:
            return None, None
        total = int(stat.f_files)
        if total <= 0:
            return None, None
        return total, max(0, int(stat.f_favail))

    def usage(self, kind: ManagedDirectoryKind) -> DirectoryUsage:
        path = self._directories.root(kind)
        total, used, free = shutil.disk_usage(path)
        total_inodes, free_inodes = self._inode_capacity(path)
        return DirectoryUsage(
            path,
            total,
            used,
            free,
            total_inodes=total_inodes,
            free_inodes=free_inodes,
        )

    def overview(self, kind: ManagedDirectoryKind) -> DirectoryOverview:
        path = self._directories.root(kind)
        total, used, free = shutil.disk_usage(path)
        total_inodes, free_inodes = self._inode_capacity(path)
        return DirectoryOverview(
            path,
            sum(1 for _ in path.iterdir()),
            total,
            used,
            free,
            total_inodes=total_inodes,
            free_inodes=free_inodes,
        )

    def content_stats(self, kind: ManagedDirectoryKind) -> DirectoryContentStats:
        root = self._directories.root(kind)
        stats = self.entry_stats(root, count_root_directory=False)
        return DirectoryContentStats(root, stats.files, stats.directories, stats.bytes)

    def entries(self, kind: ManagedDirectoryKind, *, limit: int | None = None) -> tuple[DirectoryEntryStats, ...]:
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("directory entry limit must be a non-negative integer or None")
        root = self._directories.root(kind)
        values = [self.entry_stats(path) for path in root.iterdir()]
        values.sort(key=lambda value: (-value.bytes, value.path.name))
        return tuple(values if limit is None else values[:limit])

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
