"""Finite producer-owned writer cuts, synchronous receipts, and mixed batching."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
import time
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import DurableUnifiedSchedulingAuthority, durable


def _wait_queued(scheduler, count):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with scheduler._transition_lock:
            if len(scheduler._transition_queue) >= count:
                return
        time.sleep(.001)
    raise AssertionError('writer producers failed to enqueue')


def test_completed_leader_returns_while_later_writer_cut_is_stalled(tmp_path, monkeypatch):
    scheduler = DurableUnifiedSchedulingAuthority(tmp_path/'service.sqlite')
    first_sql, first_release = Event(), Event()
    second_sql, second_release = Event(), Event()
    checkpoints = 0
    original = scheduler._maybe_checkpoint

    def gated_checkpoint(conn):
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == 1:
            first_sql.set()
            assert first_release.wait(4)
        else:
            second_sql.set()
            assert second_release.wait(4)
        return original(conn)

    monkeypatch.setattr(scheduler, '_maybe_checkpoint', gated_checkpoint)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            leader = workers.submit(scheduler.record_grant, tenant_id='paper', flow_id='first')
            try:
                assert first_sql.wait(2)
                successor = workers.submit(scheduler.record_grant, tenant_id='paper', flow_id='later')
                _wait_queued(scheduler, 1)
                first_release.set()
                assert second_sql.wait(2)
                assert leader.result(timeout=.5) == 1, 'later cut held an already-durable receipt hostage'
                assert not successor.done()
            finally:
                first_release.set()
                second_release.set()
            assert successor.result(timeout=3) == 2
    finally:
        first_release.set()
        second_release.set()
        scheduler.close()


def test_grants_and_completions_share_one_natural_fifo_durable_cut(tmp_path, monkeypatch):
    path = tmp_path/'service.sqlite'
    scheduler = DurableUnifiedSchedulingAuthority(path)
    scheduler.record_grant(tenant_id='paper', flow_id='old')
    entered, release = Event(), Event()
    original_read = scheduler._read_cut
    commits = []
    original_transaction = durable.immediate_sqlite_transaction

    def gated_read():
        if not entered.is_set():
            entered.set()
            assert release.wait(4)
        return original_read()

    @contextmanager
    def counted(*args, **kwargs):
        with original_transaction(*args, **kwargs) as conn:
            yield conn
        commits.append(kwargs.get('label'))

    monkeypatch.setattr(scheduler, '_read_cut', gated_read)
    monkeypatch.setattr(durable, 'immediate_sqlite_transaction', counted)
    try:
        with ThreadPoolExecutor(max_workers=3) as workers:
            leader = workers.submit(scheduler.record_grant, tenant_id='paper', flow_id='new')
            assert entered.wait(2)
            completion = workers.submit(scheduler.record_completion, tenant_id='paper', flow_id='old', service_quanta=9)
            invalid = workers.submit(scheduler.record_completion, tenant_id='paper', flow_id='missing', service_quanta=1)
            try:
                _wait_queued(scheduler, 3)
            finally:
                release.set()
            assert leader.result(timeout=3) == 2
            assert completion.result(timeout=3) is None
            assert isinstance(invalid.exception(timeout=3), RuntimeError)
        assert commits == ['global scheduling grant group']
        cold = DurableUnifiedSchedulingAuthority(path)
        try:
            assert cold.service_revision() == 3
            assert cold._flow_states[cold._flow_key('paper', None, 'old')].in_flight == 0
            assert cold._flow_states[cold._flow_key('paper', None, 'new')].in_flight == 1
        finally:
            cold.close()
    finally:
        release.set()
        scheduler.close()


def test_same_producer_reentry_rejects_before_creating_an_unfinishable_receipt(tmp_path, monkeypatch):
    import pytest
    scheduler = DurableUnifiedSchedulingAuthority(tmp_path/'service.sqlite')
    original = scheduler._maybe_checkpoint

    def attempt_reentry(conn):
        with pytest.raises(RuntimeError, match='synchronously reenter its own cut'):
            scheduler.record_grant(tenant_id='paper', flow_id='recursive')
        with scheduler._transition_lock:
            assert not scheduler._transition_queue
        return original(conn)

    try:
        monkeypatch.setattr(scheduler, '_maybe_checkpoint', attempt_reentry)
        assert scheduler.record_grant(tenant_id='paper', flow_id='outer') == 1
        assert scheduler.service_revision() == 1
        assert not getattr(scheduler._write_scope, 'inside', False)
        monkeypatch.setattr(scheduler, '_maybe_checkpoint', original)
        scheduler.record_completion(tenant_id='paper', flow_id='outer', service_quanta=1)
        assert scheduler.service_revision() == 2
    finally:
        scheduler.close()
