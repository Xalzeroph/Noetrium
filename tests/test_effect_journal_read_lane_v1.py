"""Effect snapshots cannot block the unique durable effect-write session."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from noetrium_platform.infrastructure.reliability.effect.runtime.sqlite_backend import (
    SQLiteEffectJournalBackend,
)


def test_read_only_effect_queries_do_not_wait_on_active_effect_write(tmp_path):
    backend=SQLiteEffectJournalBackend(Path(tmp_path)/'effects.sqlite3')
    entered,release=Event(),Event()
    def hold_effect_transaction():
        with backend.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                entered.set()
                assert release.wait(3)
            finally:
                conn.rollback()
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            writer=workers.submit(hold_effect_transaction)
            assert entered.wait(2)
            try:
                assert workers.submit(backend.read,'absent-effect').result(timeout=.8) is None
                assert workers.submit(backend.scan_run,run_id='paper-run').result(timeout=.8)==()
            finally:
                release.set()
            writer.result(timeout=2)
        assert backend._readers.open_count==1
    finally:
        release.set();backend.close()
