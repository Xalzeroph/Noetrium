from __future__ import annotations

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicWriteActorPort
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.reliability.forensics.providers.index_backend import ForensicProjectionBackend
from noetrium_platform.infrastructure.reliability.forensics.providers.index_db import ForensicIndexDB
from noetrium_platform.infrastructure.reliability.forensics.providers.index_projection import event_document_projection, event_projection, failure_projection, mutation_projection, raw_projection
from noetrium_platform.infrastructure.reliability.failure.api import is_failure_record
from noetrium_platform.infrastructure.reliability.forensics.api.mutation import is_mutation_event


class ForensicIndexWriter:
    """Projection façade. Encoding and SQLite transaction authority are separate."""

    def __init__(self, db: ForensicIndexDB, writer_actor: ForensicWriteActorPort | None = None) -> None:
        if db.read_only:
            raise PermissionError("read-only forensic index cannot create writer")
        if writer_actor is None:
            raise ValueError("writable forensic index writer requires writer_actor")
        self.db = db
        self.backend = ForensicProjectionBackend(db, writer_actor)

    @staticmethod
    def _validate_event_batch(
        items:tuple[tuple[NoetriumUnit,dict[str,object],int,str],...],
    )->None:
        previous_rows=None
        for _,_,rows,tail_hash in items:
            ForensicProjectionBackend.validate_freshness(rows,tail_hash)
            if previous_rows is not None and rows<=previous_rows:
                raise ValueError("event projection batch rows must be strictly increasing")
            previous_rows=rows

    def project_events_batch(
        self,
        items:tuple[tuple[NoetriumUnit,dict[str,object],int,str],...],
    )->None:
        if not items:
            return
        self._validate_event_batch(items)
        _,_,rows,tail_hash=items[-1]
        bundles=tuple(
            event_document_projection(document)
            for event,document,_,_ in items
            if not is_failure_record(event)
            and not is_mutation_event(event)
        )
        if bundles:
            self.backend.project_batch(
                bundles,
                ledger="events",rows=rows,tail_hash=tail_hash,
            )
        else:
            self.backend.set_freshness("events",rows,tail_hash)

    def project_event(self,event:NoetriumUnit,*,rows:int,tail_hash:str)->None:
        if is_failure_record(event) or is_mutation_event(event):
            self.backend.set_freshness("events",rows,tail_hash)
            return
        self.backend.project(
            event_projection(event),
            ledger="events",rows=rows,tail_hash=tail_hash,
        )

    def project_failure(self,failure:NoetriumUnit,*,rows:int,tail_hash:str)->None:
        self.backend.project(failure_projection(failure),ledger="failures",rows=rows,tail_hash=tail_hash)

    def project_mutation(self,mutation:NoetriumUnit,*,rows:int,tail_hash:str)->None:
        self.backend.project(mutation_projection(mutation),ledger="mutations",rows=rows,tail_hash=tail_hash)

    # Rebuild writes are raw fixed-cut projections and never alias live project_* APIs.
    def set_freshness(self,ledger:str,rows:int,tail_hash:str)->None:
        self.backend.set_freshness(ledger,rows,tail_hash)

    def add_raw_payload(self,kind:str,payload:dict[str,object])->None:
        self.backend.upsert(raw_projection(kind,payload))

    def close(self)->None:
        self.backend.close()
