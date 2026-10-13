from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.api import RepositorySourceIndexPort
from noetrium_platform.foundation.governance.providers import RepositorySourceTree

from ..report import ArchitectureReport, build_architecture_report as _build_architecture_report


def build_architecture_report(
    root: Path,
    *,
    hotspot_limit: int = 20,
    source_index: RepositorySourceIndexPort | None = None,
) -> ArchitectureReport:
    """Compose the architecture analyzer over one exact repository source cut."""

    root = Path(root).resolve()
    resolved_index = source_index or RepositorySourceTree(root).index()
    return _build_architecture_report(
        root,
        hotspot_limit=hotspot_limit,
        source_index=resolved_index,
    )


__all__ = ["build_architecture_report"]
