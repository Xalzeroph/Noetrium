from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from runtime_manager_test_support import make_runtime_control_store
from noetrium_platform.infrastructure.lifecycle.launch_control import ExactRuntimeController
from noetrium_platform.infrastructure.lifecycle.launch_control.one_click import OneClickRuntimeManager
from noetrium_platform.infrastructure.reliability.recovery.execution.runtime.file_lock import FileLockedRecoveryExecutionFactory
from tests_support import recovery_lease_state
from tests_support import frozen_runtime_manifest


class ExactAdapter:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, action, manifest):
        del manifest
        self.calls.append(action)
        return (f"evidence:{action.value}",)


class Plane:
    def __init__(self, controller):
        self.controller = controller

    def run_exact(self, manifest, *, control_id, action_guard=None, observer=None, observer_failure_sink=None):
        return self.controller.run(
            manifest,
            control_id=control_id,
            action_guard=action_guard,
            observer=observer,
            observer_failure_sink=observer_failure_sink,
        )


class ExplodingObserver:
    def action_started(self, action, *, mutating): raise RuntimeError("observer-secret")
    def action_finished(self, action, *, result, mutating): raise RuntimeError("observer-secret")
    def reconcile_finished(self, *, scope): raise RuntimeError("observer-secret")
    def exact_service_started(self): raise RuntimeError("observer-secret")
    def qualification_verified(self): raise RuntimeError("observer-secret")
    def lease_wait_started(self): raise RuntimeError("observer-secret")
    def lease_acquired(self): raise RuntimeError("observer-secret")
    def lease_conflict(self): raise RuntimeError("observer-secret")
    def recovery_round(self, action, *, round_number): raise RuntimeError("observer-secret")


class CollectingFailureSink:
    def __init__(self) -> None:
        self.rows = []

    def record(self, failure) -> None:
        self.rows.append(failure)


class ExplodingFailureSink:
    def record(self, failure) -> None:
        del failure
        raise RuntimeError("failure-sink-secret")


class RuntimeObserverIsolationV183Tests(unittest.TestCase):
    def test_control_observer_failure_never_changes_runtime_truth(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            adapter = ExactAdapter()
            sink = CollectingFailureSink()
            controller = ExactRuntimeController(make_runtime_control_store(root / "runtime.json"), adapter)
            report = controller.run(
                frozen_runtime_manifest(),
                control_id="observer-control",
                observer=ExplodingObserver(),
                observer_failure_sink=sink,
            )
            self.assertEqual(report.state.phase.value, "succeeded")
            self.assertTrue(report.observer_failures)
            self.assertEqual(tuple(sink.rows), report.observer_failures)
            self.assertTrue(all(row.error_type == "RuntimeError" for row in report.observer_failures))
            self.assertNotIn("observer-secret", repr(report.observer_failures))

    def test_one_click_observer_and_failure_sink_cannot_change_recovery_truth(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            adapter = ExactAdapter()
            runtime_store = make_runtime_control_store(root / "runtime.json")
            controller = ExactRuntimeController(runtime_store, adapter)
            manager = OneClickRuntimeManager(
                Plane(controller),
                FileLockedRecoveryExecutionFactory(
                    recovery_lease_state(root / "lease.json"),
                    lock_path=root / "recovery.execution.lock",
                ),
                runtime_store,
            )
            report = manager.run_exact(
                frozen_runtime_manifest(),
                control_id="observer-one-click",
                owner_id="owner",
                observer=ExplodingObserver(),
                observer_failure_sink=ExplodingFailureSink(),
            )
            self.assertEqual(report.runtime.state.phase.value, "succeeded")
            self.assertTrue(report.history_verified)
            self.assertTrue(report.observer_failures)
            self.assertNotIn("observer-secret", repr(report.observer_failures))
            self.assertNotIn("failure-sink-secret", repr(report.observer_failures))


if __name__ == "__main__":
    unittest.main()
