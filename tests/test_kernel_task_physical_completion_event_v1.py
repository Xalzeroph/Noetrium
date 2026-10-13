"""Physical completion signals for Kernel-owned tasks are event-driven."""
from threading import Event, Thread

from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind, ExecutionSpec, TaskFailureScope,
)


def test_serial_completion_callback_is_exactly_once_and_fenced():
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("physical-completion-callback-test")
    entered = Event()
    release = Event()
    done = Event()
    outcomes = []

    def work(context):
        entered.set()
        assert release.wait(5)
        return "physical-done"

    try:
        handle = group.submit(
            ExecutionSpec(
                task_id="completion-test", lane_kind=ExecutionLaneKind.SERIAL,
                lane_id="completion-test-lane",
                failure_scope=TaskFailureScope.CALLER,
            ),
            work,
        )
        handle.add_done_callback(
            lambda finished: (outcomes.append(
                (finished.task_id, finished.done(), finished.result(timeout=0))
            ), done.set())
        )
        assert entered.wait(3)
        assert not done.is_set()
        release.set()
        assert done.wait(3)
        assert outcomes == [("completion-test", True, "physical-done")]
        # Subscription after completion is an immediate event, not a poll.
        after = Event()
        handle.add_done_callback(lambda _: after.set())
        assert after.wait(1)
    finally:
        release.set()
        runtime.close()


def test_cancelled_pending_serial_task_also_notifies_physical_completion():
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("physical-cancel-callback-test")
    entered = Event()
    release = Event()
    done = Event()

    def hold(context):
        entered.set()
        assert release.wait(5)

    def queued(context):
        raise AssertionError("cancelled task must not execute")

    try:
        holder = group.submit(
            ExecutionSpec(task_id="holder", lane_kind=ExecutionLaneKind.SERIAL,
                          lane_id="same-lane", failure_scope=TaskFailureScope.CALLER),
            hold,
        )
        assert entered.wait(2)
        waiting = group.submit(
            ExecutionSpec(task_id="waiting", lane_kind=ExecutionLaneKind.SERIAL,
                          lane_id="same-lane", failure_scope=TaskFailureScope.CALLER),
            queued,
        )
        waiting.add_done_callback(lambda task: done.set())
        waiting.cancel()
        assert done.wait(3)
        assert waiting.done()
    finally:
        release.set()
        runtime.close()
