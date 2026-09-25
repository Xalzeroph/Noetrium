from __future__ import annotations

from noetrium_platform.foundation.governance.system_registry.api import SystemRegistryPort
from noetrium_platform.foundation.kernel.api import PlatformSystemCatalogPort


class RegistryPlatformSystemCatalog(PlatformSystemCatalogPort):
    """Composition adapter from Governance topology to the Platform runtime port."""

    def __init__(self, registry: SystemRegistryPort) -> None:
        self._registry = registry

    def contains(self, system_id: str) -> bool:
        return self._registry.contains(system_id)


__all__ = ["RegistryPlatformSystemCatalog"]
