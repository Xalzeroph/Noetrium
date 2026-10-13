from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.structure import NoetriumUnit


@runtime_checkable
class PortfolioCatalogPort(Protocol):
    """Project-manifest Unit index; workspace/program hierarchy is not authority."""

    def register_project(self, manifest: NoetriumUnit) -> None: ...
    def project(self, project_id: str) -> NoetriumUnit: ...
    def projects(
        self,
        *,
        program_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]: ...


__all__ = ["PortfolioCatalogPort"]
