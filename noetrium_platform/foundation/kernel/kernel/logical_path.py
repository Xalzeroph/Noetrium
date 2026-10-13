from __future__ import annotations

from enum import StrEnum
import ntpath
import os
from pathlib import Path
import posixpath


class PathFlavor(StrEnum):
    NATIVE = "native"
    POSIX = "posix"
    WINDOWS = "windows"


def is_absolute_target_path(value: str | os.PathLike[str]) -> bool:
    """Recognize absolute paths for either local or remote target hosts."""

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


def logical_absolute_path(
    value: str | os.PathLike[str],
    *,
    expand_user: bool = False,
) -> Path:
    """Return an absolute logical path without dereferencing live filesystem state.

    ``Path.resolve()``/``realpath()`` can observe a mutable leaf while another
    process renames it and therefore change the logical authority identity.
    ``abspath`` is deliberately lexical: it anchors the caller's requested path
    without following the current file object or any rotating generation.
    """

    path = Path(value)
    if expand_user:
        path = path.expanduser()
    return Path(os.path.abspath(os.fspath(path)))


def normalize_target_path(
    value: str | os.PathLike[str],
    *,
    flavor: PathFlavor = PathFlavor.NATIVE,
) -> str:
    """Lexically normalize a target-host path without observing filesystem state."""

    raw = os.fspath(value)
    if flavor is PathFlavor.WINDOWS:
        return ntpath.normpath(raw)
    if flavor is PathFlavor.POSIX:
        return posixpath.normpath(raw)
    return str(logical_absolute_path(raw))


__all__ = [
    "PathFlavor",
    "is_absolute_target_path",
    "logical_absolute_path",
    "normalize_target_path",
    "require_absolute_target_path",
]
