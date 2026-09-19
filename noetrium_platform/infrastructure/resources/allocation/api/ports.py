from __future__ import annotations

from typing import Protocol

from .contracts import (
    EndpointAllocation,
    EndpointAllocationRequest,
    EndpointBindingProof,
    EndpointProbeResult,
    EndpointReservationResult,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.lease.api import ResourceLease, ResourceOwner


class EndpointProbePort(Protocol):
    def probe(self, endpoint: NetworkEndpoint) -> EndpointProbeResult: ...


class AtomicEndpointReservationPort(Protocol):
    def reserve(
        self,
        *,
        owner: ResourceOwner,
        lease: ResourceLease,
        allocation: EndpointAllocation,
        ttl_seconds: float,
        now: float | None = None,
    ) -> EndpointReservationResult: ...
    def confirm_bound(
        self, proof: EndpointBindingProof, *, now: float | None = None
    ) -> EndpointAllocation: ...
    def replace_bound(
        self, proof: EndpointBindingProof, *, expected_previous_binding_proof_digest: str,
        now: float | None = None,
    ) -> EndpointAllocation: ...
    def renew(
        self, allocation_id: str, *, ttl_seconds: float, now: float | None = None
    ) -> EndpointAllocation: ...
    def renew_many(
        self, allocation_ids: tuple[str, ...], *, ttl_seconds: float, now: float | None = None
    ) -> tuple[EndpointAllocation, ...]: ...
    def release(self, allocation_id: str) -> EndpointAllocation: ...
    def get(self, allocation_id: str) -> EndpointAllocation | None: ...
    def active(self) -> tuple[EndpointAllocation, ...]: ...
    def reconcile_orphans(self, *, now: float | None = None) -> tuple[EndpointAllocation, ...]: ...


class EndpointLeaseGuardPort(Protocol):
    def start(self) -> None: ...
    def assert_healthy(self) -> None: ...
    def close(self) -> None: ...


class EndpointLeaseGuardFactoryPort(Protocol):
    def create(self, allocation_ids: tuple[str, ...]) -> EndpointLeaseGuardPort: ...


class EndpointAllocationPort(Protocol):
    def allocate(self, request: EndpointAllocationRequest) -> EndpointAllocation: ...
    def confirm_bound(self, proof: EndpointBindingProof) -> EndpointAllocation: ...
    def replace_bound(
        self, proof: EndpointBindingProof, *, expected_previous_binding_proof_digest: str
    ) -> EndpointAllocation: ...
    def renew(self, allocation_id: str, *, ttl_seconds: float | None = None) -> EndpointAllocation: ...
    def renew_many(self, allocation_ids: tuple[str, ...], *, ttl_seconds: float | None = None) -> tuple[EndpointAllocation, ...]: ...
    def release(self, allocation_id: str) -> EndpointAllocation: ...
    def get(self, allocation_id: str) -> EndpointAllocation: ...
    def active(self) -> tuple[EndpointAllocation, ...]: ...


__all__ = [
    "AtomicEndpointReservationPort",
    "EndpointAllocationPort",
    "EndpointLeaseGuardFactoryPort",
    "EndpointLeaseGuardPort",
    "EndpointProbePort",
]
