from __future__ import annotations

import math
from threading import Lock
from time import time
from typing import cast

from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.foundation.kernel.concurrency.api import (
    HeartbeatSchedulerPort,
    HeartbeatSpec,
    ScheduledTaskHandlePort,
    TaskContextPort,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.container.api import (
    DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
    DockerContainerLeaseGuardFactoryPort,
    DockerContainerLeaseGuardPort,
    DockerContainerLeasePolicy,
    DockerContainerObservation,
    DockerContainerReconciliation,
    DockerManagedContainerPort,
    DockerReconcileStopPort,
    ManagedDockerContainerLease,
)
from noetrium_platform.infrastructure.resources.container.api.contracts import (
    LABEL_ALLOCATION,
    LABEL_FENCING,
    LABEL_HOLDER,
    LABEL_LEASE,
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
        policy: DockerContainerLeasePolicy = DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
        reconcile_on_start: bool = True,
    ) -> None:
        self.ownership = ownership
        self.leases = leases
        self.runtime = runtime
        self.policy = policy
        if reconcile_on_start:
            self.reconcile()

    @staticmethod
    def _resource(allocation_id: str) -> ResourceIdentity:
        return ResourceIdentity(ResourceKind.CONTAINER, allocation_id)

    @staticmethod
    def _lease_id(allocation_id: str) -> str:
        return f"container:{allocation_id}"

    @staticmethod
    def _name(allocation_id: str, fencing_token: int) -> str:
        digest = canonical_digest(
            {
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

    @staticmethod
    def _validate_observation(
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
            self._name(allocation_id, lease.fencing_token),
            lease,
        )

        observed = self.runtime.inspect(handle.container_name)
        if observed is None:
            return handle
        self._validate_observation(handle, observed)
        if not observed.running:
            # A stopped container cannot remain the owner of an active
            # generation. End it now so the next reserve advances fencing.
            self.runtime.remove(observed.container_id, force=True)
            self.leases.release(lease.lease_id)
            return self.reserve(
                allocation_id=allocation_id,
                holder_scope=holder_scope,
                image=image,
                runtime_identity_digest=runtime_identity_digest,
            )
        # Exact live replay after controller/process restart: adopt, do not
        # create a second container or advance the fencing generation.
        return handle

    def docker_run_prefix(
        self,
        handle: ManagedDockerContainerLease,
    ) -> tuple[str, ...]:
        return (
            self.runtime.docker_executable,
            "run",
            "--rm",
            *handle.docker_run_options(),
        )

    def confirm_running(
        self,
        handle: ManagedDockerContainerLease,
        *,
        timeout_seconds: float = 10.0,
    ) -> DockerContainerObservation:
        observed = self.runtime.wait_running(
            handle.container_name,
            timeout_seconds=timeout_seconds,
        )
        self._validate_observation(handle, observed)
        return observed

    def renew(
        self,
        handle: ManagedDockerContainerLease,
    ) -> ManagedDockerContainerLease:
        renewed = self.leases.renew(
            handle.lease.lease_id,
            fencing_token=handle.lease.fencing_token,
            ttl_seconds=self.policy.ttl_seconds,
        )
        return ManagedDockerContainerLease(
            handle.allocation_id,
            handle.holder_scope,
            handle.image,
            handle.runtime_identity_digest,
            handle.container_name,
            renewed,
        )

    def renew_many(
        self,
        handles: tuple[ManagedDockerContainerLease, ...],
    ) -> tuple[ManagedDockerContainerLease, ...]:
        return tuple(self.renew(handle) for handle in handles)

    def release(self, handle: ManagedDockerContainerLease) -> ResourceLease:
        # Physical effect first. Never publish logical release while a container
        # may still exist.
        self.runtime.remove(handle.container_name, force=True)
        if self.runtime.inspect(handle.container_name) is not None:
            raise DockerContainerLeaseConflict(
                "managed Docker container survived release"
            )
        return self.leases.release(handle.lease.lease_id)

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

        for observed in self.runtime.list_managed():
            labels = observed.labels
            allocation_id = labels.get(LABEL_ALLOCATION)
            lease_id = labels.get(LABEL_LEASE)
            fencing_raw = labels.get(LABEL_FENCING)
            runtime_digest = labels.get(LABEL_RUNTIME)
            holder_key = labels.get(LABEL_HOLDER)
            lease: ResourceLease | None = None
            fencing: int | None = None

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
                exact_resource
                and lease is not None
                and lease.state is LeaseState.ACTIVE
                and lease.fencing_token == fencing
                and holder_key == lease.holder_scope.key
                and self._runtime_digest_valid(runtime_digest)
                and observed.running
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
                released_lease = self.leases.release(lease.lease_id, now=now_epoch_s)
                if released_lease.state is not LeaseState.RELEASED:
                    raise DockerContainerLeaseConflict(
                        "managed Docker reconcile failed to release lease"
                    )
                released.append(lease.lease_id)

        return DockerContainerReconciliation(
            tuple(sorted(set(removed))),
            tuple(sorted(set(released))),
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
                now=now_epoch_s,
            )
            if released_lease.state is not LeaseState.RELEASED:
                raise DockerContainerLeaseConflict(
                    "managed Docker shutdown failed to release lease"
                )
            released.append(lease.lease_id)

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


class DockerContainerLeaseHeartbeatError(RuntimeError):
    pass


class DockerContainerLeaseHeartbeatGuard(DockerContainerLeaseGuardPort):
    def __init__(
        self,
        *,
        authority: DockerContainerLeaseAuthority,
        handles: tuple[ManagedDockerContainerLease, ...],
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: DockerContainerLeasePolicy = DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
    ) -> None:
        if not handles:
            raise ValueError("container lease heartbeat requires handles")
        allocation_ids = tuple(handle.allocation_id for handle in handles)
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError(
                "container lease heartbeat allocation ids must be unique"
            )
        if not lane_id.strip():
            raise ValueError("container lease heartbeat lane_id required")
        if lane_capacity is not None and lane_capacity <= 0:
            raise ValueError(
                "container lease heartbeat lane capacity must be positive"
            )
        self._authority = authority
        self._handles = handles
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy
        self._lock = Lock()
        self._scheduled: ScheduledTaskHandlePort | None = None
        self._closed = False

    @property
    def handles(self) -> tuple[ManagedDockerContainerLease, ...]:
        with self._lock:
            return self._handles

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise DockerContainerLeaseHeartbeatError(
                    "container lease heartbeat is closed"
                )
            if self._scheduled is not None:
                return
            allocation_ids = tuple(
                handle.allocation_id for handle in self._handles
            )
            self._scheduled = self._heartbeat_scheduler.register(
                self._task_group.group_id,
                HeartbeatSpec(
                    heartbeat_id="container-lease:" + ",".join(allocation_ids),
                    lane_id=self._lane_id,
                    interval_seconds=self._policy.renewal_interval_seconds,
                    initial_delay_seconds=self._policy.renewal_interval_seconds,
                    lane_capacity=self._lane_capacity,
                ),
                self._renew_once,
            )

    def _renew_once(self, context: TaskContextPort) -> None:
        context.checkpoint()
        with self._lock:
            handles = self._handles
        renewed = self._authority.renew_many(handles)
        with self._lock:
            self._handles = renewed
        context.checkpoint()

    def assert_healthy(self) -> None:
        with self._lock:
            scheduled = self._scheduled
        if scheduled is None:
            return
        try:
            scheduled.assert_healthy()
            self._task_group.assert_healthy()
        except BaseException as exc:
            raise DockerContainerLeaseHeartbeatError(
                "container lease heartbeat failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            scheduled = self._scheduled
        if scheduled is not None:
            scheduled.cancel()
        self.assert_healthy()


class DockerContainerLeaseHeartbeatFactory(DockerContainerLeaseGuardFactoryPort):
    def __init__(
        self,
        *,
        authority: DockerContainerLeaseAuthority,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: DockerContainerLeasePolicy = DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
    ) -> None:
        self._authority = authority
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy

    @property
    def policy(self) -> DockerContainerLeasePolicy:
        return self._policy

    def create(
        self,
        handles: tuple[ManagedDockerContainerLease, ...],
    ) -> DockerContainerLeaseHeartbeatGuard:
        return DockerContainerLeaseHeartbeatGuard(
            authority=self._authority,
            handles=handles,
            task_group=self._task_group,
            heartbeat_scheduler=self._heartbeat_scheduler,
            lane_id=self._lane_id,
            lane_capacity=self._lane_capacity,
            policy=self._policy,
        )


__all__ = [
    "DockerContainerLeaseAuthority",
    "DockerContainerLeaseConflict",
    "DockerContainerLeaseHeartbeatError",
    "DockerContainerLeaseHeartbeatFactory",
    "DockerContainerLeaseHeartbeatGuard",
]
