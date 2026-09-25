from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.reliability.diagnostics.api import IncidentPattern, IncidentProjectionSync

from noetrium_platform.infrastructure.reliability.forensics.composition.incident_index import IncidentPatternIndex


class ForensicIncidentProjection:
    """Adapter joining authoritative failure ledger to a disposable incident SQLite projection."""

    def __init__(self, failure_ledger, path: Path) -> None:
        self.failure_ledger = failure_ledger
        self.index = IncidentPatternIndex(path)

    def synchronize(self) -> IncidentProjectionSync:
        return self.index.sync_from_failure_ledger(self.failure_ledger)

    def get(self, fingerprint: str) -> IncidentPattern | None:
        return self.index.get(fingerprint)


__all__ = ["ForensicIncidentProjection"]
