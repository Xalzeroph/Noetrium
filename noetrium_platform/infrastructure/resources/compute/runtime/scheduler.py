from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
from time import time

from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocation, ComputeHost, ComputePlacementUnavailable, ComputeRequirement,
    GpuDeviceStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, GpuSharingMode,
    HostRuntimeObserverPort, HostRuntimeSnapshot, HostRuntimeStatus,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseClockPort, LeaseState, ResourceIdentity, ResourceKind, ResourceLease, ResourceLeaseConflict,
    ResourceLeasePort, ResourceOwner, ResourceOwnership, ResourceOwnershipPort,
)
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    begin_immediate_sqlite_transaction,
    durable_sqlite_connection,
    rollback_sqlite_writer,
)
from noetrium_platform.infrastructure.resources.providers.sqlite_resource import (
    authoritative_lease_now,
    ensure_resource_schema,
)
from noetrium_platform.infrastructure.resources.lease.runtime.clock import LocalLeaseClock
from noetrium_platform.infrastructure.resources.providers.sqlite_lease_ops import (
    acquire_resource_lease, ensure_resource_owner, reconcile_expired_resource_leases,
    release_resource_lease, renew_resource_lease,
)

from .inventory import InMemoryComputeInventory


def _lease_now(now: float | None) -> float:
    value = time() if now is None else float(now)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("compute lease observation time must be finite and positive")
    return value


def _lease_expiry(ttl_seconds: float | None, now_epoch_s: float) -> float | None:
    if ttl_seconds is None:
        return None
    value = float(ttl_seconds)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("compute lease ttl_seconds must be finite and positive")
    return now_epoch_s + value


def _allocation_matches(
    allocation: ComputeAllocation, host: ComputeHost, scope: ScopeIdentity,
    placement_scope: ScopeIdentity | None, requirement: ComputeRequirement,
) -> bool:
    target_scope = scope if placement_scope is None else placement_scope
    if allocation.scope != scope or host.scope != target_scope or not host.enabled:
        return False
    if allocation.cpu_cores != requirement.cpu_cores or allocation.memory_bytes != requirement.memory_bytes:
        return False
    if len(allocation.gpu_ids) != requirement.gpu_count:
        return False
    labels = dict(host.labels)
    if any(labels.get(key) != value for key, value in requirement.required_labels):
        return False
    gpu_map = {gpu.gpu_id: gpu for gpu in host.gpus}
    return all(
        gpu_id in gpu_map
        and gpu_map[gpu_id].memory_bytes >= requirement.minimum_gpu_memory_bytes
        for gpu_id in allocation.gpu_ids
    )


def _same_compute_generation(
    current: ComputeAllocation,
    expected: ComputeAllocation,
) -> bool:
    return (
        current.allocation_id == expected.allocation_id
        and current.scope == expected.scope
        and current.host_id == expected.host_id
        and current.cpu_cores == expected.cpu_cores
        and current.memory_bytes == expected.memory_bytes
        and current.gpu_ids == expected.gpu_ids
        and current.lease_fencing_token == expected.lease_fencing_token
    )


def _require_compute_generation(
    current: ComputeAllocation,
    expected: ComputeAllocation,
) -> None:
    if type(expected) is not ComputeAllocation:
        raise TypeError("compute lease operation requires ComputeAllocation")
    if not _same_compute_generation(current, expected):
        raise ResourceLeaseConflict(
            f"stale compute allocation generation: {expected.allocation_id}"
        )


@dataclass(slots=True)
class _HostUsage:
    cpu_cores: int = 0
    memory_bytes: int = 0
    gpu_ids: set[str] = field(default_factory=set)


def _observe_gpu_runtime(observer: GpuRuntimeObserverPort | None) -> GpuRuntimeSnapshot | None:
    if observer is None:
        return None
    try:
        snapshot = observer.snapshot()
    except Exception:
        return None
    return snapshot if snapshot.available else None


def _observe_host_runtime(observer: HostRuntimeObserverPort | None) -> HostRuntimeSnapshot | None:
    if observer is None:
        return None
    try:
        snapshot = observer.snapshot()
    except Exception:
        return None
    return snapshot if snapshot.available else None


@dataclass(frozen=True, slots=True)
class _GpuRuntimeIndex:
    devices_by_id: dict[str, GpuDeviceStatus]
    process_count_by_uuid: dict[str, int]
    processes_complete: bool


def _gpu_runtime_index(
    snapshot: GpuRuntimeSnapshot | None,
) -> _GpuRuntimeIndex | None:
    if snapshot is None:
        return None
    devices_by_id: dict[str, GpuDeviceStatus] = {}
    for device in snapshot.devices:
        # Preserve the previous first-match lookup semantics for malformed or
        # colliding runtime identities while avoiding repeated linear scans.
        devices_by_id.setdefault(device.uuid, device)
        devices_by_id.setdefault(device.index, device)
    process_count_by_uuid: dict[str, int] = {}
    for process in snapshot.processes:
        process_count_by_uuid[process.gpu_uuid] = (
            process_count_by_uuid.get(process.gpu_uuid, 0) + 1
        )
    return _GpuRuntimeIndex(
        devices_by_id=devices_by_id,
        process_count_by_uuid=process_count_by_uuid,
        processes_complete=snapshot.processes_complete,
    )


class ComputePhysicalConvergencePending(RuntimeError):
    """An expired compute lease still has unproven physical GPU consumers."""

    def __init__(self, allocations: tuple[ComputeAllocation, ...]) -> None:
        self.allocations = allocations
        detail = ",".join(
            f"{row.allocation_id}[{','.join(row.gpu_ids)}]"
            for row in allocations
        )
        super().__init__(
            "expired compute allocation physical convergence pending: " + detail
        )


def _gpu_allocation_physically_converged(
    allocation: ComputeAllocation,
    snapshot: GpuRuntimeSnapshot | None,
) -> bool:
    if not allocation.gpu_ids:
        return True
    runtime = _gpu_runtime_index(snapshot)
    if runtime is None or not runtime.processes_complete:
        return False
    for gpu_id in allocation.gpu_ids:
        device = runtime.devices_by_id.get(gpu_id)
        if device is None:
            return False
        if runtime.process_count_by_uuid.get(device.uuid, 0) > 0:
            return False
    return True


def _host_runtime_index(
    snapshot: HostRuntimeSnapshot | None,
) -> dict[str, HostRuntimeStatus] | None:
    if snapshot is None:
        return None
    return {
        item.host_id: item
        for item in snapshot.hosts
        if item.available
    }


def _runtime_rank(
    gpu, requirement: ComputeRequirement, runtime_index: _GpuRuntimeIndex | None,
):
    if runtime_index is None:
        # Shared placement depends on live external usage facts.  Falling back
        # to static inventory would treat an unknown busy GPU as spare capacity.
        if requirement.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED:
            return None
        return (2, 0, 0, gpu.memory_bytes, gpu.gpu_id)
    device = runtime_index.devices_by_id.get(gpu.gpu_id)
    if device is None:
        return None
    free_bytes = device.memory_free_mb * 1024 * 1024
    if free_bytes < requirement.required_gpu_free_memory_bytes:
        return None
    if device.utilization_percent > requirement.max_gpu_utilization_percent:
        return None
    process_count = runtime_index.process_count_by_uuid.get(device.uuid, 0)
    process_visibility_unknown = not runtime_index.processes_complete
    if (process_count or process_visibility_unknown) and requirement.gpu_sharing_mode is GpuSharingMode.IDLE_ONLY:
        return None
    return (
        1 if process_count or process_visibility_unknown else 0,
        device.utilization_percent,
        free_bytes - requirement.required_gpu_free_memory_bytes,
        gpu.memory_bytes - requirement.minimum_gpu_memory_bytes,
        gpu.gpu_id,
    )


def _eligible_gpus(
    host: ComputeHost, usage: _HostUsage, requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
):
    rows = []
    for gpu in host.gpus:
        if gpu.gpu_id in usage.gpu_ids:
            continue
        if gpu.memory_bytes < requirement.minimum_gpu_memory_bytes:
            continue
        rank = _runtime_rank(gpu, requirement, runtime_index)
        if rank is None:
            continue
        rows.append((rank, gpu))
    rows.sort(key=lambda item: item[0])
    return tuple(rows)


def _placement_score(
    host: ComputeHost, usage: _HostUsage, requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
    host_runtime_index: dict[str, HostRuntimeStatus] | None,
):
    cpu_after = host.cpu_cores - usage.cpu_cores - requirement.cpu_cores
    memory_after = host.memory_bytes - usage.memory_bytes - requirement.memory_bytes
    if cpu_after < 0 or memory_after < 0:
        return None
    live = (
        None
        if host_runtime_index is None
        else host_runtime_index.get(host.host_id)
    )
    if live is None:
        if requirement.require_host_runtime:
            return None
        runtime_rank = (1, 0.0, 0.0)
    else:
        effective_cpu = min(float(host.cpu_cores), float(live.effective_cpu_cores))
        if effective_cpu <= 0:
            return None
        cpu_load_ratio = live.cpu_load_1m / effective_cpu
        if cpu_load_ratio > requirement.max_cpu_load_ratio:
            return None
        runtime_cpu_available = max(
            0.0, effective_cpu - live.cpu_load_1m - requirement.cpu_headroom_cores
        )
        if requirement.cpu_cores > runtime_cpu_available:
            return None
        if requirement.memory_bytes + requirement.memory_headroom_bytes > live.available_memory_bytes:
            return None
        memory_pressure = 1.0 - min(
            1.0, live.available_memory_bytes / max(1, host.memory_bytes)
        )
        runtime_rank = (0, cpu_load_ratio, memory_pressure)
    eligible = _eligible_gpus(host, usage, requirement, runtime_index)
    if len(eligible) < requirement.gpu_count:
        return None
    selected_rows = eligible[: requirement.gpu_count]
    selected = tuple(gpu for _rank, gpu in selected_rows)
    if requirement.gpu_count == 0:
        accelerator_penalty = 0 if not host.gpus else 1
        accelerator_bytes = sum(gpu.memory_bytes for gpu in host.gpus)
        score = (
            runtime_rank, accelerator_penalty, accelerator_bytes,
            cpu_after / host.cpu_cores + memory_after / host.memory_bytes,
            cpu_after, memory_after, host.host_id,
        )
    else:
        shared_count = sum(rank[0] for rank, _gpu in selected_rows)
        utilization = sum(rank[1] for rank, _gpu in selected_rows)
        free_excess = sum(rank[2] for rank, _gpu in selected_rows)
        gpu_excess = sum(
            gpu.memory_bytes - requirement.minimum_gpu_memory_bytes for gpu in selected
        )
        remaining = eligible[requirement.gpu_count :]
        score = (
            shared_count, utilization, runtime_rank, free_excess, gpu_excess, len(remaining),
            sum(gpu.memory_bytes for _rank, gpu in remaining),
            cpu_after / host.cpu_cores + memory_after / host.memory_bytes,
            cpu_after, memory_after, host.host_id,
        )
    return score, tuple(gpu.gpu_id for gpu in selected)


def _ordered_placements(
    hosts: tuple[ComputeHost, ...], usage_for, requirement: ComputeRequirement,
    runtime_snapshot: GpuRuntimeSnapshot | None,
    host_runtime_snapshot: HostRuntimeSnapshot | None,
):
    runtime_index = _gpu_runtime_index(runtime_snapshot)
    host_runtime_index = _host_runtime_index(host_runtime_snapshot)
    rows = []
    for host in hosts:
        placement = _placement_score(
            host,
            usage_for(host.host_id),
            requirement,
            runtime_index,
            host_runtime_index,
        )
        if placement is not None:
            score, gpu_ids = placement
            rows.append((score, host, gpu_ids))
    rows.sort(key=lambda item: item[0])
    return tuple(rows)


def _allocation_resource(allocation_id: str) -> ResourceIdentity:
    if not allocation_id.strip():
        raise ValueError("compute allocation_id must be non-empty")
    return ResourceIdentity(ResourceKind.COMPUTE, allocation_id)


def _allocation_lease(allocation_id: str, scope: ScopeIdentity) -> ResourceLease:
    return ResourceLease(
        lease_id=f"compute:{allocation_id}",
        resource=_allocation_resource(allocation_id),
        holder_scope=scope,
        purpose="compute-allocation",
    )


def _allocation_request_digest(
    scope: ScopeIdentity,
    placement_scope: ScopeIdentity | None,
    requirement: ComputeRequirement,
) -> str:
    return canonical_digest({
        "scope": scope,
        "placement_scope": placement_scope,
        "requirement": requirement,
    })


class InMemoryComputeScheduler:
    """Placement authority composed with the canonical generic lease authority."""
    def __init__(
        self,
        inventory: InMemoryComputeInventory,
        *,
        ownership: ResourceOwnershipPort | None = None,
        leases: ResourceLeasePort | None = None,
        gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
        host_runtime_observer: HostRuntimeObserverPort | None = None,
    ) -> None:
        if ownership is None or leases is None:
            raise ValueError(
                "compute scheduler requires explicit resource ownership and lease ports; "
                "bind the ResourceLeaseAuthority from composition"
            )
        self._inventory = inventory
        self._ownership = ownership
        self._leases = leases
        self._gpu_runtime_observer = gpu_runtime_observer
        self._host_runtime_observer = host_runtime_observer
        self._allocations: dict[str, ComputeAllocation] = {}
        self._request_digests: dict[str, str] = {}
        self._usage_by_host: dict[str, _HostUsage] = {}
        self._lock = RLock()

    def _usage(self, host_id: str) -> _HostUsage:
        return self._usage_by_host.get(host_id, _HostUsage())
    @staticmethod
    def _eligible_inventory_hosts(
        hosts: tuple[ComputeHost, ...],
        requirement: ComputeRequirement,
    ) -> tuple[ComputeHost, ...]:
        required_labels = dict(requirement.required_labels)
        return tuple(
            host
            for host in hosts
            if host.enabled
            and not any(
                dict(host.labels).get(key) != value
                for key, value in required_labels.items()
            )
        )

    def _placements_locked(
        self,
        hosts: tuple[ComputeHost, ...],
        requirement: ComputeRequirement,
        *,
        runtime_snapshot: GpuRuntimeSnapshot | None,
        host_runtime_snapshot: HostRuntimeSnapshot | None,
    ):
        return _ordered_placements(
            hosts,
            self._usage,
            requirement,
            runtime_snapshot,
            host_runtime_snapshot,
        )

    def _release_usage_locked(self, row: ComputeAllocation) -> None:
        usage = self._usage_by_host.get(row.host_id)
        if usage is None:
            raise RuntimeError(f"compute usage index missing for allocation: {row.allocation_id}")
        remaining_gpus = set(usage.gpu_ids)
        remaining_gpus.difference_update(row.gpu_ids)
        next_usage = _HostUsage(
            cpu_cores=usage.cpu_cores - row.cpu_cores,
            memory_bytes=usage.memory_bytes - row.memory_bytes,
            gpu_ids=remaining_gpus,
        )
        if next_usage.cpu_cores < 0 or next_usage.memory_bytes < 0:
            raise RuntimeError(f"compute usage index underflow: {row.allocation_id}")
        if next_usage.cpu_cores or next_usage.memory_bytes or next_usage.gpu_ids:
            self._usage_by_host[row.host_id] = next_usage
        else:
            self._usage_by_host.pop(row.host_id, None)

    def _reconcile_expired_locked(
        self,
        now_epoch_s: float | None,
        runtime_snapshot: GpuRuntimeSnapshot | None,
    ) -> tuple[ComputeAllocation, ...]:
        del runtime_snapshot
        self._leases.reconcile_expired(
            now=now_epoch_s,
            resource_kind=ResourceKind.COMPUTE,
        )
        # Lease expiry revokes holder mutation authority; it is not proof that
        # the workload/model process stopped. Keep every expired allocation in
        # the usage index so CPU, memory and GPU capacity remain quarantined
        # until an exclusive recovery owner proves upper physical convergence.
        pending: list[ComputeAllocation] = []
        for allocation_id, row in tuple(self._allocations.items()):
            lease = self._leases.get(
                f"compute:{allocation_id}",
                now=now_epoch_s,
            )
            if lease.state is LeaseState.ACTIVE:
                continue
            if lease.fencing_token != row.lease_fencing_token:
                raise ResourceLeaseConflict(
                    f"compute allocation lease generation drifted: {allocation_id}"
                )
            pending.append(row)
        return tuple(sorted(pending, key=lambda row: row.allocation_id))

    def candidates(
        self,
        requirement: ComputeRequirement,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeHost, ...]:
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        host_runtime_snapshot = _observe_host_runtime(self._host_runtime_observer)
        hosts = self._eligible_inventory_hosts(
            tuple(self._inventory.list_hosts(scope=scope)),
            requirement,
        )
        with self._lock:
            self._reconcile_expired_locked(None, runtime_snapshot)
            return tuple(
                host for _score, host, _gpu_ids
                in self._placements_locked(
                    hosts,
                    requirement,
                    runtime_snapshot=runtime_snapshot,
                    host_runtime_snapshot=host_runtime_snapshot,
                )
            )
    def allocate(
        self,
        allocation_id: str,
        scope: ScopeIdentity,
        requirement: ComputeRequirement,
        *,
        placement_scope: ScopeIdentity | None = None,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ComputeAllocation:
        now_epoch_s = None if now is None else _lease_now(now)
        request_digest = _allocation_request_digest(scope, placement_scope, requirement)
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        host_runtime_snapshot = _observe_host_runtime(self._host_runtime_observer)
        hosts = self._eligible_inventory_hosts(
            tuple(
                self._inventory.list_hosts(
                    scope=scope if placement_scope is None else placement_scope
                )
            ),
            requirement,
        )
        with self._lock:
            self._reconcile_expired_locked(now_epoch_s, runtime_snapshot)
            prior_digest = self._request_digests.get(allocation_id)
            if prior_digest is not None and prior_digest != request_digest:
                raise ValueError(f"allocation identity conflict: {allocation_id}")
            existing = self._allocations.get(allocation_id)
            if existing is not None:
                lease = self._leases.get(
                    f"compute:{allocation_id}",
                    now=now_epoch_s,
                )
                if (
                    lease.state is LeaseState.ACTIVE
                    and lease.fencing_token == existing.lease_fencing_token
                ):
                    return existing
                raise ComputePhysicalConvergencePending((existing,))
            placements = self._placements_locked(
                hosts,
                requirement,
                runtime_snapshot=runtime_snapshot,
                host_runtime_snapshot=host_runtime_snapshot,
            )
            if not placements:
                raise ComputePlacementUnavailable(requirement)
            _score, host, gpu_ids = placements[0]
            resource = _allocation_resource(allocation_id)
            self._ownership.register_owner(
                ResourceOwner(resource, scope, ResourceOwnership.PLATFORM_MANAGED)
            )
            granted = self._leases.acquire(
                _allocation_lease(allocation_id, scope),
                ttl_seconds=ttl_seconds,
                now=now_epoch_s,
            )
            try:
                allocation = ComputeAllocation(
                    allocation_id=allocation_id,
                    scope=scope,
                    host_id=host.host_id,
                    cpu_cores=requirement.cpu_cores,
                    memory_bytes=requirement.memory_bytes,
                    gpu_ids=gpu_ids,
                    lease_fencing_token=granted.fencing_token,
                    lease_expires_at_epoch_s=granted.expires_at_epoch_s,
                )
                usage = self._usage(host.host_id)
                self._usage_by_host[host.host_id] = _HostUsage(
                    cpu_cores=usage.cpu_cores + allocation.cpu_cores,
                    memory_bytes=usage.memory_bytes + allocation.memory_bytes,
                    gpu_ids=set(usage.gpu_ids).union(allocation.gpu_ids),
                )
                self._allocations[allocation_id] = allocation
                self._request_digests[allocation_id] = request_digest
                return allocation
            except BaseException:
                self._leases.release(granted.lease_id, fencing_token=granted.fencing_token)
                raise

    def renew_many(
        self,
        allocations: tuple[ComputeAllocation, ...],
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        if (
            not allocations
            or any(type(row) is not ComputeAllocation for row in allocations)
        ):
            raise ValueError(
                "compute renewal requires typed allocation generations"
            )
        allocation_ids = tuple(row.allocation_id for row in allocations)
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("compute renewal requires unique allocation ids")
        now_epoch_s = None if now is None else _lease_now(now)
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        with self._lock:
            self._reconcile_expired_locked(now_epoch_s, runtime_snapshot)
            missing = [item for item in allocation_ids if item not in self._allocations]
            if missing:
                raise KeyError(missing[0])
            renewed: list[ComputeAllocation] = []
            for expected in allocations:
                current = self._allocations[expected.allocation_id]
                _require_compute_generation(current, expected)
                granted = self._leases.renew(
                    f"compute:{expected.allocation_id}",
                    fencing_token=expected.lease_fencing_token,
                    ttl_seconds=ttl_seconds,
                    now=now_epoch_s,
                )
                updated = replace(
                    current,
                    lease_fencing_token=granted.fencing_token,
                    lease_expires_at_epoch_s=granted.expires_at_epoch_s,
                )
                self._allocations[expected.allocation_id] = updated
                renewed.append(updated)
            return tuple(renewed)

    def reconcile_expired(
        self,
        *,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        now_epoch_s = None if now is None else _lease_now(now)
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        with self._lock:
            pending = self._reconcile_expired_locked(now_epoch_s, runtime_snapshot)
            if pending:
                raise ComputePhysicalConvergencePending(pending)
            return ()

    def release(self, allocation: ComputeAllocation) -> None:
        if type(allocation) is not ComputeAllocation:
            raise TypeError("compute release requires ComputeAllocation")
        with self._lock:
            row = self._allocations.get(allocation.allocation_id)
            if row is None:
                return
            _require_compute_generation(row, allocation)
            self._leases.release(f"compute:{allocation.allocation_id}", fencing_token=row.lease_fencing_token)
            self._allocations.pop(allocation.allocation_id, None)
            self._release_usage_locked(row)

    def recover_release(self, allocation: ComputeAllocation) -> None:
        """Retire one exact generation under exclusive upper-layer recovery."""

        if type(allocation) is not ComputeAllocation:
            raise TypeError("compute recovery release requires ComputeAllocation")
        with self._lock:
            row = self._allocations.get(allocation.allocation_id)
            if row is None:
                return
            _require_compute_generation(row, allocation)
            lease = self._leases.get(
                f"compute:{allocation.allocation_id}",
            )
            if lease.fencing_token != allocation.lease_fencing_token:
                raise ResourceLeaseConflict(
                    f"stale compute recovery generation: {allocation.allocation_id}"
                )
            if lease.state is LeaseState.ACTIVE:
                self._leases.release(
                    f"compute:{allocation.allocation_id}",
                    fencing_token=allocation.lease_fencing_token,
                )
            elif lease.state not in {LeaseState.EXPIRED, LeaseState.RELEASED}:
                raise ResourceLeaseConflict(
                    f"compute recovery lease state is not terminal: {allocation.allocation_id}"
                )
            self._allocations.pop(allocation.allocation_id, None)
            self._release_usage_locked(row)

    def allocations(
        self,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        with self._lock:
            self._reconcile_expired_locked(None, runtime_snapshot)
            return tuple(sorted(
                (row for row in self._allocations.values() if scope is None or row.scope == scope),
                key=lambda row: row.allocation_id,
            ))


class SQLiteComputeScheduler:
    """Crash-safe compute placement over the canonical SQLite lease authority."""

    SCHEMA_VERSION = 2

    def __init__(
        self,
        path: str | Path,
        inventory: InMemoryComputeInventory,
        *,
        timeout_seconds: float = 30.0,
        clock: LeaseClockPort | None = None,
        gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
        host_runtime_observer: HostRuntimeObserverPort | None = None,
    ) -> None:
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._inventory = inventory
        self._clock = LocalLeaseClock() if clock is None else clock
        self._gpu_runtime_observer = gpu_runtime_observer
        self._host_runtime_observer = host_runtime_observer
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(conn, timeout_seconds=self.timeout_seconds)
            ensure_resource_schema(conn)
            self._ensure_schema(conn)
            conn.commit()

    def _connection(self):
        return durable_sqlite_connection(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    def _authority_now(
        self,
        conn: sqlite3.Connection,
        explicit_now: float | None,
    ) -> float:
        if explicit_now is not None:
            return _lease_now(explicit_now)
        return authoritative_lease_now(conn, self._clock.read())

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS compute_scheduler_meta("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT value FROM compute_scheduler_meta WHERE key='schema_version'"
        ).fetchone()
        if row is not None and int(row[0]) != self.SCHEMA_VERSION:
            raise RuntimeError(
                "unsupported SQLiteComputeScheduler schema; recreate the v2 authority store"
            )
        conn.execute(
            "INSERT OR REPLACE INTO compute_scheduler_meta(key,value) VALUES('schema_version',?)",
            (str(self.SCHEMA_VERSION),),
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS compute_allocation_identity("
            "allocation_id TEXT PRIMARY KEY,request_digest TEXT NOT NULL,"
            "scope_kind TEXT NOT NULL,scope_id TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS compute_allocations("
            "allocation_id TEXT PRIMARY KEY REFERENCES compute_allocation_identity(allocation_id),"
            "host_id TEXT NOT NULL,cpu_cores INTEGER NOT NULL,memory_bytes INTEGER NOT NULL,"
            "gpu_ids_json TEXT NOT NULL,lease_id TEXT NOT NULL UNIQUE "
            "REFERENCES resource_leases(lease_id))"
        )
        conn.execute("DROP TABLE IF EXISTS compute_allocation_fencing")

    @staticmethod
    def _gpu_json(gpu_ids: tuple[str, ...]) -> str:
        return json.dumps(list(gpu_ids), sort_keys=False, separators=(",", ":"))
    _SELECT = (
        "c.allocation_id,i.scope_kind,i.scope_id,c.host_id,c.cpu_cores,c.memory_bytes,"
        "c.gpu_ids_json,l.lease_id,l.holder_generation,l.fencing_token,l.expires_at_epoch_s"
    )

    @classmethod
    def _decode_row(cls, row: tuple[object, ...]) -> ComputeAllocation:
        gpu_value = json.loads(str(row[6]))
        if not isinstance(gpu_value, list) or not all(isinstance(item, str) for item in gpu_value):
            raise RuntimeError("compute allocation GPU payload is corrupt")
        return ComputeAllocation(
            allocation_id=str(row[0]),
            scope=ScopeIdentity(ScopeKind(str(row[1])), str(row[2])),
            host_id=str(row[3]),
            cpu_cores=int(row[4]),
            memory_bytes=int(row[5]),
            gpu_ids=tuple(gpu_value),
            lease_fencing_token=int(row[9]),
            lease_expires_at_epoch_s=None if row[10] is None else float(row[10]),
        )

    def _active_rows(
        self,
        conn: sqlite3.Connection,
        now_epoch_s: float,
    ) -> tuple[ComputeAllocation, ...]:
        rows = conn.execute(
            f"SELECT {self._SELECT} FROM compute_allocations c "
            "JOIN compute_allocation_identity i USING(allocation_id) "
            "JOIN resource_leases l ON l.lease_id=c.lease_id "
            "WHERE l.state='active' AND "
            "(l.expires_at_epoch_s IS NULL OR l.expires_at_epoch_s>?) "
            "ORDER BY c.allocation_id",
            (now_epoch_s,),
        ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def _capacity_rows(
        self,
        conn: sqlite3.Connection,
    ) -> tuple[ComputeAllocation, ...]:
        """Rows that still fence scheduler capacity, including GPU quarantine."""

        rows = conn.execute(
            f"SELECT {self._SELECT} FROM compute_allocations c "
            "JOIN compute_allocation_identity i USING(allocation_id) "
            "JOIN resource_leases l ON l.lease_id=c.lease_id "
            "ORDER BY c.allocation_id"
        ).fetchall()
        return tuple(self._decode_row(row) for row in rows)

    def _active_row(
        self,
        conn: sqlite3.Connection,
        allocation_id: str,
        now_epoch_s: float,
    ) -> ComputeAllocation | None:
        row = conn.execute(
            f"SELECT {self._SELECT} FROM compute_allocations c "
            "JOIN compute_allocation_identity i USING(allocation_id) "
            "JOIN resource_leases l ON l.lease_id=c.lease_id "
            "WHERE c.allocation_id=? AND l.state='active' AND "
            "(l.expires_at_epoch_s IS NULL OR l.expires_at_epoch_s>?)",
            (allocation_id, now_epoch_s),
        ).fetchone()
        return None if row is None else self._decode_row(row)

    def _capacity_row(
        self,
        conn: sqlite3.Connection,
        allocation_id: str,
    ) -> ComputeAllocation | None:
        row = conn.execute(
            f"SELECT {self._SELECT} FROM compute_allocations c "
            "JOIN compute_allocation_identity i USING(allocation_id) "
            "JOIN resource_leases l ON l.lease_id=c.lease_id "
            "WHERE c.allocation_id=?",
            (allocation_id,),
        ).fetchone()
        return None if row is None else self._decode_row(row)

    def _cleanup_expired(
        self,
        conn: sqlite3.Connection,
        now_epoch_s: float,
        runtime_snapshot: GpuRuntimeSnapshot | None,
    ) -> tuple[tuple[ComputeAllocation, ...], tuple[ComputeAllocation, ...]]:
        reconcile_expired_resource_leases(
            conn,
            now_epoch_s=now_epoch_s,
            resource_kind=ResourceKind.COMPUTE,
        )
        rows = conn.execute(
            f"SELECT {self._SELECT} FROM compute_allocations c "
            "JOIN compute_allocation_identity i USING(allocation_id) "
            "JOIN resource_leases l ON l.lease_id=c.lease_id "
            "WHERE l.state='expired' AND l.resource_kind=? "
            "ORDER BY c.allocation_id",
            (ResourceKind.COMPUTE.value,),
        ).fetchall()
        del runtime_snapshot
        pending = tuple(
            sorted(
                (self._decode_row(raw) for raw in rows),
                key=lambda row: row.allocation_id,
            )
        )
        # Expired rows remain in compute_allocations and therefore continue to
        # fence capacity. Only recover_release(), called after upper physical
        # owners converge, may remove them.
        return (), pending
    @staticmethod
    def _usage(rows: tuple[ComputeAllocation, ...], host_id: str) -> _HostUsage:
        usage = _HostUsage()
        for row in rows:
            if row.host_id != host_id:
                continue
            usage.cpu_cores += row.cpu_cores
            usage.memory_bytes += row.memory_bytes
            usage.gpu_ids.update(row.gpu_ids)
        return usage

    def _placements(
        self,
        rows: tuple[ComputeAllocation, ...],
        requirement: ComputeRequirement,
        scope: ScopeIdentity | None,
        runtime_snapshot: GpuRuntimeSnapshot | None,
        host_runtime_snapshot: HostRuntimeSnapshot | None,
    ):
        required_labels = dict(requirement.required_labels)
        hosts = tuple(
            host for host in self._inventory.list_hosts(scope=scope)
            if host.enabled
            and not any(
                dict(host.labels).get(key) != value
                for key, value in required_labels.items()
            )
        )
        return _ordered_placements(
            hosts,
            lambda host_id: self._usage(rows, host_id),
            requirement,
            runtime_snapshot,
            host_runtime_snapshot,
        )

    def candidates(
        self,
        requirement: ComputeRequirement,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeHost, ...]:
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        host_runtime_snapshot = _observe_host_runtime(self._host_runtime_observer)
        with self._connection() as conn:
            rows = self._capacity_rows(conn)
        return tuple(
            host for _score, host, _gpu_ids
            in self._placements(
                rows,
                requirement,
                scope,
                runtime_snapshot,
                host_runtime_snapshot,
            )
        )

    def _ensure_identity(
        self,
        conn: sqlite3.Connection,
        allocation_id: str,
        request_digest: str,
        scope: ScopeIdentity,
    ) -> None:
        row = conn.execute(
            "SELECT request_digest,scope_kind,scope_id FROM compute_allocation_identity "
            "WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        expected = (request_digest, scope.kind.value, scope.scope_id)
        if row is not None:
            if tuple(map(str, row)) != expected:
                raise ValueError(f"allocation identity conflict: {allocation_id}")
            return
        conn.execute(
            "INSERT INTO compute_allocation_identity("
            "allocation_id,request_digest,scope_kind,scope_id) VALUES(?,?,?,?)",
            (allocation_id, request_digest, scope.kind.value, scope.scope_id),
        )
    def allocate(
        self,
        allocation_id: str,
        scope: ScopeIdentity,
        requirement: ComputeRequirement,
        *,
        placement_scope: ScopeIdentity | None = None,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ComputeAllocation:
        request_digest = _allocation_request_digest(scope, placement_scope, requirement)
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        host_runtime_snapshot = _observe_host_runtime(self._host_runtime_observer)
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(conn, timeout_seconds=self.timeout_seconds)
            try:
                now_epoch_s = self._authority_now(conn, now)
                _converged, pending = self._cleanup_expired(
                    conn,
                    now_epoch_s,
                    runtime_snapshot,
                )
                self._ensure_identity(conn, allocation_id, request_digest, scope)
                existing = self._active_row(conn, allocation_id, now_epoch_s)
                if existing is not None:
                    conn.commit()
                    return existing
                quarantined = self._capacity_row(conn, allocation_id)
                if quarantined is not None:
                    conn.commit()
                    raise ComputePhysicalConvergencePending((quarantined,))
                rows = self._capacity_rows(conn)
                placements = self._placements(
                    rows,
                    requirement,
                    scope if placement_scope is None else placement_scope,
                    runtime_snapshot,
                    host_runtime_snapshot,
                )
                if not placements:
                    raise ComputePlacementUnavailable(requirement)
                _score, host, gpu_ids = placements[0]
                resource = _allocation_resource(allocation_id)
                ensure_resource_owner(
                    conn,
                    ResourceOwner(resource, scope, ResourceOwnership.PLATFORM_MANAGED),
                )
                granted = acquire_resource_lease(
                    conn,
                    _allocation_lease(allocation_id, scope),
                    ttl_seconds=ttl_seconds,
                    now_epoch_s=now_epoch_s,
                )
                conn.execute(
                    "INSERT INTO compute_allocations("
                    "allocation_id,host_id,cpu_cores,memory_bytes,gpu_ids_json,lease_id) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        allocation_id,
                        host.host_id,
                        requirement.cpu_cores,
                        requirement.memory_bytes,
                        self._gpu_json(gpu_ids),
                        granted.lease_id,
                    ),
                )
                allocation = ComputeAllocation(
                    allocation_id=allocation_id,
                    scope=scope,
                    host_id=host.host_id,
                    cpu_cores=requirement.cpu_cores,
                    memory_bytes=requirement.memory_bytes,
                    gpu_ids=gpu_ids,
                    lease_fencing_token=granted.fencing_token,
                    lease_expires_at_epoch_s=granted.expires_at_epoch_s,
                )
                conn.commit()
                return allocation
            except ComputePhysicalConvergencePending:
                raise
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute scheduler",
                )
                raise
    def renew_many(
        self,
        allocations: tuple[ComputeAllocation, ...],
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        if (
            not allocations
            or any(type(row) is not ComputeAllocation for row in allocations)
        ):
            raise ValueError(
                "compute renewal requires typed allocation generations"
            )
        allocation_ids = tuple(row.allocation_id for row in allocations)
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("compute renewal requires unique allocation ids")
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(conn, timeout_seconds=self.timeout_seconds)
            try:
                now_epoch_s = self._authority_now(conn, now)
                self._cleanup_expired(
                    conn,
                    now_epoch_s,
                    runtime_snapshot,
                )
                current: list[ComputeAllocation] = []
                for expected in allocations:
                    row = self._active_row(
                        conn,
                        expected.allocation_id,
                        now_epoch_s,
                    )
                    if row is None:
                        raise KeyError(expected.allocation_id)
                    _require_compute_generation(row, expected)
                    current.append(row)
                renewed: list[ComputeAllocation] = []
                for row, expected in zip(current, allocations, strict=True):
                    lease = renew_resource_lease(
                        conn,
                        f"compute:{row.allocation_id}",
                        fencing_token=expected.lease_fencing_token,
                        ttl_seconds=ttl_seconds,
                        now_epoch_s=now_epoch_s,
                    )
                    renewed.append(replace(
                        row,
                        lease_fencing_token=lease.fencing_token,
                        lease_expires_at_epoch_s=lease.expires_at_epoch_s,
                    ))
                conn.commit()
                return tuple(renewed)
            except ComputePhysicalConvergencePending:
                raise
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute scheduler",
                )
                raise
    def reconcile_expired(
        self,
        *,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(conn, timeout_seconds=self.timeout_seconds)
            try:
                now_epoch_s = self._authority_now(conn, now)
                _converged, pending = self._cleanup_expired(
                    conn,
                    now_epoch_s,
                    runtime_snapshot,
                )
                conn.commit()
                if pending:
                    raise ComputePhysicalConvergencePending(pending)
                return ()
            except ComputePhysicalConvergencePending:
                raise
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute scheduler",
                )
                raise

    def release(self, allocation: ComputeAllocation) -> None:
        if type(allocation) is not ComputeAllocation:
            raise TypeError("compute release requires ComputeAllocation")
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(conn, timeout_seconds=self.timeout_seconds)
            try:
                now_epoch_s = self._authority_now(conn, None)
                self._cleanup_expired(
                    conn,
                    now_epoch_s,
                    runtime_snapshot,
                )
                current = self._active_row(
                    conn,
                    allocation.allocation_id,
                    now_epoch_s,
                )
                if current is None:
                    conn.commit()
                    return
                _require_compute_generation(current, allocation)
                release_resource_lease(
                    conn,
                    f"compute:{allocation.allocation_id}",
                    fencing_token=allocation.lease_fencing_token,
                    now_epoch_s=now_epoch_s,
                )
                deleted = conn.execute(
                    "DELETE FROM compute_allocations WHERE allocation_id=?",
                    (allocation.allocation_id,),
                )
                if deleted.rowcount != 1:
                    raise ResourceLeaseConflict(
                        f"compute release lost authority: {allocation.allocation_id}"
                    )
                conn.commit()
            except ComputePhysicalConvergencePending:
                raise
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute scheduler",
                )
                raise

    def recover_release(self, allocation: ComputeAllocation) -> None:
        """Retire one exact generation under exclusive upper-layer recovery."""

        if type(allocation) is not ComputeAllocation:
            raise TypeError("compute recovery release requires ComputeAllocation")
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                now_epoch_s = self._authority_now(conn, None)
                reconcile_expired_resource_leases(
                    conn,
                    now_epoch_s=now_epoch_s,
                    resource_kind=ResourceKind.COMPUTE,
                )
                current = self._capacity_row(conn, allocation.allocation_id)
                if current is None:
                    conn.commit()
                    return
                _require_compute_generation(current, allocation)
                lease_row = conn.execute(
                    "SELECT state,fencing_token FROM resource_leases WHERE lease_id=?",
                    (f"compute:{allocation.allocation_id}",),
                ).fetchone()
                if lease_row is None:
                    raise ResourceLeaseConflict(
                        f"compute recovery lease is missing: {allocation.allocation_id}"
                    )
                lease_state = LeaseState(str(lease_row[0]))
                lease_fencing = int(lease_row[1])
                if lease_fencing != allocation.lease_fencing_token:
                    raise ResourceLeaseConflict(
                        f"stale compute recovery generation: {allocation.allocation_id}"
                    )
                if lease_state is LeaseState.ACTIVE:
                    release_resource_lease(
                        conn,
                        f"compute:{allocation.allocation_id}",
                        fencing_token=allocation.lease_fencing_token,
                        now_epoch_s=now_epoch_s,
                    )
                elif lease_state not in {LeaseState.EXPIRED, LeaseState.RELEASED}:
                    raise ResourceLeaseConflict(
                        f"compute recovery lease state is not terminal: {allocation.allocation_id}"
                    )
                deleted = conn.execute(
                    "DELETE FROM compute_allocations WHERE allocation_id=?",
                    (allocation.allocation_id,),
                )
                if deleted.rowcount != 1:
                    raise ResourceLeaseConflict(
                        f"compute recovery release lost authority: {allocation.allocation_id}"
                    )
                conn.commit()
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute recovery release",
                )
                raise

    def allocations(
        self,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        with self._connection() as conn:
            rows = self._capacity_rows(conn)
        return tuple(row for row in rows if scope is None or row.scope == scope)


__all__ = [
    "ComputePhysicalConvergencePending",
    "InMemoryComputeScheduler",
    "SQLiteComputeScheduler",
]
