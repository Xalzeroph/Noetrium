from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlatformSystemCatalogPort(Protocol):
    """Minimal platform-facing view of installed system identities.

    The Platform runtime must not know which subsystem implements topology storage.
    Governance may provide the catalog, but Platform depends only on this narrow port.
    """

    def contains(self, system_id: str) -> bool: ...


__all__ = ["PlatformSystemCatalogPort"]
