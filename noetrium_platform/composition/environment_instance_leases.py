from __future__ import annotations

from dataclasses import dataclass
import math
from time import time

from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentBinding,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentInstanceAcquisition,
    EnvironmentInstanceState,
    ExecutionEnvironmentCatalogPort,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeasePort,
    ResourceOwner,
    ResourceOwnership,
    ResourceOwnershipPort,
)


@dataclass(frozen=True, slots=True)
class EnvironmentInstanceLeasePolicy:
    ttl_seconds: float = 120.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.ttl_seconds)) or self.ttl_seconds <= 0:
            raise ValueError("environment instance lease ttl_seconds must be finite and > 0")
        if (
            not math.isfinite(float(self.renewal_interval_seconds))
            or self.renewal_interval_seconds <= 0
        ):
            raise ValueError(
                "environment instance lease renewal_interval_seconds must be finite and > 0"
            )
        if self.renewal_interval_seconds >= self.ttl_seconds:
            raise ValueError(
                "environment instance lease renewal interval must be shorter than ttl"
            )


DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY = EnvironmentInstanceLeasePolicy()


@dataclass(frozen=True, slots=True)
class EnvironmentInstanceLeaseHandle:
    acquisition: EnvironmentInstanceAcquisition
    lease: ResourceLease

    def __post_init__(self) -> None:
        if self.lease.resource != _instance_resource(self.acquisition.instance.instance_id):
            raise ValueError("environment instance lease resource identity drifted")
        if self.lease.holder_scope != self.acquisition.binding.scope:
            raise ValueError("environment instance lease holder scope drifted")
        if self.lease.state is not LeaseState.ACTIVE:
            raise ValueError("environment instance lease handle requires an active lease")

    @property
    def instance(self) -> EnvironmentInstance:
        return self.acquisition.instance

    @property
    def binding(self) -> EnvironmentBinding:
        return self.acquisition.binding


@dataclass(frozen=True, slots=True)
class EnvironmentInstanceReconciliation:
    dirtied_instance_ids: tuple[str, ...]
    released_orphan_lease_ids: tuple[str, ...]


def _instance_resource(instance_id: str) -> ResourceIdentity:
    return ResourceIdentity(ResourceKind.EXECUTION_ENVIRONMENT, instance_id)


def _lease_id(instance: EnvironmentInstance) -> str:
    return f"environment-instance:{instance.instance_id}:generation:{instance.generation}"


class EnvironmentInstanceLeaseAuthority:
    """Cross-authority coordinator for reusable environment checkout leases.

    Environment remains authoritative for CLEAN/IN_USE/DIRTY/DESTROYED and
    bindings. Resource remains authoritative for TTL, fencing and lease
    ownership. Crash recovery never promotes an uncertain instance to CLEAN:
    a missing/expired lease converts the instance to DIRTY and removes stale
    bindings; a provider must later destroy or explicitly reset it.
    """

    def __init__(
        self,
        *,
        catalog: ExecutionEnvironmentCatalogPort,
        ownership: ResourceOwnershipPort,
        leases: ResourceLeasePort,
        policy: EnvironmentInstanceLeasePolicy = DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
        reconcile_on_start: bool = True,
    ) -> None:
        self.catalog = catalog
        self.ownership = ownership
        self.leases = leases
        self.policy = policy
        if reconcile_on_start:
            self.reconcile()

    def _binding_rows(self, instance_id: str) -> tuple[EnvironmentBinding, ...]:
        return tuple(
            row for row in self.catalog.bindings() if row.instance_id == instance_id
        )

    def _instance(self, instance_id: str) -> EnvironmentInstance:
        for row in self.catalog.instances():
            if row.instance_id == instance_id:
                return row
        raise KeyError(instance_id)

    def _acquire_lease(
        self,
        acquisition: EnvironmentInstanceAcquisition,
    ) -> EnvironmentInstanceLeaseHandle:
        instance = acquisition.instance
        resource = _instance_resource(instance.instance_id)
        owner = ResourceOwner(
            resource,
            PLATFORM_SCOPE,
            ResourceOwnership.PLATFORM_MANAGED,
        )
        try:
            self.ownership.register_owner(owner)
            lease = self.leases.acquire(
                ResourceLease(
                    lease_id=_lease_id(instance),
                    resource=resource,
                    holder_scope=acquisition.binding.scope,
                    purpose=(
                        f"environment-instance:{instance.instance_id}:"
                        f"generation:{instance.generation}"
                    ),
                ),
                ttl_seconds=self.policy.ttl_seconds,
            )
        except BaseException:
            try:
                self.catalog.unbind(
                    acquisition.binding.role,
                    acquisition.binding.scope,
                )
            finally:
                self.catalog.mark_instance_dirty(instance.instance_id)
            raise
        return EnvironmentInstanceLeaseHandle(acquisition, lease)

    def acquire_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        binding_id: str,
        role: str,
        scope: ScopeIdentity,
    ) -> EnvironmentInstanceLeaseHandle:
        self.reconcile()
        acquisition = self.catalog.acquire_reusable_instance(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            materialization_digest,
            binding_id=binding_id,
            role=role,
            scope=scope,
        )
        return self._acquire_lease(acquisition)

    def recover_reusable_instance(
        self,
        profile_id: str,
        profile_revision: str,
        runtime_identity_digest: str,
        materialization_digest: str,
        *,
        role: str,
        scope: ScopeIdentity,
    ) -> EnvironmentInstanceLeaseHandle:
        old_binding = self.catalog.binding(role, scope)
        old_instance = self._instance(old_binding.instance_id)
        acquisition = self.catalog.recover_reusable_instance(
            profile_id,
            profile_revision,
            runtime_identity_digest,
            materialization_digest,
            role=role,
            scope=scope,
        )
        handle = self._acquire_lease(acquisition)
        # Recovery migrates the catalog binding to a fresh CLEAN generation, but
        # it does not prove that the old physical environment has converged.
        # Keep every active lease for the abandoned generation fenced until it
        # expires naturally or an exclusive shutdown/recovery path proves that
        # physical ownership is gone. Releasing it here would make logical
        # capacity reusable underneath a potentially live old provider.
        _ = old_instance
        return handle

    def renew(
        self,
        handle: EnvironmentInstanceLeaseHandle,
    ) -> EnvironmentInstanceLeaseHandle:
        current = self._instance(handle.instance.instance_id)
        if (
            current.state is not EnvironmentInstanceState.IN_USE
            or current.generation != handle.instance.generation
        ):
            raise RuntimeError(
                "environment instance generation is no longer authoritative"
            )
        renewed = self.leases.renew(
            handle.lease.lease_id,
            fencing_token=handle.lease.fencing_token,
            ttl_seconds=self.policy.ttl_seconds,
        )
        return EnvironmentInstanceLeaseHandle(handle.acquisition, renewed)

    def renew_many(
        self,
        handles: tuple[EnvironmentInstanceLeaseHandle, ...],
    ) -> tuple[EnvironmentInstanceLeaseHandle, ...]:
        return tuple(self.renew(handle) for handle in handles)

    def release(
        self,
        handle: EnvironmentInstanceLeaseHandle,
        *,
        cleanliness: EnvironmentCleanlinessProof | None = None,
    ) -> EnvironmentInstance:
        current = self._instance(handle.instance.instance_id)
        if current.generation != handle.instance.generation:
            raise RuntimeError(
                "environment instance generation is no longer authoritative"
            )
        if current.state not in {
            EnvironmentInstanceState.IN_USE,
            EnvironmentInstanceState.DIRTY,
        }:
            raise RuntimeError(
                "environment instance generation is no longer releasable"
            )

        rows = self._binding_rows(handle.instance.instance_id)
        if rows and {row.scope for row in rows} != {handle.binding.scope}:
            raise RuntimeError("environment instance binding scope drifted")
        if (
            current.state is EnvironmentInstanceState.IN_USE
            and rows
            and handle.binding not in rows
            and any(row.role == handle.binding.role for row in rows)
        ):
            raise RuntimeError("environment instance binding generation drifted")

        # A lease owns the whole instance generation, not one role.  Unbinding
        # may partially succeed before a crash/failure, so retries accept the
        # exact same DIRTY generation with zero or fewer remaining bindings.
        for row in rows:
            self.catalog.unbind(row.role, row.scope)

        try:
            self.leases.release(
                handle.lease.lease_id,
                fencing_token=handle.lease.fencing_token,
            )
        except BaseException:
            # Once release is uncertain this generation can never be promoted
            # back to CLEAN by the same caller-supplied proof.  DIRTY is the
            # recovery-safe carrier until provider reset/destroy proves closure.
            if self._instance(handle.instance.instance_id).state is not EnvironmentInstanceState.DIRTY:
                self.catalog.mark_instance_dirty(handle.instance.instance_id)
            raise

        if self.leases.active_for(_instance_resource(handle.instance.instance_id)):
            if self._instance(handle.instance.instance_id).state is not EnvironmentInstanceState.DIRTY:
                self.catalog.mark_instance_dirty(handle.instance.instance_id)
            raise RuntimeError(
                "environment instance lease remained active after release"
            )

        current = self._instance(handle.instance.instance_id)
        if current.state is EnvironmentInstanceState.DIRTY:
            return current
        return self.catalog.release_instance(
            handle.instance.instance_id,
            cleanliness=cleanliness,
        )

    def shutdown_cleanup(
        self,
        *,
        now: float | None = None,
    ) -> EnvironmentInstanceReconciliation:
        """Abandon every live environment generation fail-closed.

        Used only after the owning runtime is quiesced and exclusively fenced.
        Unknown/unfinished generations become DIRTY; none are promoted to CLEAN.
        """

        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("environment shutdown cleanup time must be finite")

        bindings = self.catalog.bindings()
        for row in bindings:
            self.catalog.unbind(row.role, row.scope)

        released: list[str] = []
        for lease in self.leases.active_leases(
            resource_kind=ResourceKind.EXECUTION_ENVIRONMENT,
        ):
            self.leases.release(lease.lease_id, fencing_token=lease.fencing_token)
            released.append(lease.lease_id)

        dirtied: list[str] = []
        for instance in self.catalog.instances():
            if instance.state is EnvironmentInstanceState.IN_USE:
                self.catalog.mark_instance_dirty(instance.instance_id)
                dirtied.append(instance.instance_id)

        return EnvironmentInstanceReconciliation(
            tuple(sorted(set(dirtied))),
            tuple(sorted(set(released))),
        )

    def reconcile(
        self,
        *,
        now: float | None = None,
    ) -> EnvironmentInstanceReconciliation:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("environment lease reconciliation time must be finite")
        self.leases.reconcile_expired(
            resource_kind=ResourceKind.EXECUTION_ENVIRONMENT,
        )
        dirtied: list[str] = []
        released: list[str] = []

        bindings = self.catalog.bindings()
        by_instance: dict[str, list[EnvironmentBinding]] = {}
        for binding in bindings:
            by_instance.setdefault(binding.instance_id, []).append(binding)

        for instance in self.catalog.instances():
            resource = _instance_resource(instance.instance_id)
            active = self.leases.active_for(resource)
            rows = tuple(by_instance.get(instance.instance_id, ()))
            if instance.state is EnvironmentInstanceState.IN_USE:
                expected_id = _lease_id(instance)
                valid = (
                    len(active) == 1
                    and active[0].lease_id == expected_id
                    and bool(rows)
                    and {row.scope for row in rows} == {active[0].holder_scope}
                    and active[0].state is LeaseState.ACTIVE
                )
                if valid:
                    continue
                for row in rows:
                    self.catalog.unbind(row.role, row.scope)
                # Ordinary reconciliation has no provider/process convergence
                # proof. Quarantine the generation by preserving any still-live
                # Resource lease; its holder can no longer renew successfully
                # once the catalog generation is DIRTY, so it will expire unless
                # an exclusive recovery path retires it first.
                self.catalog.mark_instance_dirty(instance.instance_id)
                dirtied.append(instance.instance_id)
                continue

            # CLEAN/DIRTY/DESTROYED catalog state cannot by itself prove that a
            # physical generation attached to an active lease has disappeared.
            # Remove stale bindings, but keep the lease fence. Only TTL expiry or
            # shutdown_cleanup() after global workload convergence may release it.
            for row in rows:
                self.catalog.unbind(row.role, row.scope)

        return EnvironmentInstanceReconciliation(
            tuple(sorted(set(dirtied))),
            tuple(sorted(set(released))),
        )

__all__ = [
    "DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY",
    "EnvironmentInstanceLeaseAuthority",
    "EnvironmentInstanceLeaseHandle",
    "EnvironmentInstanceLeasePolicy",
    "EnvironmentInstanceReconciliation",
]
