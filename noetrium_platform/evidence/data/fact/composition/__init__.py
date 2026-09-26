from __future__ import annotations

from pathlib import Path

from noetrium_platform.evidence.data.fact.api import DurableFactStorePort
from noetrium_platform.evidence.data.fact.providers import SQLiteDurableFactStore


def compose_sqlite_fact_store(path: str | Path) -> DurableFactStorePort:
    return SQLiteDurableFactStore(path)


__all__ = ["compose_sqlite_fact_store"]
