from __future__ import annotations

from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicWriteActorPort
from noetrium_platform.infrastructure.reliability.failure.api import FailureEnvelope
from noetrium_platform.infrastructure.reliability.forensics.providers.index_backend import ForensicProjectionBackend
from noetrium_platform.infrastructure.reliability.forensics.providers.index_db import ForensicIndexDB
from noetrium_platform.infrastructure.reliability.forensics.providers.index_projection import event_projection, failure_projection, mutation_projection, raw_projection
from noetrium_platform.infrastructure.reliability.forensics.api.mutation import MutationRecord


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
    def _validate_event_batch(items:tuple[tuple[EventEnvelope,int,str],...])->None:
        previous_rows=None
        for _,rows,tail_hash in items:
            ForensicProjectionBackend.validate_freshness(rows,tail_hash)
            if previous_rows is not None and rows<=previous_rows:
                raise ValueError("event projection batch rows must be strictly increasing")
            previous_rows=rows

    def project_events_batch(self,items:tuple[tuple[EventEnvelope,int,str],...])->None:
        if not items:
            return
        self._validate_event_batch(items)
        _,rows,tail_hash=items[-1]
        self.backend.project_batch(
            tuple(event_projection(event) for event,_,_ in items),
            ledger="events",rows=rows,tail_hash=tail_hash,
        )

    def project_event(self,event:EventEnvelope,*,rows:int,tail_hash:str)->None:
        self.backend.project(event_projection(event),ledger="events",rows=rows,tail_hash=tail_hash)

    def project_failure(self,failure:FailureEnvelope,*,rows:int,tail_hash:str)->None:
        self.backend.project(failure_projection(failure),ledger="failures",rows=rows,tail_hash=tail_hash)

    def project_mutation(self,mutation:MutationRecord,*,rows:int,tail_hash:str)->None:
        self.backend.project(mutation_projection(mutation),ledger="mutations",rows=rows,tail_hash=tail_hash)

    # Rebuild/compat APIs intentionally bypass freshness because caller owns the rebuild cut.
    def add_event(self,event:EventEnvelope)->None:
        self.backend.upsert(event_projection(event))

    def add_failure(self,failure:FailureEnvelope)->None:
        self.backend.upsert(failure_projection(failure))

    def add_mutation(self,mutation:MutationRecord)->None:
        self.backend.upsert(mutation_projection(mutation))

    def set_freshness(self,ledger:str,rows:int,tail_hash:str)->None:
        self.backend.set_freshness(ledger,rows,tail_hash)

    def add_raw_payload(self,kind:str,payload:dict[str,object])->None:
        self.backend.upsert(raw_projection(kind,payload))

    def close(self)->None:
        self.backend.close()
