from __future__ import annotations

import math
from threading import RLock
from time import time
from typing import cast

from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.container.api import (
    DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
    DockerContainerLeasePolicy,
    DockerContainerObservation,
    DockerContainerReconciliation,
    DockerManagedContainerPort,
    DockerReconcileStopPort,
    ManagedDockerContainerLease,
)
from noetrium_platform.infrastructure.resources.container.api.contracts import (
    LABEL_AUTHORITY,
    LABEL_ALLOCATION,
    LABEL_FENCING,
    LABEL_HOLDER,
    LABEL_LEASE,
    LABEL_OWNER_GENERATION,
    LABEL_RUNTIME,
)
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


class DockerContainerLeaseConflict(RuntimeError):
    pass


class DockerContainerLeaseAuthority:
    """Resource-fenced lifecycle authority for physical Docker containers.

    A Resource lease is acquired before Docker creation. Physical removal
    always precedes logical release. Reconciliation only touches CONTAINER
    leases and only containers carrying the exact Noetrium managed label.
    """

    def __init__(
        self,
        *,
        ownership: ResourceOwnershipPort,
        leases: ResourceLeasePort,
        runtime: DockerManagedContainerPort,
        authority_id: str,
        owner_generation_id: str,
        policy: DockerContainerLeasePolicy = DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
        reconcile_on_start: bool = True,
    ) -> None:
        for field_name, value in (
            ("authority_id", authority_id),
            ("owner_generation_id", owner_generation_id),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"Docker container {field_name} must be lowercase sha256"
                )
        self.ownership = ownership
        self.leases = leases
        self.runtime = runtime
        self.authority_id = authority_id
        self.owner_generation_id = owner_generation_id
        self.policy = policy
        self._confirmed_lock = RLock()
        self._confirmed_handles: dict[str, ManagedDockerContainerLease] = {}
        # Opportunistic warm cache only. Durable lease/fencing remains authority.
        # After process restart this map is empty, so reconcile treats any
        # stopped physical container as stale and removes it fail-closed.
        self._parked_handles: dict[str, ManagedDockerContainerLease] = {}
        if reconcile_on_start:
            self.reconcile()

    @staticmethod
    def _resource(allocation_id: str) -> ResourceIdentity:
        return ResourceIdentity(ResourceKind.CONTAINER, allocation_id)

    @staticmethod
    def _lease_id(allocation_id: str) -> str:
        return f"container:{allocation_id}"

    def _name(self, allocation_id: str, fencing_token: int) -> str:
        digest = canonical_digest(
            {
                "authority_id": self.authority_id,
                "owner_generation_id": self.owner_generation_id,
                "allocation_id": allocation_id,
                "fencing_token": fencing_token,
            }
        )
        return f"noetrium-{digest[:20]}-{fencing_token}"

    @staticmethod
    def _runtime_digest_valid(value: str | None) -> bool:
        return (
            type(value) is str
            and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value)
        )

    def _require_handle_authority(
        self,
        handle: ManagedDockerContainerLease,
    ) -> None:
        if type(handle) is not ManagedDockerContainerLease:
            raise TypeError("managed Docker lifecycle requires ManagedDockerContainerLease")
        if handle.authority_id != self.authority_id:
            raise DockerContainerLeaseConflict(
                "managed Docker handle belongs to a different authority"
            )
        if handle.owner_generation_id != self.owner_generation_id:
            raise DockerContainerLeaseConflict(
                "managed Docker handle belongs to a stale owner generation"
            )

    @staticmethod
    def _matches_exact_generation(
        handle: ManagedDockerContainerLease,
        observed: DockerContainerObservation,
    ) -> bool:
        expected = dict(handle.labels)
        return (
            observed.image == handle.image
            and all(observed.labels.get(key) == value for key, value in expected.items())
        )

    @classmethod
    def _validate_observation(
        cls,
        handle: ManagedDockerContainerLease,
        observed: DockerContainerObservation,
    ) -> None:
        expected = dict(handle.labels)
        for key, value in expected.items():
            if observed.labels.get(key) != value:
                raise DockerContainerLeaseConflict(
                    f"managed Docker label drift: {key}"
                )
        if observed.image != handle.image:
            raise DockerContainerLeaseConflict("managed Docker image drift")
        if observed.name != handle.container_name:
            raise DockerContainerLeaseConflict("managed Docker name drift")

    def _exact_physical_candidates(
        self,
        handle: ManagedDockerContainerLease,
    ) -> tuple[DockerContainerObservation, ...]:
        return tuple(
            observed
            for observed in self.runtime.list_managed()
            if self._matches_exact_generation(handle, observed)
        )

    def _remember_confirmed(
        self,
        handle: ManagedDockerContainerLease,
    ) -> None:
        with self._confirmed_lock:
            self._confirmed_handles[handle.lease.lease_id] = handle

    def _forget_confirmed(
        self,
        handle: ManagedDockerContainerLease,
    ) -> None:
        with self._confirmed_lock:
            current = self._confirmed_handles.get(handle.lease.lease_id)
            if (
                current is not None
                and current.lease.fencing_token == handle.lease.fencing_token
            ):
                self._confirmed_handles.pop(handle.lease.lease_id, None)

    def _confirmed_snapshot(self) -> tuple[ManagedDockerContainerLease, ...]:
        with self._confirmed_lock:
            return tuple(self._confirmed_handles.values())


    def _parked_exact(
        self,
        *,
        lease_id: str,
        fencing_token: int,
    ) -> bool:
        with self._confirmed_lock:
            parked = self._parked_handles.get(lease_id)
            return (
                parked is not None
                and parked.lease.fencing_token == fencing_token
            )


    def park(
        self,
        handle: ManagedDockerContainerLease,
        *,
        timeout_seconds: float = 30.0,
    ) -> DockerContainerObservation:
        self._require_handle_authority(handle)
        current = self.leases.get(handle.lease.lease_id)
        if (
            current.state is not LeaseState.ACTIVE
            or current.fencing_token != handle.lease.fencing_token
        ):
            raise DockerContainerLeaseConflict(
                "cannot park stale Docker lease generation"
            )
        observed = self.runtime.inspect(handle.container_name)
        if observed is None:
            raise DockerContainerLeaseConflict(
                "cannot park missing Docker container"
            )
        self._validate_observation(handle, observed)

        # Publish current-generation parking intent before physical stop.
        # Reconcile may observe the container immediately after it stops.
        with self._confirmed_lock:
            parked = self._parked_handles.get(handle.lease.lease_id)
            if (
                parked is not None
                and parked.lease.fencing_token != handle.lease.fencing_token
            ):
                raise DockerContainerLeaseConflict(
                    "cannot park over a different Docker lease generation"
                )
            self._parked_handles[handle.lease.lease_id] = handle
        try:
            if observed.running:
                observed = self.runtime.stop(
                    observed.container_id,
                    timeout_seconds=timeout_seconds,
                )
            self._validate_observation(handle, observed)
            if observed.running:
                raise DockerContainerLeaseConflict(
                    "Docker park did not quiesce physical container"
                )
            current = self.leases.get(handle.lease.lease_id)
            if (
                current.state is not LeaseState.ACTIVE
                or current.fencing_token != handle.lease.fencing_token
            ):
                raise DockerContainerLeaseConflict(
                    "Docker lease generation changed while parking"
                )
            return observed
        except BaseException:
            with self._confirmed_lock:
                parked = self._parked_handles.get(handle.lease.lease_id)
                if (
                    parked is not None
                    and parked.lease.fencing_token == handle.lease.fencing_token
                ):
                    self._parked_handles.pop(handle.lease.lease_id, None)
            raise


    def resume(
        self,
        handle: ManagedDockerContainerLease,
        *,
        timeout_seconds: float = 30.0,
    ) -> DockerContainerObservation:
        self._require_handle_authority(handle)
        if not self._parked_exact(
            lease_id=handle.lease.lease_id,
            fencing_token=handle.lease.fencing_token,
        ):
            raise DockerContainerLeaseConflict(
                "Docker resume requires current-generation parked handle"
            )
        current = self.leases.get(handle.lease.lease_id)
        if (
            current.state is not LeaseState.ACTIVE
            or current.fencing_token != handle.lease.fencing_token
        ):
            raise DockerContainerLeaseConflict(
                "cannot resume stale Docker lease generation"
            )
        observed = self.runtime.inspect(handle.container_name)
        if observed is None:
            raise DockerContainerLeaseConflict(
                "cannot resume missing parked Docker container"
            )
        self._validate_observation(handle, observed)
        if not observed.running:
            observed = self.runtime.start(
                observed.container_id,
                timeout_seconds=timeout_seconds,
            )
        self._validate_observation(handle, observed)
        if not observed.running:
            raise DockerContainerLeaseConflict(
                "Docker resume did not restore running container"
            )
        with self._confirmed_lock:
            self._parked_handles.pop(handle.lease.lease_id, None)
        self._remember_confirmed(handle)
        return observed

    def reserve(
        self,
        *,
        allocation_id: str,
        holder_scope: ScopeIdentity,
        image: str,
        runtime_identity_digest: str,
    ) -> ManagedDockerContainerLease:
        if not allocation_id.strip() or not image.strip():
            raise ValueError("managed Docker reservation identity is required")
        if not self._runtime_digest_valid(runtime_identity_digest):
            raise ValueError(
                "managed Docker runtime identity must be lowercase sha256"
            )

        self.reconcile()
        foreign = tuple(
            observed
            for observed in self.runtime.list_managed()
            if observed.labels.get(LABEL_ALLOCATION) == allocation_id
            and observed.labels.get(LABEL_OWNER_GENERATION)
            != self.owner_generation_id
        )
        if foreign:
            raise DockerContainerLeaseConflict(
                "managed Docker allocation is quarantined by another owner "
                "generation and requires exclusive recovery"
            )
        resource = self._resource(allocation_id)
        self.ownership.register_owner(
            ResourceOwner(
                resource,
                PLATFORM_SCOPE,
                ResourceOwnership.PLATFORM_MANAGED,
            )
        )
        lease = self.leases.acquire(
            ResourceLease(
                lease_id=self._lease_id(allocation_id),
                resource=resource,
                holder_scope=holder_scope,
                purpose=f"managed-docker-container:{allocation_id}",
            ),
            ttl_seconds=self.policy.ttl_seconds,
        )
        handle = ManagedDockerContainerLease(
            allocation_id,
            holder_scope,
            image,
            runtime_identity_digest,
            self.authority_id,
            self.owner_generation_id,
            self._name(allocation_id, lease.fencing_token),
            lease,
        )

        observed = self.runtime.inspect(handle.container_name)
        if observed is None:
            return handle
        try:
            self._validate_observation(handle, observed)
        except DockerContainerLeaseConflict:
            self.leases.release(
                lease.lease_id,
                fencing_token=lease.fencing_token,
            )
            raise
        if not observed.running:
            # A stopped container cannot remain the owner of an active
            # generation. End it now so the next reserve advances fencing.
            self.runtime.remove(observed.container_id, force=True)
            self.leases.release(lease.lease_id, fencing_token=lease.fencing_token)
            return self.reserve(
                allocation_id=allocation_id,
                holder_scope=holder_scope,
                image=image,
                runtime_identity_digest=runtime_identity_digest,
            )
        raise DockerContainerLeaseConflict(
            "managed Docker allocation already has a live container in the "
            "current controller generation"
        )

    def observe_exact(
        self,
        handle: ManagedDockerContainerLease,
    ) -> DockerContainerObservation | None:
        """Resolve one exact physical container generation from durable labels."""

        self._require_handle_authority(handle)
        named = self.runtime.inspect(handle.container_name)
        if named is not None and self._matches_exact_generation(handle, named):
            self._validate_observation(handle, named)
            return named

        candidates = self._exact_physical_candidates(handle)
        if len(candidates) > 1:
            raise DockerContainerLeaseConflict(
                "managed Docker generation maps to multiple physical containers"
            )
        if candidates:
            return candidates[0]
        if named is not None:
            raise DockerContainerLeaseConflict(
                "managed Docker name was reused before exact generation converged"
            )
        return None

    def recover(
        self,
        *,
        allocation_id: str,
        image: str,
        runtime_identity_digest: str,
    ) -> ManagedDockerContainerLease | None:
        """Rebuild the current-generation handle from ResourceLease + Docker truth.

        No container-specific registry is consulted or created. A missing active
        lease means there is no recoverable generation. Physical absence with an
        active lease remains representable so the caller can reconcile/release
        that fenced logical generation.
        """

        if not allocation_id.strip() or not image.strip():
            raise ValueError("managed Docker recovery identity is required")
        if not self._runtime_digest_valid(runtime_identity_digest):
            raise ValueError(
                "managed Docker runtime identity must be lowercase sha256"
            )
        try:
            lease = self.leases.get(self._lease_id(allocation_id))
        except KeyError:
            return None
        if lease.state is not LeaseState.ACTIVE:
            return None
        resource = self._resource(allocation_id)
        if lease.resource != resource:
            raise DockerContainerLeaseConflict(
                "managed Docker recovery resource identity drifted"
            )

        handle = ManagedDockerContainerLease(
            allocation_id,
            lease.holder_scope,
            image,
            runtime_identity_digest,
            self.authority_id,
            self.owner_generation_id,
            self._name(allocation_id, lease.fencing_token),
            lease,
        )
        observed = self.observe_exact(handle)
        if observed is not None and observed.running:
            self._remember_confirmed(handle)
        return handle

    def docker_run_prefix(
        self,
        handle: ManagedDockerContainerLease,
    ) -> tuple[str, ...]:
        self._require_handle_authority(handle)
        # Read/recovery Docker commands remain available under hard pressure,
        # but every new physical container generation must cross the dedicated
        # storage-expansion admission group immediately before process launch.
        self.runtime.assert_expansion_admissible()
        return (
            self.runtime.docker_executable,
            "run",
            *handle.docker_run_options(),
        )

    def confirm_running(
        self,
        handle: ManagedDockerContainerLease,
        *,
        timeout_seconds: float = 10.0,
    ) -> DockerContainerObservation:
        self._require_handle_authority(handle)
        observed = self.runtime.wait_running(
            handle.container_name,
            timeout_seconds=timeout_seconds,
        )
        self._validate_observation(handle, observed)
        with self._confirmed_lock:
            self._parked_handles.pop(handle.lease.lease_id, None)
        self._remember_confirmed(handle)
        return observed

    def renew(
        self,
        handle: ManagedDockerContainerLease,
    ) -> ManagedDockerContainerLease:
        self._require_handle_authority(handle)
        renewed = self.leases.renew(
            handle.lease.lease_id,
            fencing_token=handle.lease.fencing_token,
            ttl_seconds=self.policy.ttl_seconds,
        )
        renewed_handle = ManagedDockerContainerLease(
            handle.allocation_id,
            handle.holder_scope,
            handle.image,
            handle.runtime_identity_digest,
            handle.authority_id,
            handle.owner_generation_id,
            handle.container_name,
            renewed,
        )
        with self._confirmed_lock:
            current = self._confirmed_handles.get(handle.lease.lease_id)
            if (
                current is not None
                and current.lease.fencing_token == handle.lease.fencing_token
            ):
                self._confirmed_handles[handle.lease.lease_id] = renewed_handle
            parked = self._parked_handles.get(handle.lease.lease_id)
            if (
                parked is not None
                and parked.lease.fencing_token == handle.lease.fencing_token
            ):
                self._parked_handles[handle.lease.lease_id] = renewed_handle
        return renewed_handle

    def renew_many(
        self,
        handles: tuple[ManagedDockerContainerLease, ...],
    ) -> tuple[ManagedDockerContainerLease, ...]:
        return tuple(self.renew(handle) for handle in handles)

    def release(self, handle: ManagedDockerContainerLease) -> ResourceLease:
        self._require_handle_authority(handle)
        # The deterministic name is only a lookup hint, not physical identity:
        # Docker permits external rename and later name reuse. Resolve the exact
        # generation by immutable managed labels before any destructive effect.
        named = self.runtime.inspect(handle.container_name)
        target: DockerContainerObservation | None = None
        if named is not None and self._matches_exact_generation(handle, named):
            self._validate_observation(handle, named)
            target = named
        else:
            candidates = self._exact_physical_candidates(handle)
            if len(candidates) > 1:
                raise DockerContainerLeaseConflict(
                    "managed Docker generation maps to multiple physical containers"
                )
            if candidates:
                target = candidates[0]
            elif named is not None:
                # The old name now resolves to a different physical generation,
                # but absence of the exact target cannot be proven from that
                # name. Keep the durable lease fenced rather than freeing it.
                raise DockerContainerLeaseConflict(
                    "managed Docker name was reused before exact generation converged"
                )

        if target is not None:
            self.runtime.remove(target.container_id, force=True)
            if self.runtime.inspect(target.container_id) is not None:
                raise DockerContainerLeaseConflict(
                    "managed Docker container survived release"
                )
        # Physical effect first. Never publish logical release while the exact
        # owned container may still exist. Generic lease release is itself
        # fenced, so a delayed close cannot release a replacement generation.
        released = self.leases.release(
            handle.lease.lease_id,
            fencing_token=handle.lease.fencing_token,
        )
        with self._confirmed_lock:
            parked = self._parked_handles.get(handle.lease.lease_id)
            if (
                parked is not None
                and parked.lease.fencing_token == handle.lease.fencing_token
            ):
                self._parked_handles.pop(handle.lease.lease_id, None)
        self._forget_confirmed(handle)
        return released

    def reconcile(
        self,
        *,
        now: float | None = None,
    ) -> DockerContainerReconciliation:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("Docker reconciliation time must be finite")

        self.leases.reconcile_expired(
            now=now_epoch_s,
            resource_kind=ResourceKind.CONTAINER,
        )
        removed: list[str] = []
        released: list[str] = []
        quarantined: list[str] = []

        for observed in self.runtime.list_managed():
            labels = observed.labels
            allocation_id = labels.get(LABEL_ALLOCATION)
            lease_id = labels.get(LABEL_LEASE)
            fencing_raw = labels.get(LABEL_FENCING)
            runtime_digest = labels.get(LABEL_RUNTIME)
            authority_id = labels.get(LABEL_AUTHORITY)
            owner_generation_id = labels.get(LABEL_OWNER_GENERATION)
            holder_key = labels.get(LABEL_HOLDER)
            lease: ResourceLease | None = None
            fencing: int | None = None

            if owner_generation_id != self.owner_generation_id:
                quarantined.append(observed.container_id)
                continue

            if allocation_id and lease_id and fencing_raw:
                try:
                    fencing = int(fencing_raw)
                    lease = self.leases.get(lease_id, now=now_epoch_s)
                except (KeyError, ValueError):
                    lease = None

            exact_resource = (
                lease is not None
                and allocation_id is not None
                and lease.resource == self._resource(allocation_id)
            )
            valid = (
                authority_id == self.authority_id
                and owner_generation_id == self.owner_generation_id
                and exact_resource
                and lease is not None
                and lease.state is LeaseState.ACTIVE
                and lease.fencing_token == fencing
                and holder_key == lease.holder_scope.key
                and self._runtime_digest_valid(runtime_digest)
                and (
                    observed.running
                    or (
                        fencing is not None
                        and self._parked_exact(
                            lease_id=lease.lease_id,
                            fencing_token=fencing,
                        )
                    )
                )
            )
            if valid:
                continue

            # This is a Noetrium-managed ephemeral container. Invalid fencing,
            # expired ownership, malformed labels, or a stopped process makes
            # the physical object non-authoritative and safe to reap.
            self.runtime.remove(observed.container_id, force=True)
            if self.runtime.inspect(observed.container_id) is not None:
                raise DockerContainerLeaseConflict(
                    "managed Docker reconcile removal was not observable"
                )
            removed.append(observed.container_id)

            # If the lease is still active and really belongs to this container
            # allocation, end the old generation after physical removal.
            if (
                exact_resource
                and lease is not None
                and lease.state is LeaseState.ACTIVE
            ):
                released_lease = self.leases.release(lease.lease_id, fencing_token=lease.fencing_token)
                if released_lease.state is not LeaseState.RELEASED:
                    raise DockerContainerLeaseConflict(
                        "managed Docker reconcile failed to release lease"
                    )
                released.append(lease.lease_id)
                with self._confirmed_lock:
                    current = self._confirmed_handles.get(lease.lease_id)
                    if (
                        current is not None
                        and current.lease.fencing_token == lease.fencing_token
                    ):
                        self._confirmed_handles.pop(lease.lease_id, None)
                    parked = self._parked_handles.get(lease.lease_id)
                    if (
                        parked is not None
                        and parked.lease.fencing_token == lease.fencing_token
                    ):
                        self._parked_handles.pop(lease.lease_id, None)

        # A confirmed current-generation container that disappears entirely
        # cannot be discovered by list_managed(). Its durable lease must not
        # remain active and be reused with the same fencing token/name.
        for handle in self._confirmed_snapshot():
            try:
                lease = self.leases.get(handle.lease.lease_id, now=now_epoch_s)
            except KeyError:
                self._forget_confirmed(handle)
                continue
            if (
                lease.state is not LeaseState.ACTIVE
                or lease.fencing_token != handle.lease.fencing_token
            ):
                self._forget_confirmed(handle)
                continue

            candidates = self._exact_physical_candidates(handle)
            if len(candidates) > 1:
                raise DockerContainerLeaseConflict(
                    "confirmed Docker generation maps to multiple physical containers"
                )
            if candidates:
                continue

            released_lease = self.leases.release(
                lease.lease_id,
                fencing_token=lease.fencing_token,
                now=now_epoch_s,
            )
            if released_lease.state is not LeaseState.RELEASED:
                raise DockerContainerLeaseConflict(
                    "confirmed missing Docker generation failed to release lease"
                )
            released.append(lease.lease_id)
            self._forget_confirmed(handle)

        return DockerContainerReconciliation(
            tuple(sorted(set(removed))),
            tuple(sorted(set(released))),
            tuple(sorted(set(quarantined))),
        )

    def shutdown_cleanup(
        self,
        *,
        now: float | None = None,
    ) -> DockerContainerReconciliation:
        """Remove every managed physical container, then end container leases.

        This is only for an exclusively owned, quiesced platform runtime. The
        physical effect is completed before logical ownership is released.
        """

        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("Docker shutdown cleanup time must be finite")

        removed: list[str] = []
        for observed in self.runtime.list_managed():
            self.runtime.remove(observed.container_id, force=True)
            if self.runtime.inspect(observed.container_id) is not None:
                raise DockerContainerLeaseConflict(
                    "managed Docker container survived shutdown cleanup"
                )
            removed.append(observed.container_id)

        released: list[str] = []
        for lease in self.leases.active_leases(
            resource_kind=ResourceKind.CONTAINER,
            now=now_epoch_s,
        ):
            released_lease = self.leases.release(
                lease.lease_id,
                fencing_token=lease.fencing_token,
                now=now_epoch_s,
            )
            if released_lease.state is not LeaseState.RELEASED:
                raise DockerContainerLeaseConflict(
                    "managed Docker shutdown failed to release lease"
                )
            released.append(lease.lease_id)

        with self._confirmed_lock:
            self._confirmed_handles.clear()
            self._parked_handles.clear()
        return DockerContainerReconciliation(
            tuple(sorted(set(removed))),
            tuple(sorted(set(released))),
        )

    def run_reconciler(
        self,
        *,
        interval_seconds: float,
        stop: DockerReconcileStopPort,
        max_cycles: int | None = None,
    ) -> DockerContainerReconciliation:
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(float(interval_seconds))
            or float(interval_seconds) <= 0
        ):
            raise ValueError(
                "Docker reconciliation interval must be finite and positive"
            )
        if max_cycles is not None and (
            isinstance(max_cycles, bool)
            or not isinstance(max_cycles, int)
            or max_cycles <= 0
        ):
            raise ValueError("Docker reconciliation max_cycles must be positive")
        cycles = 0
        latest = DockerContainerReconciliation(())
        while True:
            latest = self.reconcile()
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                return latest
            if stop.wait(float(interval_seconds)):
                return latest

__all__ = ["DockerContainerLeaseAuthority", "DockerContainerLeaseConflict"]
