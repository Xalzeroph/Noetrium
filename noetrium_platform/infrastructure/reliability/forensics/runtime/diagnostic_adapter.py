from __future__ import annotations

from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicStorePort
from noetrium_platform.infrastructure.reliability.diagnostics.api import (
    DiagnosticObjectRecord, OperationInvocationRecord, StateWriterRecord,
)


class ForensicDiagnosticEvidence:
    """Read-only adapter from forensic hash-ledger/index implementation to diagnostics ports."""

    def __init__(self, store: ForensicStorePort) -> None:
        self.store = store

    @property
    def source_ref(self) -> str:
        return str(self.store.root)

    def verify_authoritative(self) -> dict[str, tuple[int, str]]:
        return self.store.verify_all()

    def projection_freshness(
        self,
    ) -> tuple[bool, dict[str, tuple[int, str]], dict[str, tuple[int, str]]]:
        return self.store.index_freshness()

    def read_session(self):
        return self.store.index.read_session()

    def locate(self, object_id: str) -> DiagnosticObjectRecord | None:
        return self.store.index.locate(object_id)

    def last_writer(self, run_id: str, state_name: str) -> StateWriterRecord | None:
        return self.store.index.last_writer(run_id, state_name)

    def around(
        self,
        *,
        run_id: str,
        timestamp: float,
        seconds: float = 30.0,
    ) -> tuple[DiagnosticObjectRecord, ...]:
        return self.store.index.around(run_id=run_id, timestamp=timestamp, seconds=seconds)

    def recent_state_writers(
        self,
        *,
        run_id: str,
        before: float,
        limit: int = 12,
    ) -> tuple[StateWriterRecord, ...]:
        return self.store.index.recent_state_writers(run_id=run_id, before=before, limit=limit)

    def related_to(self, object_id: str, *, limit: int = 100) -> tuple[DiagnosticObjectRecord, ...]:
        return self.store.index.related_to(object_id, limit=limit)

    def unclosed_operations(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
    ) -> tuple[OperationInvocationRecord, ...]:
        return self.store.index.unclosed_operations(run_id=run_id, limit=limit)


__all__ = ["ForensicDiagnosticEvidence"]
