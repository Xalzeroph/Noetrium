from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from noetrium_platform.capabilities.model.serving.api import RecoveryStep
from noetrium_platform.capabilities.model.serving.runtime import DurableExactRecoveryRunner
from noetrium_platform.capabilities.model.serving.providers.recovery_storage import FileDurableRecoveryStore

from test_model_os_v11 import ModelOSV11Tests, _RecoveryExecutor


class ExplodingObserver:
    def attempt_started(self, *, cause): raise RuntimeError("observer-secret")
    def step_started(self, step): raise RuntimeError("observer-secret")
    def step_finished(self, step, *, result): raise RuntimeError("observer-secret")
    def attempt_finished(self, *, result): raise RuntimeError("observer-secret")


class CollectingFailureSink:
    def __init__(self): self.rows=[]
    def record(self, failure): self.rows.append(failure)


class RecoveryObserverIsolationV179Tests(unittest.TestCase):
    def test_observer_failure_never_changes_durable_recovery_truth(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            plan=ModelOSV11Tests()._plan()
            store=FileDurableRecoveryStore(root/"recovery.json", guard_path=root/"guard.lock")
            sink=CollectingFailureSink()
            report=DurableExactRecoveryRunner(
                store,
                _RecoveryExecutor(None),
                observer=ExplodingObserver(),
                observer_failure_sink=sink,
            ).run(plan, attempt_id="observer-isolation")
            self.assertEqual(report.attempt.phase.value,"succeeded")
            self.assertTrue(report.observer_failures)
            self.assertEqual(tuple(sink.rows), report.observer_failures)
            self.assertTrue(all(row.error_type=="RuntimeError" for row in report.observer_failures))
            self.assertNotIn("observer-secret", repr(report.observer_failures))


if __name__=="__main__": unittest.main()
