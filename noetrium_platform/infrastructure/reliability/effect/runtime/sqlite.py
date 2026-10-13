from __future__ import annotations

from pathlib import Path

from .persistent import EffectIntentJournalRuntime
from .sqlite_backend import SQLiteEffectJournalBackend


def sqlite_effect_intent_journal(
    path: Path,
    *,
    timeout_seconds: float = 30.0,
) -> EffectIntentJournalRuntime:
    return EffectIntentJournalRuntime(
        SQLiteEffectJournalBackend(path, timeout_seconds=timeout_seconds)
    )


__all__ = ["sqlite_effect_intent_journal"]
