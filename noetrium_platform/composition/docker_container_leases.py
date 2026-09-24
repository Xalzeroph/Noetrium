from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Lock
from time import time
from uuid import uuid4
from typing import Protocol

from noetrium_platform.capabilities.environment.providers.docker_containers import (
    DockerContainerObservation,
    DockerManagedContainerPort,
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE, ScopeIdentity
from noetrium_platform.foundation.kernel.concurrency.api import (
    HeartbeatSchedulerPort,
    HeartbeatSpec,
    ScheduledTaskHandlePort,
    TaskContextPort,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
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


_LABEL_ALLOCATION = "io.noetrium.allocation-id"
_LABEL_LEASE = "io.noetrium.lease-id"
_LABEL_FENCING = "io.noetrium.fencing-token"
_LABEL_RUNTIME = "io.noetrium.runtime-identity"
_LABEL_HOLDER = "io.noetrium.holder-scope"


class DockerReconcileStopPort(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...


@dataclass(frozen=True, slots=True)
class DockerContainerLeasePolicy:
    ttl_seconds: float = 120.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.ttl_seconds)) or self.ttl_seconds <= 0:
            raise ValueError("container lease ttl_seconds must be finite and > 0")
        if (
            not math.isfinite(float(self.renewal_interval_seconds))
            or self.renewal_interval_seconds <= 0
        ):
            raise ValueError(
                "container lease renewal_interval_seconds must be finite and > 0"
            )
        if self.renewal_interval_seconds >= self.ttl_seconds:
            raise ValueError("container lease renewal interval must be shorter than ttl")


DEFAULT_DOCKER_CONTAINER_LEASE_POLICY = DockerContainerLeasePolicy()


@dataclass(frozen=True, slots=True)
class ManagedDockerContainerLease:
    allocation_id: str
    holder_scope: ScopeIdentity
    image: str
    runtime_identity_digest: str
    container_name: str
    lease: ResourceLease

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.image.strip():
            raise ValueError("managed Docker container identity is incomplete")
        if (
            len(self.runtime_identity_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.runtime_identity_digest)
        ):
            raise ValueError("managed Docker runtime identity must be lowercase sha256")
        if self.lease.resource != ResourceIdentity(
            ResourceKind.CONTAINER, self.allocation_id
        ):
            raise ValueError("managed Docker resource identity drifted")
        if self.lease.holder_scope != self.holder_scope:
            raise ValueError("managed Docker holder scope drifted")
        if self.lease.state is not LeaseState.ACTIVE:
            raise ValueError("managed Docker lease must be active")

    @property
    def labels(self) -> tuple[tuple[str, str], ...]:
        return (
            (MANAGED_CONTAINER_LABEL, MANAGED_CONTAINER_LABEL_VALUE),
            (_LABEL_ALLOCATION, self.allocation_id),
            (_LABEL_LEASE, self.lease.lease_id),
            (_LABEL_FENCING, str(self.lease.fencing_token)),
            (_LABEL_RUNTIME, self.runtime_identity_digest),
            (_LABEL_HOLDER, self.holder_scope.key),
        )

    def docker_run_options(self) -> tuple[str, ...]:
        values: list[str] = ["--name", self.container_name]
        for key, value in self.labels:
            values.extend(("--label", f"{key}={value}"))
        return tuple(values)


@dataclass(frozen=True, slots=True)
class DockerContainerReconciliation:
    removed_container_ids: tuple[str, ...]


class DockerContainerLeaseConflict(RuntimeError):
    pass


class DockerContainerLeaseAuthority:
    """Resource-fenced lifecycle for physical Docker containers.

    The Resource lease is acquired before Docker creation. A container is
    released only after exact physical removal. Startup reconciliation scans
    only Noetrium-managed labels and removes containers whose lease is absent,
    expired, released, or fencing-mismatched.
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
    def _name(allocation_id: str, fencing_token: int) -> str:
        digest = canonical_digest(
            {"allocation_id": allocation_id, "fencing_token": fencing_token}
        )
        return f"noetrium-{digest[:20]}-{fencing_token}"

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
        if (
            len(runtime_identity_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in runtime_identity_digest)
        ):
            raise ValueError("managed Docker runtime identity must be lowercase sha256")
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
                lease_id=f"container:{allocation_id}:{uuid4().hex}",
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
        if self.runtime.inspect(handle.container_name) is not None:
            self.leases.release(lease.lease_id)
            raise DockerContainerLeaseConflict(
                "managed Docker container name already exists for new fencing generation"
            )
        return handle

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

    def docker_run_prefix(
        self,
        handle: ManagedDockerContainerLease,
    ) -> tuple[str, ...]:
        """Return the only supported launch prefix for this fenced container."""

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
        # may still be alive.
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
        self.leases.reconcile_expired(now=now_epoch_s)
        removed: list[str] = []
        for observed in self.runtime.list_managed():
            labels = observed.labels
            allocation_id = labels.get(_LABEL_ALLOCATION)
            lease_id = labels.get(_LABEL_LEASE)
            fencing_raw = labels.get(_LABEL_FENCING)
            valid = False
            if allocation_id and lease_id and fencing_raw:
                try:
                    fencing = int(fencing_raw)
                    lease = self.leases.get(lease_id, now=now_epoch_s)
                except (KeyError, ValueError):
                    lease = None
                if lease is not None:
                    valid = (
                        lease.state is LeaseState.ACTIVE
                        and lease.resource == self._resource(allocation_id)
                        and lease.fencing_token == fencing
                    )
            if valid:
                continue
            self.runtime.remove(observed.container_id, force=True)
            removed.append(observed.container_id)
        return DockerContainerReconciliation(tuple(sorted(set(removed))))

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


class DockerContainerLeaseHeartbeatGuard:
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
            raise ValueError("container lease heartbeat allocation ids must be unique")
        if not lane_id.strip():
            raise ValueError("container lease heartbeat lane_id required")
        if lane_capacity is not None and lane_capacity <= 0:
            raise ValueError("container lease heartbeat lane capacity must be positive")
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
                f"container lease heartbeat failed: {type(exc).__name__}: {exc}"
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


class DockerContainerLeaseHeartbeatFactory:
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
    "DEFAULT_DOCKER_CONTAINER_LEASE_POLICY",
    "DockerContainerLeaseAuthority",
    "DockerContainerLeaseConflict",
    "DockerContainerLeaseHeartbeatError",
    "DockerContainerLeaseHeartbeatFactory",
    "DockerContainerLeaseHeartbeatGuard",
    "DockerContainerLeasePolicy",
    "DockerContainerReconciliation",
    "DockerReconcileStopPort",
    "ManagedDockerContainerLease",
]
