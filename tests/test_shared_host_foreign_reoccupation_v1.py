from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocationRequest,
    EndpointAllocationState,
    EndpointBindingProof,
    EndpointProbeResult,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import (
    AtomicEndpointAllocator,
    InMemoryEndpointAllocator,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
    ManualLeaseClock,
)
from noetrium_platform.infrastructure.resources.providers import (
    SQLiteEndpointAllocationStore,
)


class _ForeignReoccupationProbe:
    def __init__(self) -> None:
        self.available = True
        self.calls = 0

    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult:
        self.calls += 1
        return EndpointProbeResult(
            endpoint,
            self.available,
            "free" if self.available else "foreign-listener",
        )


def _clock() -> ManualLeaseClock:
    return ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )


def _request(name: str, port: int) -> EndpointAllocationRequest:
    return EndpointAllocationRequest(
        allocation_id=name,
        holder_scope=ScopeIdentity(ScopeKind.BRANCH, f"branch-{name}"),
        purpose="shared-host foreign reoccupation test",
        host="127.0.0.1",
        candidate_ports=(port,),
    )


@pytest.mark.parametrize("durable", (False, True))
def test_exact_binder_release_ignores_foreign_listener_reoccupation(
    tmp_path,
    durable: bool,
) -> None:
    probe = _ForeignReoccupationProbe()
    clock = _clock()
    if durable:
        allocator = AtomicEndpointAllocator(
            reservations=SQLiteEndpointAllocationStore(
                tmp_path / "endpoint-reoccupation.sqlite",
                clock=clock,
            ),
            probe=probe,
            lease_ttl_seconds=30.0,
        )
    else:
        resources = InMemoryResourceLeaseRegistry(clock=clock)
        allocator = InMemoryEndpointAllocator(
            ownership=resources,
            leases=resources,
            probe=probe,
            lease_ttl_seconds=30.0,
        )

    reserved = allocator.allocate(_request("service", 28111))
    bound = allocator.confirm_bound(
        EndpointBindingProof(
            allocation_id=reserved.allocation_id,
            endpoint=reserved.endpoint,
            lease_fencing_token=reserved.lease_fencing_token,
            binder_identity_digest="a" * 64,
            observed_at_epoch_s=100.0,
            evidence_ref="exact-binder-generation-stopped",
        )
    )

    # The exact binder generation is already stopped by its upper runtime.
    # Another user wins the race and binds the same socket before our logical
    # lease is retired. Release must not probe, signal, or otherwise conflate
    # that foreign listener with the old Noetrium binder.
    probe.available = False
    calls_before_release = probe.calls
    released = allocator.release(bound)

    assert released.state is EndpointAllocationState.RELEASED
    assert probe.calls == calls_before_release
    assert allocator.active() == ()
