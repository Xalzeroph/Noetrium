"""Nested Trial/Workload controls preserve the single cancellation authority."""

from threading import RLock, Thread
import time

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ExecutionControlPort, TaskDeadlineExceeded
from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import _CancellationState
from noetrium_platform.research.experimentation.lifecycle.study.providers.trial import (
    _TrialScientificExecutionControl,
)
from noetrium_platform.research.experimentation.workload.runtime.graph import (
    _WorkloadExecutionBudgetControl,
)


class ManualControl:
    def __init__(self):
        self.signal = _CancellationState()

    @property
    def cancelled(self):
        return self.signal.cancelled

    @property
    def reason(self):
        return self.signal.reason

    @property
    def deadline(self):
        return None

    @property
    def remaining_seconds(self):
        return None

    @property
    def scientific_deadline(self):
        return None

    def subscribe_cancel(self, callback):
        return self.signal.subscribe_cancel(callback)

    def wait(self, timeout=None):
        return self.signal.wait(timeout)

    def checkpoint(self):
        return self.signal.checkpoint()


class DeadlineControl(ManualControl):
    def __init__(self, seconds):
        super().__init__()
        self._deadline = Deadline.after(seconds)

    @property
    def deadline(self):
        return self._deadline

    @property
    def remaining_seconds(self):
        return self._deadline.remaining_seconds

    def checkpoint(self):
        super().checkpoint()
        if self._deadline.expired:
            raise TaskDeadlineExceeded("infrastructure worker deadline expired")


class ScientificControl(ManualControl):
    def __init__(self, seconds):
        super().__init__()
        self._scientific_deadline = Deadline.after(seconds)
        self._active = True

    @property
    def scientific_time_active(self):
        return self._active

    @property
    def scientific_deadline(self):
        return self._scientific_deadline

    def activate_scientific_time(self):
        self._active = True

    @property
    def deadline(self):
        return self._scientific_deadline

    @property
    def remaining_seconds(self):
        return self._scientific_deadline.remaining_seconds


def test_unbounded_or_nested_scientific_control_is_valid_protocol():
    from noetrium_platform.foundation.kernel.concurrency.api import (
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert isinstance(UNBOUNDED_EXECUTION_CONTROL, ExecutionControlPort)
    assert isinstance(ManualControl(), ExecutionControlPort)
    parent = ManualControl()
    trial = object.__new__(_TrialScientificExecutionControl)
    trial._parent = parent
    assert isinstance(trial, ExecutionControlPort)
    seen = []
    release = trial.subscribe_cancel(lambda: seen.append("cancel"))
    parent.signal.cancel("trial stopped")
    assert seen == ["cancel"]
    release()


def test_workload_wait_wakes_on_worker_cancel_without_polling_or_losing_truth():
    parent = ManualControl()
    worker = ManualControl()
    control = object.__new__(_WorkloadExecutionBudgetControl)
    control._parent = parent
    control._worker = worker
    control._lock = RLock()
    control._active = False
    control._deadline = None
    control._task_id = "scientific-workload"
    assert isinstance(control, ExecutionControlPort)

    result = []
    task = Thread(target=lambda: result.append(control.wait(None)))
    task.start()
    try:
        worker.signal.cancel("worker cancelled")
        task.join(timeout=1)
        assert not task.is_alive(), "worker cancellation must wake unbounded wait"
        assert result == [True]
        assert control.cancelled
        assert control.reason == "worker cancelled"
    finally:
        if task.is_alive():
            parent.signal.cancel("force test cleanup")
            task.join(timeout=1)


def test_workload_wait_without_cancel_respects_requested_timeout():
    parent = ManualControl()
    control = object.__new__(_WorkloadExecutionBudgetControl)
    control._parent = parent
    control._worker = None
    control._lock = RLock()
    control._active = False
    control._deadline = None
    control._task_id = "scientific-workload"
    assert control.wait(0.01) is False


def test_worker_runtime_deadline_does_not_shorten_scientific_projection():
    scientific = ScientificControl(5.0)
    worker = DeadlineControl(0.05)
    control = _WorkloadExecutionBudgetControl(
        scientific, 2.0, "scientific-workload", worker_control=worker
    )
    control.activate_scientific_time()
    assert control.scientific_deadline is not None
    assert control.scientific_deadline.remaining_seconds > 1.5
    assert control.deadline is not None
    assert control.deadline.remaining_seconds < 0.2
    time.sleep(0.06)
    assert not control.scientific_deadline_expired
    with pytest.raises(TaskDeadlineExceeded, match="infrastructure worker"):
        control.checkpoint()


def test_trial_scientific_projection_excludes_parent_runtime_deadline():
    class Budget:
        def snapshot(self, scope_id):
            return type("Snapshot", (), {"scientific_time_active": True})()

        def remaining_seconds(self, scope_id):
            return 3.0

        def require_active(self, scope_id):
            return None

    parent = DeadlineControl(0.05)
    trial = object.__new__(_TrialScientificExecutionControl)
    trial._parent = parent
    trial._budget = Budget()
    trial._scope_id = "trial-scope"
    assert trial.scientific_deadline is not None
    assert trial.scientific_deadline.remaining_seconds > 2.5
    assert trial.deadline is not None
    assert trial.deadline.remaining_seconds < 0.2
