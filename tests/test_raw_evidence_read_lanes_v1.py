"""Untrusted diagnostic reads do not consume the durable family-writer lane."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from noetrium_platform.evidence.observability.capture.composition import (
    build_file_raw_observation_lake,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


def test_slow_read_verification_does_not_block_exact_family_fsync(tmp_path, monkeypatch):
    import noetrium_platform.evidence.observability.capture.providers.file_persistence as persistence
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group('raw-evidence-reader-independence')
    lake = build_file_raw_observation_lake(Path(tmp_path), task_group=group)
    ctx = ExecutionContext('paper-run', 'trial', 'phase')
    entered, release = Event(), Event()
    actual_scan = persistence.scan_raw_segment
    def delayed_scan(*args, **kwargs):
        if kwargs.get('limit_bytes') is not None and not kwargs.get('repair_partial_tail'):
            entered.set()
            assert release.wait(3), 'reader was not released by test'
        return actual_scan(*args, **kwargs)
    try:
        first = lake.append_once(
            ctx, 'study.raw', {'kind':'task', 'status':'running','n':1},
            idempotency_key='first',
        )
        monkeypatch.setattr(persistence, 'scan_raw_segment', delayed_scan)
        with ThreadPoolExecutor(max_workers=2) as workers:
            reader = workers.submit(lake.read,'paper-run','study.raw')
            assert entered.wait(2), 'read must freeze completed segment prefix first'
            try:
                second = workers.submit(
                    lake.append_once,ctx,'study.raw',
                    {'kind':'task','status':'running','n':2},
                    idempotency_key='second',
                )
                later = second.result(timeout=.85)
                assert later.sequence == first.sequence + 1
            finally:
                release.set()
            frozen = reader.result(timeout=3)
        assert [row['payload']['n'] for row in frozen] == [1]
        monkeypatch.setattr(persistence,'scan_raw_segment',actual_scan)
        assert [row['payload']['n'] for row in lake.read('paper-run','study.raw')] == [1,2]
        assert not lake.verify('paper-run','study.raw')
    finally:
        release.set()
        monkeypatch.setattr(persistence,'scan_raw_segment',actual_scan)
        lake.close(); runtime.close()


def test_read_one_pass_still_verifies_uncaptured_tail(tmp_path,monkeypatch):
    from noetrium_platform.evidence.observability.capture.api import (
        RawObservationCorruptionError,
    )
    from noetrium_platform.evidence.observability.capture.providers.segment_pool import RawSegmentPool
    import noetrium_platform.evidence.observability.capture.providers.file_persistence as persistence
    runtime=build_concurrency_runtime()
    group=runtime.open_task_group('raw-verified-scan-one-pass')
    lake=build_file_raw_observation_lake(tmp_path,task_group=group)
    ctx=ExecutionContext('paper-run','trial','step')
    try:
        for i in range(15):
            lake.append_once(ctx,'study.raw',{'kind':'task','status':'running','n':i},
                             idempotency_key=f'unique-{i}')
        opens=[]
        original=persistence.scan_raw_segment
        def capture(*args,**kwargs):
            opens.append(kwargs.get('read_rows_limit'))
            return original(*args,**kwargs)
        monkeypatch.setattr(persistence,'scan_raw_segment',capture)
        rows=lake.read('paper-run','study.raw',limit=2)
        assert [row['payload']['n'] for row in rows]==[0,1]
        assert opens==[2]
        target=RawSegmentPool.target(tmp_path,'paper-run','study.raw')
        contents=target.read_bytes()
        # Flip only a validly-framed trailing record's payload; the first two
        # records remain unchanged, so a limit-only verifier would miss this.
        target.write_bytes(contents.replace(b'"n":14',b'"n":99'))
        with pytest.raises(RawObservationCorruptionError,match='digest mismatch'):
            lake.read('paper-run','study.raw',limit=1)
    finally:
        lake.close();runtime.close()
