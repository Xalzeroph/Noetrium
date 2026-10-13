"""Qualified lifetime continuity must preserve measured model parallelism."""
from __future__ import annotations

from dataclasses import replace

from model_admission_test_support import make_model_admission_registry
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointReplicaSet
from noetrium_platform.capabilities.model.serving.endpoint.composition import build_adaptive_model_endpoint_pool
from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import UnifiedSchedulingAuthority
from tests.test_model_endpoint_admission_v2 import _StaticTransport
from tests.test_model_flow_continuity_v1 import _binding


def test_low_latency_preference_does_not_serialize_qualified_lifetime_flows() -> None:
    """A preferred start of one is a scheduling prior, never a hard flow ceiling."""
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("qualified-continuity-parallelism")
    registry = make_model_admission_registry()
    scheduling = UnifiedSchedulingAuthority()
    base = _binding(
        latency_isolation_concurrency=1,
        preferred_admitted_concurrency=1,
        max_admitted_concurrency=32,
    )
    bindings = tuple(
        replace(
            base,
            deployment_id=f"qualified-{index}",
            deployment_generation=(str(index + 1) * 64)[:64],
            base_url=f"http://127.0.0.1:{18000 + index}",
        )
        for index in range(3)
    )
    replicas = ModelEndpointReplicaSet(bindings)
    pools = tuple(
        build_adaptive_model_endpoint_pool(
            replicas,
            task_group=group,
            admission_registry=registry,
            transport=_StaticTransport(
                {"choices": [{"message": {"content": "ok"}}]}
            ),
            scheduling_authority=scheduling,
        )
        for _ in range(3)
    )
    flows = tuple(f"trial-{index}" for index in range(9))
    try:
        expected_pool_flow_capacity = (
            len(bindings) * base.max_admitted_concurrency
        )
        assert all(
            pool.persistent_flow_capacity == expected_pool_flow_capacity
            for pool in pools
        )
        for flow in flows:
            pools[0].reserve_flow_bundle(
                pools,
                "paper",
                flow,
                deadline=Deadline.after(0.5),
                cancellation=None,
            )
        assert all(len(pool._reserved_flows) == len(flows) for pool in pools)
        claims_by_deployment: dict[str, int] = {}
        for pool in pools:
            for deployment_id, _lease in pool._physical_flow_claims.values():
                claims_by_deployment[deployment_id] = (
                    claims_by_deployment.get(deployment_id, 0) + 1
                )
        assert sum(claims_by_deployment.values()) == len(flows) * len(pools)
        assert max(claims_by_deployment.values()) <= base.max_admitted_concurrency
    finally:
        for flow in reversed(flows):
            for pool in pools:
                if flow in pool._physical_flow_claims:
                    pool.release_flow(flow)
        for pool in pools:
            pool.close()
        registry.close()
        runtime.close()


def test_idle_lifetime_affinity_does_not_consume_active_adaptive_slots() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    import time

    from noetrium_platform.capabilities.model.request.api import model_lifetime_flow_id
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointResponse,
        ModelEndpointRoute,
    )
    from tests.model_endpoint_test_support import make_test_model_endpoint_pool
    from tests.test_model_flow_continuity_v1 import _request

    entered: list[str] = []
    lock = Lock()
    first_wave = Event()
    release = Event()

    class Endpoint:
        def __init__(self, binding):
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self):
            return self._route

        def complete(self, request):
            with lock:
                entered.append(request.request.request_id)
                if len(entered) >= 3:
                    first_wave.set()
            if not release.wait(5):
                raise TimeoutError("parallelism test release gate did not open")
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    base = _binding(
        latency_isolation_concurrency=1,
        preferred_admitted_concurrency=1,
        max_admitted_concurrency=32,
    )
    bindings = tuple(
        replace(
            base,
            deployment_id=f"active-{index}",
            deployment_generation=(str(index + 4) * 64)[:64],
            base_url=f"http://127.0.0.1:{18100 + index}",
        )
        for index in range(3)
    )
    pool = make_test_model_endpoint_pool(ModelEndpointReplicaSet(bindings), Endpoint)
    lifetimes = tuple(f"life-{index}" for index in range(9))
    flows = tuple(model_lifetime_flow_id(lifetime) for lifetime in lifetimes)
    for flow in flows:
        pool.reserve_flow("paper", flow, deadline=Deadline.after(0.5), cancellation=None)
    assert pool.snapshot().reserved_flow_count == len(lifetimes)

    try:
        with ThreadPoolExecutor(max_workers=len(lifetimes)) as executor:
            futures = tuple(
                executor.submit(
                    pool.complete,
                    _request(
                        f"request-{index}",
                        tenant_id="paper",
                        lifetime_id=lifetime,
                    ),
                    {},
                    input_tokens=1,
                    requested_output_tokens=1,
                    timeout_s=5,
                )
                for index, lifetime in enumerate(lifetimes)
            )
            assert first_wave.wait(2), "three qualified replicas did not serve concurrently"
            time.sleep(0.05)
            with lock:
                assert len(entered) == 3
            release.set()
            assert all(future.result(timeout=5).response.text == "ok" for future in futures)
    finally:
        release.set()
        for flow in flows:
            if flow in pool._reserved_flows:
                pool.release_flow(flow)
        pool.close()
