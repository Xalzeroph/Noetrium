from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
from pathlib import Path
import sqlite3
from time import time

from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocation, ComputeBindingProof, ComputeHost, ComputeInventoryPort, ComputePlacementUnavailable, ComputeRequirement,
    GpuDeviceStatus, GpuRuntimeObserverPort, GpuRuntimeSnapshot, GpuSharingMode,
    HostRuntimeObserverPort, HostRuntimeSnapshot, HostRuntimeStatus,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseClockPort, LeaseState, ResourceIdentity, ResourceKind, ResourceLease, ResourceLeaseConflict,
    ResourceOwner, ResourceOwnership,
)
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    begin_immediate_sqlite_transaction,
    durable_sqlite_connection,
    rollback_sqlite_writer,
)
from noetrium_platform.infrastructure.resources.sqlite_resource import (
    acquire_resource_lease,
    authoritative_lease_now,
    ensure_resource_owner,
    ensure_resource_schema,
    reconcile_expired_resource_leases,
    release_resource_lease,
    renew_resource_lease,
)



def _lease_now(now: float | None) -> float:
    value = time() if now is None else float(now)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("compute lease observation time must be finite and positive")
    return value






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
        and current.gpu_sharing_mode is expected.gpu_sharing_mode
        and current.gpu_memory_reservation_bytes
        == expected.gpu_memory_reservation_bytes
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
    unbound_cpu_cores: int = 0
    unbound_memory_bytes: int = 0
    gpu_allocation_counts: dict[str, int] = field(default_factory=dict)
    gpu_exclusive_counts: dict[str, int] = field(default_factory=dict)
    gpu_memory_reservation_bytes: dict[str, int] = field(default_factory=dict)


def _increment_count(values: dict[str, int], key: str) -> dict[str, int]:
    updated = dict(values)
    updated[key] = updated.get(key, 0) + 1
    return updated


def _decrement_count(values: dict[str, int], key: str) -> dict[str, int]:
    updated = dict(values)
    current = updated.get(key, 0)
    if current <= 0:
        raise RuntimeError(f"compute GPU usage index underflow: {key}")
    if current == 1:
        updated.pop(key, None)
    else:
        updated[key] = current - 1
    return updated


def _add_allocation_usage(
    usage: _HostUsage,
    allocation: ComputeAllocation,
) -> _HostUsage:
    allocation_counts = dict(usage.gpu_allocation_counts)
    exclusive_counts = dict(usage.gpu_exclusive_counts)
    gpu_memory_reservations = dict(usage.gpu_memory_reservation_bytes)
    for index, gpu_id in enumerate(allocation.gpu_ids):
        allocation_counts = _increment_count(allocation_counts, gpu_id)
        if allocation.gpu_sharing_mode is GpuSharingMode.IDLE_ONLY:
            exclusive_counts = _increment_count(exclusive_counts, gpu_id)
        reserved = (
            0
            if not allocation.gpu_memory_reservation_bytes
            else allocation.gpu_memory_reservation_bytes[index]
        )
        gpu_memory_reservations[gpu_id] = (
            gpu_memory_reservations.get(gpu_id, 0) + reserved
        )
    return _HostUsage(
        cpu_cores=usage.cpu_cores + allocation.cpu_cores,
        memory_bytes=usage.memory_bytes + allocation.memory_bytes,
        unbound_cpu_cores=(
            usage.unbound_cpu_cores
            + (0 if allocation.is_bound else allocation.cpu_cores)
        ),
        unbound_memory_bytes=(
            usage.unbound_memory_bytes
            + (0 if allocation.is_bound else allocation.memory_bytes)
        ),
        gpu_allocation_counts=allocation_counts,
        gpu_exclusive_counts=exclusive_counts,
        gpu_memory_reservation_bytes=gpu_memory_reservations,
    )








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


def _required_gpu_memory_bytes(
    gpu,
    requirement: ComputeRequirement,
    device: GpuDeviceStatus,
) -> int:
    runtime_total_bytes = device.memory_total_mb * 1024 * 1024
    fractional_requirement = (
        0
        if requirement.required_gpu_memory_fraction is None
        else math.ceil(
            max(gpu.memory_bytes, runtime_total_bytes)
            * requirement.required_gpu_memory_fraction
        )
    )
    return max(
        requirement.required_gpu_free_memory_bytes,
        fractional_requirement,
    )


def _required_gpu_admission_free_bytes(
    gpu,
    requirement: ComputeRequirement,
    device: GpuDeviceStatus,
) -> int:
    reservation = _required_gpu_memory_bytes(gpu, requirement, device)
    runtime_total_bytes = device.memory_total_mb * 1024 * 1024
    headroom = math.ceil(
        runtime_total_bytes * float(requirement.gpu_admission_headroom_fraction)
    )
    return reservation + headroom


def _runtime_rank(
    gpu,
    requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
    *,
    logical_reserved_bytes: int = 0,
):
    if runtime_index is None:
        # GPU placement always depends on live external usage facts.
        return None
    device = runtime_index.devices_by_id.get(gpu.gpu_id)
    if device is None:
        return None
    required_free_bytes = _required_gpu_admission_free_bytes(
        gpu,
        requirement,
        device,
    )
    runtime_total_bytes = device.memory_total_mb * 1024 * 1024
    physical_free_bytes = max(0, device.memory_free_mb * 1024 * 1024)
    logical_total_bytes = min(gpu.memory_bytes, runtime_total_bytes)
    observable_free_bytes = min(physical_free_bytes, logical_total_bytes)
    # A live allocation owns its declared VRAM reservation until release, even
    # after binding. Runtime telemetry may lag behind a newly bound process, so
    # subtracting only from logical total can temporarily reuse capacity already
    # promised by another allocation. The durable reservation is authoritative.
    free_bytes = max(0, observable_free_bytes - logical_reserved_bytes)
    if free_bytes < required_free_bytes:
        return None
    if device.utilization_percent > requirement.max_gpu_utilization_percent:
        return None
    process_count = runtime_index.process_count_by_uuid.get(device.uuid, 0)
    process_visibility_unknown = not runtime_index.processes_complete
    if (
        process_count or process_visibility_unknown
    ) and requirement.gpu_sharing_mode is GpuSharingMode.IDLE_ONLY:
        return None
    return (
        1 if process_count or process_visibility_unknown else 0,
        device.utilization_percent,
        free_bytes - required_free_bytes,
        gpu.memory_bytes - requirement.minimum_gpu_memory_bytes,
        gpu.gpu_id,
    )


def _eligible_gpus(
    host: ComputeHost,
    usage: _HostUsage,
    requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
    *,
    quarantined_gpus: frozenset[tuple[str, str]] = frozenset(),
):
    rows = []
    for gpu in host.gpus:
        if (host.host_id, gpu.gpu_id) in quarantined_gpus:
            continue
        allocation_count = usage.gpu_allocation_counts.get(gpu.gpu_id, 0)
        exclusive_count = usage.gpu_exclusive_counts.get(gpu.gpu_id, 0)
        if requirement.gpu_sharing_mode is GpuSharingMode.IDLE_ONLY:
            if allocation_count:
                continue
        elif exclusive_count:
            continue
        if gpu.memory_bytes < requirement.minimum_gpu_memory_bytes:
            continue
        rank = _runtime_rank(
            gpu,
            requirement,
            runtime_index,
            logical_reserved_bytes=usage.gpu_memory_reservation_bytes.get(
                gpu.gpu_id,
                0,
            ),
        )
        if rank is None:
            continue
        rows.append((rank, gpu))
    rows.sort(key=lambda item: item[0])
    return tuple(rows)

def _placement_score(
    host: ComputeHost, usage: _HostUsage, requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
    host_runtime_index: dict[str, HostRuntimeStatus] | None,
    *,
    quarantined_gpus: frozenset[tuple[str, str]] = frozenset(),
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
        projected_unbound_cpu = usage.unbound_cpu_cores
        projected_cpu_load = (
            live.cpu_load_1m
            + projected_unbound_cpu
            + requirement.cpu_cores
        )
        cpu_load_ratio = projected_cpu_load / effective_cpu
        if (
            requirement.max_cpu_load_ratio is not None
            and cpu_load_ratio > requirement.max_cpu_load_ratio
        ):
            return None
        if (
            requirement.cpu_headroom_cores > 0
            and live.cpu_load_1m
            + projected_unbound_cpu
            + requirement.cpu_cores
            + requirement.cpu_headroom_cores
            > effective_cpu
        ):
            return None
        if (
            usage.unbound_memory_bytes
            + requirement.memory_bytes
            + requirement.memory_headroom_bytes
            > live.available_memory_bytes
        ):
            return None
        memory_pressure = 1.0 - min(
            1.0, live.available_memory_bytes / max(1, host.memory_bytes)
        )
        runtime_rank = (0, cpu_load_ratio, memory_pressure)
    eligible = _eligible_gpus(
        host,
        usage,
        requirement,
        runtime_index,
        quarantined_gpus=quarantined_gpus,
    )
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
    *,
    quarantined_gpus: frozenset[tuple[str, str]] = frozenset(),
):
    if (
        requirement.gpu_count > 0
        and requirement.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
        and requirement.required_gpu_free_memory_bytes <= 0
        and requirement.required_gpu_memory_fraction is None
    ):
        raise ValueError(
            "shared GPU scheduling requires a positive free-memory reservation "
            "or required_gpu_memory_fraction"
        )
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
            quarantined_gpus=quarantined_gpus,
        )
        if placement is not None:
            score, gpu_ids = placement
            rows.append((score, host, gpu_ids))
    rows.sort(key=lambda item: item[0])
    return tuple(rows)


def _gpu_memory_reservations(
    host: ComputeHost,
    gpu_ids: tuple[str, ...],
    requirement: ComputeRequirement,
    runtime_snapshot: GpuRuntimeSnapshot | None,
) -> tuple[int, ...]:
    if not gpu_ids:
        return ()
    runtime_index = _gpu_runtime_index(runtime_snapshot)
    if runtime_index is None:
        raise ComputePlacementUnavailable(requirement)
    gpu_map = {gpu.gpu_id: gpu for gpu in host.gpus}
    reservations: list[int] = []
    for gpu_id in gpu_ids:
        gpu = gpu_map[gpu_id]
        device = runtime_index.devices_by_id.get(gpu_id)
        if device is None:
            raise ComputePlacementUnavailable(requirement)
        reservations.append(
            _required_gpu_memory_bytes(gpu, requirement, device)
        )
    return tuple(reservations)


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


class ComputeScheduler:
    """Crash-safe compute placement over the canonical SQLite lease authority."""

    SCHEMA_VERSION = 4

    def __init__(
        self,
        path: str | Path,
        inventory: ComputeInventoryPort,
        *,
        timeout_seconds: float = 30.0,
        clock: LeaseClockPort,
        gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
        host_runtime_observer: HostRuntimeObserverPort | None = None,
    ) -> None:
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._inventory = inventory
        if not isinstance(clock, LeaseClockPort):
            raise TypeError("SQLite compute scheduler requires LeaseClockPort")
        self._clock = clock
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
            _lease_now(explicit_now)
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
                "unsupported ComputeScheduler schema; recreate the v4 authority store"
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
            "gpu_ids_json TEXT NOT NULL,"
            "gpu_sharing_mode TEXT NOT NULL,"
            "gpu_memory_reservation_json TEXT NOT NULL,"
            "binding_proof_digest TEXT,"
            "binding_binder_identity_digest TEXT,"
            "binding_evidence_ref TEXT,"
            "bound_at_epoch_s REAL,"
            "lease_id TEXT NOT NULL UNIQUE REFERENCES resource_leases(lease_id))"
        )
        conn.execute("DROP TABLE IF EXISTS compute_allocation_fencing")

    @staticmethod
    def _gpu_json(gpu_ids: tuple[str, ...]) -> str:
        return json.dumps(list(gpu_ids), sort_keys=False, separators=(",", ":"))
    _SELECT = (
        "c.allocation_id,i.scope_kind,i.scope_id,c.host_id,c.cpu_cores,c.memory_bytes,"
        "c.gpu_ids_json,c.gpu_sharing_mode,c.gpu_memory_reservation_json,"
        "c.binding_proof_digest,c.binding_binder_identity_digest,"
        "c.binding_evidence_ref,c.bound_at_epoch_s,"
        "l.lease_id,l.holder_generation,l.fencing_token,l.expires_at_epoch_s"
    )

    @classmethod
    def _decode_row(cls, row: tuple[object, ...]) -> ComputeAllocation:
        gpu_value = json.loads(str(row[6]))
        reservation_value = json.loads(str(row[8]))
        if (
            not isinstance(gpu_value, list)
            or not all(isinstance(item, str) for item in gpu_value)
        ):
            raise RuntimeError("compute allocation GPU payload is corrupt")
        if (
            not isinstance(reservation_value, list)
            or not all(
                type(item) is int and item >= 0
                for item in reservation_value
            )
        ):
            raise RuntimeError(
                "compute allocation GPU reservation payload is corrupt"
            )
        return ComputeAllocation(
            allocation_id=str(row[0]),
            scope=ScopeIdentity(ScopeKind(str(row[1])), str(row[2])),
            host_id=str(row[3]),
            cpu_cores=int(row[4]),
            memory_bytes=int(row[5]),
            gpu_ids=tuple(gpu_value),
            lease_fencing_token=int(row[15]),
            lease_expires_at_epoch_s=(
                None if row[16] is None else float(row[16])
            ),
            binding_proof_digest=(
                None if row[9] is None else str(row[9])
            ),
            binding_binder_identity_digest=(
                None if row[10] is None else str(row[10])
            ),
            binding_evidence_ref=(
                None if row[11] is None else str(row[11])
            ),
            bound_at_epoch_s=(
                None if row[12] is None else float(row[12])
            ),
            gpu_sharing_mode=GpuSharingMode(str(row[7])),
            gpu_memory_reservation_bytes=tuple(reservation_value),
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
    def _usage(
        rows: tuple[ComputeAllocation, ...],
        host_id: str,
    ) -> _HostUsage:
        usage = _HostUsage()
        for row in rows:
            if row.host_id == host_id:
                usage = _add_allocation_usage(usage, row)
        return usage

    def _placements(
        self,
        rows: tuple[ComputeAllocation, ...],
        requirement: ComputeRequirement,
        scope: ScopeIdentity | None,
        runtime_snapshot: GpuRuntimeSnapshot | None,
        host_runtime_snapshot: HostRuntimeSnapshot | None,
        *,
        quarantined_gpus: frozenset[tuple[str, str]] = frozenset(),
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
            quarantined_gpus=quarantined_gpus,
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
            begin_immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                now_epoch_s = self._authority_now(conn, None)
                _converged, pending = self._cleanup_expired(
                    conn,
                    now_epoch_s,
                    runtime_snapshot,
                )
                rows = self._capacity_rows(conn)
                conn.commit()
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute candidates",
                )
                raise
        quarantined_gpus = frozenset(
            (row.host_id, gpu_id)
            for row in pending
            for gpu_id in row.gpu_ids
        )
        return tuple(
            host for _score, host, _gpu_ids
            in self._placements(
                rows,
                requirement,
                scope,
                runtime_snapshot,
                host_runtime_snapshot,
                quarantined_gpus=quarantined_gpus,
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
                quarantined_gpus = frozenset(
                    (row.host_id, gpu_id)
                    for row in pending
                    for gpu_id in row.gpu_ids
                )
                placements = self._placements(
                    rows,
                    requirement,
                    scope if placement_scope is None else placement_scope,
                    runtime_snapshot,
                    host_runtime_snapshot,
                    quarantined_gpus=quarantined_gpus,
                )
                if not placements:
                    required_labels = dict(requirement.required_labels)
                    placement_identity = (
                        scope if placement_scope is None else placement_scope
                    )
                    eligible_host_ids = {
                        host.host_id
                        for host in self._inventory.list_hosts(
                            scope=placement_identity
                        )
                        if host.enabled
                        and not any(
                            dict(host.labels).get(key) != value
                            for key, value in required_labels.items()
                        )
                    }
                    blocking_pending = tuple(
                        row
                        for row in pending
                        if row.gpu_ids and row.host_id in eligible_host_ids
                    )
                    if requirement.gpu_count and blocking_pending:
                        without_quarantine = self._placements(
                            rows,
                            requirement,
                            placement_identity,
                            runtime_snapshot,
                            host_runtime_snapshot,
                        )
                        if without_quarantine:
                            raise ComputePhysicalConvergencePending(
                                blocking_pending
                            )
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
                gpu_reservations = _gpu_memory_reservations(
                    host,
                    gpu_ids,
                    requirement,
                    runtime_snapshot,
                )
                conn.execute(
                    "INSERT INTO compute_allocations("
                    "allocation_id,host_id,cpu_cores,memory_bytes,gpu_ids_json,"
                    "gpu_sharing_mode,gpu_memory_reservation_json,lease_id) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        allocation_id,
                        host.host_id,
                        requirement.cpu_cores,
                        requirement.memory_bytes,
                        self._gpu_json(gpu_ids),
                        requirement.gpu_sharing_mode.value,
                        self._gpu_json(gpu_reservations),
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
                    gpu_sharing_mode=requirement.gpu_sharing_mode,
                    gpu_memory_reservation_bytes=gpu_reservations,
                )
                conn.commit()
                return allocation
            except ComputePhysicalConvergencePending as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute scheduler pending convergence",
                )
                raise
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute scheduler",
                )
                raise
    @staticmethod
    def _validate_binding_proof(
        current: ComputeAllocation,
        proof: ComputeBindingProof,
    ) -> str:
        if type(proof) is not ComputeBindingProof:
            raise TypeError("compute binding requires ComputeBindingProof")
        if (
            proof.allocation_id != current.allocation_id
            or proof.host_id != current.host_id
            or proof.gpu_ids != current.gpu_ids
            or proof.lease_fencing_token != current.lease_fencing_token
        ):
            raise ResourceLeaseConflict(
                f"compute binding proof does not match allocation generation: "
                f"{current.allocation_id}"
            )
        return proof.digest()

    def confirm_bound(
        self,
        proof: ComputeBindingProof,
    ) -> ComputeAllocation:
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                now_epoch_s = self._authority_now(conn, None)
                current = self._active_row(
                    conn,
                    proof.allocation_id,
                    now_epoch_s,
                )
                if current is None:
                    raise ResourceLeaseConflict(
                        f"compute binding lost active allocation: "
                        f"{proof.allocation_id}"
                    )
                proof_digest = self._validate_binding_proof(current, proof)
                if current.binding_proof_digest is not None:
                    if current.binding_proof_digest == proof_digest:
                        conn.commit()
                        return current
                    raise ResourceLeaseConflict(
                        f"compute allocation already bound: {proof.allocation_id}"
                    )
                updated = conn.execute(
                    "UPDATE compute_allocations SET "
                    "binding_proof_digest=?,binding_binder_identity_digest=?,"
                    "binding_evidence_ref=?,bound_at_epoch_s=? "
                    "WHERE allocation_id=? AND binding_proof_digest IS NULL",
                    (
                        proof_digest,
                        proof.binder_identity_digest,
                        proof.evidence_ref,
                        proof.observed_at_epoch_s,
                        proof.allocation_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise ResourceLeaseConflict(
                        f"compute binding lost unbound generation: "
                        f"{proof.allocation_id}"
                    )
                row = self._active_row(
                    conn,
                    proof.allocation_id,
                    now_epoch_s,
                )
                if row is None:
                    raise ResourceLeaseConflict(
                        f"compute binding disappeared before commit: "
                        f"{proof.allocation_id}"
                    )
                conn.commit()
                return row
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute binding",
                )
                raise

    def replace_bound(
        self,
        proof: ComputeBindingProof,
        *,
        previous_binding_proof_digest: str,
    ) -> ComputeAllocation:
        if (
            type(previous_binding_proof_digest) is not str
            or len(previous_binding_proof_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in previous_binding_proof_digest
            )
        ):
            raise ValueError(
                "previous compute binding proof digest must be canonical SHA-256"
            )
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                now_epoch_s = self._authority_now(conn, None)
                current = self._active_row(
                    conn,
                    proof.allocation_id,
                    now_epoch_s,
                )
                if current is None:
                    raise ResourceLeaseConflict(
                        f"compute binding replacement lost active allocation: "
                        f"{proof.allocation_id}"
                    )
                proof_digest = self._validate_binding_proof(current, proof)
                if current.binding_proof_digest != previous_binding_proof_digest:
                    raise ResourceLeaseConflict(
                        f"compute binding replacement lost prior generation: "
                        f"{proof.allocation_id}"
                    )
                if current.binding_binder_identity_digest == proof.binder_identity_digest:
                    raise ResourceLeaseConflict(
                        f"compute binding replacement requires a new binder generation: "
                        f"{proof.allocation_id}"
                    )
                updated = conn.execute(
                    "UPDATE compute_allocations SET "
                    "binding_proof_digest=?,binding_binder_identity_digest=?,"
                    "binding_evidence_ref=?,bound_at_epoch_s=? "
                    "WHERE allocation_id=? AND binding_proof_digest=?",
                    (
                        proof_digest,
                        proof.binder_identity_digest,
                        proof.evidence_ref,
                        proof.observed_at_epoch_s,
                        proof.allocation_id,
                        previous_binding_proof_digest,
                    ),
                )
                if updated.rowcount != 1:
                    raise ResourceLeaseConflict(
                        f"compute binding replacement lost CAS authority: "
                        f"{proof.allocation_id}"
                    )
                row = self._active_row(
                    conn,
                    proof.allocation_id,
                    now_epoch_s,
                )
                if row is None:
                    raise ResourceLeaseConflict(
                        f"compute binding replacement disappeared before commit: "
                        f"{proof.allocation_id}"
                    )
                conn.commit()
                return row
            except BaseException as primary:
                rollback_sqlite_writer(
                    conn,
                    primary,
                    label="compute binding replacement",
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
        """Release exact live-owner bookkeeping after upper teardown converged."""
        if type(allocation) is not ComputeAllocation:
            raise TypeError("compute release requires ComputeAllocation")
        with self._connection() as conn:
            begin_immediate_sqlite_transaction(conn, timeout_seconds=self.timeout_seconds)
            try:
                now_epoch_s = self._authority_now(conn, None)
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
        """Retire one exact generation after upper recovery proves convergence."""

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
    "ComputeScheduler",
]
