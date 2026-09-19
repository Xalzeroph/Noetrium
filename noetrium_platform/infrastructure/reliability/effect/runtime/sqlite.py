from __future__ import annotations

from pathlib import Path

from .persistent import PersistentEffectIntentJournal
from .sqlite_backend import SQLiteEffectJournalBackend


class SQLiteEffectIntentJournal(PersistentEffectIntentJournal):
    def __init__(self, path: Path, *, timeout_seconds: float = 30.0) -> None:
        super().__init__(SQLiteEffectJournalBackend(path, timeout_seconds=timeout_seconds))


__all__ = ["SQLiteEffectIntentJournal"]
