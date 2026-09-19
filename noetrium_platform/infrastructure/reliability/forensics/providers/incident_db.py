from __future__ import annotations

from contextlib import closing, contextmanager
import sqlite3
from pathlib import Path

from noetrium_platform.infrastructure.reliability.forensics.providers.incident_codec import decode_strings
from noetrium_platform.infrastructure.reliability.diagnostics.api import IncidentPattern


class IncidentSQLiteStore:
    """Disposable SQLite storage authority for incident recurrence projections."""

    def __init__(self,path:Path)->None:
        self.path=path
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self._init()

    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    def _init(self)->None:
        with closing(self.connect()) as db, db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS patterns(
              fingerprint TEXT PRIMARY KEY, family_fingerprint TEXT NOT NULL,
              count INTEGER NOT NULL, first_seen REAL NOT NULL,last_seen REAL NOT NULL,
              examples_json TEXT NOT NULL, signature_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS families(
              family_fingerprint TEXT PRIMARY KEY,count INTEGER NOT NULL,
              first_seen REAL NOT NULL,last_seen REAL NOT NULL,examples_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS seen_failures(
              failure_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, family_fingerprint TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS source_freshness(
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), rows INTEGER NOT NULL, tail_hash TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_patterns_family ON patterns(family_fingerprint);
            """)

    @contextmanager
    def transaction(self):
        db=self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def freshness(db)->tuple[int,str]:
        row=db.execute("SELECT rows,tail_hash FROM source_freshness WHERE singleton=1").fetchone()
        return (int(row[0]),str(row[1])) if row else (0,"0"*64)

    @staticmethod
    def set_freshness(db,rows:int,tail_hash:str)->None:
        db.execute(
            "INSERT OR REPLACE INTO source_freshness(singleton,rows,tail_hash) VALUES(1,?,?)",
            (rows,tail_hash),
        )

    @staticmethod
    def reset_projection(db)->None:
        db.execute("DELETE FROM patterns")
        db.execute("DELETE FROM families")
        db.execute("DELETE FROM seen_failures")
        db.execute("DELETE FROM source_freshness")

    def get(self,fingerprint:str)->IncidentPattern|None:
        with closing(self.connect()) as db:
            row=db.execute(
                "SELECT family_fingerprint,count,first_seen,last_seen,examples_json,signature_json FROM patterns WHERE fingerprint=?",
                (fingerprint,),
            ).fetchone()
            if row is None:
                return None
            family=db.execute(
                "SELECT count,examples_json FROM families WHERE family_fingerprint=?",
                (row[0],),
            ).fetchone()
        if family is None:
            raise RuntimeError("incident exact pattern exists without family projection")
        return IncidentPattern(
            fingerprint,str(row[0]),int(row[1]),int(family[0]),float(row[2]),float(row[3]),
            decode_strings(row[4]),decode_strings(family[1]),decode_strings(row[5]),
        )
