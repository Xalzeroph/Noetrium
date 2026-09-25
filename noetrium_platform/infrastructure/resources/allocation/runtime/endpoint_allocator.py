from __future__ import annotations

from dataclasses import replace
import math
from threading import RLock
from time import time

from noetrium_platform.infrastructure.resources.allocation.api import (
    AtomicEndpointReservationPort,
    DEFAULT_ENDPOINT_LEASE_POLICY,
    EndpointAllocation,
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
    LeaseState,
    ResourceLease,
    ResourceLeasePort,
    ResourceKind,
    ResourceOwner,
    ResourceOwnership,
    ResourceOwnershipPort,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity


class EndpointAllocationConflict(RuntimeError):
    pass


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
    ) -> None:
        if not math.isfinite(float(lease_ttl_seconds)) or lease_ttl_seconds <= 0:
            raise ValueError("endpoint lease_ttl_seconds must be finite and > 0")
        self._reservations = reservations
        self._probe = probe
        self._candidates = candidates
        self._lease_ttl_seconds = float(lease_ttl_seconds)

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
        return self.allocate(
            _automatic_request(
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
            )
        )

    def allocate(self, request: EndpointAllocationRequest) -> EndpointAllocation:
        # Never admit a fresh physical endpoint while stale durable generations
        # have not yet converged against OS listener truth.
        self.reconcile()
        request_digest = request.digest()
        existing = self._reservations.get(request.allocation_id)
        if existing is not None:
            return self._resolve_existing(request, request_digest, existing)

        attempts: list[str] = []
        for endpoint in request.candidates():
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

    def release(self, allocation: EndpointAllocation) -> EndpointAllocation:
        if type(allocation) is not EndpointAllocation:
            raise TypeError("endpoint release requires EndpointAllocation")
        current = self._reservations.get(allocation.allocation_id)
        if current is None:
            raise KeyError(allocation.allocation_id)
        _require_allocation_generation(current, allocation)
        if current.state is EndpointAllocationState.RELEASED:
            return current
        if current.state is EndpointAllocationState.BOUND:
            physical = self._probe.probe(current.endpoint)
            if not physical.available:
                raise EndpointPhysicalConvergencePending((current.allocation_id,))
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


class InMemoryEndpointAllocator(EndpointAllocationPort):
    """Deterministic in-process allocator over injected lease/probe authorities.

    This implementation is intentionally independent from the durable atomic
    reservation authority. Its single process lock gives the in-memory composition
    one transaction boundary while the durable composition uses
    :class:`AtomicEndpointAllocator`.
    """

    def __init__(
        self,
        *,
        ownership: ResourceOwnershipPort,
        leases: ResourceLeasePort,
        probe: EndpointProbePort,
        candidates: EndpointCandidatePortSourcePort | None = None,
        lease_ttl_seconds: float = DEFAULT_ENDPOINT_LEASE_POLICY.ttl_seconds,
    ) -> None:
        if not math.isfinite(float(lease_ttl_seconds)) or lease_ttl_seconds <= 0:
            raise ValueError("endpoint lease_ttl_seconds must be finite and > 0")
        self._ownership = ownership
        self._leases = leases
        self._probe = probe
        self._candidates = candidates
        self._lease_ttl_seconds = float(lease_ttl_seconds)
        self._allocations: dict[str, EndpointAllocation] = {}
        self._lock = RLock()

    def _reconcile_allocation_locked(self, allocation_id: str) -> EndpointAllocation:
        try:
            return self._allocations[allocation_id]
        except KeyError as exc:
            raise KeyError(allocation_id) from exc

    def _lease_authoritative_locked(
        self,
        current: EndpointAllocation,
    ) -> bool:
        if not current.state.is_live:
            return False
        try:
            lease = self._leases.get(current.lease_id)
        except KeyError:
            return False
        return (
            lease.state is LeaseState.ACTIVE
            and lease.resource == current.endpoint.resource
            and lease.holder_scope == current.holder_scope
            and lease.purpose == current.purpose
            and lease.holder_generation == current.lease_holder_generation
            and lease.fencing_token == current.lease_fencing_token
        )

    def _require_lease_authority_locked(
        self,
        current: EndpointAllocation,
    ) -> None:
        if not self._lease_authoritative_locked(current):
            raise EndpointAllocationConflict(
                "endpoint allocation lease is no longer authoritative: "
                f"{current.allocation_id}"
            )

    def _existing_for_request_locked(
        self, request: EndpointAllocationRequest, request_digest: str
    ) -> EndpointAllocation | None:
        if request.allocation_id not in self._allocations:
            return None
        existing = self._reconcile_allocation_locked(request.allocation_id)
        if existing.request_digest != request_digest:
            raise EndpointAllocationConflict(request.allocation_id)
        if existing.state.is_live:
            return existing
        raise EndpointAllocationConflict(
            f"endpoint allocation was already released: {request.allocation_id}"
        )

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
        return self.allocate(
            _automatic_request(
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
            )
        )

    def allocate(self, request: EndpointAllocationRequest) -> EndpointAllocation:
        self.reconcile()
        request_digest = request.digest()
        with self._lock:
            existing = self._existing_for_request_locked(request, request_digest)
            if existing is not None:
                return existing

        attempts: list[str] = []
        for endpoint in request.candidates():
            resource = endpoint.resource
            try:
                self._ownership.register_owner(
                    ResourceOwner(resource, request.owner_scope, request.ownership)
                )
            except Exception as exc:
                attempts.append(f"{endpoint.key}:owner:{type(exc).__name__}")
                continue
            if self._leases.active_for(resource):
                attempts.append(f"{endpoint.key}:lease-active")
                continue

            # OS availability is an external fact and may block.  It must not
            # monopolize the allocator's in-process state lock.  The commit
            # section below rechecks both allocation identity and lease state.
            result = self._probe.probe(endpoint)
            if not result.available:
                attempts.append(f"{endpoint.key}:probe:{result.reason}")
                continue

            lease_id = f"endpoint:{request.allocation_id}:{endpoint.key}"
            with self._lock:
                existing = self._existing_for_request_locked(request, request_digest)
                if existing is not None:
                    return existing
                if self._leases.active_for(resource):
                    attempts.append(f"{endpoint.key}:lease-active")
                    continue
                try:
                    granted = self._leases.acquire(
                        ResourceLease(
                            lease_id=lease_id,
                            resource=resource,
                            holder_scope=request.holder_scope,
                            purpose=request.purpose,
                        ),
                        ttl_seconds=self._lease_ttl_seconds,
                    )
                except Exception as exc:
                    attempts.append(f"{endpoint.key}:lease:{type(exc).__name__}")
                    continue
                allocation = EndpointAllocation(
                    allocation_id=request.allocation_id,
                    endpoint=endpoint,
                    lease_id=lease_id,
                    holder_scope=request.holder_scope,
                    purpose=request.purpose,
                    request_digest=request_digest,
                    lease_holder_generation=granted.holder_generation,
                    lease_fencing_token=granted.fencing_token,
                    lease_expires_at_epoch_s=granted.expires_at_epoch_s,
                )
                self._allocations[request.allocation_id] = allocation
                return allocation
        raise EndpointAllocationUnavailable(request, tuple(attempts))

    def confirm_bound(self, proof: EndpointBindingProof) -> EndpointAllocation:
        with self._lock:
            current = self._reconcile_allocation_locked(proof.allocation_id)
            if current.state is EndpointAllocationState.RELEASED:
                raise EndpointAllocationConflict(
                    f"endpoint allocation is released: {proof.allocation_id}"
                )
            self._require_lease_authority_locked(current)
            if current.endpoint != proof.endpoint:
                raise EndpointAllocationConflict(
                    f"endpoint binding proof endpoint mismatch: {proof.allocation_id}"
                )
            if current.lease_fencing_token != proof.lease_fencing_token:
                raise EndpointAllocationConflict(
                    f"endpoint binding proof fencing lost: {proof.allocation_id}"
                )
            proof_digest = proof.digest()
            if current.state is EndpointAllocationState.BOUND:
                if (
                    current.binding_proof_digest == proof_digest
                    and current.binding_evidence_ref == proof.evidence_ref
                    and current.bound_at_epoch_s == proof.observed_at_epoch_s
                ):
                    return current
                raise EndpointAllocationConflict(
                    f"endpoint allocation already has a different binding proof: {proof.allocation_id}"
                )
            updated = replace(
                current,
                state=EndpointAllocationState.BOUND,
                binding_proof_digest=proof_digest,
                binding_binder_identity_digest=proof.binder_identity_digest,
                binding_evidence_ref=proof.evidence_ref,
                bound_at_epoch_s=proof.observed_at_epoch_s,
            )
            self._allocations[proof.allocation_id] = updated
            return updated

    def replace_bound(
        self, proof: EndpointBindingProof, *, expected_previous_binding_proof_digest: str
    ) -> EndpointAllocation:
        if len(expected_previous_binding_proof_digest) != 64 or any(
            character not in "0123456789abcdef" for character in expected_previous_binding_proof_digest
        ):
            raise ValueError("expected previous endpoint binding proof digest must be canonical SHA-256")
        with self._lock:
            current = self._reconcile_allocation_locked(proof.allocation_id)
            if current.state is not EndpointAllocationState.BOUND:
                raise EndpointAllocationConflict(f"endpoint allocation is not bound: {proof.allocation_id}")
            self._require_lease_authority_locked(current)
            if current.endpoint != proof.endpoint:
                raise EndpointAllocationConflict(f"endpoint binding proof endpoint mismatch: {proof.allocation_id}")
            if current.lease_fencing_token != proof.lease_fencing_token:
                raise EndpointAllocationConflict(f"endpoint binding proof fencing lost: {proof.allocation_id}")
            if current.binding_proof_digest != expected_previous_binding_proof_digest:
                raise EndpointAllocationConflict(f"endpoint binding replacement lost prior generation: {proof.allocation_id}")
            if current.binding_binder_identity_digest == proof.binder_identity_digest:
                raise EndpointAllocationConflict(f"endpoint binding replacement must use a new binder generation: {proof.allocation_id}")
            proof_digest = proof.digest()
            if proof_digest == current.binding_proof_digest:
                raise EndpointAllocationConflict(f"endpoint binding replacement proof is already current: {proof.allocation_id}")
            updated = replace(
                current, binding_proof_digest=proof_digest,
                binding_binder_identity_digest=proof.binder_identity_digest,
                binding_evidence_ref=proof.evidence_ref, bound_at_epoch_s=proof.observed_at_epoch_s,
            )
            self._allocations[proof.allocation_id] = updated
            return updated

    def renew(
        self,
        allocation: EndpointAllocation,
        *,
        ttl_seconds: float | None = None,
    ) -> EndpointAllocation:
        if type(allocation) is not EndpointAllocation:
            raise TypeError("endpoint renewal requires EndpointAllocation")
        with self._lock:
            current = self._reconcile_allocation_locked(allocation.allocation_id)
            _require_allocation_generation(current, allocation)
            if not current.state.is_live:
                raise EndpointAllocationConflict(
                    f"endpoint allocation is not active: {allocation.allocation_id}"
                )
            ttl = self._lease_ttl_seconds if ttl_seconds is None else float(ttl_seconds)
            if not math.isfinite(ttl) or ttl <= 0:
                raise ValueError("endpoint lease ttl_seconds must be finite and > 0")
            granted = self._leases.renew(
                current.lease_id,
                fencing_token=allocation.lease_fencing_token,
                ttl_seconds=ttl,
            )
            updated = replace(
                current,
                lease_holder_generation=granted.holder_generation,
                lease_fencing_token=granted.fencing_token,
                lease_expires_at_epoch_s=granted.expires_at_epoch_s,
            )
            self._allocations[allocation.allocation_id] = updated
            return updated

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
        with self._lock:
            return tuple(
                self.renew(allocation, ttl_seconds=ttl_seconds)
                for allocation in allocations
            )

    def release(self, allocation: EndpointAllocation) -> EndpointAllocation:
        if type(allocation) is not EndpointAllocation:
            raise TypeError("endpoint release requires EndpointAllocation")
        with self._lock:
            current = self._reconcile_allocation_locked(allocation.allocation_id)
            _require_allocation_generation(current, allocation)
            if current.state is EndpointAllocationState.RELEASED:
                return current
            self._require_lease_authority_locked(current)

        if current.state is EndpointAllocationState.BOUND:
            physical = self._probe.probe(current.endpoint)
            if not physical.available:
                raise EndpointPhysicalConvergencePending((current.allocation_id,))

        with self._lock:
            current = self._reconcile_allocation_locked(allocation.allocation_id)
            _require_allocation_generation(current, allocation)
            if current.state is EndpointAllocationState.RELEASED:
                return current
            self._require_lease_authority_locked(current)
            self._leases.release(
                current.lease_id,
                fencing_token=current.lease_fencing_token,
            )
            released = replace(current, state=EndpointAllocationState.RELEASED)
            self._allocations[allocation.allocation_id] = released
            return released

    def get(self, allocation_id: str) -> EndpointAllocation:
        with self._lock:
            return self._reconcile_allocation_locked(allocation_id)

    def active(self) -> tuple[EndpointAllocation, ...]:
        with self._lock:
            rows = tuple(
                self._reconcile_allocation_locked(allocation_id)
                for allocation_id in tuple(self._allocations)
            )
            return tuple(
                sorted(
                    (row for row in rows if row.state.is_live),
                    key=lambda row: row.allocation_id,
                )
            )

    def reconcile(
        self,
        *,
        now: float | None = None,
    ) -> tuple[EndpointAllocation, ...]:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s) or now_epoch_s <= 0:
            raise ValueError("endpoint reconciliation time must be finite and positive")
        self._leases.reconcile_expired(
            resource_kind=ResourceKind.NETWORK_ENDPOINT,
        )
        with self._lock:
            orphans = tuple(
                row
                for row in self._allocations.values()
                if row.state.is_live
                and not self._lease_authoritative_locked(row)
            )

        released: list[EndpointAllocation] = []
        pending: list[str] = []
        for expected in orphans:
            if expected.state is EndpointAllocationState.BOUND:
                physical = self._probe.probe(expected.endpoint)
                if not physical.available:
                    pending.append(expected.allocation_id)
                    continue
            with self._lock:
                current = self._reconcile_allocation_locked(expected.allocation_id)
                _require_allocation_generation(current, expected)
                if current.state is EndpointAllocationState.RELEASED:
                    continue
                if self._lease_authoritative_locked(current):
                    continue
                retired = replace(current, state=EndpointAllocationState.RELEASED)
                self._allocations[current.allocation_id] = retired
                released.append(retired)

        if pending:
            raise EndpointPhysicalConvergencePending(tuple(pending))
        return tuple(sorted(released, key=lambda row: row.allocation_id))


__all__ = [
    "AtomicEndpointAllocator",
    "EndpointAllocationConflict",
    "EndpointAllocationUnavailable",
    "EndpointPhysicalConvergencePending",
    "InMemoryEndpointAllocator",
]
