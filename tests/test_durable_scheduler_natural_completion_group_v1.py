"""Naturally concurrent fair-service completions share one exact durable commit."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
import sqlite3
from time import monotonic, sleep

import pytest

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import durable


def _prepare(scheduler, size):
    for i in range(size):
        scheduler.record_grant(tenant_id='paper', flow_id=f'flow-{i}',
                               reserved_service_quanta=3)


def _race_at_single_writer(path, scheduler, size, *, invalid=None):
    with sqlite3.connect(path,timeout=.1,isolation_level=None) as physical:
        physical.execute('BEGIN IMMEDIATE')
        try:
            with ThreadPoolExecutor(max_workers=size) as workers:
                attempts=[]
                for i in range(size):
                    flow='missing-flow' if i == invalid else f'flow-{i}'
                    attempts.append(workers.submit(
                        scheduler.record_completion, tenant_id='paper',
                        flow_id=flow, service_quanta=5,
                        reserved_service_quanta=3,
                    ))
                deadline=monotonic()+4
                while monotonic()<deadline:
                    with scheduler._transition_lock:
                        queued=len(scheduler._transition_queue)
                    if queued>=size:
                        break
                    sleep(.003)
                assert queued>=size, f'coalescing queue contained {queued} of {size}'
                physical.execute('ROLLBACK')
                return [job.exception(timeout=5) for job in attempts]
        finally:
            if physical.in_transaction:
                physical.rollback()


def test_naturally_racing_completions_share_one_fsync_transaction(tmp_path,monkeypatch):
    path=tmp_path/'fair.sqlite'
    scheduler=DurableUnifiedSchedulingAuthority(path)
    _prepare(scheduler,12)
    previous = {
        i: scheduler._flow_states[scheduler._flow_key('paper',None,f'flow-{i}')].service_quanta
        for i in range(12)
    }
    transactions=[]
    original=durable.immediate_sqlite_transaction
    @contextmanager
    def counted(db, *, timeout_seconds, label):
        if label=='global scheduling completion group':
            transactions.append(label)
        with original(db,timeout_seconds=timeout_seconds,label=label) as conn:
            yield conn
    monkeypatch.setattr(durable,'immediate_sqlite_transaction',counted)
    failures=_race_at_single_writer(path,scheduler,12)
    assert failures==[None]*12
    assert transactions==['global scheduling completion group']
    cold=DurableUnifiedSchedulingAuthority(path)
    assert cold.service_revision()==24
    for i in range(12):
        state=cold._flow_states[cold._flow_key('paper',None,f'flow-{i}')]
        assert state.in_flight==0
        assert state.service_quanta==previous[i]+5
        assert state.reserved_service_quanta==0
    cold.close();scheduler.close()


def test_invalid_completion_isolated_without_corrupting_other_flow(tmp_path):
    path=tmp_path/'fair.sqlite'
    scheduler=DurableUnifiedSchedulingAuthority(path)
    _prepare(scheduler,10)
    failures=_race_at_single_writer(path,scheduler,10,invalid=4)
    assert sum(f is None for f in failures)==9
    assert isinstance(failures[4],RuntimeError)
    assert 'no active flow' in str(failures[4])
    cold=DurableUnifiedSchedulingAuthority(path)
    assert cold.service_revision()==19
    assert cold._flow_states[cold._flow_key('paper',None,'flow-4')].in_flight==1
    scheduler.record_completion(tenant_id='paper',flow_id='flow-4',
                                service_quanta=5,reserved_service_quanta=3)
    assert cold.service_revision()==20
    cold.close();scheduler.close()


def test_failing_physical_transaction_rolls_back_and_unblocks_all(tmp_path,monkeypatch):
    path=tmp_path/'fair.sqlite'
    scheduler=DurableUnifiedSchedulingAuthority(path)
    _prepare(scheduler,8)
    original=durable.immediate_sqlite_transaction
    @contextmanager
    def broken(db,*,timeout_seconds,label):
        with original(db,timeout_seconds=timeout_seconds,label=label) as conn:
            yield conn
            if label=='global scheduling completion group':
                raise OSError('injected physical commit failure')
    monkeypatch.setattr(durable,'immediate_sqlite_transaction',broken)
    failures=_race_at_single_writer(path,scheduler,8)
    assert all(isinstance(f,OSError) for f in failures)
    cold=DurableUnifiedSchedulingAuthority(path)
    assert cold.service_revision()==8
    for i in range(8):
        assert cold._flow_states[cold._flow_key('paper',None,f'flow-{i}')].in_flight==1
    monkeypatch.setattr(durable,'immediate_sqlite_transaction',original)
    for i in range(8):
        scheduler.record_completion(tenant_id='paper',flow_id=f'flow-{i}',
                                    service_quanta=5,reserved_service_quanta=3)
    assert cold.service_revision()==16
    cold.close();scheduler.close()


def test_grouping_remains_cross_process_linearizable(tmp_path):
    import subprocess,sys
    path=tmp_path/'fair.sqlite'
    scheduler=DurableUnifiedSchedulingAuthority(path)
    _prepare(scheduler,10)
    child = '''
import sys
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import DurableUnifiedSchedulingAuthority
s=DurableUnifiedSchedulingAuthority(sys.argv[1])
for i in range(5):
 s.record_grant(tenant_id='remote',flow_id='remote-'+str(i))
 s.record_completion(tenant_id='remote',flow_id='remote-'+str(i),service_quanta=9)
'''
    with ThreadPoolExecutor(max_workers=2) as pool:
        local=pool.submit(_race_at_single_writer,path,scheduler,10)
        remote=pool.submit(subprocess.run,[sys.executable,'-c',child,str(path)],
                           capture_output=True,text=True,timeout=20)
        assert local.result(timeout=15)==[None]*10
        finished=remote.result(timeout=15)
        assert finished.returncode==0,finished.stderr
    cold=DurableUnifiedSchedulingAuthority(path)
    assert cold.service_revision()==30
    for i in range(5):
        state=cold._flow_states[cold._flow_key('remote',None,'remote-'+str(i))]
        assert state.in_flight==0
    assert scheduler.service_revision()==30
    cold.close();scheduler.close()


def test_concurrent_groups_do_not_deadlock_with_grants_and_fair_reads(tmp_path):
    path=tmp_path/'fair.sqlite'
    scheduler=DurableUnifiedSchedulingAuthority(path)
    _prepare(scheduler,24)
    from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
        ExecutionPriority,SchedulingCandidate,
    )
    candidate=SchedulingCandidate(
        ticket=1,group_id='paper-group',flow_id='flow-1',tenant_id='paper',
        priority=ExecutionPriority.NORMAL,enqueued_monotonic=1.,
    )
    with ThreadPoolExecutor(max_workers=24) as pool:
        completions=[pool.submit(scheduler.record_completion,tenant_id='paper',
            flow_id=f'flow-{i}',service_quanta=1,reserved_service_quanta=3)
            for i in range(24)]
        lookups=[pool.submit(scheduler.ordering_key,candidate,now_monotonic=2.)
                 for _ in range(24)]
        assert all(f.result(timeout=10) is None for f in completions)
        assert all(isinstance(f.result(timeout=10),tuple) for f in lookups)
    assert scheduler.service_revision()==48
    scheduler.record_grant(tenant_id='paper',flow_id='again')
    scheduler.record_completion(tenant_id='paper',flow_id='again',service_quanta=1)
    assert scheduler.service_revision()==50
    scheduler.close()
