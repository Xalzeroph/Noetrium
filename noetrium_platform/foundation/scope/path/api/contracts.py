from __future__ import annotations

import ntpath
import os
import posixpath
from enum import StrEnum
from pathlib import Path


class PathFlavor(StrEnum):
    NATIVE = "native"
    POSIX = "posix"
    WINDOWS = "windows"


def is_absolute_target_path(value: str | os.PathLike[str]) -> bool:
    """Recognize paths for either local or remote target hosts."""

    raw = os.fspath(value)
    return Path(raw).is_absolute() or ntpath.isabs(raw) or posixpath.isabs(raw)


def require_absolute_target_path(
    value: str | os.PathLike[str],
    *,
    field: str,
) -> str:
    raw = os.fspath(value)
    if not is_absolute_target_path(raw):
        raise ValueError(f"{field} must be an absolute target path")
    return raw


__all__ = ["PathFlavor", "is_absolute_target_path", "require_absolute_target_path"]
