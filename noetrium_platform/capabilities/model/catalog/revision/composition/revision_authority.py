from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.catalog.revision.api import ModelRevisionAuthorityPort
from noetrium_platform.capabilities.model.catalog.revision.providers import SQLiteModelRevisionAuthority


def sqlite_revision_authority(path: str | Path) -> ModelRevisionAuthorityPort:
    """Compose the durable local authority for one logical model revision lineage."""
    return SQLiteModelRevisionAuthority(path)


__all__ = ["sqlite_revision_authority"]
