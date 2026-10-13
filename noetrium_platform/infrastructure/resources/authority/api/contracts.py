from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    current_execution_context,
    JsonValue,
    canonical_digest,
)
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import math
from types import MappingProxyType

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.governance.api import (
    is_scope_unit,
    scope_key,
    scope_requires_live_lease,
)
from .resource_units import (
    TicketState,
    binding_field,
    claim_field,
    is_authority_lease,
    is_realization_binding,
    is_realization_ticket,
    is_resource_claim,
    is_resource_observation,
    lease_field,
    lease_live_at,
    observation_field,
    ticket_field,
)


def _text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _non_negative_int(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class AuthorityLeasePolicy:
    """TTL and renewal cadence for Universal Authority consumer leases."""

    ttl_seconds: float = 120.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        ttl = float(self.ttl_seconds)
        renewal = float(self.renewal_interval_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("authority lease ttl_seconds must be finite and > 0")
        if not math.isfinite(renewal) or renewal <= 0:
            raise ValueError(
                "authority lease renewal_interval_seconds must be finite and > 0"
            )
        if renewal >= ttl:
            raise ValueError(
                "authority lease renewal interval must be shorter than ttl"
            )


DEFAULT_AUTHORITY_LEASE_POLICY = AuthorityLeasePolicy()


@dataclass(frozen=True, slots=True)
class ResourceCapacity:
    limits: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                (_text(k, "capacity dimension"), _non_negative_int(v, "capacity limit"))
                for k, v in self.limits
            )
        )
        if len({k for k, _ in normalized}) != len(normalized):
            raise ValueError("capacity dimensions must be unique")
        object.__setattr__(self, "limits", normalized)

    @property
    def by_dimension(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self.limits))


class ResourceObservationNotReady(RuntimeError):
    """A physical realization observation has not converged to bindable READY state."""


class ResourceClaimConflict(RuntimeError):
    """Authority conflict enriched only with diagnostic locus, never resource truth."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        context = current_execution_context()
        if context is None or context.graph_coordinate is None:
            return
        coordinate = context.graph_coordinate
        self.add_note(
            "graph resource locus: "
            f"node={coordinate.graph_node_id} "
            f"attempt={coordinate.attempt_id} "
            f"generation={coordinate.generation}"
        )


@dataclass(frozen=True, slots=True)
class ClaimAggregate:
    amounts: tuple[tuple[str, int], ...] = ()
    shared: tuple[str, ...] = ()
    exclusive: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_amounts = tuple(
            sorted(
                (_text(k, "aggregate dimension"), _non_negative_int(v, "aggregate amount"))
                for k, v in self.amounts
            )
        )
        normalized_shared = tuple(
            sorted(set(_text(v, "aggregate shared token") for v in self.shared))
        )
        normalized_exclusive = tuple(
            sorted(_text(v, "aggregate exclusive token") for v in self.exclusive)
        )
        if len({k for k, _ in normalized_amounts}) != len(normalized_amounts):
            raise ValueError("aggregate dimensions must be unique")
        if len(set(normalized_exclusive)) != len(normalized_exclusive):
            raise ValueError("aggregate exclusive tokens must be unique")
        if set(normalized_shared) & set(normalized_exclusive):
            raise ValueError("aggregate token cannot be both shared and exclusive")
        object.__setattr__(self, "amounts", normalized_amounts)
        object.__setattr__(self, "shared", normalized_shared)
        object.__setattr__(self, "exclusive", normalized_exclusive)

    @classmethod
    def zero(cls) -> "ClaimAggregate":
        return cls()

    def compose(
        self,
        other: "ClaimAggregate",
        *,
        capacity: ResourceCapacity | None = None,
    ) -> "ClaimAggregate":
        if type(other) is not ClaimAggregate:
            raise TypeError("claim composition requires ClaimAggregate")
        self_shared = set(self.shared)
        other_shared = set(other.shared)
        self_exclusive = set(self.exclusive)
        other_exclusive = set(other.exclusive)
        overlap = (
            self_exclusive & (other_exclusive | other_shared)
        ) | (other_exclusive & self_shared)
        if overlap:
            raise ResourceClaimConflict(
                f"exclusive claim conflict: {tuple(sorted(overlap))}"
            )
        totals = dict(self.amounts)
        for key, value in other.amounts:
            totals[key] = totals.get(key, 0) + value
        if capacity is not None:
            limits = capacity.by_dimension
            for key, value in totals.items():
                if key not in limits:
                    raise ResourceClaimConflict(
                        f"capacity dimension is undeclared: {key}"
                    )
                limit = limits[key]
                if value > limit:
                    raise ResourceClaimConflict(
                        f"capacity exceeded for {key}: requested={value} limit={limit}"
                    )
        return ClaimAggregate(
            tuple(totals.items()),
            tuple(sorted(self_shared | other_shared)),
            self.exclusive + other.exclusive,
        )

    @classmethod
    def from_claim(cls, claim: NoetriumUnit) -> "ClaimAggregate":
        if not is_resource_claim(claim):
            raise TypeError("claim aggregate requires resource.claim Unit")
        return cls(
            tuple(claim_field(claim, "amounts")),
            tuple(claim_field(claim, "shared")),
            tuple(claim_field(claim, "exclusive")),
        )


def compose_claims(
    claims: tuple[NoetriumUnit, ...],
    *,
    capacity: ResourceCapacity | None = None,
) -> ClaimAggregate:
    if type(claims) is not tuple or any(
        not is_resource_claim(row) for row in claims
    ):
        raise TypeError("claim composition requires resource.claim Unit tuple")

    limits = None if capacity is None else capacity.by_dimension
    totals: dict[str, int] = {}
    shared: set[str] = set()
    exclusive: set[str] = set()

    for claim in sorted(
        claims,
        key=lambda row: str(claim_field(row, "claim_id")),
    ):
        for key, value in claim_field(claim, "amounts"):
            total = totals.get(key, 0) + value
            if limits is not None:
                if key not in limits:
                    raise ResourceClaimConflict(
                        f"capacity dimension is undeclared: {key}"
                    )
                limit = limits[key]
                if total > limit:
                    raise ResourceClaimConflict(
                        f"capacity exceeded for {key}: "
                        f"requested={total} limit={limit}"
                    )
            totals[key] = total

        claim_shared = tuple(claim_field(claim, "shared"))
        claim_exclusive = tuple(claim_field(claim, "exclusive"))
        overlap = (
            set(claim_exclusive) & (exclusive | shared)
        ) | (exclusive & set(claim_shared))
        if overlap:
            raise ResourceClaimConflict(
                f"exclusive claim conflict: {tuple(sorted(overlap))}"
            )
        shared.update(claim_shared)
        exclusive.update(claim_exclusive)

    return ClaimAggregate(
        tuple(totals.items()),
        tuple(shared),
        tuple(exclusive),
    )


@dataclass(frozen=True, slots=True, order=True)
class AuthorityGeneration:
    resource_key: str
    generation: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_key", _text(self.resource_key, "authority resource")
        )
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("authority generation must be positive")

    def fences(self, other: "AuthorityGeneration") -> bool:
        if type(other) is not AuthorityGeneration:
            raise TypeError(
                "generation fencing comparison requires AuthorityGeneration"
            )
        return (
            self.resource_key == other.resource_key
            and self.generation > other.generation
        )


@dataclass(frozen=True, slots=True)
class ResourceRealizationSpec:
    provider_kind: str
    parameters: Mapping[str, JsonValue] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_kind",
            _text(self.provider_kind, "realization provider kind"),
        )
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType({} if self.parameters is None else dict(self.parameters)),
        )

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(
            {
                "provider_kind": self.provider_kind,
                "parameters": dict(self.parameters or {}),
            }
        )


class ResourceLifecycleView(StrEnum):
    ABSENT = "absent"
    RESERVED = "reserved"
    REALIZING = "realizing"
    READY = "ready"
    IN_USE = "in-use"
    RETIRING = "retiring"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class AuthoritySnapshot:
    generations: tuple[AuthorityGeneration, ...]
    claims: tuple[NoetriumUnit, ...]
    leases: tuple[NoetriumUnit, ...]
    tickets: tuple[NoetriumUnit, ...]
    bindings: tuple[NoetriumUnit, ...]
    _generation_by_key: Mapping[str, AuthorityGeneration] = field(
        init=False, repr=False, compare=False
    )
    _claims_by_key: Mapping[str, tuple[NoetriumUnit, ...]] = field(
        init=False, repr=False, compare=False
    )
    _current_claims_by_key: Mapping[str, tuple[NoetriumUnit, ...]] = field(
        init=False, repr=False, compare=False
    )
    _tickets_by_key: Mapping[str, tuple[NoetriumUnit, ...]] = field(
        init=False, repr=False, compare=False
    )
    _current_ticket_by_key: Mapping[str, NoetriumUnit] = field(
        init=False, repr=False, compare=False
    )
    _ticket_by_id: Mapping[str, NoetriumUnit] = field(
        init=False, repr=False, compare=False
    )
    _binding_by_key: Mapping[str, NoetriumUnit] = field(
        init=False, repr=False, compare=False
    )
    _leases_by_key: Mapping[str, tuple[NoetriumUnit, ...]] = field(
        init=False, repr=False, compare=False
    )
    _lease_by_id: Mapping[str, NoetriumUnit] = field(
        init=False, repr=False, compare=False
    )
    _claims_by_owner_lease: Mapping[str, tuple[NoetriumUnit, ...]] = field(
        init=False, repr=False, compare=False
    )
    _exclusive_tokens: frozenset[str] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        generations: dict[str, AuthorityGeneration] = {}
        for row in self.generations:
            if type(row) is not AuthorityGeneration:
                raise TypeError("authority snapshot generations must be typed")
            if row.resource_key in generations:
                raise ValueError(
                    f"authority snapshot duplicates generation for {row.resource_key}"
                )
            generations[row.resource_key] = row

        if any(not is_resource_claim(row) for row in self.claims):
            raise TypeError("authority snapshot claims must be resource.claim Units")
        claims_mut: dict[str, list[NoetriumUnit]] = {}
        claims_by_owner_mut: dict[str, list[NoetriumUnit]] = {}
        exclusive_tokens: set[str] = set()
        for row in self.claims:
            key = str(claim_field(row, "resource_key"))
            claims_mut.setdefault(key, []).append(row)
            owner_lease_id = claim_field(row, "owner_lease_id")
            if owner_lease_id is not None:
                claims_by_owner_mut.setdefault(str(owner_lease_id), []).append(row)
            for token in tuple(claim_field(row, "exclusive")):
                if token in exclusive_tokens:
                    raise RuntimeError(
                        "authority snapshot contains duplicate active exclusive token: "
                        + str(token)
                    )
                exclusive_tokens.add(str(token))
        claims = {key: tuple(rows) for key, rows in claims_mut.items()}
        current_claims = {
            key: tuple(
                row
                for row in claims.get(key, ())
                if int(claim_field(row, "generation")) == generation.generation
            )
            for key, generation in generations.items()
        }

        if any(not is_realization_ticket(row) for row in self.tickets):
            raise TypeError("authority snapshot tickets must be resource.ticket Units")
        tickets_mut: dict[str, list[NoetriumUnit]] = {}
        tickets_by_id: dict[str, NoetriumUnit] = {}
        for row in self.tickets:
            key = str(ticket_field(row, "resource_key"))
            ticket_id = str(ticket_field(row, "ticket_id"))
            tickets_mut.setdefault(key, []).append(row)
            if ticket_id in tickets_by_id:
                raise ValueError(
                    f"authority snapshot duplicates ticket id {ticket_id}"
                )
            tickets_by_id[ticket_id] = row
        tickets = {key: tuple(rows) for key, rows in tickets_mut.items()}
        current_tickets: dict[str, NoetriumUnit] = {}
        for key, generation in generations.items():
            rows = tuple(
                row
                for row in tickets.get(key, ())
                if int(ticket_field(row, "generation")) == generation.generation
                and ticket_field(row, "state") is not TicketState.RETIRED
            )
            if len(rows) > 1:
                raise RuntimeError(
                    f"authority snapshot contains multiple live tickets for {key}"
                )
            if rows:
                current_tickets[key] = rows[0]

        if any(not is_realization_binding(row) for row in self.bindings):
            raise TypeError("authority snapshot bindings must be resource.realization-binding Units")
        bindings: dict[str, NoetriumUnit] = {}
        for row in self.bindings:
            key = str(binding_field(row, "resource_key"))
            generation = generations.get(key)
            if generation is None or int(binding_field(row, "generation")) != generation.generation:
                continue
            if key in bindings:
                raise RuntimeError(
                    f"authority snapshot contains multiple current bindings for {key}"
                )
            bindings[key] = row

        if any(not is_authority_lease(row) for row in self.leases):
            raise TypeError("authority snapshot leases must be resource.lease Units")
        leases_mut: dict[str, list[NoetriumUnit]] = {}
        lease_by_id: dict[str, NoetriumUnit] = {}
        for row in self.leases:
            key = str(lease_field(row, "resource_key"))
            lease_id = str(lease_field(row, "lease_id"))
            if lease_id in lease_by_id:
                raise ValueError(f"authority snapshot duplicates lease id {lease_id}")
            lease_by_id[lease_id] = row
            leases_mut.setdefault(key, []).append(row)
        leases = {key: tuple(rows) for key, rows in leases_mut.items()}
        claims_by_owner = {
            key: tuple(sorted(rows, key=lambda row: str(claim_field(row, "claim_id"))))
            for key, rows in claims_by_owner_mut.items()
        }

        for name, value in (
            ("_generation_by_key", generations),
            ("_claims_by_key", claims),
            ("_current_claims_by_key", current_claims),
            ("_tickets_by_key", tickets),
            ("_current_ticket_by_key", current_tickets),
            ("_ticket_by_id", tickets_by_id),
            ("_binding_by_key", bindings),
            ("_leases_by_key", leases),
            ("_lease_by_id", lease_by_id),
            ("_claims_by_owner_lease", claims_by_owner),
        ):
            object.__setattr__(self, name, MappingProxyType(value))
        object.__setattr__(self, "_exclusive_tokens", frozenset(exclusive_tokens))

    def generation_for(self, resource_key: str) -> AuthorityGeneration | None:
        return self._generation_by_key.get(resource_key)

    def tickets_for(self, resource_key: str) -> tuple[NoetriumUnit, ...]:
        return self._tickets_by_key.get(resource_key, ())

    def claims_for(self, resource_key: str) -> tuple[NoetriumUnit, ...]:
        return self._claims_by_key.get(resource_key, ())

    def current_claims_for(self, resource_key: str) -> tuple[NoetriumUnit, ...]:
        return self._current_claims_by_key.get(resource_key, ())

    def current_ticket_for(self, resource_key: str) -> NoetriumUnit | None:
        return self._current_ticket_by_key.get(resource_key)

    def ticket_by_id(self, ticket_id: str) -> NoetriumUnit | None:
        return self._ticket_by_id.get(ticket_id)

    def binding_for(self, resource_key: str) -> NoetriumUnit | None:
        return self._binding_by_key.get(resource_key)

    def lease_by_id(self, lease_id: str) -> NoetriumUnit | None:
        if type(lease_id) is not str or not lease_id.strip():
            raise ValueError("authority lease lookup requires non-empty text")
        return self._lease_by_id.get(lease_id.strip())

    def claims_for_owner_lease(
        self,
        lease_id: str,
    ) -> tuple[NoetriumUnit, ...]:
        if type(lease_id) is not str or not lease_id.strip():
            raise ValueError("owner lease claim lookup requires non-empty text")
        return self._claims_by_owner_lease.get(lease_id.strip(), ())

    def _scope_lease_chain_live(
        self,
        *,
        owner_scope: NoetriumUnit,
        scope_generation: int,
        scope_lease_id: str | None,
        now_epoch_s: float,
        visiting: frozenset[str] = frozenset(),
    ) -> bool:
        if not is_scope_unit(owner_scope):
            return False
        scope_resource_key = "scope:" + scope_key(owner_scope)
        generation = self._generation_by_key.get(scope_resource_key)
        if generation is None or generation.generation != int(scope_generation):
            return False
        if not scope_requires_live_lease(owner_scope):
            return scope_lease_id is None
        if scope_lease_id is None or scope_lease_id in visiting:
            return False
        lease = self._lease_by_id.get(scope_lease_id)
        if lease is None:
            return False
        if (
            str(lease_field(lease, "resource_key")) != scope_resource_key
            or int(lease_field(lease, "generation")) != int(scope_generation)
            or not lease_live_at(
                lease,
                now_epoch_s,
                current_generation=scope_generation,
            )
        ):
            return False
        return self._scope_lease_chain_live(
            owner_scope=lease_field(lease, "owner_scope"),
            scope_generation=int(lease_field(lease, "scope_generation")),
            scope_lease_id=lease_field(lease, "scope_lease_id"),
            now_epoch_s=now_epoch_s,
            visiting=visiting | {scope_lease_id},
        )

    def orphaned_claim_groups(
        self,
        *,
        now_epoch_s: float,
    ) -> tuple[tuple[str, tuple[NoetriumUnit, ...]], ...]:
        """Return active claims whose complete Scope/lease ownership is dead.

        The group key is the lease whose loss invalidated the claims. Dynamic
        Scope loss takes precedence over an optional resource-owner lease,
        because every child resource becomes unauthorized when its Scope dies.
        """
        now = float(now_epoch_s)
        if not math.isfinite(now) or now <= 0:
            raise ValueError("orphan observation time must be finite and positive")

        grouped: dict[str, list[NoetriumUnit]] = {}
        for claim in self.claims:
            scope_lease_id = claim_field(claim, "scope_lease_id")
            owner_lease_id = claim_field(claim, "owner_lease_id")
            scope_live = self._scope_lease_chain_live(
                owner_scope=claim_field(claim, "owner_scope"),
                scope_generation=int(claim_field(claim, "scope_generation")),
                scope_lease_id=scope_lease_id,
                now_epoch_s=now,
            )
            group: str | None = None
            if not scope_live:
                group = (
                    str(scope_lease_id)
                    if scope_lease_id is not None
                    else (
                        str(owner_lease_id)
                        if owner_lease_id is not None
                        else "missing-scope-owner:"
                        + str(claim_field(claim, "claim_id"))
                    )
                )
            elif owner_lease_id is not None:
                owner = self._lease_by_id.get(str(owner_lease_id))
                owner_live = owner is not None
                if owner is not None:
                    generation = self._generation_by_key.get(
                        str(lease_field(owner, "resource_key"))
                    )
                    owner_live = (
                        generation is not None
                        and lease_field(owner, "owner_scope")
                        == claim_field(claim, "owner_scope")
                        and int(lease_field(owner, "scope_generation"))
                        == int(claim_field(claim, "scope_generation"))
                        and lease_field(owner, "scope_lease_id") == scope_lease_id
                        and lease_live_at(
                            owner,
                            now,
                            current_generation=generation.generation,
                        )
                        and self._scope_lease_chain_live(
                            owner_scope=lease_field(owner, "owner_scope"),
                            scope_generation=int(
                                lease_field(owner, "scope_generation")
                            ),
                            scope_lease_id=lease_field(owner, "scope_lease_id"),
                            now_epoch_s=now,
                        )
                    )
                if not owner_live:
                    group = str(owner_lease_id)
            if group is not None:
                grouped.setdefault(group, []).append(claim)

        return tuple(
            (
                lease_id,
                tuple(
                    sorted(
                        claims,
                        key=lambda row: str(claim_field(row, "claim_id")),
                    )
                ),
            )
            for lease_id, claims in sorted(grouped.items())
        )
    @property
    def exclusive_token_count(self) -> int:
        return len(self._exclusive_tokens)

    def exclusive_token_claimed(self, token: str) -> bool:
        if type(token) is not str or not token:
            raise ValueError("authority exclusive token lookup requires non-empty text")
        return token in self._exclusive_tokens

    def lifecycle_view(
        self,
        resource_key: str,
        observation: NoetriumUnit | None,
        *,
        now_epoch_s: float,
    ) -> ResourceLifecycleView:
        if observation is not None and not is_resource_observation(observation):
            raise TypeError("lifecycle observation must be resource.observation Unit")
        generation = self.generation_for(resource_key)
        if generation is None:
            return ResourceLifecycleView.ABSENT
        current = tuple(
            row
            for row in self.tickets_for(resource_key)
            if int(ticket_field(row, "generation")) == generation.generation
        )
        if any(ticket_field(row, "state") is TicketState.RETIRING for row in current):
            return ResourceLifecycleView.RETIRING
        binding = self.binding_for(resource_key)
        if (
            binding is not None
            and observation is not None
            and bool(observation_field(observation, "exists"))
            and bool(observation_field(observation, "ready"))
            and int(observation_field(observation, "generation")) == generation.generation
            and observation_field(observation, "ticket_id") == binding_field(binding, "ticket_id")
            and observation_field(observation, "spec_digest") == binding_field(binding, "spec_digest")
        ):
            live = any(
                lease_live_at(
                    lease,
                    now_epoch_s,
                    current_generation=generation.generation,
                )
                for lease in self._leases_by_key.get(resource_key, ())
            )
            return ResourceLifecycleView.IN_USE if live else ResourceLifecycleView.READY
        if any(ticket_field(row, "state") is TicketState.PREPARED for row in current):
            return ResourceLifecycleView.REALIZING
        if self.current_claims_for(resource_key):
            return ResourceLifecycleView.RESERVED
        if current and all(ticket_field(row, "state") is TicketState.RETIRED for row in current):
            return ResourceLifecycleView.RETIRED
        return ResourceLifecycleView.ABSENT


class ReconcileActionKind(StrEnum):
    ADVANCE_GENERATION = "advance-generation"
    ACQUIRE_CLAIM = "acquire-claim"
    PREPARE = "prepare"
    REALIZE = "realize"
    BIND = "bind"
    RETIRE = "retire"
    CONFIRM_ABSENT = "confirm-absent"
    RELEASE_CLAIM = "release-claim"


@dataclass(frozen=True, slots=True)
class ReconcileAction:
    ordinal: int
    kind: ReconcileActionKind
    resource_id: str
    reference_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError(
                "reconcile action ordinal must be non-negative"
            )
        if not isinstance(self.kind, ReconcileActionKind):
            raise TypeError(
                "reconcile action kind must be ReconcileActionKind"
            )
        object.__setattr__(
            self,
            "resource_id",
            _text(self.resource_id, "reconcile resource"),
        )
        if self.reference_id is not None:
            object.__setattr__(
                self,
                "reference_id",
                _text(self.reference_id, "reconcile reference"),
            )


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    topology_digest: str
    actions: tuple[ReconcileAction, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "topology_digest",
            _text(self.topology_digest, "topology digest"),
        )
        expected = tuple(range(len(self.actions)))
        observed = tuple(row.ordinal for row in self.actions)
        if observed != expected:
            raise ValueError(
                "reconcile action ordinals must be contiguous and deterministic"
            )

    @property
    def converged(self) -> bool:
        return not self.actions


__all__ = [
    "AuthorityGeneration",
    "AuthorityLeasePolicy",
    "AuthoritySnapshot",
    "ClaimAggregate",
    "ReconcileAction",
    "ReconcileActionKind",
    "ReconcilePlan",
    "ResourceCapacity",
    "ResourceClaimConflict",
    "ResourceLifecycleView",
    "ResourceRealizationSpec",
    "DEFAULT_AUTHORITY_LEASE_POLICY",
    "compose_claims",
]
