"""Shared read-only SQLite connections retain fresh cross-process fairness cuts."""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from threading import Barrier

import pytest

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)
from tests.test_durable_cross_process_scheduling_v1 import _candidate


def test_cached_reader_reuses_descriptor_and_observes_other_process_writes(tmp_path):
    p=tmp_path/'fair.sqlite'
    first=DurableUnifiedSchedulingAuthority(p)
    second=DurableUnifiedSchedulingAuthority(p)
    try:
        assert first._readers.open_count==0
        assert first.service_revision()==0
        assert first._readers.open_count==1
        for _ in range(40):
            first.ordering_key(_candidate(1,'paper'),now_monotonic=2.0)
        assert first._readers.open_count==1
        second.record_grant(tenant_id='paper',flow_id='flow')
        second.record_completion(tenant_id='paper',flow_id='flow',service_quanta=7)
        assert first.service_revision()==2
        assert first._readers.open_count==1
        assert first.select((_candidate(1,'paper'),_candidate(2,'other')),
                            now_monotonic=3.0)==2
    finally:
        second.close()
        first.close()
    with pytest.raises(RuntimeError,match='closed'):
        first._readers.session().__enter__()


def test_cached_reader_serializes_thread_sharing(tmp_path):
    s=DurableUnifiedSchedulingAuthority(tmp_path/'fair.sqlite')
    try:
        barrier=Barrier(4)
        def run(_):
            barrier.wait(timeout=3)
            return tuple(s.ordering_key(_candidate(i,'paper'),now_monotonic=2.0)
                         for i in range(20))
        with ThreadPoolExecutor(max_workers=4) as workers:
            outputs=list(workers.map(run,range(4)))
        assert all(row==outputs[0] for row in outputs)
        assert s._readers.open_count==1
    finally:
        s.close()


def test_cached_reader_cannot_cross_fork(tmp_path):
    if 'fork' not in multiprocessing.get_all_start_methods():
        pytest.skip('fork semantics require a fork-capable host')
    s=DurableUnifiedSchedulingAuthority(tmp_path/'fair.sqlite')
    s.service_revision()
    ctx=multiprocessing.get_context('fork')
    recv,send=ctx.Pipe(False)
    def child():
        try:
            s.service_revision()
            send.send('unexpected-success')
        except RuntimeError as exc:
            send.send(str(exc))
        finally:
            send.close()
    child_process=ctx.Process(target=child)
    child_process.start();child_process.join(4)
    try:
        assert child_process.exitcode==0
        assert 'process boundary' in recv.recv()
        assert s.service_revision()==0
    finally:
        recv.close();s.close()


def test_data_version_skips_idle_snapshots_and_catches_committed_service(tmp_path):
    import sqlite3
    from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
        durable,
    )
    p=tmp_path/'fair.sqlite'
    reader=DurableUnifiedSchedulingAuthority(p)
    writer=DurableUnifiedSchedulingAuthority(p)
    try:
        seen=[]
        original=reader._catch_up
        def instrumented(conn):
            seen.append(conn)
            return original(conn)
        reader._catch_up=instrumented
        assert reader.service_revision()==0
        for _ in range(30):
            assert reader.service_revision()==0
        assert len(seen)==1, 'idle committed cut must not replay checkpoints'
        writer.record_grant(tenant_id='paper',flow_id='run')
        assert reader.service_revision()==1
        assert len(seen)==2
        writer.record_completion(tenant_id='paper',flow_id='run',service_quanta=2)
        assert reader.service_revision()==2
        assert len(seen)==3
    finally:
        writer.close();reader.close()


def test_data_version_invalidates_on_checkpoint_maintenance_without_new_events(tmp_path, monkeypatch):
    import sqlite3
    from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import durable
    monkeypatch.setattr(durable,'_CHECKPOINT_INTERVAL',2)
    p=tmp_path/'fair.sqlite'
    writer=DurableUnifiedSchedulingAuthority(p)
    writer.record_grant(tenant_id='paper',flow_id='run')
    writer.record_completion(tenant_id='paper',flow_id='run',service_quanta=2)
    reader=DurableUnifiedSchedulingAuthority(p)
    try:
        assert reader.service_revision()==2
        observed=[]
        original=reader._catch_up
        def track(conn):
            observed.append(conn)
            return original(conn)
        reader._catch_up=track
        with sqlite3.connect(p) as conn:
            conn.execute(
                "UPDATE unified_scheduling_checkpoint SET payload=payload || ' '",
            )
        # A derived checkpoint update can occur without any new service event.
        # The changed database invalidates the fast cut; replay retains its
        # existing monotone position and can verify newer checkpoint cuts.
        assert reader.service_revision()==2
        assert len(observed)==1
    finally:
        reader.close();writer.close()


def test_service_delta_reuses_reader_without_losing_other_process_invalidations(tmp_path):
    path=tmp_path/'fair.sqlite'
    reader=DurableUnifiedSchedulingAuthority(path)
    writer=DurableUnifiedSchedulingAuthority(path)
    try:
        initial,full=reader.service_changes_since(None)
        assert initial==0 and full is None
        writer.record_grant(tenant_id='paper',flow_id='flow-a')
        revision,changed=reader.service_changes_since(initial)
        assert revision==1 and changed==frozenset({'flow-a'})
        assert reader._readers.open_count==1
        writer.record_completion(
            tenant_id='paper',flow_id='flow-a',service_quanta=7,
        )
        writer.record_grant(tenant_id='paper',flow_id='flow-b')
        revision,changed=reader.service_changes_since(1)
        assert revision==3 and changed==frozenset({'flow-a','flow-b'})
        for _ in range(20):
            assert reader.service_changes_since(1)==(3,frozenset({'flow-a','flow-b'}))
        assert reader._readers.open_count==1
    finally:
        writer.close()
        reader.close()
