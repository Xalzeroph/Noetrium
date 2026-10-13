"""A sealed runtime retains terminal debt until a later physical join converges."""
from threading import Event
import pytest
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime, build_scheduling_authority
from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget, Deadline, ExecutionSpec, ExecutionLaneKind, TaskFailurePolicy


def test_failed_bounded_join_does_not_close_the_only_owner_of_async_cleanup(monkeypatch):
    runtime = build_execution_concurrency_runtime(
        scheduling_authority=build_scheduling_authority(),
        concurrency_budget=ConcurrencyBudget(max_blocking_io_workers=1, max_cpu_workers=1, max_async_io_in_flight=2),
        admission_budget=AdmissionBudget(max_total_in_flight=2, max_in_flight_per_group=2, max_blocking_io_in_flight=1, max_async_io_in_flight=2, max_cpu_in_flight=1),
    )
    entered, release = Event(), Event()
    original = runtime.admission._release

    def delayed_release(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime.admission, '_release', delayed_release)
    group = runtime.open_task_group('terminal-owner', failure_policy=TaskFailurePolicy.COLLECT_ALL)
    async def immediate(context):
        return 13
    try:
        group.submit(ExecutionSpec(task_id='done', lane_kind=ExecutionLaneKind.ASYNC_IO), immediate)
        assert entered.wait(1)
        with pytest.raises(ExceptionGroup):
            runtime.close(deadline=Deadline.after(.02))
        assert runtime.concurrency.topology_snapshot().closed
        assert not runtime.concurrency.topology_snapshot().converged
        assert not runtime.concurrency._retirement_io._closed
    finally:
        release.set()
        runtime.close(deadline=Deadline.after(2))
    assert runtime.concurrency.topology_snapshot().converged
    assert runtime.concurrency._retirement_io._closed
