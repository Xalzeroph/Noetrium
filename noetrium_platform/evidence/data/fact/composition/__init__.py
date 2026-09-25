from __future__ import annotations

from pathlib import Path

from noetrium_platform.evidence.data.fact.api import DurableFactStorePort
from noetrium_platform.evidence.data.fact.providers import SQLiteDurableFactStore
from noetrium_platform.evidence.data.fact.runtime import InMemoryDurableFactStore


def compose_in_memory_fact_store() -> DurableFactStorePort:
    return InMemoryDurableFactStore()


def compose_sqlite_fact_store(path: str | Path) -> DurableFactStorePort:
    return SQLiteDurableFactStore(path)


__all__ = ["compose_in_memory_fact_store", "compose_sqlite_fact_store"]
