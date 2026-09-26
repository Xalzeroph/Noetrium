from __future__ import annotations

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointCandidatePortSourcePort,
    EndpointProbePort,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import (
    AtomicEndpointAllocator,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceLeasePort,
    ResourceOwnershipPort,
)
from noetrium_platform.infrastructure.resources.providers import (
    SQLiteEndpointAllocationStore,
)

from tests.resource_lease_support import TestResourceLeaseRegistry


class TestEndpointAllocator:
    """Test composition of the sole production endpoint allocator/authority path."""

    __test__ = False

    def __init__(
        self,
        *,
        ownership: ResourceOwnershipPort,
        leases: ResourceLeasePort,
        probe: EndpointProbePort,
        candidates: EndpointCandidatePortSourcePort | None = None,
        lease_ttl_seconds: float = 30.0,
        auto_candidate_rounds: int = 4,
    ) -> None:
        if ownership is not leases:
            raise ValueError(
                "test endpoint composition requires one resource ownership/lease authority"
            )
        if not isinstance(leases, TestResourceLeaseRegistry):
            raise TypeError(
                "test endpoint composition requires TestResourceLeaseRegistry"
            )
        self.resources = leases
        self.reservations = SQLiteEndpointAllocationStore(
            leases.path,
            clock=leases.clock,
        )
        self.delegate = AtomicEndpointAllocator(
            reservations=self.reservations,
            probe=probe,
            candidates=candidates,
            lease_ttl_seconds=lease_ttl_seconds,
            auto_candidate_rounds=auto_candidate_rounds,
        )

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)


__all__ = ["TestEndpointAllocator"]
