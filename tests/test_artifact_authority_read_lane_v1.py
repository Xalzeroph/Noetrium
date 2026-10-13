"""Artifact verification reads and immutable DAG lookups stay off writer admission."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from noetrium_platform.evidence.artifact.lineage.relation.api import ArtifactLineageEdge
from noetrium_platform.evidence.artifact.lineage.relation.providers import SQLiteArtifactLineageStore
from noetrium_platform.evidence.artifact.reference.providers import SQLiteArtifactReferenceStore
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from tests.test_durable_artifact_authorities_v207 import _content


def _assert_read_without_waiting_on_writer(store, read, expected):
    held, release = Event(), Event()
    def write_in_progress():
        with store._writers.session() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                held.set()
                assert release.wait(3)
            finally:
                db.rollback()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            holder=executor.submit(write_in_progress)
            assert held.wait(2)
            try:
                assert executor.submit(read).result(timeout=.8) == expected
            finally:
                release.set()
            holder.result(timeout=2)
        assert store._readers.open_count==1
    finally:
        release.set()
        store.close()


def test_reference_lookup_can_read_committed_cut_during_next_cas(tmp_path):
    store=SQLiteArtifactReferenceStore(tmp_path/'reference.sqlite3')
    record=store.compare_and_set(
        'latest',PLATFORM_SCOPE,expected_generation=0,artifact_id='artifact:v1',
    )
    _assert_read_without_waiting_on_writer(
        store,lambda: store.resolve('latest',PLATFORM_SCOPE),record,
    )


def test_lineage_projection_can_read_committed_cut_during_append(tmp_path):
    store=SQLiteArtifactLineageStore(tmp_path/'lineage.sqlite3')
    edge=ArtifactLineageEdge(
        _content('artifact:parent','a'),_content('artifact:child','b'),
        'derived_from',
    )
    store.add(edge)
    _assert_read_without_waiting_on_writer(
        store,lambda:store.parents(_content('artifact:child','b')),(edge,),
    )
