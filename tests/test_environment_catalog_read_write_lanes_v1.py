"""Environment catalog snapshots are independent; local generations stay atomic."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentProfileRevision,
)
from noetrium_platform.capabilities.environment.catalog.runtime import (
    SQLiteExecutionEnvironmentCatalog,
)
from noetrium_platform.foundation.scope.runtime import InMemoryScopeIndex


def test_environment_control_read_does_not_wait_for_physical_sqlite_writer(tmp_path):
    store=SQLiteExecutionEnvironmentCatalog(tmp_path/'catalog.sqlite',InMemoryScopeIndex())
    writer_entered,release=Event(),Event()
    def writer():
        with store._writers.session() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                writer_entered.set()
                assert release.wait(3)
            finally:
                db.rollback()
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            held=workers.submit(writer)
            assert writer_entered.wait(2)
            try:
                assert workers.submit(store.instances).result(timeout=.7)==()
                assert store._readers.open_count==1
            finally:
                release.set()
            held.result(timeout=2)
    finally:
        release.set();store.close()


def test_local_concurrent_catalog_mutations_publish_all_generations(tmp_path):
    path=tmp_path/'catalog.sqlite'
    store=SQLiteExecutionEnvironmentCatalog(path,InMemoryScopeIndex())
    def register(index):
        row=EnvironmentProfileRevision(f'profile-{index}','web',f'{index+1:064x}')
        store.register_profile_revision(row)
        return row
    try:
        with ThreadPoolExecutor(max_workers=8) as workers:
            expected=tuple(workers.map(register,range(16)))
        assert store._state_generation==16
        for row in expected:
            assert store.profile_revision(row.profile_id,row.profile_revision)==row
        assert store._readers.open_count==1
        # The durable cut, not this process's cache, is the final arbiter.
        reopened=SQLiteExecutionEnvironmentCatalog(path,InMemoryScopeIndex())
        try:
            assert reopened._state_generation==16
            for row in expected:
                assert reopened.profile_revision(row.profile_id,row.profile_revision)==row
        finally:reopened.close()
    finally:store.close()


def test_stale_writer_does_not_publish_uncommitted_local_catalog_state(tmp_path):
    from noetrium_platform.capabilities.environment.catalog.runtime.catalog import (
        EnvironmentCatalogNotFound, EnvironmentCatalogStaleRevision,
    )
    path=tmp_path/'catalog.sqlite'
    first=SQLiteExecutionEnvironmentCatalog(path,InMemoryScopeIndex())
    second=SQLiteExecutionEnvironmentCatalog(path,InMemoryScopeIndex())
    a=EnvironmentProfileRevision('paper-a','web','a'*64)
    b=EnvironmentProfileRevision('paper-b','web','b'*64)
    try:
        # Interleave a real external generation after this owner's _load()
        # but before the subsequent CAS publication. A pre-call external
        # commit would correctly be seen by the ordinary read-only _load().
        original=second._persist
        def interleaved():
            first.register_profile_revision(a)
            return original()
        second._persist=interleaved
        try:
            with pytest.raises(EnvironmentCatalogStaleRevision):
                second.register_profile_revision(b)
        finally:
            second._persist=original
        assert second._loaded is False
        assert second.profile_revision(a.profile_id,a.profile_revision)==a
        with pytest.raises(EnvironmentCatalogNotFound):
            second.profile_revision(b.profile_id,b.profile_revision)
        second.register_profile_revision(b)
        assert first.profile_revision(b.profile_id,b.profile_revision)==b
    finally:
        second.close();first.close()
