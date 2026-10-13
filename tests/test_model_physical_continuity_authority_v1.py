from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import UnifiedSchedulingAuthority

from tests.model_endpoint_test_support import make_test_model_endpoint_pool

from uuid import uuid4

import pytest

from model_admission_test_support import make_model_admission_registry
from noetrium_platform.capabilities.model.serving.runtime import (
    ModelAdmissionRegistry,
    ModelAdmissionTimeout,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE


def test_physical_continuity_reserves_one_real_slot_across_registries() -> None:
    primary = make_model_admission_registry()
    authority = primary._test_authority
    owner = uuid4().hex
    from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
    # Independent Authority object over the same durable source validates that
    # a second process cannot create a competing capacity ledger.
    other_authority = UniversalResourceAuthority(authority.path)
    other_lease = other_authority.acquire_ttl_lease(
        lease_id="secondary-continuity-test:" + owner,
        resource_key="secondary-continuity-test:" + owner,
        holder_key="secondary-continuity-test:" + owner,
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=3600.0,
        metadata={"kind": "test-continuity-secondary-owner"},
    )
    secondary = ModelAdmissionRegistry(other_authority, other_lease)
    a = primary.controller_for(
        deployment_id="same-deployment", deployment_generation="a" * 64,
        qualified_capacity=2, continuity_capacity=1,
    )
    b = secondary.controller_for(
        deployment_id="same-deployment", deployment_generation="a" * 64,
        qualified_capacity=2, continuity_capacity=1,
    )
    first = a.try_reserve_continuity(owner_id="paper-a", flow_id="agent-a")
    assert first is not None
    # A separate Registry, logical endpoint pool and owner generation cannot
    # consume the already-allocated certified flow entitlement.
    assert b.try_reserve_continuity(owner_id="paper-b", flow_id="agent-b") is None
    normal = b.acquire(owner_id="paper-b", timeout_seconds=0.1)
    with pytest.raises(ModelAdmissionTimeout):
        b.acquire(owner_id="paper-b", timeout_seconds=0.025)
    with pytest.raises(RuntimeError, match="claims remain"):
        a.close()
    normal.release()
    first.release()
    second = b.try_reserve_continuity(owner_id="paper-b", flow_id="agent-b")
    assert second is not None
    second.release()
    a.close()
    b.close()
    primary.close()
    secondary.close()


def test_physical_continuity_qualification_drift_is_fail_closed() -> None:
    registry = make_model_admission_registry()
    controller = registry.controller_for(
        deployment_id="model", deployment_generation="b" * 64,
        qualified_capacity=3, continuity_capacity=2,
    )
    with pytest.raises(ValueError, match="qualification drift"):
        controller.qualify_continuity(1)
    with pytest.raises(ValueError, match="within physical capacity"):
        controller.qualify_continuity(4)
    controller.close()
    registry.close()


def test_physical_reserved_slot_is_borrowed_without_double_counting() -> None:
    registry = make_model_admission_registry()
    a = registry.controller_for(
        deployment_id="one-slot", deployment_generation="c" * 64,
        qualified_capacity=1, continuity_capacity=1,
    )
    reserved = a.try_reserve_continuity(owner_id="paper", flow_id="life")
    assert reserved is not None
    first = a.acquire(
        owner_id="paper", continuity_claim_id=reserved.claim_id,
        timeout_seconds=0.1,
    )
    assert a.snapshot().active == 1
    with pytest.raises(ModelAdmissionTimeout):
        a.acquire(owner_id="paper", timeout_seconds=0.025)
    with pytest.raises(ModelAdmissionTimeout):
        a.acquire(
            owner_id="paper", continuity_claim_id=reserved.claim_id,
            timeout_seconds=0.025,
        )
    first.release()
    assert a.snapshot().active == 0
    second = a.acquire(
        owner_id="paper", continuity_claim_id=reserved.claim_id,
        timeout_seconds=0.1,
    )
    second.release()
    reserved.release()
    a.close()
    registry.close()


def test_endpoint_pools_share_one_physical_continuity_claim() -> None:
    from noetrium_platform.capabilities.model.request.api import (
        model_lifetime_flow_id, model_request_owner_id,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointReplicaSet, ModelEndpointResponse, ModelEndpointRoute,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
        AdaptiveModelEndpointPool, ModelEndpointPoolUnavailable,
    )
    from tests.test_model_flow_continuity_v1 import _binding, _request

    registry = make_model_admission_registry()
    binding = _binding(latency_isolation_concurrency=1, max_admitted_concurrency=1)
    controller = registry.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=1, continuity_capacity=1,
    )
    borrowed = []

    class Endpoint:
        def __init__(self, binding):
            self._route = ModelEndpointRoute(
                binding.deployment_id, binding.deployment_generation, binding.base_url
            )
        @property
        def route(self):
            return self._route
        def complete(self, request):
            borrowed.append(request.continuity_claim_id)
            with controller.acquire(
                owner_id=model_request_owner_id(request.request),
                continuity_claim_id=request.continuity_claim_id,
                timeout_seconds=0.1,
            ):
                return ModelEndpointResponse(
                    request_id=request.request.request_id,
                    deployment_id=request.deployment_id, text="physical authorization ok",
                )

    endpoints = ModelEndpointReplicaSet((binding,))
    controllers = {binding.deployment_id: controller}
    first = make_test_model_endpoint_pool(
        endpoints, Endpoint, physical_continuity_controllers=controllers,
    )
    second = make_test_model_endpoint_pool(
        endpoints, Endpoint, physical_continuity_controllers=controllers,
    )
    a_flow = model_lifetime_flow_id("life-a")
    b_flow = model_lifetime_flow_id("life-b")
    first.reserve_flow("paper-a", a_flow, deadline=None, cancellation=None)
    claim_id = first._physical_flow_claims[a_flow][1].claim_id
    from concurrent.futures import ThreadPoolExecutor
    from noetrium_platform.foundation.kernel.concurrency.api import Deadline
    from threading import Event
    waiting_entered = Event()
    def reserve_second():
        waiting_entered.set()
        second.reserve_flow(
            "paper-b", b_flow,
            deadline=Deadline.after(5.0), cancellation=None,
        )
    with ThreadPoolExecutor(max_workers=1) as workers:
        blocked = workers.submit(reserve_second)
        assert waiting_entered.wait(2.0)
        # At the exact physical cut a second logical pool cannot reserve
        # the same physical slot, yet the request must stay alive rather than
        # turning transient contention into a failed scientific experiment.
        assert not blocked.done()
        result = first.complete(
            _request("a1", tenant_id="paper-a", lifetime_id="life-a"), {},
            input_tokens=1, requested_output_tokens=1,
        )
        assert result.response.text == "physical authorization ok"
        assert borrowed == [claim_id]
        assert first.snapshot().reserved_flow_count == 1
        assert not blocked.done()
        first.release_flow(a_flow)
        blocked.result(timeout=3.0)
    response = second.complete(
        _request("b1", tenant_id="paper-b", lifetime_id="life-b"), {},
        input_tokens=1, requested_output_tokens=1,
    )
    assert response.response.text == "physical authorization ok"
    assert borrowed[-1] != claim_id
    second.release_flow(b_flow)
    first.close()
    second.close()
    registry.close()


def test_replicated_physical_flow_stays_on_exact_claimed_deployment() -> None:
    from noetrium_platform.capabilities.model.request.api import (
        model_lifetime_flow_id, model_request_owner_id,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointReplicaSet, ModelEndpointResponse, ModelEndpointRoute,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.runtime import AdaptiveModelEndpointPool
    from tests.test_model_endpoint_replica_pool_v1 import _binding
    from tests.test_model_flow_continuity_v1 import _request

    registry = make_model_admission_registry()
    bindings = (_binding(0, capacity=1), _binding(1, capacity=1))
    controllers = {
        binding.deployment_id: registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=1, continuity_capacity=1,
        )
        for binding in bindings
    }

    class Endpoint:
        def __init__(self, binding):
            self._route = ModelEndpointRoute(
                binding.deployment_id, binding.deployment_generation, binding.base_url
            )
        @property
        def route(self):
            return self._route
        def complete(self, request):
            with controllers[request.deployment_id].acquire(
                owner_id=model_request_owner_id(request.request),
                continuity_claim_id=request.continuity_claim_id,
                timeout_seconds=0.1,
            ):
                return ModelEndpointResponse(
                    request_id=request.request.request_id,
                    deployment_id=request.deployment_id, text="routed",
                )

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings), Endpoint,
        physical_continuity_controllers=controllers,
    )
    flow_ids = tuple(model_lifetime_flow_id(f"life-{i}") for i in range(2))
    for i, flow in enumerate(flow_ids):
        pool.reserve_flow(f"paper-{i}", flow, deadline=None, cancellation=None)
    physical = {
        flow: pool._physical_flow_claims[flow][0] for flow in flow_ids
    }
    assert len(set(physical.values())) == 2
    for i, flow in enumerate(flow_ids):
        result = pool.complete(
            _request(f"physical-{i}", tenant_id=f"paper-{i}", lifetime_id=f"life-{i}"),
            {}, input_tokens=1, requested_output_tokens=1,
        )
        assert result.response.deployment_id == physical[flow]
    for flow in flow_ids:
        pool.release_flow(flow)
    pool.close()
    registry.close()


def test_physical_continuity_balances_long_lived_flows_before_replica_saturation() -> None:
    """Long-lived flows must not first-fit into replica zero while peers idle."""
    from collections import Counter

    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointReplicaSet, ModelEndpointRoute,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
        AdaptiveModelEndpointPool,
    )
    from tests.test_model_endpoint_replica_pool_v1 import _binding

    registry = make_model_admission_registry()
    bindings = tuple(_binding(i, capacity=3) for i in range(3))
    controllers = {
        binding.deployment_id: registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=3,
            continuity_capacity=3,
        )
        for binding in bindings
    }

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

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        Endpoint,
        physical_continuity_controllers=controllers,
    )
    flows = tuple(f"balanced-life-{i}" for i in range(6))
    try:
        for flow in flows:
            pool.reserve_flow(
                "paper", flow, deadline=None, cancellation=None,
            )
        distribution = Counter(
            pool._physical_flow_claims[flow][0] for flow in flows
        )
        assert set(distribution) == set(controllers)
        assert sorted(distribution.values()) == [2, 2, 2]
    finally:
        for flow in flows:
            if flow in pool._physical_flow_claims:
                pool.release_flow(flow)
        pool.close()
        registry.close()


def test_physical_placement_observes_other_pool_and_active_request_claims() -> None:
    """Placement consumes one global Authority cut, not pool-local utilization."""
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointReplicaSet, ModelEndpointRoute,
    )
    from tests.test_model_endpoint_replica_pool_v1 import _binding

    registry = make_model_admission_registry()
    bindings = tuple(_binding(i, capacity=2) for i in range(2))
    controllers = {
        binding.deployment_id: registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=2,
            continuity_capacity=2,
        )
        for binding in bindings
    }

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

    replica_set = ModelEndpointReplicaSet(bindings)
    first = make_test_model_endpoint_pool(
        replica_set, Endpoint, physical_continuity_controllers=controllers,
    )
    second = make_test_model_endpoint_pool(
        replica_set, Endpoint, physical_continuity_controllers=controllers,
    )
    occupied = None
    try:
        first.reserve_flow("tenant-a", "life:a", deadline=None, cancellation=None)
        first_deployment = first._physical_flow_claims["life:a"][0]
        # An ordinary request on that same deployment fills its remaining
        # physical slot; the second *independent* pool must choose its peer.
        occupied = controllers[first_deployment].acquire(
            owner_id="tenant-b", timeout_seconds=0.5,
        )
        second.reserve_flow("tenant-c", "life:c", deadline=None, cancellation=None)
        assert second._physical_flow_claims["life:c"][0] != first_deployment
    finally:
        if occupied is not None:
            occupied.release()
        if "life:a" in first._physical_flow_claims:
            first.release_flow("life:a")
        if "life:c" in second._physical_flow_claims:
            second.release_flow("life:c")
        first.close()
        second.close()
        registry.close()


def test_commit_event_wakes_cross_pool_flow_without_timeout_polling() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    import time

    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointReplicaSet, ModelEndpointRoute,
    )
    from tests.test_model_endpoint_replica_pool_v1 import _binding

    class CommitFeed:
        def __init__(self):
            self.lock = Lock()
            self.callbacks = {}
            self.next_token = 0

        def subscribe(self, keys, callback):
            assert keys
            with self.lock:
                self.next_token += 1
                token = self.next_token
                self.callbacks[token] = callback

            def unsubscribe():
                with self.lock:
                    self.callbacks.pop(token, None)
            return unsubscribe

        def emit(self):
            with self.lock:
                callbacks = tuple(self.callbacks.values())
            for callback in callbacks:
                callback()

        def close(self):
            with self.lock:
                self.callbacks.clear()

    registry = make_model_admission_registry()
    feed = CommitFeed()
    registry._change_feed = feed
    binding = _binding(0, capacity=1)
    controller = registry.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=1,
        continuity_capacity=1,
    )

    class Endpoint:
        def __init__(self, member):
            self._route = ModelEndpointRoute(
                member.deployment_id,
                member.deployment_generation,
                member.base_url,
            )

        @property
        def route(self):
            return self._route

    replica_set = ModelEndpointReplicaSet((binding,))
    controllers = {binding.deployment_id: controller}
    first = make_test_model_endpoint_pool(
        replica_set, Endpoint, physical_continuity_controllers=controllers,
    )
    second = make_test_model_endpoint_pool(
        replica_set, Endpoint, physical_continuity_controllers=controllers,
    )
    first.reserve_flow("holder", "flow:held", deadline=None, cancellation=None)
    attempts = [0]
    attempt_lock = Lock()
    attempted = Event()
    original_try = second._acquire_physical_flow_claim

    def counted_try(*, owner_id, flow_id):
        result = original_try(owner_id=owner_id, flow_id=flow_id)
        with attempt_lock:
            attempts[0] += 1
        attempted.set()
        return result

    second._acquire_physical_flow_claim = counted_try
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                second.reserve_flow, "waiting", "flow:waiting",
                deadline=None, cancellation=None,
            )
            assert attempted.wait(3)
            with attempt_lock:
                initial_attempts = attempts[0]
            # The waiter remains asleep despite an available fallback timer:
            # only a physical commit event can wake its Condition.
            time.sleep(0.12)
            with attempt_lock:
                assert attempts[0] == initial_attempts
            assert not pending.done()
            first.release_flow("flow:held")
            feed.emit()
            pending.result(timeout=3)
        assert second._physical_flow_claims["flow:waiting"][0] == binding.deployment_id
    finally:
        if "flow:held" in first._physical_flow_claims:
            first.release_flow("flow:held")
        if "flow:waiting" in second._physical_flow_claims:
            second.release_flow("flow:waiting")
        first.close()
        second.close()
        registry.close()


def test_same_physical_flow_identity_cannot_double_reserve_spare_capacity() -> None:
    registry = make_model_admission_registry()
    controller = registry.controller_for(
        deployment_id="double-flow", deployment_generation="d" * 64,
        qualified_capacity=3, continuity_capacity=3,
    )
    first = controller.try_reserve_continuity(owner_id="paper-a", flow_id="same-life")
    assert first is not None
    assert controller.try_reserve_continuity(owner_id="paper-b", flow_id="same-life") is None
    distinct = controller.try_reserve_continuity(owner_id="paper-b", flow_id="other-life")
    assert distinct is not None
    first.release()
    after_release = controller.try_reserve_continuity(owner_id="paper-b", flow_id="same-life")
    assert after_release is not None
    after_release.release()
    distinct.release()
    controller.close()
    registry.close()


def test_native_model_transport_uses_reserved_physical_slot_without_extra_claim() -> None:
    from noetrium_platform.capabilities.model.request.api import model_lifetime_flow_id
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        JsonHttpResponse, ModelEndpointReplicaSet, ModelEndpointRoute,
        OperationalModelEndpointReplica,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.composition import (
        build_adaptive_model_endpoint_pool,
    )
    from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
    from tests.test_model_flow_continuity_v1 import _request

    class Transport:
        def __init__(self) -> None:
            self.calls = 0
        async def post_json(self, url, body, *, timeout_s, headers=()):
            del url, body, timeout_s, headers
            self.calls += 1
            return JsonHttpResponse(200, {
                "choices": [{"message": {"content": "real-slot"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            })

    registry = make_model_admission_registry()
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("native-continuity-physical-test")
    route = ModelEndpointRoute("physical-native", "e" * 64, "http://127.0.0.1:18000")
    transport = Transport()
    pool = build_adaptive_model_endpoint_pool(
        ModelEndpointReplicaSet((OperationalModelEndpointReplica(route, 1),)),
        task_group=group, admission_registry=registry, transport=transport,
     scheduling_authority=UnifiedSchedulingAuthority())
    flow = model_lifetime_flow_id("native-life")
    try:
        pool.reserve_flow("paper", flow, deadline=None, cancellation=None)
        controller = registry.controller_for(
            deployment_id=route.deployment_id,
            deployment_generation=route.deployment_generation,
            qualified_capacity=1, continuity_capacity=1,
        )
        assert controller.snapshot().active == 0
        result = pool.complete(
            _request("native-1", tenant_id="paper", lifetime_id="native-life"),
            {"model": "qwen", "messages": [{"role": "user", "content": "hello"}]},
            input_tokens=1, requested_output_tokens=1,
        )
        assert result.response.text == "real-slot"
        assert transport.calls == 1
        assert controller.snapshot().active == 0
        assert len(controller._claims_at_cut()[1]) == 1
        pool.release_flow(flow)
        assert controller._claims_at_cut()[1] == ()
    finally:
        pool.close()
        registry.close()
        runtime.close()


def test_qualified_model_dispatch_uses_certified_physical_continuity() -> None:
    from noetrium_platform.capabilities.model.request.api import model_lifetime_flow_id
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        JsonHttpResponse, ModelEndpointReplicaSet,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.composition import (
        build_adaptive_model_endpoint_pool,
    )
    from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
    from tests.test_model_flow_continuity_v1 import _binding, _request

    class Transport:
        async def post_json(self, url, body, *, timeout_s, headers=()):
            del url, body, timeout_s, headers
            return JsonHttpResponse(200, {
                "choices": [{"message": {"content": "qualified"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            })

    registry = make_model_admission_registry()
    runtime = build_concurrency_runtime()
    group = runtime.open_task_group("qualified-continuity-physical-test")
    binding = _binding(latency_isolation_concurrency=1, max_admitted_concurrency=1)
    pool = build_adaptive_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        task_group=group, admission_registry=registry, transport=Transport(),
     scheduling_authority=UnifiedSchedulingAuthority())
    flow = model_lifetime_flow_id("qualified-life")
    try:
        pool.reserve_flow("paper", flow, deadline=None, cancellation=None)
        result = pool.complete(
            _request("qualified-1", tenant_id="paper", lifetime_id="qualified-life"),
            {"model": "qwen", "messages": [{"role": "user", "content": "qualified"}]},
            input_tokens=1, requested_output_tokens=1,
        )
        assert result.response.text == "qualified"
        pool.release_flow(flow)
    finally:
        pool.close()
        registry.close()
        runtime.close()


def test_continuity_reservation_cannot_release_while_physical_request_borrows() -> None:
    from noetrium_platform.infrastructure.resources.authority import ResourceClaimConflict
    registry = make_model_admission_registry()
    controller = registry.controller_for(
        deployment_id="affine-model", deployment_generation="f" * 64,
        qualified_capacity=1, continuity_capacity=1,
    )
    reservation = controller.try_reserve_continuity(
        owner_id="paper", flow_id="physical-life",
    )
    assert reservation is not None
    borrowed = controller.acquire(
        owner_id="paper", continuity_claim_id=reservation.claim_id,
        timeout_seconds=0.1,
    )
    with pytest.raises(ResourceClaimConflict, match="active child"):
        reservation.release()
    with pytest.raises(ModelAdmissionTimeout):
        controller.acquire(owner_id="other", timeout_seconds=0.025)
    borrowed.release()
    reservation.release()
    replacement = controller.acquire(owner_id="other", timeout_seconds=0.1)
    replacement.release()
    controller.close()
    registry.close()


def test_cross_pool_resource_claim_wait_honors_deadline_and_cancellation() -> None:
    """Cross-process-style capacity debt remains a waiter, not a leaked claim."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointReplicaSet, ModelEndpointRoute,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
        AdaptiveModelEndpointPool,
    )
    from noetrium_platform.foundation.kernel.concurrency.api import (
        Deadline, TaskCancelled,
    )
    from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import (
        _CancellationState,
    )
    from tests.test_model_flow_continuity_v1 import _binding

    registry = make_model_admission_registry()
    binding = _binding(latency_isolation_concurrency=1, max_admitted_concurrency=1)
    controller = registry.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=1,
        continuity_capacity=1,
    )

    class Endpoint:
        def __init__(self, selected):
            self._route = ModelEndpointRoute(
                selected.deployment_id, selected.deployment_generation, selected.base_url
            )

        @property
        def route(self):
            return self._route

    endpoints = ModelEndpointReplicaSet((binding,))
    controllers = {binding.deployment_id: controller}
    first = make_test_model_endpoint_pool(
        endpoints, Endpoint, physical_continuity_controllers=controllers,
    )
    second = make_test_model_endpoint_pool(
        endpoints, Endpoint, physical_continuity_controllers=controllers,
    )
    first.reserve_flow("holder", "flow:held", deadline=None, cancellation=None)
    try:
        with pytest.raises(TimeoutError, match="deadline"):
            second.reserve_flow(
                "waiter", "flow:timed-out",
                deadline=Deadline.after(0.05), cancellation=None,
            )
        assert second.snapshot().reserved_flow_count == 0
        assert second._waiter_count == 0
        assert not second._physical_flow_claims

        cancellation = _CancellationState()
        admitted = Event()
        with ThreadPoolExecutor(max_workers=1) as workers:
            waiting = workers.submit(
                second.reserve_flow, "waiter", "flow:cancelled",
                deadline=None, cancellation=cancellation,
            )
            # The wait remains eligible in the scheduler rather than failing.
            assert not waiting.done()
            admitted.set()
            cancellation.cancel("abandon unavailable physical claim")
            with pytest.raises(TaskCancelled, match="abandon unavailable physical claim"):
                waiting.result(timeout=2.0)
        assert second._waiter_count == 0
        assert second.snapshot().reserved_flow_count == 0
        assert not second._physical_flow_claims
        # The holder's claim was never stolen, and a later fresh waiter wins
        # once its owning flow genuinely releases physical continuity.
        first.release_flow("flow:held")
        second.reserve_flow(
            "waiter", "flow:fresh",
            deadline=Deadline.after(2.0), cancellation=None,
        )
        second.release_flow("flow:fresh")
    finally:
        first.release_flow("flow:held")
        first.close()
        second.close()
        registry.close()


def test_independent_authority_registries_wait_for_same_physical_release() -> None:
    """A second controller reads durable truth, not the first pool's Condition."""
    from concurrent.futures import ThreadPoolExecutor
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointReplicaSet, ModelEndpointRoute,
    )
    from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
        AdaptiveModelEndpointPool,
    )
    from noetrium_platform.capabilities.model.serving.runtime import (
        ModelAdmissionRegistry,
    )
    from noetrium_platform.foundation.kernel.concurrency.api import Deadline
    from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
    from noetrium_platform.infrastructure.resources.authority import (
        UniversalResourceAuthority,
    )
    from tests.test_model_flow_continuity_v1 import _binding

    primary = make_model_admission_registry()
    authority = UniversalResourceAuthority(primary._test_authority.path)
    owner = "independent-registry:" + uuid4().hex
    lease = authority.acquire_ttl_lease(
        lease_id=owner, resource_key=owner, holder_key=owner,
        owner_scope=PLATFORM_SCOPE, ttl_seconds=3600.0,
        metadata={"kind": "test-independent-registry"},
    )
    secondary = ModelAdmissionRegistry(authority, lease)
    binding = _binding(latency_isolation_concurrency=1, max_admitted_concurrency=1)
    first_controller = primary.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=1, continuity_capacity=1,
    )
    second_controller = secondary.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=1, continuity_capacity=1,
    )

    class Endpoint:
        def __init__(self, value):
            self._route = ModelEndpointRoute(
                value.deployment_id, value.deployment_generation, value.base_url,
            )

        @property
        def route(self):
            return self._route

    endpoints = ModelEndpointReplicaSet((binding,))
    first = make_test_model_endpoint_pool(
        endpoints, Endpoint,
        physical_continuity_controllers={binding.deployment_id: first_controller},
    )
    second = make_test_model_endpoint_pool(
        endpoints, Endpoint,
        physical_continuity_controllers={binding.deployment_id: second_controller},
    )
    first.reserve_flow("A", "world:A", deadline=None, cancellation=None)
    with ThreadPoolExecutor(max_workers=1) as workers:
        waiting = workers.submit(
            second.reserve_flow, "B", "world:B",
            deadline=Deadline.after(5.0), cancellation=None,
        )
        assert not waiting.done()
        assert second.snapshot().reserved_flow_count == 0
        assert len(second._physical_flow_claims) == 0
        first.release_flow("world:A")
        waiting.result(timeout=4.0)
    assert second.snapshot().reserved_flow_count == 1
    assert len(second._physical_flow_claims) == 1
    second.release_flow("world:B")
    first.close()
    second.close()
    first_controller.close()
    second_controller.close()
    primary.close()
    secondary.close()
