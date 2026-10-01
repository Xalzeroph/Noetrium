from __future__ import annotations

from dataclasses import replace
import math
from typing import Callable

from noetrium_platform.infrastructure.resources.allocation.api import (
    AtomicEndpointReservationPort,
    DEFAULT_ENDPOINT_LEASE_POLICY,
    EndpointAllocation,
    EndpointAllocationConflict,
    EndpointAllocationRequest,
    EndpointAllocationState,
    EndpointBindingProof,
    EndpointCandidatePortSourcePort,
    EndpointAllocationPort,
    EndpointProbePort,
    EndpointProtocol,
    EndpointReservationStatus,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceLease,
    ResourceOwner,
    ResourceOwnership,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity


class EndpointPhysicalConvergencePending(RuntimeError):
    """A logical endpoint owner is stale but the OS still reports a listener."""

    def __init__(self, allocation_ids: tuple[str, ...]) -> None:
        self.allocation_ids = tuple(sorted(set(allocation_ids)))
        super().__init__(
            "endpoint physical convergence is not proven: "
            + ",".join(self.allocation_ids)
        )


class EndpointAllocationUnavailable(RuntimeError):
    def __init__(self, request: EndpointAllocationRequest, attempts: tuple[str, ...]) -> None:
        self.request = request
        self.attempts = attempts
        detail = "; ".join(attempts) if attempts else "no candidates"
        super().__init__(f"no endpoint candidate is allocatable for {request.allocation_id}: {detail}")


def _same_allocation_generation(
    current: EndpointAllocation,
    expected: EndpointAllocation,
) -> bool:
    return (
        current.allocation_id == expected.allocation_id
        and current.endpoint == expected.endpoint
        and current.lease_id == expected.lease_id
        and current.holder_scope == expected.holder_scope
        and current.purpose == expected.purpose
        and current.request_digest == expected.request_digest
        and current.lease_holder_generation == expected.lease_holder_generation
        and current.lease_fencing_token == expected.lease_fencing_token
    )


def _require_allocation_generation(
    current: EndpointAllocation,
    expected: EndpointAllocation,
) -> None:
    if type(expected) is not EndpointAllocation:
        raise TypeError("endpoint lease operation requires EndpointAllocation")
    if not _same_allocation_generation(current, expected):
        raise EndpointAllocationConflict(
            f"stale endpoint allocation generation: {expected.allocation_id}"
        )


def _automatic_request(
    candidates: EndpointCandidatePortSourcePort | None,
    *,
    allocation_id: str,
    holder_scope: ScopeIdentity,
    purpose: str,
    host: str,
    candidate_count: int,
    preferred_ports: tuple[int, ...],
    protocol: EndpointProtocol,
    owner_scope: ScopeIdentity,
    ownership: ResourceOwnership,
) -> EndpointAllocationRequest:
    if candidates is None:
        raise RuntimeError(
            "automatic endpoint allocation requires a Resource candidate source"
        )
    if type(candidate_count) is not int or candidate_count <= 0:
        raise ValueError("endpoint candidate_count must be positive")
    if len(set(preferred_ports)) != len(preferred_ports):
        raise ValueError("preferred endpoint ports must be unique")
    if any(not 1 <= port <= 65535 for port in preferred_ports):
        raise ValueError("preferred endpoint ports must be between 1 and 65535")
    discovered = candidates.candidate_ports(
        host=host,
        count=candidate_count,
        protocol=protocol,
    )
    return EndpointAllocationRequest(
        allocation_id=allocation_id,
        holder_scope=holder_scope,
        purpose=purpose,
        host=host,
        candidate_ports=tuple(dict.fromkeys((*preferred_ports, *discovered))),
        protocol=protocol,
        owner_scope=owner_scope,
        ownership=ownership,
    )


def _allocate_auto_with_fresh_candidates(
    allocate: Callable[[EndpointAllocationRequest], EndpointAllocation],
    candidates: EndpointCandidatePortSourcePort | None,
    *,
    allocation_id: str,
    holder_scope: ScopeIdentity,
    purpose: str,
    host: str,
    candidate_count: int,
    preferred_ports: tuple[int, ...],
    protocol: EndpointProtocol,
    owner_scope: ScopeIdentity,
    ownership: ResourceOwnership,
    candidate_rounds: int,
) -> EndpointAllocation:
    if type(candidate_rounds) is not int or candidate_rounds <= 0:
        raise ValueError("endpoint automatic candidate rounds must be positive")
    failures: list[str] = []
    last_request: EndpointAllocationRequest | None = None
    for round_index in range(candidate_rounds):
        request = _automatic_request(
            candidates,
            allocation_id=allocation_id,
            holder_scope=holder_scope,
            purpose=purpose,
            host=host,
            candidate_count=candidate_count,
            preferred_ports=preferred_ports,
            protocol=protocol,
            owner_scope=owner_scope,
            ownership=ownership,
        )
        last_request = request
        try:
            return allocate(request)
        except EndpointAllocationUnavailable as exc:
            failures.extend(
                f"round={round_index + 1}:{attempt}"
                for attempt in exc.attempts
            )
    assert last_request is not None
    raise EndpointAllocationUnavailable(last_request, tuple(failures))


class AtomicEndpointAllocator(EndpointAllocationPort):
    """Provider-neutral endpoint allocation policy over one atomic reservation authority.

    Candidate order and OS probing are runtime policy. Ownership, lease fencing and
    allocation persistence are committed by ``AtomicEndpointReservationPort`` as one
    transaction. This keeps the allocator independent of SQLite while preventing the
    old lease-then-allocation split-transaction leak.
    """

    def __init__(
        self,
        *,
        reservations: AtomicEndpointReservationPort,
        probe: EndpointProbePort,
        candidates: EndpointCandidatePortSourcePort | None = None,
        lease_ttl_seconds: float = DEFAULT_ENDPOINT_LEASE_POLICY.ttl_seconds,
        auto_candidate_rounds: int = 4,
    ) -> None:
        if not math.isfinite(float(lease_ttl_seconds)) or lease_ttl_seconds <= 0:
            raise ValueError("endpoint lease_ttl_seconds must be finite and > 0")
        self._reservations = reservations
        self._probe = probe
        self._candidates = candidates
        if type(auto_candidate_rounds) is not int or auto_candidate_rounds <= 0:
            raise ValueError("endpoint auto_candidate_rounds must be positive")
        self._lease_ttl_seconds = float(lease_ttl_seconds)
        self._auto_candidate_rounds = auto_candidate_rounds

    def allocate_auto(
        self,
        *,
        allocation_id: str,
        holder_scope: ScopeIdentity,
        purpose: str,
        host: str = "127.0.0.1",
        candidate_count: int = 32,
        preferred_ports: tuple[int, ...] = (),
        protocol: EndpointProtocol = EndpointProtocol.TCP,
        owner_scope: ScopeIdentity = PLATFORM_SCOPE,
        ownership: ResourceOwnership = ResourceOwnership.PLATFORM_MANAGED,
    ) -> EndpointAllocation:
        return _allocate_auto_with_fresh_candidates(
            self.allocate,
            self._candidates,
            allocation_id=allocation_id,
            holder_scope=holder_scope,
            purpose=purpose,
            host=host,
            candidate_count=candidate_count,
            preferred_ports=preferred_ports,
            protocol=protocol,
            owner_scope=owner_scope,
            ownership=ownership,
            candidate_rounds=self._auto_candidate_rounds,
        )

    def _reconcile_existing_allocation(
        self,
        allocation_id: str,
    ) -> EndpointAllocation | None:
        current = self._reservations.get(allocation_id)
        if current is None or not current.state.is_live:
            return current
        orphan = next(
            (
                row
                for row in self._reservations.expire_orphans()
                if row.allocation_id == allocation_id
            ),
            None,
        )
        if orphan is None:
            return current
        if orphan.state is EndpointAllocationState.BOUND:
            physical = self._probe.probe(orphan.endpoint)
            if not physical.available:
                raise EndpointPhysicalConvergencePending((allocation_id,))
        return self._reservations.retire_orphan(orphan)

    def allocate(self, request: EndpointAllocationRequest) -> EndpointAllocation:
        request_digest = request.digest()
        existing = self._reconcile_existing_allocation(request.allocation_id)
        if existing is not None:
            return self._resolve_existing(request, request_digest, existing)

        # A quarantined generation fences only its own physical endpoint. It
        # must never stop unrelated endpoint allocations elsewhere on the host.
        quarantined_resources = {
            row.endpoint.resource
            for row in self._reservations.active()
            if row.state.is_live
        }
        attempts: list[str] = []
        for endpoint in request.candidates():
            if endpoint.resource in quarantined_resources:
                attempts.append(f"{endpoint.key}:generation-quarantined")
                continue
            probe = self._probe.probe(endpoint)
            if not probe.available:
                attempts.append(f"{endpoint.key}:probe:{probe.reason}")
                continue

            lease_id = f"endpoint:{request.allocation_id}:{endpoint.key}"
            result = self._reservations.reserve(
                owner=ResourceOwner(endpoint.resource, request.owner_scope, request.ownership),
                lease=ResourceLease(
                    lease_id=lease_id,
                    resource=endpoint.resource,
                    holder_scope=request.holder_scope,
                    purpose=request.purpose,
                ),
                allocation=EndpointAllocation(
                    allocation_id=request.allocation_id,
                    endpoint=endpoint,
                    lease_id=lease_id,
                    holder_scope=request.holder_scope,
                    purpose=request.purpose,
                    request_digest=request_digest,
                ),
                ttl_seconds=self._lease_ttl_seconds,
            )
            if result.status is EndpointReservationStatus.RESERVED:
                assert result.allocation is not None
                return result.allocation
            if result.status is EndpointReservationStatus.EXISTING:
                assert result.allocation is not None
                return self._resolve_existing(request, request_digest, result.allocation)
            if result.status is EndpointReservationStatus.RESOURCE_BUSY:
                attempts.append(f"{endpoint.key}:lease-active")
                continue
            if result.status is EndpointReservationStatus.OWNER_CONFLICT:
                attempts.append(f"{endpoint.key}:owner-conflict")
                continue
            attempts.append(f"{endpoint.key}:reservation:{result.status.value}")

        raise EndpointAllocationUnavailable(request, tuple(attempts))

    @staticmethod
    def _resolve_existing(
        request: EndpointAllocationRequest,
        request_digest: str,
        existing: EndpointAllocation,
    ) -> EndpointAllocation:
        if existing.request_digest != request_digest:
            raise EndpointAllocationConflict(request.allocation_id)
        if existing.state.is_live:
            return existing
        raise EndpointAllocationConflict(
            f"endpoint allocation was already released: {request.allocation_id}"
        )

    def confirm_bound(self, proof: EndpointBindingProof) -> EndpointAllocation:
        return self._reservations.confirm_bound(proof)

    def replace_bound(
        self, proof: EndpointBindingProof, *, expected_previous_binding_proof_digest: str
    ) -> EndpointAllocation:
        return self._reservations.replace_bound(
            proof, expected_previous_binding_proof_digest=expected_previous_binding_proof_digest
        )

    def reacquire(
        self,
        allocation: EndpointAllocation,
        *,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> EndpointAllocation:
        if type(allocation) is not EndpointAllocation:
            raise TypeError("endpoint reacquisition requires EndpointAllocation")
        ttl = self._lease_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError(
                "endpoint reacquisition ttl_seconds must be finite and > 0"
            )
        return self._reservations.reacquire(
            allocation,
            ttl_seconds=ttl,
            now=now,
        )

    def renew(
        self,
        allocation: EndpointAllocation,
        *,
        ttl_seconds: float | None = None,
    ) -> EndpointAllocation:
        if type(allocation) is not EndpointAllocation:
            raise TypeError("endpoint renewal requires EndpointAllocation")
        ttl = self._lease_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("endpoint lease ttl_seconds must be finite and > 0")
        return self._reservations.renew(allocation, ttl_seconds=ttl)

    def renew_many(
        self,
        allocations: tuple[EndpointAllocation, ...],
        *,
        ttl_seconds: float | None = None,
    ) -> tuple[EndpointAllocation, ...]:
        if not allocations:
            return ()
        if any(type(row) is not EndpointAllocation for row in allocations):
            raise TypeError("endpoint renewal requires typed allocation generations")
        allocation_ids = tuple(row.allocation_id for row in allocations)
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("endpoint allocation ids must be unique")
        ttl = self._lease_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("endpoint lease ttl_seconds must be finite and > 0")
        return self._reservations.renew_many(allocations, ttl_seconds=ttl)

    def retain_many(
        self,
        allocations: tuple[EndpointAllocation, ...],
        *,
        now: float | None = None,
    ) -> tuple[EndpointAllocation, ...]:
        if not allocations:
            return ()
        if any(type(row) is not EndpointAllocation for row in allocations):
            raise TypeError(
                "endpoint retention requires typed allocation generations"
            )
        return self._reservations.renew_many(
            allocations,
            ttl_seconds=None,
            now=now,
        )

    def release(self, allocation: EndpointAllocation) -> EndpointAllocation:
        """Release one exact live binder generation after upper teardown.

        Socket occupancy is not ownership evidence: after the exact Noetrium
        binder stops, another user may immediately bind the same address. The
        old logical lease must still retire, while orphan reconciliation remains
        conservative because it lacks that upper-generation convergence proof.
        """
        if type(allocation) is not EndpointAllocation:
            raise TypeError("endpoint release requires EndpointAllocation")
        current = self._reservations.get(allocation.allocation_id)
        if current is None:
            raise KeyError(allocation.allocation_id)
        _require_allocation_generation(current, allocation)
        if current.state is EndpointAllocationState.RELEASED:
            return current
        return self._reservations.release(allocation)

    def recover_release(
        self,
        allocation: EndpointAllocation,
        *,
        now: float | None = None,
    ) -> EndpointAllocation:
        """Retire one exact generation after upper recovery proved binder stop."""

        if type(allocation) is not EndpointAllocation:
            raise TypeError("endpoint recovery release requires EndpointAllocation")
        current = self._reservations.get(allocation.allocation_id)
        if current is None:
            raise KeyError(allocation.allocation_id)
        _require_allocation_generation(current, allocation)
        if current.state is EndpointAllocationState.RELEASED:
            return current

        orphans = {
            row.allocation_id: row
            for row in self._reservations.expire_orphans(now=now)
        }
        orphan = orphans.get(allocation.allocation_id)
        if orphan is not None:
            _require_allocation_generation(orphan, allocation)
            return self._reservations.retire_orphan(orphan, now=now)

        # The lease is still authoritative. Upper recovery has already proven
        # the exact binder generation stopped, so live-owner release is safe.
        return self._reservations.release(allocation)

    def get(self, allocation_id: str) -> EndpointAllocation:
        current = self._reservations.get(allocation_id)
        if current is None:
            raise KeyError(allocation_id)
        return current

    def active(self) -> tuple[EndpointAllocation, ...]:
        return self._reservations.active()

    def reconcile(
        self,
        *,
        now: float | None = None,
    ) -> tuple[EndpointAllocation, ...]:
        orphans = self._reservations.expire_orphans(now=now)
        released: list[EndpointAllocation] = []
        pending: list[str] = []
        for allocation in orphans:
            if allocation.state is EndpointAllocationState.BOUND:
                physical = self._probe.probe(allocation.endpoint)
                if not physical.available:
                    pending.append(allocation.allocation_id)
                    continue
            released.append(
                self._reservations.retire_orphan(allocation, now=now)
            )
        if pending:
            raise EndpointPhysicalConvergencePending(tuple(pending))
        return tuple(sorted(released, key=lambda row: row.allocation_id))



__all__ = [
    "AtomicEndpointAllocator",
    "EndpointAllocationConflict",
    "EndpointAllocationUnavailable",
    "EndpointPhysicalConvergencePending",
]
