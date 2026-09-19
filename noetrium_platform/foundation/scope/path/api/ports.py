from __future__ import annotations

import os
from typing import Protocol

from .contracts import PathFlavor


class ScopePathPort(Protocol):
    def is_absolute(self, value: str | os.PathLike[str]) -> bool: ...
    def require_absolute(self, value: str | os.PathLike[str], *, field: str) -> str: ...
    def normalize(self, value: str | os.PathLike[str], *, flavor: PathFlavor = PathFlavor.NATIVE) -> str: ...


__all__ = ["ScopePathPort"]
