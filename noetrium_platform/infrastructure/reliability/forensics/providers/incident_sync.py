from __future__ import annotations

from itertools import chain

from noetrium_platform.infrastructure.reliability.failure.api import fingerprint_failure
from noetrium_platform.infrastructure.reliability.diagnostics.api import IncidentProjectionSync
from noetrium_platform.infrastructure.reliability.forensics.providers.incident_db import IncidentSQLiteStore
from noetrium_platform.infrastructure.reliability.forensics.providers.incident_projection import IncidentProjectionWriter


class IncidentLedgerSynchronizer:
    """Synchronizes a disposable incident projection against one verified failure-ledger cut."""

    def __init__(self,store:IncidentSQLiteStore,writer:IncidentProjectionWriter)->None:
        self.store=store
        self.writer=writer

    def sync(self,ledger)->IncidentProjectionSync:
        with self.store.transaction() as db:
            source_rows,source_tail=self.store.freshness(db)
            cut=ledger.verified_cut_after(source_rows)
            rebuilt=False
            if source_rows and cut.checkpoint_hash!=source_tail:
                self.store.reset_projection(db)
                source_rows=0
                cut=ledger.verified_cut_after(0)
                rebuilt=True
            added=0
            payloads = chain.from_iterable(
                ledger.iter_verified_payload_batches(cut, batch_size=512)
            )
            for payload in payloads:
                failure_id=str(payload.get("failure_id") or "")
                if not failure_id:
                    continue
                if self.writer.project(
                    db,fingerprint_failure(payload),failure_id,
                    timestamp=float(payload.get("created_at") or 0.0),
                ):
                    added+=1
            self.store.set_freshness(db,cut.total_rows,cut.tail_hash)
        return IncidentProjectionSync(cut.total_rows,cut.tail_hash,added,rebuilt)
