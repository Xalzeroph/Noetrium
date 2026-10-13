"""Physical model Claim retirement reuses the original synchronous caller."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    JsonHttpResponse, ModelEndpointRequest, ModelEndpointRoute,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers.native import (
    NativeModelProviderEndpoint,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget, ExecutionLaneKind, ExecutionSpec, TaskFailureScope,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from tests.test_model_endpoint_provider_v1 import _envelope


def test_retirement_has_no_second_admission_even_when_serial_workers_are_full():
    qualified_capacity = 4
    runtime = build_concurrency_runtime(budget=ConcurrencyBudget(
        max_serial_workers=1,
        max_blocking_io_workers=1,
        max_cpu_workers=1,
        max_async_io_in_flight=qualified_capacity,
    ))
    group = runtime.open_task_group("already-authorized-caller-retirement")
    mutex = Lock()
    counters = {"active": 0, "peak": 0, "completed": 0}

    class Lease:
        def release(self):
            with mutex:
                counters["active"] += 1
                counters["peak"] = max(counters["peak"], counters["active"])
            time.sleep(.065)
            with mutex:
                counters["active"] -= 1
                counters["completed"] += 1

    class Admission:
        capacity = qualified_capacity
        def acquire(self, **kwargs):
            return Lease()

    class Transport:
        async def post_json(self, *args, **kwargs):
            await asyncio.sleep(.005)
            return JsonHttpResponse(200, {
                "choices": [{"message": {"content": "done"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            })

    serial_entered, serial_release = Event(), Event()

    def occupy_unrelated_serial(context):
        serial_entered.set()
        assert serial_release.wait(3)

    unrelated = group.submit(
        ExecutionSpec(
            task_id="fully-occupied-serial-domain",
            lane_kind=ExecutionLaneKind.SERIAL,
            lane_id="unrelated-saturated-serial-worker",
            failure_scope=TaskFailureScope.CALLER,
        ),
        occupy_unrelated_serial,
    )
    assert serial_entered.wait(2)

    endpoint = NativeModelProviderEndpoint(
        route=ModelEndpointRoute(
            "test-model", "a" * 64, "http://127.0.0.1:18888"
        ),
        task_group=group,
        admission=Admission(),
        transport=Transport(),
        owns_transport=False,
    )

    def request(index):
        item = ModelEndpointRequest(
            request=_envelope(f"concurrent-{index}"),
            deployment_id="test-model",
            deployment_generation="a" * 64,
            body={
                "model": "qwen",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        return endpoint.complete(item)

    async def heartbeat(context):
        await asyncio.sleep(.018)
        return time.perf_counter()

    try:
        began = time.perf_counter()
        heartbeat_handle = group.submit(
            ExecutionSpec(task_id="model-loop-heartbeat",
                          lane_kind=ExecutionLaneKind.ASYNC_IO,
                          failure_scope=TaskFailureScope.CALLER),
            heartbeat,
        )
        with ThreadPoolExecutor(max_workers=qualified_capacity) as pool:
            completed = list(pool.map(request, range(qualified_capacity)))
        elapsed = time.perf_counter() - began
        assert len(completed) == qualified_capacity
        assert all(row.text == "done" for row in completed)
        assert counters["completed"] == qualified_capacity
        assert counters["peak"] >= 2
        assert heartbeat_handle.result(timeout=1) - began < .14
        assert elapsed < .27
        assert not unrelated.done(), "unrelated serial work remained blocked"
        assert not any(
            "model-admission-retire" in lane.lane_id
            for lane in runtime.topology_snapshot().serial_lanes
        )
        for row in completed:
            timings = dict(row.stage_timings_ns)
            assert timings["authority_release_commit"] >= 0
            assert "authority_release_submission_wait" not in timings
    finally:
        serial_release.set()
        runtime.close()
