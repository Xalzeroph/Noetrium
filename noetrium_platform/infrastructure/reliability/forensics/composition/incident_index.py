from __future__ import annotations

import time
from pathlib import Path

from noetrium_platform.infrastructure.reliability.failure.api import FailureFingerprint
from noetrium_platform.infrastructure.reliability.diagnostics.api import IncidentPattern, IncidentProjectionSync
from noetrium_platform.infrastructure.reliability.forensics.providers.incident_db import IncidentSQLiteStore
from noetrium_platform.infrastructure.reliability.forensics.providers.incident_projection import IncidentProjectionWriter
from noetrium_platform.infrastructure.reliability.forensics.providers.incident_sync import IncidentLedgerSynchronizer


class IncidentPatternIndex:
    """Thin recurrence projection façade over storage, writer and ledger synchronizer."""

    def __init__(self,path:Path)->None:
        self.path=path
        self.store=IncidentSQLiteStore(path)
        self.writer=IncidentProjectionWriter()
        self.synchronizer=IncidentLedgerSynchronizer(self.store,self.writer)

    def sync_from_failure_ledger(self,ledger)->IncidentProjectionSync:
        return self.synchronizer.sync(ledger)

    def observe(
        self,fp:FailureFingerprint,failure_id:str,*,timestamp:float|None=None,max_examples:int=8,
    )->IncidentPattern:
        ts=time.time() if timestamp is None else timestamp
        with self.store.transaction() as db:
            self.writer.project(db,fp,failure_id,timestamp=ts,max_examples=max_examples)
        result=self.store.get(fp.fingerprint)
        if result is None:
            raise RuntimeError("incident projection write completed without exact pattern")
        return result

    def get(self,fingerprint:str)->IncidentPattern|None:
        return self.store.get(fingerprint)


__all__=["IncidentPattern","IncidentProjectionSync","IncidentPatternIndex"]
