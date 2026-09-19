from __future__ import annotations

import ntpath
import os
import posixpath

from noetrium_platform.foundation.kernel.kernel.logical_path import logical_absolute_path

from ..api import PathFlavor, is_absolute_target_path, require_absolute_target_path


class TargetPathResolver:
    """Pure target-path semantics; it never owns directory layout."""

    def is_absolute(self, value: str | os.PathLike[str]) -> bool:
        return is_absolute_target_path(value)

    def require_absolute(self, value: str | os.PathLike[str], *, field: str) -> str:
        return require_absolute_target_path(value, field=field)

    def normalize(
        self,
        value: str | os.PathLike[str],
        *,
        flavor: PathFlavor = PathFlavor.NATIVE,
    ) -> str:
        raw = os.fspath(value)
        if flavor is PathFlavor.WINDOWS:
            return ntpath.normpath(raw)
        if flavor is PathFlavor.POSIX:
            return posixpath.normpath(raw)
        return str(logical_absolute_path(raw))


__all__ = ["TargetPathResolver"]
