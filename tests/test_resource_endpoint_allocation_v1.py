from __future__ import annotations

from dataclasses import replace
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocationRequest,
    EndpointAllocationState,
    EndpointBindingProof,
    EndpointProbeResult,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import (
    EndpointAllocationUnavailable,
    InMemoryEndpointAllocator,
)
from noetrium_platform.infrastructure.resources.lease.api import ResourceIdentity, ResourceKind
from noetrium_platform.infrastructure.resources.lease.runtime import InMemoryResourceLeaseRegistry
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind


class ScriptedProbe:
    def __init__(self, unavailable: set[int] = set()) -> None:
        self.unavailable = unavailable
        self.seen: list[int] = []

    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        self.seen.append(endpoint.port)
        return EndpointProbeResult(
            endpoint,
            endpoint.port not in self.unavailable,
            "scripted-unavailable" if endpoint.port in self.unavailable else "scripted-available",
        )


def _request(allocation_id: str, ports: tuple[int, ...]) -> EndpointAllocationRequest:
    return EndpointAllocationRequest(
        allocation_id=allocation_id,
        holder_scope=ScopeIdentity(ScopeKind.BRANCH, allocation_id),
        purpose="minecraft branch server",
        host="127.0.0.1",
        candidate_ports=ports,
        owner_scope=PLATFORM_SCOPE,
    )


def test_endpoint_allocator_uses_explicit_order_and_lease_exclusivity() -> None:
    leases = InMemoryResourceLeaseRegistry()
    probe = ScriptedProbe()
    allocator = InMemoryEndpointAllocator(ownership=leases, leases=leases, probe=probe)

    first = allocator.allocate(_request("branch-a", (25565, 25566)))
    second = allocator.allocate(_request("branch-b", (25565, 25566)))

    assert first.endpoint.port == 25565
    assert second.endpoint.port == 25566
    assert probe.seen == [25565, 25566]
    assert len(leases.active_for(first.endpoint.resource)) == 1


def test_endpoint_allocator_releases_logical_lease_and_allows_reallocation() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocator = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ScriptedProbe(),
    )

    first = allocator.allocate(_request("branch-a", (25565,)))
    released = allocator.release(first.allocation_id)
    assert released.state.value == "released"
    assert not leases.active_for(first.endpoint.resource)

    second = allocator.allocate(_request("branch-b", (25565,)))
    assert second.endpoint == first.endpoint


def test_in_memory_endpoint_binding_is_fencing_bound_and_preserves_history() -> None:
    leases = InMemoryResourceLeaseRegistry()
    allocator = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ScriptedProbe(),
    )
    reserved = allocator.allocate(_request("branch-bound", (25565,)))
    assert reserved.state is EndpointAllocationState.RESERVED
    proof = EndpointBindingProof(
        allocation_id=reserved.allocation_id,
        endpoint=reserved.endpoint,
        lease_fencing_token=reserved.lease_fencing_token,
        binder_identity_digest="c" * 64,
        observed_at_epoch_s=1000.0,
        evidence_ref="in-memory-listener-evidence",
    )
    bound = allocator.confirm_bound(proof)
    assert bound.state is EndpointAllocationState.BOUND
    assert allocator.confirm_bound(proof) == bound
    released = allocator.release(bound.allocation_id)
    assert released.state is EndpointAllocationState.RELEASED
    assert released.binding_proof_digest == proof.digest()


def test_endpoint_allocator_reports_probe_rejection_without_fallback() -> None:
    leases = InMemoryResourceLeaseRegistry()
    probe = ScriptedProbe({25565, 25566})
    allocator = InMemoryEndpointAllocator(ownership=leases, leases=leases, probe=probe)

    with pytest.raises(EndpointAllocationUnavailable) as raised:
        allocator.allocate(_request("branch-a", (25565, 25566)))

    assert raised.value.attempts == (
        "tcp://127.0.0.1:25565:probe:scripted-unavailable",
        "tcp://127.0.0.1:25566:probe:scripted-unavailable",
    )


def test_resource_lease_registry_rejects_two_active_leases_for_one_resource() -> None:
    registry = InMemoryResourceLeaseRegistry()
    resource = ResourceIdentity(ResourceKind.STORAGE, "artifact-pool")
    from noetrium_platform.infrastructure.resources.lease.api import ResourceLease, ResourceOwner

    registry.register_owner(ResourceOwner(resource, PLATFORM_SCOPE))
    registry.acquire(ResourceLease("lease-a", resource, PLATFORM_SCOPE, "first"))
    with pytest.raises(RuntimeError):
        registry.acquire(ResourceLease("lease-b", resource, PLATFORM_SCOPE, "second"))


def test_endpoint_allocator_does_not_hold_state_lock_during_probe() -> None:
    barrier = Barrier(2)

    class ConcurrentProbe:
        def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
            barrier.wait(timeout=2.0)
            return EndpointProbeResult(endpoint, True, "concurrent-probe")

    leases = InMemoryResourceLeaseRegistry()
    allocator = InMemoryEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ConcurrentProbe(),
    )
    requests = (
        _request("branch-left", (25565,)),
        _request("branch-right", (25566,)),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(allocator.allocate, requests))

    assert {row.endpoint.port for row in results} == {25565, 25566}

def test_expired_in_memory_endpoint_lease_cannot_be_confirmed_bound() -> None:
    class StaleLeaseRegistry(InMemoryResourceLeaseRegistry):
        stale = False

        def get(self, lease_id: str):
            lease = super().get(lease_id)
            if self.stale:
                return replace(lease, expires_at_epoch_s=1.0, acquired_at_epoch_s=0.5)
            return lease

    leases = StaleLeaseRegistry()
    allocator = InMemoryEndpointAllocator(
        ownership=leases, leases=leases, probe=ScriptedProbe()
    )
    reserved = allocator.allocate(_request("branch-expired", (25567,)))
    leases.stale = True
    proof = EndpointBindingProof(
        reserved.allocation_id, reserved.endpoint, reserved.lease_fencing_token,
        "d" * 64, 1234.0, "expired-listener-evidence",
    )
    with pytest.raises(RuntimeError, match="released"):
        allocator.confirm_bound(proof)
    assert allocator.get(reserved.allocation_id).state is EndpointAllocationState.RELEASED
    assert allocator.active() == ()


def test_in_memory_endpoint_reconciles_underlying_fencing_drift() -> None:
    class DriftedLeaseRegistry(InMemoryResourceLeaseRegistry):
        drifted = False

        def get(self, lease_id: str):
            lease = super().get(lease_id)
            if self.drifted:
                return replace(lease, fencing_token=lease.fencing_token + 1)
            return lease

    leases = DriftedLeaseRegistry()
    allocator = InMemoryEndpointAllocator(
        ownership=leases, leases=leases, probe=ScriptedProbe()
    )
    reserved = allocator.allocate(_request("branch-fencing-drift", (25568,)))
    leases.drifted = True
    assert allocator.get(reserved.allocation_id).state is EndpointAllocationState.RELEASED
    assert allocator.active() == ()
