from __future__ import annotations

import os
from pathlib import Path


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


__all__ = ["logical_absolute_path"]
