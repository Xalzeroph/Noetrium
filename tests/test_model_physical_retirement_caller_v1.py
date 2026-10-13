"""The owning synchronous model caller retires only physically finished Claims."""
from __future__ import annotations

from threading import Event, Thread

import pytest

from noetrium_platform.capabilities.model.serving.endpoint.providers.native import (
    NativeModelProviderEndpoint, _PhysicalRetirementGate,
)


def test_logical_timeout_returns_without_freeing_claim_until_physical_completion():
    subscribed, leave_physical_task = Event(), Event()
    observer_result, released = Event(), Event()
    counters = {"cancel": 0, "release": 0}
    raised = []

    class Lease:
        def release(self):
            assert leave_physical_task.is_set()
            counters["release"] += 1
            released.set()

    class Handle:
        callback = None

        def add_done_callback(self, callback):
            self.callback = callback
            subscribed.set()

        def result(self, timeout=None):
            raise AssertionError("timed-out caller must not rejoin unfinished transport")

        def cancel(self):
            counters["cancel"] += 1
            return True

        def physical_complete(self):
            leave_physical_task.set()
            self.callback(self)

    handle = Handle()

    def caller():
        try:
            NativeModelProviderEndpoint._await_and_retire(
                handle, Lease(), gate=_PhysicalRetirementGate(),
                timeout_seconds=.001
            )
        except BaseException as exc:
            raised.append(exc)
        finally:
            observer_result.set()

    worker = Thread(target=caller, daemon=True)
    worker.start()
    try:
        assert subscribed.wait(1)
        assert observer_result.wait(1), (
            "logical caller must fail closed instead of waiting forever for transport"
        )
        worker.join(1)
        assert not worker.is_alive()
        assert counters["cancel"] == 1
        assert counters["release"] == 0
        assert not released.is_set(), "Claim must remain fenced while HTTP may still run"
        assert len(raised) == 1
        assert isinstance(raised[0], TimeoutError)

        handle.physical_complete()
        assert released.wait(1)
        assert counters["release"] == 1
    finally:
        if not leave_physical_task.is_set():
            handle.physical_complete()
        worker.join(2)


def test_completed_handle_wins_timeout_transfer_race_and_keeps_parent_retirement():
    released = []
    gate = _PhysicalRetirementGate()
    gate.signal_if_never_started()

    class Lease:
        def release(self):
            released.append("released")

    class Handle:
        def add_done_callback(self, callback):
            callback(self)

        def cancel(self):
            raise AssertionError("completed handle must not be cancelled")

        def result(self, timeout=None):
            return "done"

    assert NativeModelProviderEndpoint._await_and_retire(
        Handle(), Lease(), gate=gate, timeout_seconds=.001
    ) == "done"
    assert released == ["released"]


def test_claim_retirement_failure_is_not_recorded_as_success():
    class Lease:
        def release(self):
            raise RuntimeError("Resource Authority commit rejected")

    class Handle:
        def add_done_callback(self, callback):
            callback(self)

        def result(self, timeout=None):
            return "provider-output"

    timings = {}
    with pytest.raises(RuntimeError, match="commit rejected"):
        NativeModelProviderEndpoint._await_and_retire(
            Handle(), Lease(), gate=_PhysicalRetirementGate(),
            timeout_seconds=None, timings_ns=timings
        )
    assert timings["authority_release_commit"] >= 0
    assert timings["authority_release"] >= 0


def test_execution_and_retirement_failures_are_both_preserved():
    class Lease:
        def release(self):
            raise RuntimeError("authority commit unavailable")

    class Handle:
        def add_done_callback(self, callback):
            callback(self)

        def result(self, timeout=None):
            raise ValueError("provider returned invalid response")

    with pytest.raises(BaseExceptionGroup) as failure:
        NativeModelProviderEndpoint._await_and_retire(
            Handle(), Lease(), gate=_PhysicalRetirementGate(),
            timeout_seconds=None
        )
    assert len(failure.value.exceptions) == 2
    assert isinstance(failure.value.exceptions[0], ValueError)
    assert isinstance(failure.value.exceptions[1], RuntimeError)


def test_kernel_parent_task_remains_live_during_blocking_authority_retirement():
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from tests.test_model_endpoint_provider_v1 import _request
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        JsonHttpResponse, ModelEndpointRoute,
    )
    from noetrium_platform.foundation.kernel.concurrency.composition import (
        build_concurrency_runtime,
    )

    started_release, allow_release = Event(), Event()
    released = Event()

    class Lease:
        def release(self):
            started_release.set()
            assert allow_release.wait(3)
            released.set()

    class Admission:
        capacity = 1
        def acquire(self, **kwargs):
            return Lease()

    class Transport:
        async def post_json(self, *args, **kwargs):
            return JsonHttpResponse(200, {
                "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            })

    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("parent-fenced-model-release")
    endpoint = NativeModelProviderEndpoint(
        route=ModelEndpointRoute(
            "dep-1", "a" * 64, "http://127.0.0.1:30000"
        ),
        transport=Transport(),
        task_group=group,
        admission=Admission(),
        owns_transport=False,
    )
    with ThreadPoolExecutor(max_workers=1) as callers:
        task = callers.submit(endpoint.complete, _request())
        try:
            assert started_release.wait(2)
            assert not released.is_set()
            snapshots = runtime.topology_snapshot().groups[0].tasks
            assert len(snapshots) == 1
            assert not snapshots[0].execution_done, (
                "Kernel TaskGroup must stay live until Claim retirement commits"
            )
            assert not task.done()
        finally:
            allow_release.set()
        assert task.result(timeout=3).text == "done"
    assert released.is_set()
    assert all(t.execution_done for t in runtime.topology_snapshot().groups[0].tasks)
    runtime.close()
