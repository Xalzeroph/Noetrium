from __future__ import annotations

import json

import pytest

from noetrium_platform.infrastructure.reliability.forensics.providers.index_db import ForensicIndexDB
from noetrium_platform.infrastructure.reliability.forensics.providers.index_reader import ForensicIndexReader


def _db(tmp_path) -> ForensicIndexDB:
    return ForensicIndexDB(tmp_path / "index.sqlite3", read_only=False)


def _insert_object(
    db: ForensicIndexDB,
    *,
    object_id: str,
    run_id: str | None,
    task_id: str | None,
    timestamp: float,
    payload: object,
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO object_index VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                object_id,
                "event",
                run_id,
                task_id,
                None,
                None,
                None,
                "component",
                timestamp,
                json.dumps(payload, sort_keys=True),
            ),
        )
        conn.commit()


def test_related_to_preserves_runless_object_correlation(tmp_path) -> None:
    db = _db(tmp_path)
    _insert_object(
        db,
        object_id="event-a",
        run_id=None,
        task_id="task-1",
        timestamp=1.0,
        payload={"event_id": "event-a"},
    )
    _insert_object(
        db,
        object_id="event-b",
        run_id=None,
        task_id="task-1",
        timestamp=2.0,
        payload={"event_id": "event-b"},
    )
    rows = ForensicIndexReader(db).related_to("event-a")
    assert tuple(row.object_id for row in rows) == ("event-a", "event-b")


def test_closed_read_session_fails_closed(tmp_path) -> None:
    reader = ForensicIndexReader(_db(tmp_path))
    session = reader.session()
    assert session.freshness() == {}
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="read session is closed"):
        session.freshness()
    with pytest.raises(RuntimeError, match="read session is closed"):
        session.__enter__()


def test_projection_payload_must_decode_to_object(tmp_path) -> None:
    db = _db(tmp_path)
    _insert_object(
        db,
        object_id="bad-payload",
        run_id="run-1",
        task_id=None,
        timestamp=1.0,
        payload=["not", "an", "object"],
    )
    with pytest.raises(ValueError, match="payload must decode to an object"):
        ForensicIndexReader(db).locate("bad-payload")


def test_read_session_enforces_sqlite_query_only(tmp_path) -> None:
    import sqlite3

    reader = ForensicIndexReader(_db(tmp_path))
    with reader.session() as session:
        conn = session._connection()
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(
                "INSERT INTO ledger_freshness(ledger,rows,tail_hash) VALUES(?,?,?)",
                ("events", 0, "0" * 64),
            )


def test_negative_around_window_is_rejected(tmp_path) -> None:
    reader = ForensicIndexReader(_db(tmp_path))
    with pytest.raises(ValueError, match="seconds must be non-negative"):
        reader.around(run_id="run-1", timestamp=10.0, seconds=-0.1)
