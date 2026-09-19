from __future__ import annotations

from noetrium_platform.foundation.kernel.api import PlatformManifest, PlatformSystemCatalogPort


class InMemoryPlatformRuntime:
    def __init__(self, manifest: PlatformManifest, systems: PlatformSystemCatalogPort) -> None:
        self._manifest = manifest
        self._systems = systems
        self._opened = False

    @property
    def manifest(self) -> PlatformManifest:
        return self._manifest

    def open(self) -> None:
        missing = [system_id for system_id in self._manifest.systems if not self._systems.contains(system_id)]
        if missing:
            raise RuntimeError(f"missing systems: {missing}")
        self._opened = True

    def close(self) -> None:
        self._opened = False

    @property
    def is_open(self) -> bool:
        return self._opened
