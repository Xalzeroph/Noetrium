from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.foundation.kernel.structure import NoetriumUnit

from .contracts import (
    AuthorityGeneration,
    AuthoritySnapshot,
    ResourceCapacity,
    ResourceRealizationSpec,
)


@runtime_checkable
class PhysicalResourceProvider(Protocol):
    """Thin physical ISA. All policy belongs to Authority."""

    def realize(
        self,
        spec: Mapping[str, JsonValue],
        ticket: NoetriumUnit,
    ) -> NoetriumUnit: ...

    def observe(
        self,
        reference: NoetriumUnit,
    ) -> NoetriumUnit: ...

    def retire(
        self,
        reference: NoetriumUnit,
        ticket: NoetriumUnit,
    ) -> NoetriumUnit: ...


@runtime_checkable
class ResourceLeaseHeartbeatGuardPort(Protocol):
    """One borrower-owned heartbeat lifetime without exposing renewal internals."""

    def start(self) -> None: ...
    def assert_healthy(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class ResourceLeaseHeartbeatFactoryPort(Protocol):
    """Composition supplies the sole Resource Authority renewal mechanism."""

    def create(self, leases: tuple[NoetriumUnit, ...]) -> ResourceLeaseHeartbeatGuardPort: ...


@runtime_checkable
class ResourceAuthorityPort(Protocol):
    """Single mutable authority for every logical and physical resource lifetime."""

    def declare_capacity(self, capacity: ResourceCapacity) -> None: ...

    def ensure_capacity(self, capacity: ResourceCapacity) -> None:
        """Declare immutable capacity dimensions or prove exact equality."""
        ...

    def ensure_generation(self, resource_key: str) -> AuthorityGeneration: ...

    def ensure_scope_generation(
        self,
        scope: NoetriumUnit,
    ) -> AuthorityGeneration: ...

    def scope_ownership_cut(
        self,
        scope: NoetriumUnit,
        *,
        scope_lease: NoetriumUnit | None = None,
    ) -> tuple[AuthorityGeneration, str | None]: ...

    def acquire_scope_lease(
        self,
        *,
        scope: NoetriumUnit,
        parent_scope: NoetriumUnit,
        holder_key: str,
        ttl_seconds: float,
        parent_scope_lease: NoetriumUnit | None = None,
        now: float | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> NoetriumUnit: ...

    def acquire_consumer_lease(
        self,
        *,
        lease_id: str,
        resource_key: str,
        holder_key: str,
        owner_scope: NoetriumUnit,
        scope_lease: NoetriumUnit | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> NoetriumUnit: ...

    def acquire_ttl_lease(
        self,
        *,
        lease_id: str,
        resource_key: str,
        holder_key: str,
        owner_scope: NoetriumUnit,
        scope_lease: NoetriumUnit | None = None,
        ttl_seconds: float,
        now: float | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> NoetriumUnit: ...

    def release_lease(self, lease: NoetriumUnit) -> NoetriumUnit: ...

    def fence_if_no_live_leases(
        self,
        resource_key: str,
        *,
        holder_key: str,
        excluding_leases: tuple[NoetriumUnit, ...] = (),
        now: float | None = None,
    ) -> NoetriumUnit: ...

    def admit_bundle(
        self,
        candidate_groups: tuple[tuple[NoetriumUnit, ...], ...],
    ) -> tuple[NoetriumUnit, ...]: ...

    def release_claim(self, claim_id: str) -> NoetriumUnit: ...

    def active_leases(
        self,
        resource_key: str,
        *,
        now: float | None = None,
    ) -> tuple[NoetriumUnit, ...]: ...

    def snapshot(self) -> AuthoritySnapshot: ...

    def snapshot_for_resource_keys(
        self,
        resource_keys: frozenset[str],
    ) -> AuthoritySnapshot: ...

    def snapshot_for_claim_kinds(
        self,
        claim_kinds: frozenset[str],
    ) -> AuthoritySnapshot: ...

    def snapshot_for_holder(self, holder_key: str) -> AuthoritySnapshot: ...

    def binding_for_physical(
        self,
        provider_kind: str,
        physical_id: str,
    ) -> NoetriumUnit | None: ...

    def reconcile_orphan_claims(self) -> tuple[NoetriumUnit, ...]: ...

    def reconcile_orphan_claims_for_claim_kinds(
        self,
        claim_kinds: frozenset[str],
    ) -> tuple[NoetriumUnit, ...]: ...

    def orphaned_claim_groups_for_claim_kinds(
        self,
        claim_kinds: frozenset[str],
        *,
        now: float | None = None,
    ) -> tuple[tuple[str, tuple[NoetriumUnit, ...]], ...]: ...

    def orphaned_claim_groups(
        self,
        *,
        now: float | None = None,
    ) -> tuple[tuple[str, tuple[NoetriumUnit, ...]], ...]: ...

    def reconcile(
        self,
        topology: NoetriumUnit,
        *,
        claim_candidates: Mapping[
            str,
            Callable[[AuthoritySnapshot, int], tuple[NoetriumUnit, ...]],
        ],
        realization_specs: Mapping[
            str,
            Callable[[AuthoritySnapshot], ResourceRealizationSpec],
        ],
        providers: Mapping[str, PhysicalResourceProvider],
        desired_resource_ids: frozenset[str] | None = None,
    ) -> AuthoritySnapshot: ...


__all__ = ["PhysicalResourceProvider", "ResourceAuthorityPort"]
