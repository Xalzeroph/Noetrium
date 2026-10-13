from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.unit import NoetriumUnit


class ScopeIndexPort(Protocol):
    """Disposable/rebuildable index over immutable scope Units and links."""

    def register(self, scope: NoetriumUnit, parent: NoetriumUnit | None) -> None: ...
    def parent(self, scope: NoetriumUnit) -> NoetriumUnit | None: ...
    def ancestry(self, scope: NoetriumUnit) -> tuple[NoetriumUnit, ...]: ...
    def children(self, scope: NoetriumUnit) -> tuple[NoetriumUnit, ...]: ...
    def contains(self, scope: NoetriumUnit) -> bool: ...


__all__ = ["ScopeIndexPort"]
