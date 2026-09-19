from __future__ import annotations

from pathlib import Path

from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicWriteActorPort
from noetrium_platform.infrastructure.reliability.diagnostics.api import (
    DiagnosticObjectRecord, OperationInvocationRecord, StateWriterRecord,
)
from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope
from noetrium_platform.infrastructure.reliability.forensics.providers.index_db import ForensicIndexDB
from noetrium_platform.infrastructure.reliability.forensics.providers.index_reader import ForensicIndexReader
from noetrium_platform.infrastructure.reliability.forensics.providers.index_writer import ForensicIndexWriter
from noetrium_platform.infrastructure.reliability.forensics.api.mutation import MutationRecord


class ForensicIndex:
    """Explicit composition of a pure reader and the optional write projection."""

    def __init__(self, path: Path, *, read_only: bool = False, writer_actor: ForensicWriteActorPort | None = None):
        self.path = path
        self.read_only = read_only
        self.db = ForensicIndexDB(path, read_only=read_only)
        self.reader = ForensicIndexReader(self.db)
        if read_only:
            if writer_actor is not None:
                raise ValueError("read-only forensic index cannot own a writer actor")
            self.writer = None
        else:
            if writer_actor is None:
                raise ValueError("writable forensic index requires writer_actor")
            self.writer = ForensicIndexWriter(self.db, writer_actor)
        self._before_read = None

    def _write(self) -> ForensicIndexWriter:
        if self.writer is None:
            raise PermissionError("read-only forensic index cannot mutate")
        return self.writer

    def add_event(self, event: EventEnvelope) -> None: self._write().add_event(event)
    def add_failure(self, failure: FailureEnvelope) -> None: self._write().add_failure(failure)
    def add_mutation(self, mutation: MutationRecord) -> None: self._write().add_mutation(mutation)
    def add_raw_payload(self, kind: str, payload: dict[str, object]) -> None: self._write().add_raw_payload(kind, payload)
    def project_event(self,event:EventEnvelope,*,rows:int,tail_hash:str)->None: self._write().project_event(event,rows=rows,tail_hash=tail_hash)
    def project_events_batch(self,items:tuple[tuple[EventEnvelope,int,str],...])->None: self._write().project_events_batch(items)
    def project_failure(self,failure:FailureEnvelope,*,rows:int,tail_hash:str)->None: self._write().project_failure(failure,rows=rows,tail_hash=tail_hash)
    def project_mutation(self,mutation:MutationRecord,*,rows:int,tail_hash:str)->None: self._write().project_mutation(mutation,rows=rows,tail_hash=tail_hash)
    def close(self)->None:
        if self.writer is not None: self.writer.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
    def set_freshness(self, ledger: str, rows: int, tail_hash: str) -> None: self._write().set_freshness(ledger, rows, tail_hash)

    def set_read_barrier(self,callback)->None: self._before_read=callback
    def _barrier(self)->None:
        if self._before_read is not None: self._before_read()
    def read_session(self): self._barrier(); return self.reader.session()
    def freshness(self) -> dict[str, tuple[int, str]]: self._barrier(); return self.reader.freshness()
    def locate(self, object_id: str) -> DiagnosticObjectRecord | None: self._barrier(); return self.reader.locate(object_id)
    def last_writer(self, run_id: str, state_name: str) -> StateWriterRecord | None: self._barrier(); return self.reader.last_writer(run_id, state_name)
    def around(self, *, run_id: str, timestamp: float, seconds: float = 30.0) -> tuple[DiagnosticObjectRecord, ...]: self._barrier(); return self.reader.around(run_id=run_id, timestamp=timestamp, seconds=seconds)
    def recent_state_writers(self, *, run_id: str, before: float, limit: int = 12) -> tuple[StateWriterRecord, ...]: self._barrier(); return self.reader.recent_state_writers(run_id=run_id, before=before, limit=limit)
    def related_to(self, object_id: str, *, limit: int = 100) -> tuple[DiagnosticObjectRecord, ...]: self._barrier(); return self.reader.related_to(object_id, limit=limit)
    def operation_invocation(self, invocation_id: str) -> OperationInvocationRecord | None: self._barrier(); return self.reader.operation_invocation(invocation_id)
    def unclosed_operations(self, *, run_id: str | None = None, limit: int = 100) -> tuple[OperationInvocationRecord, ...]: self._barrier(); return self.reader.unclosed_operations(run_id=run_id, limit=limit)
    def operations_open_at(self, *, run_id: str, timestamp: float, limit: int = 100) -> tuple[OperationInvocationRecord, ...]: self._barrier(); return self.reader.operations_open_at(run_id=run_id, timestamp=timestamp, limit=limit)
