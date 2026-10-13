"""Resource-backed lifetime control.

There is intentionally no lifetime authority here.  Every mutable lifecycle
fact -- generation, admission fence and borrower lease -- lives in the single
ResourceAuthorityPort.  This module retains only immutable dependency wiring
and physical retire callbacks, then projects lifecycle state from the resource
Authority snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Callable

from noetrium_platform.foundation.api import (
    NoetriumUnit,
    ResourceAuthorityPort,
    claim_field,
    lease_field,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.api import PLATFORM_SCOPE


class ResourceLifetimePhase(StrEnum):
    LIVE = "live"
    RETIRING = "retiring"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class ResourceLifetimeSnapshot:
    domain_id: str
    resource_key: str
    owner_generation_id: str
    phase: ResourceLifetimePhase
    active_lease_count: int
    dependencies: tuple[str, ...]
    generation: int


@dataclass(frozen=True, slots=True)
class ResourceLifetimeRegistration:
    """Immutable registration token; never a mutable ownership record."""

    domain_id: str
    resource_key: str
    owner_generation_id: str
    generation: int

    def __post_init__(self) -> None:
        if not self.domain_id.strip() or not self.resource_key.strip():
            raise ValueError("resource lifetime registration identity is required")
        if not self.owner_generation_id.strip():
            raise ValueError("resource lifetime owner generation is required")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("resource lifetime registration generation must be positive")


@dataclass(frozen=True, slots=True)
class _DomainRegistration:
    token: ResourceLifetimeRegistration
    topology: NoetriumUnit
    retire: Callable[[], None] | None


class ResourceLifetimeLease:
    """Thin borrower handle over one authorized Universal Resource lease Unit."""

    __slots__ = ("_controller", "_lease", "_lock")

    def __init__(
        self,
        controller: "ResourceLifetimeController",
        lease: NoetriumUnit,
    ) -> None:
        self._controller = controller
        self._lease = lease
        self._lock = RLock()

    @property
    def lease_id(self) -> str:
        return str(lease_field(self._lease, "lease_id"))

    @property
    def domain_id(self) -> str:
        return str(lease_field(self._lease, "metadata")["lifetime_domain_id"])

    @property
    def holder_key(self) -> str:
        return str(lease_field(self._lease, "holder_key"))

    @property
    def generation(self) -> int:
        return int(lease_field(self._lease, "generation"))

    @property
    def released(self) -> bool:
        return bool(lease_field(self._lease, "released"))

    @property
    def unit(self) -> NoetriumUnit:
        return self._lease

    def release(self) -> None:
        with self._lock:
            if self.released:
                return
            self._lease = self._controller.release(self)

    def __enter__(self) -> "ResourceLifetimeLease":
        if self.released:
            raise RuntimeError("released resource lifetime lease cannot be re-entered")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.release()
        return False


class ResourceLifetimeController:
    """Dependency/retirement controller backed by the universal resource Authority.

    The controller owns no generation, lease set, fencing token or lifecycle
    phase.  Its only local data is immutable registration topology, physical
    retire callbacks, and a lease-id sequence.  All decisions are made from the
    ResourceAuthorityPort's journal-backed state.
    """

    def __init__(
        self,
        authority_key: str,
        owner_generation_id: str,
        resource_authority: ResourceAuthorityPort,
    ) -> None:
        if not authority_key.strip() or not owner_generation_id.strip():
            raise ValueError("resource lifetime controller identity is required")
        if not isinstance(resource_authority, ResourceAuthorityPort):
            raise TypeError("resource lifetime controller requires ResourceAuthorityPort")
        self.authority_key = authority_key.strip()
        self.owner_generation_id = owner_generation_id.strip()
        self.resource_authority = resource_authority
        self._lock = RLock()
        self._domains: dict[str, _DomainRegistration] = {}
        self._next_lease_sequence = 1
        self._root_domain_id = f"{self.authority_key}:root"
        self._register_locked(self._root_domain_id, dependencies=(), retire=None)

    @property
    def root_domain_id(self) -> str:
        return self._root_domain_id

    def _resource_key(self, domain_id: str) -> str:
        return "lifecycle:" + canonical_digest(
            {
                "authority_key": self.authority_key,
                "owner_generation_id": self.owner_generation_id,
                "domain_id": domain_id,
            }
        )

    def _register_locked(
        self,
        domain_id: str,
        *,
        dependencies: tuple[str, ...],
        retire: Callable[[], None] | None,
    ) -> ResourceLifetimeRegistration:
        if type(domain_id) is not str or not domain_id.strip():
            raise ValueError("resource lifetime domain_id is required")
        if type(dependencies) is not tuple or any(
            type(value) is not str or not value.strip() for value in dependencies
        ):
            raise TypeError("resource lifetime dependencies must be a text tuple")
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("resource lifetime dependencies must be unique")
        if retire is not None and not callable(retire):
            raise TypeError("resource lifetime retire callback must be callable or None")
        if domain_id in self._domains:
            raise ValueError(f"duplicate resource lifetime domain: {domain_id}")
        missing = tuple(value for value in dependencies if value not in self._domains)
        if missing:
            raise ValueError(
                f"resource lifetime dependencies must already exist: {missing}"
            )
        resource_key = self._resource_key(domain_id)
        generation = self.resource_authority.ensure_generation(resource_key)
        token = ResourceLifetimeRegistration(
            domain_id,
            resource_key,
            self.owner_generation_id,
            int(generation.generation),
        )
        dependency_ids = tuple(sorted(dependencies))
        topology = NoetriumUnit(
            unit_id=(
                "lifetime-domain:"
                + canonical_digest(
                    {
                        "domain_id": domain_id,
                        "dependencies": dependency_ids,
                    }
                )
            ),
            schemas=("lifecycle.domain-topology",),
            attributes={
                "kind": "lifetime-domain-topology",
                "domain_id": domain_id,
                "dependencies": dependency_ids,
            },
        )
        self._domains[domain_id] = _DomainRegistration(
            token,
            topology,
            retire,
        )
        return token

    def register(
        self,
        domain_id: str,
        *,
        dependencies: tuple[str, ...] | None = None,
        retire: Callable[[], None] | None,
    ) -> ResourceLifetimeRegistration:
        with self._lock:
            return self._register_locked(
                domain_id,
                dependencies=(
                    (self._root_domain_id,) if dependencies is None else dependencies
                ),
                retire=retire,
            )

    def _registration(self, domain_id: str) -> _DomainRegistration:
        try:
            return self._domains[domain_id]
        except KeyError as exc:
            raise KeyError(domain_id) from exc

    def _current_retirement_gate(
        self,
        registration: _DomainRegistration,
    ) -> NoetriumUnit | None:
        snapshot = self.resource_authority.snapshot()
        token = "lease-admission:" + registration.token.resource_key
        gates = tuple(
            claim
            for claim in snapshot.current_claims_for(registration.token.resource_key)
            if token in tuple(claim_field(claim, "exclusive"))
            and dict(claim_field(claim, "attributes") or {}).get("kind")
            == "lease-admission-fence"
        )
        if len(gates) > 1:
            raise RuntimeError(
                "resource lifetime contains multiple current retirement gates: "
                + registration.token.domain_id
            )
        if gates and claim_field(gates[0], "holder_key") != self.owner_generation_id:
            raise RuntimeError(
                "resource lifetime retirement gate is owned by another generation: "
                + registration.token.domain_id
            )
        return gates[0] if gates else None

    def acquire(
        self,
        holder_key: str,
        *,
        domain_id: str | None = None,
    ) -> ResourceLifetimeLease:
        if type(holder_key) is not str or not holder_key.strip():
            raise ValueError("resource lifetime holder_key is required")
        key = self._root_domain_id if domain_id is None else domain_id
        with self._lock:
            registration = self._registration(key)
            current = self.resource_authority.snapshot().generation_for(
                registration.token.resource_key
            )
            if (
                current is None
                or current.generation != registration.token.generation
                or self._current_retirement_gate(registration) is not None
            ):
                raise RuntimeError(
                    "resource lifetime domain does not admit new leases: " + key
                )
            sequence = self._next_lease_sequence
            self._next_lease_sequence += 1
        lease_id = "lifetime-lease:" + canonical_digest(
            {
                "resource_key": registration.token.resource_key,
                "owner_generation_id": self.owner_generation_id,
                "holder_key": holder_key.strip(),
                "sequence": sequence,
            }
        )
        lease = self.resource_authority.acquire_consumer_lease(
            lease_id=lease_id,
            resource_key=registration.token.resource_key,
            holder_key=holder_key.strip(),
            owner_scope=PLATFORM_SCOPE,
            metadata={
                "kind": "resource-lifetime-borrow",
                "lifetime_domain_id": key,
                "lifetime_owner_generation_id": self.owner_generation_id,
            },
        )
        return ResourceLifetimeLease(self, lease)

    def release(self, lease: ResourceLifetimeLease) -> NoetriumUnit:
        if not isinstance(lease, ResourceLifetimeLease):
            raise TypeError("resource lifetime release requires ResourceLifetimeLease")
        metadata = dict(lease_field(lease.unit, "metadata") or {})
        if metadata.get("lifetime_owner_generation_id") != self.owner_generation_id:
            raise RuntimeError("resource lifetime lease owner generation drifted")
        return self.resource_authority.release_lease(lease.unit)

    def _phase(self, registration: _DomainRegistration) -> tuple[ResourceLifetimePhase, int]:
        snapshot = self.resource_authority.snapshot()
        current = snapshot.generation_for(registration.token.resource_key)
        if current is None:
            raise RuntimeError(
                "resource lifetime generation disappeared: "
                + registration.token.domain_id
            )
        if current.generation < registration.token.generation:
            raise RuntimeError("resource lifetime generation regressed")
        if current.generation == registration.token.generation:
            return ResourceLifetimePhase.LIVE, current.generation
        gate = self._current_retirement_gate(registration)
        return (
            ResourceLifetimePhase.RETIRING if gate is not None else ResourceLifetimePhase.RETIRED,
            current.generation,
        )

    def snapshot(self) -> tuple[ResourceLifetimeSnapshot, ...]:
        with self._lock:
            registrations = tuple(self._domains.values())
        rows = []
        for registration in sorted(
            registrations, key=lambda row: row.token.domain_id
        ):
            phase, generation = self._phase(registration)
            leases = self.resource_authority.active_leases(
                registration.token.resource_key
            )
            rows.append(
                ResourceLifetimeSnapshot(
                    registration.token.domain_id,
                    registration.token.resource_key,
                    self.owner_generation_id,
                    phase,
                    len(leases),
                    tuple(registration.topology.attribute("dependencies", ())),
                    generation,
                )
            )
        return tuple(rows)

    @property
    def quiescent(self) -> bool:
        with self._lock:
            registrations = tuple(self._domains.values())
        return all(
            not self.resource_authority.active_leases(row.token.resource_key)
            for row in registrations
        )

    def retire_all(self) -> tuple[str, ...]:
        """Fence then retire every domain in reverse dependency order."""

        with self._lock:
            registrations = tuple(reversed(tuple(self._domains.values())))
        active = tuple(
            (row.token.domain_id, len(leases))
            for row in registrations
            if (leases := self.resource_authority.active_leases(row.token.resource_key))
        )
        if active:
            raise RuntimeError(
                "resource lifetime owner generation is not quiescent; active leases="
                + repr(active)
            )

        retired: list[str] = []
        for registration in registrations:
            snapshot = self.resource_authority.snapshot()
            current = snapshot.generation_for(registration.token.resource_key)
            if current is None:
                raise RuntimeError(
                    "resource lifetime generation disappeared: "
                    + registration.token.domain_id
                )
            gate = self._current_retirement_gate(registration)
            if current.generation > registration.token.generation and gate is None:
                continue
            if current.generation == registration.token.generation:
                gate = self.resource_authority.fence_if_no_live_leases(
                    registration.token.resource_key,
                    holder_key=self.owner_generation_id,
                )
            elif gate is None:
                raise RuntimeError(
                    "resource lifetime generation advanced without retirement gate: "
                    + registration.token.domain_id
                )
            retire = registration.retire
            if retire is not None:
                retire()
            self.resource_authority.release_claim(
                str(claim_field(gate, "claim_id"))
            )
            retired.append(registration.token.domain_id)
        return tuple(retired)


__all__ = [
    "ResourceLifetimeController",
    "ResourceLifetimeLease",
    "ResourceLifetimePhase",
    "ResourceLifetimeRegistration",
    "ResourceLifetimeSnapshot",
]
