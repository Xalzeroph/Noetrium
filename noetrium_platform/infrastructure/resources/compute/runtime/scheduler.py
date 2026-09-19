from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
from time import time

from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocation, ComputeHost, ComputeRequirement, GpuRuntimeObserverPort,
    GpuRuntimeSnapshot, GpuSharingMode, HostRuntimeObserverPort, HostRuntimeSnapshot,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity, ResourceKind, ResourceLease, ResourceLeasePort, ResourceOwner,
    ResourceOwnership, ResourceOwnershipPort,
)
from noetrium_platform.infrastructure.resources.providers.sqlite_connection import durable_sqlite_connection
from noetrium_platform.infrastructure.resources.providers.sqlite_resource import ensure_resource_schema
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


def _host_runtime(snapshot: HostRuntimeSnapshot | None, host_id: str):
    if snapshot is None:
        return None
    return next(
        (item for item in snapshot.hosts if item.host_id == host_id and item.available),
        None,
    )


def _runtime_device(snapshot: GpuRuntimeSnapshot | None, gpu_id: str):
    if snapshot is None:
        return None
    return next(
        (device for device in snapshot.devices if device.uuid == gpu_id or device.index == gpu_id),
        None,
    )


def _runtime_rank(
    gpu, requirement: ComputeRequirement, snapshot: GpuRuntimeSnapshot | None,
):
    if snapshot is None:
        # Shared placement depends on live external usage facts.  Falling back
        # to static inventory would treat an unknown busy GPU as spare capacity.
        if requirement.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED:
            return None
        return (2, 0, 0, gpu.memory_bytes, gpu.gpu_id)
    device = _runtime_device(snapshot, gpu.gpu_id)
    if device is None:
        return None
    free_bytes = device.memory_free_mb * 1024 * 1024
    if free_bytes < requirement.required_gpu_free_memory_bytes:
        return None
    if device.utilization_percent > requirement.max_gpu_utilization_percent:
        return None
    process_count = sum(1 for process in snapshot.processes if process.gpu_uuid == device.uuid)
    process_visibility_unknown = not snapshot.processes_complete
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
    runtime_snapshot: GpuRuntimeSnapshot | None,
):
    rows = []
    for gpu in host.gpus:
        if gpu.gpu_id in usage.gpu_ids:
            continue
        if gpu.memory_bytes < requirement.minimum_gpu_memory_bytes:
            continue
        rank = _runtime_rank(gpu, requirement, runtime_snapshot)
        if rank is None:
            continue
        rows.append((rank, gpu))
    rows.sort(key=lambda item: item[0])
    return tuple(rows)


def _placement_score(
    host: ComputeHost, usage: _HostUsage, requirement: ComputeRequirement,
    runtime_snapshot: GpuRuntimeSnapshot | None,
    host_runtime_snapshot: HostRuntimeSnapshot | None,
):
    cpu_after = host.cpu_cores - usage.cpu_cores - requirement.cpu_cores
    memory_after = host.memory_bytes - usage.memory_bytes - requirement.memory_bytes
    if cpu_after < 0 or memory_after < 0:
        return None
    live = _host_runtime(host_runtime_snapshot, host.host_id)
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
    eligible = _eligible_gpus(host, usage, requirement, runtime_snapshot)
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
    rows = []
    for host in hosts:
        placement = _placement_score(
            host, usage_for(host.host_id), requirement, runtime_snapshot, host_runtime_snapshot
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
    def _placements_locked(
        self,
        requirement: ComputeRequirement,
        *,
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

    def _reconcile_expired_locked(self, now_epoch_s: float) -> tuple[ComputeAllocation, ...]:
        expired_leases = self._leases.reconcile_expired(now=now_epoch_s)
        expired: list[ComputeAllocation] = []
        for lease in expired_leases:
            if lease.resource.kind is not ResourceKind.COMPUTE:
                continue
            allocation_id = lease.resource.resource_id
            row = self._allocations.pop(allocation_id, None)
            if row is None:
                continue
            self._release_usage_locked(row)
            expired.append(row)
        return tuple(sorted(expired, key=lambda row: row.allocation_id))

    def candidates(
        self,
        requirement: ComputeRequirement,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeHost, ...]:
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        host_runtime_snapshot = _observe_host_runtime(self._host_runtime_observer)
        with self._lock:
            self._reconcile_expired_locked(time())
            return tuple(
                host for _score, host, _gpu_ids
                in self._placements_locked(
                    requirement,
                    scope=scope,
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
        now_epoch_s = _lease_now(now)
        request_digest = _allocation_request_digest(scope, placement_scope, requirement)
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        host_runtime_snapshot = _observe_host_runtime(self._host_runtime_observer)
        with self._lock:
            self._reconcile_expired_locked(now_epoch_s)
            prior_digest = self._request_digests.get(allocation_id)
            if prior_digest is not None and prior_digest != request_digest:
                raise ValueError(f"allocation identity conflict: {allocation_id}")
            existing = self._allocations.get(allocation_id)
            if existing is not None:
                return existing
            placements = self._placements_locked(
                requirement,
                scope=scope if placement_scope is None else placement_scope,
                runtime_snapshot=runtime_snapshot,
                host_runtime_snapshot=host_runtime_snapshot,
            )
            if not placements:
                raise RuntimeError("no compute host satisfies requirement")
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
                self._leases.release(granted.lease_id)
                raise

    def renew_many(
        self,
        allocation_ids: tuple[str, ...],
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        if not allocation_ids or len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("compute renewal requires unique allocation ids")
        now_epoch_s = _lease_now(now)
        with self._lock:
            self._reconcile_expired_locked(now_epoch_s)
            missing = [item for item in allocation_ids if item not in self._allocations]
            if missing:
                raise KeyError(missing[0])
            renewed: list[ComputeAllocation] = []
            for allocation_id in allocation_ids:
                current = self._allocations[allocation_id]
                granted = self._leases.renew(
                    f"compute:{allocation_id}",
                    fencing_token=current.lease_fencing_token,
                    ttl_seconds=ttl_seconds,
                    now=now_epoch_s,
                )
                updated = replace(
                    current,
                    lease_fencing_token=granted.fencing_token,
                    lease_expires_at_epoch_s=granted.expires_at_epoch_s,
                )
                self._allocations[allocation_id] = updated
                renewed.append(updated)
            return tuple(renewed)

    def reconcile_expired(
        self,
        *,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        now_epoch_s = _lease_now(now)
        with self._lock:
            return self._reconcile_expired_locked(now_epoch_s)

    def release(self, allocation_id: str) -> None:
        with self._lock:
            row = self._allocations.pop(allocation_id, None)
            if row is None:
                return
            self._leases.release(f"compute:{allocation_id}")
            self._release_usage_locked(row)

    def allocations(
        self,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        with self._lock:
            self._reconcile_expired_locked(time())
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
        gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
        host_runtime_observer: HostRuntimeObserverPort | None = None,
    ) -> None:
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._inventory = inventory
        self._gpu_runtime_observer = gpu_runtime_observer
        self._host_runtime_observer = host_runtime_observer
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ensure_resource_schema(conn)
            self._ensure_schema(conn)
            conn.commit()

    def _connection(self):
        return durable_sqlite_connection(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )
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

    def _cleanup_expired(
        self,
        conn: sqlite3.Connection,
        now_epoch_s: float,
    ) -> tuple[ComputeAllocation, ...]:
        rows = conn.execute(
            f"SELECT {self._SELECT} FROM compute_allocations c "
            "JOIN compute_allocation_identity i USING(allocation_id) "
            "JOIN resource_leases l ON l.lease_id=c.lease_id "
            "WHERE l.state='active' AND l.resource_kind=? "
            "AND l.expires_at_epoch_s IS NOT NULL AND l.expires_at_epoch_s<=? "
            "ORDER BY c.allocation_id",
            (ResourceKind.COMPUTE.value, now_epoch_s),
        ).fetchall()
        expired = tuple(self._decode_row(row) for row in rows)
        leases = reconcile_expired_resource_leases(
            conn,
            now_epoch_s=now_epoch_s,
            resource_kind=ResourceKind.COMPUTE,
        )
        if leases:
            conn.executemany(
                "DELETE FROM compute_allocations WHERE lease_id=?",
                ((lease.lease_id,) for lease in leases),
            )
        return expired
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
        now_epoch_s = time()
        with self._connection() as conn:
            rows = self._active_rows(conn, now_epoch_s)
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
        now_epoch_s = _lease_now(now)
        request_digest = _allocation_request_digest(scope, placement_scope, requirement)
        runtime_snapshot = _observe_gpu_runtime(self._gpu_runtime_observer)
        host_runtime_snapshot = _observe_host_runtime(self._host_runtime_observer)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._cleanup_expired(conn, now_epoch_s)
                self._ensure_identity(conn, allocation_id, request_digest, scope)
                existing = self._active_row(conn, allocation_id, now_epoch_s)
                if existing is not None:
                    conn.commit()
                    return existing
                rows = self._active_rows(conn, now_epoch_s)
                placements = self._placements(
                    rows,
                    requirement,
                    scope if placement_scope is None else placement_scope,
                    runtime_snapshot,
                    host_runtime_snapshot,
                )
                if not placements:
                    raise RuntimeError("no compute host satisfies requirement")
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
            except BaseException:
                conn.rollback()
                raise
    def renew_many(
        self,
        allocation_ids: tuple[str, ...],
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        if not allocation_ids or len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("compute renewal requires unique allocation ids")
        now_epoch_s = _lease_now(now)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._cleanup_expired(conn, now_epoch_s)
                current: list[ComputeAllocation] = []
                for allocation_id in allocation_ids:
                    row = self._active_row(conn, allocation_id, now_epoch_s)
                    if row is None:
                        raise KeyError(allocation_id)
                    current.append(row)
                renewed: list[ComputeAllocation] = []
                for row in current:
                    lease = renew_resource_lease(
                        conn,
                        f"compute:{row.allocation_id}",
                        fencing_token=row.lease_fencing_token,
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
            except BaseException:
                conn.rollback()
                raise
    def reconcile_expired(
        self,
        *,
        now: float | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        now_epoch_s = _lease_now(now)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                expired = self._cleanup_expired(conn, now_epoch_s)
                conn.commit()
                return expired
            except BaseException:
                conn.rollback()
                raise

    def release(self, allocation_id: str) -> None:
        now_epoch_s = time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT lease_id FROM compute_allocations WHERE allocation_id=?",
                    (allocation_id,),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return
                release_resource_lease(
                    conn,
                    str(row[0]),
                    now_epoch_s=now_epoch_s,
                )
                conn.execute(
                    "DELETE FROM compute_allocations WHERE allocation_id=?",
                    (allocation_id,),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def allocations(
        self,
        *,
        scope: ScopeIdentity | None = None,
    ) -> tuple[ComputeAllocation, ...]:
        now_epoch_s = time()
        with self._connection() as conn:
            rows = self._active_rows(conn, now_epoch_s)
        return tuple(row for row in rows if scope is None or row.scope == scope)


__all__ = ["InMemoryComputeScheduler", "SQLiteComputeScheduler"]
