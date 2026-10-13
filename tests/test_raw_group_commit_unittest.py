"""Durable event-driven group commit: one authoritative actor and fsync per batch."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep
import tempfile
import unittest
from unittest.mock import patch

from noetrium_platform.evidence.observability.capture.composition import build_file_raw_observation_lake
from noetrium_platform.evidence.observability.capture.providers.segment_writer import RawSegmentWriter
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class RawGroupCommitTests(unittest.TestCase):
    def test_concurrent_scientific_records_one_fsync_and_replay_idempotency(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = build_concurrency_runtime()
            group = runtime.open_task_group('raw-group-commit-test')
            root = Path(td)
            lake = build_file_raw_observation_lake(root, task_group=group)
            persist = lake._persistence
            actor = persist._actor_for('run', 'study.raw')
            release = Event()
            started = Event()

            def occupy_lane():
                started.set()
                if not release.wait(5):
                    raise TimeoutError('test actor blocker timed out')

            blocker = actor.submit('test-occupancy', occupy_lane)
            self.assertTrue(started.wait(2))
            sync_calls = []
            original = RawSegmentWriter.append_batch

            def count_sync(writer, rows):
                sync_calls.append(len(rows))
                return original(writer, rows)

            try:
                with patch.object(RawSegmentWriter, 'append_batch', count_sync):
                    with ThreadPoolExecutor(max_workers=24) as executor:
                        jobs = [executor.submit(
                            lake.append_once,
                            ExecutionContext('run', 'trace', f's{i}'),
                            'study.raw',
                            {'kind':'task', 'status':'running', 'i': i},
                            idempotency_key=f'key:{i}',
                        ) for i in range(24)]
                        deadline = monotonic() + 3
                        while monotonic() < deadline:
                            with persist._commit_lock:
                                pending = persist._pending_commits.get(('run', 'study.raw'))
                                queued = 0 if pending is None else len(pending.records)
                            if queued == 24:
                                break
                            sleep(.005)
                        self.assertEqual(queued, 24)
                        release.set()
                        blocker.result(timeout=3)
                        receipts = [job.result(timeout=6) for job in jobs]
                self.assertEqual(sync_calls, [24])
                self.assertEqual(sorted(r.sequence for r in receipts), list(range(1, 25)))
                self.assertEqual(lake.verify('run', 'study.raw'), ())
                self.assertEqual(len(lake.read('run', 'study.raw')), 24)
                duplicate = lake.append_once(
                    ExecutionContext('run','trace','last'), 'study.raw',
                    {'kind':'task','status':'running','i':3}, idempotency_key='key:3',
                )
                self.assertEqual(duplicate.sequence, receipts[3].sequence)
                lake.close()
                runtime.close()
                reopened_runtime = build_concurrency_runtime()
                reopened_group = reopened_runtime.open_task_group('raw-group-reopen')
                try:
                    reopened = build_file_raw_observation_lake(root, task_group=reopened_group)
                    self.assertEqual(reopened.verify('run', 'study.raw'), ())
                    repeat = reopened.append_once(
                        ExecutionContext('run','trace','s3'), 'study.raw',
                        {'kind':'task','status':'running','i':3}, idempotency_key='key:3',
                    )
                    self.assertEqual(repeat.sequence, receipts[3].sequence)
                    self.assertEqual(len(reopened.read('run', 'study.raw')), 24)
                    reopened.close()
                finally:
                    reopened_runtime.close()
            finally:
                release.set()

    def test_fsync_failure_faults_writer_and_does_not_ack_group(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = build_concurrency_runtime()
            group = runtime.open_task_group('raw-group-failed-fsync')
            lake = build_file_raw_observation_lake(Path(td), task_group=group)
            from noetrium_platform.foundation.kernel.kernel.durability import PersistentAppendFile
            with patch.object(PersistentAppendFile, 'sync', side_effect=OSError('forced fsync failure')):
                with self.assertRaisesRegex(OSError, 'forced fsync failure'):
                    lake.append_once(ExecutionContext('run','trace','span'), 'study.raw',
                                     {'kind':'task','status':'running'}, idempotency_key='first')
            with self.assertRaisesRegex(RuntimeError, 'faulted'):
                lake.append_once(ExecutionContext('run','trace','span2'), 'study.raw',
                                 {'kind':'task','status':'running'}, idempotency_key='second')
            lake.close()
            runtime.close()


if __name__ == '__main__':
    unittest.main()
