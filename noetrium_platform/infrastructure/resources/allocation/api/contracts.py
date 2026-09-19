from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwnership,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _require_sha256_or_none(value: str | None, field: str) -> None:
    if value is not None and not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a canonical lowercase SHA-256 digest")


def _require_positive_finite_or_none(value: float | None, field: str) -> None:
    if value is not None and (not math.isfinite(float(value)) or value <= 0):
        raise ValueError(f"{field} must be finite and positive")


def _binding_proof_presence(
    proof_digest: str | None, binder_digest: str | None, evidence_ref: str | None, bound_at: float | None
) -> tuple[bool, bool]:
    present = (proof_digest is not None, binder_digest is not None, evidence_ref is not None, bound_at is not None)
    return any(present), all(present)


class EndpointProtocol(StrEnum):
    TCP = "tcp"
    UDP = "udp"


class EndpointAllocationState(StrEnum):
    RESERVED = "reserved"
    BOUND = "bound"
    RELEASED = "released"

    @property
    def is_live(self) -> bool:
        return self in {EndpointAllocationState.RESERVED, EndpointAllocationState.BOUND}


class EndpointReservationStatus(StrEnum):
    RESERVED = "reserved"
    EXISTING = "existing"
    RESOURCE_BUSY = "resource-busy"
    OWNER_CONFLICT = "owner-conflict"


@dataclass(frozen=True, slots=True, order=True)
class NetworkEndpoint:
    """An address that can be exclusively attached to one service instance."""

    host: str
    port: int
    protocol: EndpointProtocol = EndpointProtocol.TCP

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("network endpoint host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError("network endpoint port must be between 1 and 65535")

    @property
    def key(self) -> str:
        return f"{self.protocol.value}://{self.host.casefold()}:{self.port}"

    @property
    def resource(self) -> ResourceIdentity:
        return ResourceIdentity(ResourceKind.NETWORK_ENDPOINT, self.key)


@dataclass(frozen=True, slots=True)
class EndpointAllocationRequest:
    allocation_id: str
    holder_scope: ScopeIdentity
    purpose: str
    host: str
    candidate_ports: tuple[int, ...]
    protocol: EndpointProtocol = EndpointProtocol.TCP
    owner_scope: ScopeIdentity = PLATFORM_SCOPE
    ownership: ResourceOwnership = ResourceOwnership.EXTERNAL

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.purpose.strip() or not self.host.strip():
            raise ValueError("endpoint allocation identity, purpose and host are required")
        if not self.candidate_ports:
            raise ValueError("endpoint allocation requires explicit candidate ports")
        if len(set(self.candidate_ports)) != len(self.candidate_ports):
            raise ValueError("endpoint allocation candidate ports must be unique")
        if any(not 1 <= port <= 65535 for port in self.candidate_ports):
            raise ValueError("endpoint allocation candidate ports must be between 1 and 65535")

    def candidates(self) -> tuple[NetworkEndpoint, ...]:
        return tuple(NetworkEndpoint(self.host, port, self.protocol) for port in self.candidate_ports)

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class EndpointLeasePolicy:
    """Lifecycle policy shared by endpoint allocation and lease renewal guards."""

    ttl_seconds: float = 120.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.ttl_seconds)) or self.ttl_seconds <= 0:
            raise ValueError("endpoint lease ttl_seconds must be finite and > 0")
        if (
            not math.isfinite(float(self.renewal_interval_seconds))
            or self.renewal_interval_seconds <= 0
        ):
            raise ValueError("endpoint lease renewal_interval_seconds must be finite and > 0")
        if self.renewal_interval_seconds >= self.ttl_seconds:
            raise ValueError("endpoint lease renewal interval must be shorter than ttl")


DEFAULT_ENDPOINT_LEASE_POLICY = EndpointLeasePolicy()


@dataclass(frozen=True, slots=True)
class EndpointProbeResult:
    endpoint: NetworkEndpoint
    available: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("endpoint probe reason is required")


@dataclass(frozen=True, slots=True)
class EndpointBindingProof:
    """Runtime attestation that one reserved endpoint is owned by the expected binder.

    Resource validates allocation identity and fencing. The runtime/environment
    authority that can observe the real listener supplies the binder digest and
    evidence reference; a DB reservation alone is never treated as OS ownership.
    """

    allocation_id: str
    endpoint: NetworkEndpoint
    lease_fencing_token: int
    binder_identity_digest: str
    observed_at_epoch_s: float
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.evidence_ref.strip():
            raise ValueError("endpoint binding proof identity/evidence required")
        if self.lease_fencing_token < 1:
            raise ValueError("endpoint binding proof fencing token must be >= 1")
        if (
            len(self.binder_identity_digest) != 64
            or self.binder_identity_digest != self.binder_identity_digest.lower()
            or any(character not in "0123456789abcdef" for character in self.binder_identity_digest)
        ):
            raise ValueError("endpoint binder identity must be a canonical lowercase SHA-256 digest")
        if (
            not math.isfinite(float(self.observed_at_epoch_s))
            or self.observed_at_epoch_s <= 0
        ):
            raise ValueError("endpoint binding observation timestamp must be finite and positive")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class EndpointAllocation:
    allocation_id: str
    endpoint: NetworkEndpoint
    lease_id: str
    holder_scope: ScopeIdentity
    purpose: str
    request_digest: str
    state: EndpointAllocationState = EndpointAllocationState.RESERVED
    lease_holder_generation: int = 1
    lease_fencing_token: int = 1
    lease_expires_at_epoch_s: float | None = None
    binding_proof_digest: str | None = None
    binding_binder_identity_digest: str | None = None
    binding_evidence_ref: str | None = None
    bound_at_epoch_s: float | None = None

    def __post_init__(self) -> None:
        if not (
            self.allocation_id.strip()
            and self.lease_id.strip()
            and self.purpose.strip()
            and self.request_digest.strip()
        ):
            raise ValueError("endpoint allocation identity is incomplete")
        if self.lease_holder_generation < 1 or self.lease_fencing_token < 1:
            raise ValueError("endpoint allocation lease generation/fencing must be >= 1")
        _require_positive_finite_or_none(
            self.lease_expires_at_epoch_s, "endpoint allocation lease expiry"
        )
        _require_positive_finite_or_none(
            self.bound_at_epoch_s, "endpoint allocation bound timestamp"
        )
        _require_sha256_or_none(
            self.binding_proof_digest, "endpoint allocation binding proof"
        )
        _require_sha256_or_none(
            self.binding_binder_identity_digest, "endpoint allocation binder identity"
        )
        if self.binding_evidence_ref is not None and not self.binding_evidence_ref.strip():
            raise ValueError("endpoint allocation binding evidence reference must be non-empty")
        any_proof, complete_proof = _binding_proof_presence(
            self.binding_proof_digest,
            self.binding_binder_identity_digest,
            self.binding_evidence_ref,
            self.bound_at_epoch_s,
        )
        if any_proof and not complete_proof:
            raise ValueError("endpoint binding proof metadata must be complete or absent")
        if self.state is EndpointAllocationState.RESERVED and any_proof:
            raise ValueError("reserved endpoint allocation cannot carry binding proof metadata")
        if self.state is EndpointAllocationState.BOUND and not complete_proof:
            raise ValueError("bound endpoint allocation requires complete binding proof metadata")
        # RELEASED may retain a complete historical binding proof. Release changes
        # allocation liveness, not the evidence of which binder previously owned it.



@dataclass(frozen=True, slots=True)
class EndpointReservationResult:
    status: EndpointReservationStatus
    allocation: EndpointAllocation | None = None
    lease: ResourceLease | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status in (EndpointReservationStatus.RESERVED, EndpointReservationStatus.EXISTING):
            if self.allocation is None:
                raise ValueError("successful endpoint reservation requires allocation")
        elif self.allocation is not None:
            raise ValueError("unsuccessful endpoint reservation cannot carry allocation")


__all__ = [
    "EndpointAllocation",
    "EndpointBindingProof",
    "EndpointAllocationRequest",
    "EndpointAllocationState",
    "EndpointLeasePolicy",
    "DEFAULT_ENDPOINT_LEASE_POLICY",
    "EndpointReservationResult",
    "EndpointReservationStatus",
    "EndpointProbeResult",
    "EndpointProtocol",
    "NetworkEndpoint",
]
