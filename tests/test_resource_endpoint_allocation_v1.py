from __future__ import annotations

from tests.resource_endpoint_support import TestEndpointAllocator

from tests.resource_lease_support import TestResourceLeaseRegistry

import socket
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
)
from noetrium_platform.infrastructure.resources.allocation.providers import (
    LocalEndpointCandidateSource,
    SocketEndpointProbe,
)
from noetrium_platform.infrastructure.resources.allocation.providers import (
    LocalEndpointCandidateSource,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseConflict,
)
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock
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
    leases = TestResourceLeaseRegistry()
    probe = ScriptedProbe()
    allocator = TestEndpointAllocator(ownership=leases, leases=leases, probe=probe)

    first = allocator.allocate(_request("branch-a", (25565, 25566)))
    second = allocator.allocate(_request("branch-b", (25565, 25566)))

    assert first.endpoint.port == 25565
    assert second.endpoint.port == 25566
    assert probe.seen == [25565, 25566]
    assert len(leases.active_for(first.endpoint.resource)) == 1


def test_endpoint_allocator_releases_logical_lease_and_allows_reallocation() -> None:
    leases = TestResourceLeaseRegistry()
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ScriptedProbe(),
    )

    first = allocator.allocate(_request("branch-a", (25565,)))
    released = allocator.release(first)
    assert released.state.value == "released"
    assert not leases.active_for(first.endpoint.resource)

    second = allocator.allocate(_request("branch-b", (25565,)))
    assert second.endpoint == first.endpoint


def test_existing_endpoint_system_skips_real_os_bound_port_and_uses_kernel_candidate() -> None:
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    blocker.bind(("127.0.0.1", 0))
    occupied = int(blocker.getsockname()[1])
    leases = TestResourceLeaseRegistry()
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=SocketEndpointProbe(),
        candidates=LocalEndpointCandidateSource(),
    )
    try:
        allocation = allocator.allocate_auto(
            allocation_id="branch-os-busy",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "branch-os-busy"),
            owner_scope=PLATFORM_SCOPE,
            purpose="automatic endpoint conflict avoidance",
            host="127.0.0.1",
            preferred_ports=(occupied,),
            candidate_count=8,
        )
    finally:
        blocker.close()

    assert allocation.endpoint.port != occupied
    assert len(leases.active_for(allocation.endpoint.resource)) == 1


def test_automatic_endpoint_allocation_retries_fresh_candidates_after_contention() -> None:
    class RoundCandidates:
        def __init__(self) -> None:
            self.calls = 0

        def candidate_ports(self, *, host, count, protocol=None):
            del host, count, protocol
            self.calls += 1
            return (25565,) if self.calls == 1 else (25566,)

    candidates = RoundCandidates()
    leases = TestResourceLeaseRegistry()
    probe = ScriptedProbe({25565})
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=probe,
        candidates=candidates,
        auto_candidate_rounds=2,
    )

    allocation = allocator.allocate_auto(
        allocation_id="fresh-round",
        holder_scope=ScopeIdentity(ScopeKind.BRANCH, "fresh-round"),
        owner_scope=PLATFORM_SCOPE,
        purpose="retry transient endpoint collision",
        candidate_count=1,
    )

    assert allocation.endpoint.port == 25566
    assert candidates.calls == 2
    assert probe.seen == [25565, 25566]


def test_automatic_endpoint_retry_exhaustion_preserves_round_evidence() -> None:
    class RoundCandidates:
        def __init__(self) -> None:
            self.calls = 0

        def candidate_ports(self, *, host, count, protocol=None):
            del host, count, protocol
            self.calls += 1
            return (25564 + self.calls,)

    candidates = RoundCandidates()
    leases = TestResourceLeaseRegistry()
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ScriptedProbe({25565, 25566}),
        candidates=candidates,
        auto_candidate_rounds=2,
    )

    with pytest.raises(EndpointAllocationUnavailable) as raised:
        allocator.allocate_auto(
            allocation_id="retry-exhausted",
            holder_scope=ScopeIdentity(ScopeKind.BRANCH, "retry-exhausted"),
            owner_scope=PLATFORM_SCOPE,
            purpose="prove retry evidence",
            candidate_count=1,
        )

    assert candidates.calls == 2
    assert raised.value.attempts == (
        "round=1:tcp://127.0.0.1:25565:probe:scripted-unavailable",
        "round=2:tcp://127.0.0.1:25566:probe:scripted-unavailable",
    )


def test_in_memory_endpoint_binding_is_fencing_bound_and_preserves_history() -> None:
    leases = TestResourceLeaseRegistry()
    allocator = TestEndpointAllocator(
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
    released = allocator.release(bound)
    assert released.state is EndpointAllocationState.RELEASED
    assert released.binding_proof_digest == proof.digest()


def test_endpoint_allocator_reports_probe_rejection_without_fallback() -> None:
    leases = TestResourceLeaseRegistry()
    probe = ScriptedProbe({25565, 25566})
    allocator = TestEndpointAllocator(ownership=leases, leases=leases, probe=probe)

    with pytest.raises(EndpointAllocationUnavailable) as raised:
        allocator.allocate(_request("branch-a", (25565, 25566)))

    assert raised.value.attempts == (
        "tcp://127.0.0.1:25565:probe:scripted-unavailable",
        "tcp://127.0.0.1:25566:probe:scripted-unavailable",
    )


def test_resource_lease_registry_rejects_two_active_leases_for_one_resource() -> None:
    registry = TestResourceLeaseRegistry()
    resource = ResourceIdentity(ResourceKind.STORAGE, "artifact-pool")
    from noetrium_platform.infrastructure.resources.lease.api import ResourceOwner

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

    leases = TestResourceLeaseRegistry()
    allocator = TestEndpointAllocator(
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

def test_expired_endpoint_lease_cannot_be_confirmed_bound() -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=1_000.0,
    )
    leases = TestResourceLeaseRegistry(clock=clock)
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ScriptedProbe(),
        lease_ttl_seconds=5.0,
    )
    reserved = allocator.allocate(_request("branch-expired", (25567,)))
    clock.advance(6.0, wall_seconds=0.0)
    proof = EndpointBindingProof(
        reserved.allocation_id,
        reserved.endpoint,
        reserved.lease_fencing_token,
        "d" * 64,
        1234.0,
        "expired-listener-evidence",
    )

    with pytest.raises(ResourceLeaseConflict, match="no longer authoritative"):
        allocator.confirm_bound(proof)

    # Lease loss alone does not silently erase endpoint state. The still-live
    # row remains quarantined until the endpoint reconciliation authority
    # retires the unbound reservation.
    assert allocator.get(reserved.allocation_id).state is EndpointAllocationState.RESERVED
    released = allocator.reconcile()
    assert tuple(row.allocation_id for row in released) == ("branch-expired",)
    assert allocator.get(reserved.allocation_id).state is EndpointAllocationState.RELEASED
    assert allocator.active() == ()


def test_endpoint_reconciles_underlying_fencing_drift() -> None:
    leases = TestResourceLeaseRegistry()
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ScriptedProbe(),
    )
    reserved = allocator.allocate(_request("branch-fencing-drift", (25568,)))

    leases.release(
        reserved.lease_id,
        fencing_token=reserved.lease_fencing_token,
    )
    replacement_lease = leases.acquire(
        ResourceLease(
            reserved.lease_id,
            reserved.endpoint.resource,
            reserved.holder_scope,
            reserved.purpose,
        ),
        ttl_seconds=30.0,
    )
    assert replacement_lease.fencing_token > reserved.lease_fencing_token

    # The endpoint row is quarantined until reconciliation proves this old
    # allocation generation no longer owns the Resource lease generation.
    assert allocator.get(reserved.allocation_id).state is EndpointAllocationState.RESERVED
    released = allocator.reconcile()
    assert tuple(row.allocation_id for row in released) == ("branch-fencing-drift",)
    assert allocator.get(reserved.allocation_id).state is EndpointAllocationState.RELEASED
    assert allocator.active() == ()

def test_automatic_endpoint_request_identity_ignores_transient_candidate_set() -> None:
    left = _request("stable-request", (25001, 25002))
    right = _request("stable-request", (26001, 26002, 26003))
    assert left.digest() == right.digest()


def test_automatic_endpoint_allocation_is_resource_owned() -> None:
    leases = TestResourceLeaseRegistry()
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=SocketEndpointProbe(),
        candidates=LocalEndpointCandidateSource(),
    )
    allocation = allocator.allocate_auto(
        allocation_id="auto-resource-endpoint",
        holder_scope=ScopeIdentity(ScopeKind.BRANCH, "auto-resource-endpoint"),
        purpose="automatic endpoint authority test",
        candidate_count=8,
    )
    assert allocation.endpoint.host == "127.0.0.1"
    assert 1 <= allocation.endpoint.port <= 65535
    assert len(leases.active_for(allocation.endpoint.resource)) == 1


def test_endpoint_reconcile_releases_expired_allocation() -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=2_000.0,
    )
    leases = TestResourceLeaseRegistry(clock=clock)
    allocator = TestEndpointAllocator(
        ownership=leases,
        leases=leases,
        probe=ScriptedProbe(),
        lease_ttl_seconds=5.0,
    )
    allocation = allocator.allocate(_request("branch-expiring-reconcile", (25579,)))
    lease = leases.get(allocation.lease_id)
    assert lease.expires_at_epoch_s is not None

    clock.advance(6.0, wall_seconds=0.0)
    released = allocator.reconcile()

    assert tuple(row.allocation_id for row in released) == (
        "branch-expiring-reconcile",
    )
    assert allocator.get(allocation.allocation_id).state is EndpointAllocationState.RELEASED
    assert allocator.active() == ()
