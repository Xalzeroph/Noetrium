"""Atomic physical Method model bundle: no partial claims or cyclic wait."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from itertools import product
from types import SimpleNamespace
from threading import Event, Lock
from uuid import uuid4

import pytest
from noetrium_platform.foundation.kernel.concurrency.api import Deadline
import time

from model_admission_test_support import make_model_admission_registry
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet, ModelEndpointRoute,
)
from tests.model_endpoint_test_support import make_test_model_endpoint_pool
from tests.test_model_endpoint_replica_pool_v1 import _binding
from noetrium_platform.substrate.api import claim_field, lease_field
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority


class _Endpoint:
    def __init__(self, binding):
        self._route = ModelEndpointRoute(
            binding.deployment_id,
            binding.deployment_generation,
            binding.base_url,
        )

    @property
    def route(self):
        return self._route


def _setup(*, replicas, per_replica, pool_count=None):
    registry = make_model_admission_registry()
    bindings = tuple(_binding(i, capacity=per_replica) for i in range(replicas))
    controllers = {
        binding.deployment_id: registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=per_replica,
            continuity_capacity=per_replica,
        )
        for binding in bindings
    }
    pools = tuple(
        make_test_model_endpoint_pool(
            ModelEndpointReplicaSet(bindings),
            _Endpoint,
            physical_continuity_controllers=controllers,
        )
        for _ in range(replicas if pool_count is None else pool_count)
    )
    return registry, pools, controllers


def _live_flows(controllers):
    c = next(iter(controllers.values()))
    keys = frozenset(
        controller.physical_continuity_resource_key
        for controller in controllers.values()
    )
    return tuple(
        str(dict(claim_field(claim, "attributes") or {}).get("flow_id"))
        for claim in c.physical_bundle_snapshot(keys).claims
        if dict(claim_field(claim, "attributes") or {}).get("kind")
        == "model-continuity-slot"
    )


def test_matching_feasibility_agrees_with_exhaustive_oracle():
    # Exhaust every nonempty eligibility subset of three physical replicas,
    # with 1-2 certified slots and 1-4 independently demanded roles.
    from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import (
        AdaptiveModelEndpointPool,
    )

    class Controller:
        def __init__(self, dep, capacity):
            self.capacity = capacity
            self.physical_continuity_capacity = capacity
            self.physical_continuity_resource_key = "continuity:" + dep
            self.physical_admission_resource_key = "admission:" + dep

        def physical_bundle_snapshot(self, keys):
            return SimpleNamespace(claims=())

    deps = ("gpu-0", "gpu-1", "gpu-2")
    candidates = tuple(
        tuple(dep for index, dep in enumerate(deps) if mask & (1 << index))
        for mask in range(1, 1 << len(deps))
    )
    examined = 0
    for capacities in product((1, 2), repeat=len(deps)):
        controllers = {
            dep: Controller(dep, cap)
            for dep, cap in zip(deps, capacities, strict=True)
        }
        for roles in range(1, 5):
            for choices in product(candidates, repeat=roles):
                pools = tuple(SimpleNamespace(
                    _physical_continuity_controllers={
                        dep: controllers[dep] for dep in eligible
                    }
                ) for eligible in choices)
                actual = AdaptiveModelEndpointPool._atomic_flow_bundle_placement(
                    pools, flow_id="oracle",
                )
                possible = any(
                    all(
                        placement.count(dep) <= controllers[dep].capacity
                        for dep in deps
                    )
                    for placement in product(*choices)
                )
                assert (actual is not None) == possible, (
                    capacities, choices, actual, possible
                )
                if actual is not None:
                    placement = tuple(dep for dep, _ in actual)
                    assert all(
                        placement[index] in choices[index]
                        for index in range(roles)
                    )
                    assert all(
                        placement.count(dep) <= controllers[dep].capacity
                        for dep in deps
                    )
                examined += 1
    assert examined == 8 * (7 + 49 + 343 + 2401)


def test_flow_and_bundle_recover_expired_continuity_before_waiting(tmp_path):
    """Dead owners cannot make single or bundle advisory cuts permanently full."""
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")

    def owner_lease(label: str, ttl: float):
        identity = label + ":" + uuid4().hex
        return authority.acquire_ttl_lease(
            lease_id=identity, resource_key=identity, holder_key=identity,
            owner_scope=PLATFORM_SCOPE, ttl_seconds=ttl,
            metadata={"kind": "model-bundle-orphan-test-owner"},
        )

    stale_owner = owner_lease("stale", 1.0)
    stale_registry = ModelAdmissionRegistry(authority, stale_owner)
    bindings = tuple(_binding(i, capacity=1) for i in range(3))
    stale_controllers = {
        binding.deployment_id: stale_registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=1, continuity_capacity=1,
        )
        for binding in bindings
    }
    stale_leases = tuple(
        controller.try_reserve_continuity(
            owner_id="expired-owner", flow_id="expired:" + deployment_id,
        )
        for deployment_id, controller in stale_controllers.items()
    )
    assert all(lease is not None for lease in stale_leases)
    time.sleep(1.05)

    live_owner = owner_lease("live", 30.0)
    live_registry = ModelAdmissionRegistry(authority, live_owner)
    controllers = {
        binding.deployment_id: live_registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=1, continuity_capacity=1,
        )
        for binding in bindings
    }
    single_binding = bindings[0]
    single = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((single_binding,)), _Endpoint,
        physical_continuity_controllers={
            single_binding.deployment_id: controllers[single_binding.deployment_id]
        },
    )
    bundle_bindings = bindings[1:]
    bundle_controllers = {
        binding.deployment_id: controllers[binding.deployment_id]
        for binding in bundle_bindings
    }
    pools = tuple(
        make_test_model_endpoint_pool(
            ModelEndpointReplicaSet(bundle_bindings), _Endpoint,
            physical_continuity_controllers=bundle_controllers,
        )
        for _ in range(2)
    )
    single_flow = "recovered-expired-single"
    flow = "recovered-expired-bundle"
    try:
        single.reserve_flow(
            "tenant", single_flow, deadline=Deadline.after(0.5),
            cancellation=None,
        )
        assert single_flow in single._physical_flow_claims
        single.release_flow(single_flow)

        pools[0].reserve_flow_bundle(
            pools, "tenant", flow, deadline=Deadline.after(0.5),
            cancellation=None,
        )
        assert len(set(pool._physical_flow_claims[flow][0] for pool in pools)) == 2
        assert all(
            not row.startswith("expired:")
            for row in _live_flows(controllers)
        )
    finally:
        if single_flow in single._physical_flow_claims:
            single.release_flow(single_flow)
        single.close()
        for pool in reversed(pools):
            if flow in pool._physical_flow_claims:
                pool.release_flow(flow)
            pool.close()
        for lease in stale_leases:
            if lease is not None:
                lease.release()
        stale_registry.close()
        live_registry.close()
        authority.release_lease(stale_owner)
        authority.release_lease(live_owner)
        authority.close()



class _SilentCommitFeed:
    """Commit-backed waiter surface with no synthetic wall-clock expiry event."""

    def __init__(self):
        self._lock = Lock()
        self._callbacks = {}
        self._next = 0

    def subscribe(self, resource_keys, callback):
        assert resource_keys
        with self._lock:
            self._next += 1
            token = self._next
            self._callbacks[token] = callback

        def unsubscribe():
            with self._lock:
                self._callbacks.pop(token, None)
        return unsubscribe

    def close(self):
        with self._lock:
            self._callbacks.clear()


def test_event_backed_flow_and_bundle_wake_at_blocking_owner_expiry(tmp_path):
    """Lease expiry itself has no commit, but must still end physical denial."""
    authority = UniversalResourceAuthority(tmp_path / "authority-expiry-wake.sqlite")

    def owner_lease(label: str, ttl: float):
        identity = label + ":" + uuid4().hex
        return authority.acquire_ttl_lease(
            lease_id=identity, resource_key=identity, holder_key=identity,
            owner_scope=PLATFORM_SCOPE, ttl_seconds=ttl,
            metadata={"kind":"model-expiry-wake-test-owner"},
        )

    stale_owner = owner_lease("stale", 0.55)
    stale_registry = ModelAdmissionRegistry(authority, stale_owner)
    bindings = tuple(_binding(i + 10, capacity=1) for i in range(3))
    stale_controllers = {
        binding.deployment_id: stale_registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=1, continuity_capacity=1,
        )
        for binding in bindings
    }
    stale_leases = tuple(
        controller.try_reserve_continuity(
            owner_id="stale-owner", flow_id="stale:" + deployment_id,
        )
        for deployment_id, controller in stale_controllers.items()
    )
    assert all(lease is not None for lease in stale_leases)
    expiry = float(lease_field(stale_owner, "expires_at_epoch_s"))
    assert expiry - time.time() > 0.15, "test setup consumed stale owner TTL"

    feed = _SilentCommitFeed()
    live_owner = owner_lease("live", 10.0)
    live_registry = ModelAdmissionRegistry(
        authority, live_owner, change_feed=feed,
    )
    controllers = {
        binding.deployment_id: live_registry.controller_for(
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            qualified_capacity=1, continuity_capacity=1,
        )
        for binding in bindings
    }
    single_binding = bindings[0]
    single = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((single_binding,)), _Endpoint,
        physical_continuity_controllers={
            single_binding.deployment_id: controllers[single_binding.deployment_id]
        },
    )
    bundle_bindings = bindings[1:]
    bundle_controllers = {
        binding.deployment_id: controllers[binding.deployment_id]
        for binding in bundle_bindings
    }
    pools = tuple(
        make_test_model_endpoint_pool(
            ModelEndpointReplicaSet(bundle_bindings), _Endpoint,
            physical_continuity_controllers=bundle_controllers,
        )
        for _ in range(2)
    )
    single_flow = "expiry-wake-single"
    bundle_flow = "expiry-wake-bundle"

    def reserve_single():
        single.reserve_flow(
            "live-owner", single_flow,
            deadline=Deadline.after(1.5), cancellation=None,
        )
        return time.monotonic()

    def reserve_bundle():
        pools[0].reserve_flow_bundle(
            pools, "live-owner", bundle_flow,
            deadline=Deadline.after(1.5), cancellation=None,
        )
        return time.monotonic()

    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            one = executor.submit(reserve_single)
            two = executor.submit(reserve_bundle)
            one_done = one.result(timeout=2.0)
            two_done = two.result(timeout=2.0)
        assert one_done - started < 1.2
        assert two_done - started < 1.2
        assert single_flow in single._physical_flow_claims
        assert all(bundle_flow in pool._physical_flow_claims for pool in pools)
        assert all(
            not row.startswith("stale:")
            for row in _live_flows(controllers)
        )
    finally:
        if single_flow in single._physical_flow_claims:
            single.release_flow(single_flow)
        single.close()
        for pool in reversed(pools):
            if bundle_flow in pool._physical_flow_claims:
                pool.release_flow(bundle_flow)
            pool.close()
        for lease in stale_leases:
            if lease is not None:
                try:
                    lease.release()
                except Exception:
                    pass
        stale_registry.close()
        live_registry.close()
        feed.close()
        try:
            authority.release_lease(stale_owner)
        except Exception:
            pass
        authority.release_lease(live_owner)
        authority.close()

def test_bundle_physical_placement_spreads_roles_across_idle_replicas():
    registry, pools, controllers = _setup(
        replicas=3, per_replica=3, pool_count=2,
    )
    flow = "spread-two-model-roles"
    try:
        pools[0].reserve_flow_bundle(
            pools, "tenant", flow, deadline=None, cancellation=None,
        )
        selected = tuple(pool._physical_flow_claims[flow][0] for pool in pools)
        # Multiple roles may share a GPU when no alternative exists, but must
        # not pile onto the same replica when equal-capacity peers are idle.
        assert len(set(selected)) == 2
    finally:
        for pool in reversed(pools):
            if flow in pool._physical_flow_claims:
                pool.release_flow(flow)
            pool.close()
        registry.close()


def test_bundle_uses_all_certified_slots_of_one_replica():
    registry, pools, controllers = _setup(
        replicas=1, per_replica=2, pool_count=2,
    )
    flow = "single-gpu-multi-role"
    pools[0].reserve_flow_bundle(
        pools, "tenant", flow, deadline=None, cancellation=None,
    )
    assert len(set(
        pool._physical_flow_claims[flow][0] for pool in pools
    )) == 1
    assert len(set(
        pool._physical_flow_claims[flow][1].claim_id for pool in pools
    )) == 2
    assert sum(
        row.startswith(flow + ":role:")
        for row in _live_flows(controllers)
    ) == 2
    for pool in reversed(pools):
        pool.release_flow(flow)
        pool.close()
    assert not _live_flows(controllers)
    registry.close()


def test_blocked_bundle_deadline_leaves_no_partial_claims():
    registry, pools, controllers = _setup(
        replicas=1, per_replica=2, pool_count=2,
    )
    first, second = "occupying-two-slots", "deadline-no-claims"
    pools[0].reserve_flow_bundle(
        pools, "tenant-1", first, deadline=None, cancellation=None,
    )
    with pytest.raises(TimeoutError, match="deadline expired"):
        pools[0].reserve_flow_bundle(
            pools, "tenant-2", second,
            deadline=Deadline.after(0.15), cancellation=None,
        )
    assert not any(
        row.startswith(second + ":role:") for row in _live_flows(controllers)
    )
    assert sum(
        row.startswith(first + ":role:") for row in _live_flows(controllers)
    ) == 2
    for pool in reversed(pools):
        pool.release_flow(first)
        pool.close()
    assert not _live_flows(controllers)
    registry.close()


def test_atomic_bundle_waits_without_partial_physical_claims():
    registry, pools, controllers = _setup(replicas=3, per_replica=1)
    first, second = "model-bundle-first", "model-bundle-second"
    pools[0].reserve_flow_bundle(
        pools, "tenant-a", first, deadline=None, cancellation=None,
    )
    assert sum(row.startswith(first + ":role:") for row in _live_flows(controllers)) == 3

    entered = Event()

    def reserve_second():
        entered.set()
        pools[0].reserve_flow_bundle(
            pools, "tenant-b", second, deadline=None, cancellation=None,
        )

    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(reserve_second)
        assert entered.wait(2)
        time.sleep(0.12)
        assert not pending.done()
        assert not any(row.startswith(second + ":role:") for row in _live_flows(controllers))
        for pool in pools:
            pool.release_flow(first)
        pending.result(timeout=5)

    assert sum(row.startswith(second + ":role:") for row in _live_flows(controllers)) == 3
    for pool in pools:
        pool.release_flow(second)
        pool.close()
    assert not _live_flows(controllers)
    registry.close()


def test_many_concurrent_bundles_keep_all_or_none_and_converge():
    registry, all_pools, controllers = _setup(replicas=4, per_replica=2)
    pools = all_pools[:3]

    def run(index):
        flow = f"bundle-{index}"
        pools[0].reserve_flow_bundle(
            pools, f"tenant-{index}", flow,
            deadline=None, cancellation=None,
        )
        try:
            claims = _live_flows(controllers)
            assert sum(row.startswith(flow + ":role:") for row in claims) == len(pools)
            time.sleep(0.015)
            return flow
        finally:
            for pool in reversed(pools):
                pool.release_flow(flow)

    with ThreadPoolExecutor(max_workers=10) as workers:
        futures = tuple(workers.submit(run, i) for i in range(12))
        assert len(set(f.result(timeout=15) for f in futures)) == 12
    assert not _live_flows(controllers)
    for pool in all_pools:
        pool.close()
    registry.close()
