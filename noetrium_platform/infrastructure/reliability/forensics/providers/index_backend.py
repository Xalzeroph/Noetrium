from __future__ import annotations

from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicWriteActorPort
from noetrium_platform.infrastructure.reliability.forensics.providers.index_db import ForensicIndexDB
from noetrium_platform.infrastructure.reliability.forensics.providers.index_projection import ProjectionBundle
from noetrium_platform.infrastructure.reliability.forensics.providers.index_write_session import ForensicIndexWriteSession


class ForensicProjectionBackend:
    """Projection façade over one persistent SQLite write session."""

    def __init__(self,db:ForensicIndexDB,writer_actor:ForensicWriteActorPort)->None:
        self.db=db
        self.session=ForensicIndexWriteSession(db, writer_actor)

    @staticmethod
    def validate_freshness(rows:int,tail_hash:str)->None:
        if rows<0 or len(tail_hash)!=64:
            raise ValueError("invalid ledger freshness")

    def project(self,bundle:ProjectionBundle,*,ledger:str,rows:int,tail_hash:str)->None:
        self.validate_freshness(rows,tail_hash)
        self.session.project(bundle,ledger=ledger,rows=rows,tail_hash=tail_hash)

    def project_batch(
        self,
        bundles:tuple[ProjectionBundle,...],
        *,
        ledger:str,
        rows:int,
        tail_hash:str,
    )->None:
        if not bundles:
            return
        self.validate_freshness(rows,tail_hash)
        self.session.project_batch(
            bundles,
            ledger=ledger,
            rows=rows,
            tail_hash=tail_hash,
        )

    def upsert(self,bundle:ProjectionBundle)->None:
        self.session.upsert(bundle)

    def set_freshness(self,ledger:str,rows:int,tail_hash:str)->None:
        self.validate_freshness(rows,tail_hash)
        self.session.set_freshness(ledger,rows,tail_hash)

    def close(self)->None:
        self.session.close()
