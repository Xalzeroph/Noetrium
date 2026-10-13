"""Model-visible request reconstruction never contends with append fsync."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from noetrium_platform.capabilities.model.request.runtime import SQLiteModelRequestLedger
from tests.test_model_request_group_commit_v1 import _envelope


def test_read_committed_request_while_append_has_sqlite_writer_permit(tmp_path):
    ledger = SQLiteModelRequestLedger(tmp_path/'models.sqlite3')
    ledger.append(_envelope(0))
    entered, release = Event(), Event()
    def held_writer():
        with ledger._writer.session() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                entered.set()
                assert release.wait(3)
            finally:
                conn.rollback()
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            future=workers.submit(held_writer)
            assert entered.wait(2)
            try:
                assert workers.submit(ledger.get,'request-0').result(timeout=.7) == _envelope(0)
            finally:
                release.set()
            future.result(timeout=2)
        assert ledger._readers.open_count == 1
    finally:
        release.set();ledger.close()


def test_reconstruction_read_session_is_provably_read_only(tmp_path):
    import sqlite3
    ledger=SQLiteModelRequestLedger(tmp_path/'models.sqlite3')
    try:
        ledger.append(_envelope(3))
        with ledger._readers.session() as conn:
            with pytest.raises(sqlite3.OperationalError,match='readonly'):
                conn.execute('DELETE FROM model_requests')
        assert ledger.get('request-3') == _envelope(3)
    finally:
        ledger.close()
