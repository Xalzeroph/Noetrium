"""Reopenable memory with content-addressed SQLite persistence."""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tempfile import TemporaryDirectory

from components.reference.single_agent.memory import (
    EpisodicMemoryStore, MemoryItem, SQLiteMemoryPersistence,
)

with TemporaryDirectory() as directory:
    path = Path(directory) / "memory.sqlite"
    persistence = SQLiteMemoryPersistence(path)
    item = MemoryItem("fact-1", "Noetrium keeps exact memory identity", tags=("demo",))
    EpisodicMemoryStore(persistence=persistence).put(item)
    persistence.close()
    reopened = SQLiteMemoryPersistence(path)
    restored = EpisodicMemoryStore(persistence=reopened).get("fact-1")
    print(restored.item_digest == item.item_digest)
    reopened.close()
