"""Storage facts for deployment qualification."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Callable

from noetrium_platform.capabilities.model.qualification.api import StorageCapabilityFacts

CommandRun = Callable[[tuple[str, ...], float], tuple[int, str, str]]


class StorageFactsProbe:
    """Capture model-path filesystem capacity and access facts."""

    def __init__(self, run: CommandRun) -> None:
        self._run = run
    def capture(self, path: Path, timeout: float) -> tuple[StorageCapabilityFacts, list[str]]:
        errors: list[str] = []
        target = path if path.exists() else path.parent
        total = free = free_inodes = None
        try:
            usage = shutil.disk_usage(target)
            total, free = usage.total, usage.free
        except OSError:
            errors.append("model-path filesystem capacity unavailable")
        try:
            stat = os.statvfs(target)
            free_inodes = int(stat.f_favail)
        except (AttributeError, OSError):
            errors.append("model-path free inode count unavailable")

        filesystem = None
        device_identity = None
        code, out, _ = self._run(
            ("findmnt", "-T", str(target), "-n", "-o", "SOURCE,FSTYPE"),
            timeout,
        )
        if code == 0:
            line = next((item.strip() for item in out.splitlines() if item.strip()), "")
            fields = line.split(None, 1)
            if fields:
                device_identity = fields[0]
            if len(fields) > 1:
                filesystem = fields[1]
        else:
            errors.append("model-path filesystem identity unavailable")

        if not path.exists():
            errors.append("model path does not exist")
        readable = path.exists() and os.access(path, os.R_OK)
        writable = path.exists() and os.access(path, os.W_OK)
        if not readable:
            errors.append("model path is not readable")
        return StorageCapabilityFacts(
            path=str(path),
            total_bytes=total,
            free_bytes=free,
            free_inodes=free_inodes,
            filesystem=filesystem,
            device_identity=device_identity,
            readable=readable,
            writable=writable,
            errors=tuple(errors),
        ), errors

__all__ = ["StorageFactsProbe"]
