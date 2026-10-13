from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.authority.api import (
    AuthoritySnapshot,
    ResourceCapacity,
    claim_field,
    is_resource_claim,
    resource_claim,
)

from .api import (
    ComputeHost,
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
    GpuSharingMode,
    HostRuntimeSnapshot,
    HostRuntimeStatus,
)


def _host_cpu_dimension(host_id: str) -> str:
    return f"compute:{host_id}:cpu-cores"


def _host_memory_dimension(host_id: str) -> str:
    return f"compute:{host_id}:memory-bytes"


def _gpu_vram_dimension(host_id: str, gpu_id: str) -> str:
    return f"compute:{host_id}:gpu:{gpu_id}:vram-bytes"


def _gpu_token(host_id: str, gpu_id: str) -> str:
    return f"compute:{host_id}:gpu:{gpu_id}"


def compute_capacity(hosts: tuple[ComputeHost, ...]) -> ResourceCapacity:
    dimensions: dict[str, int] = {}
    for host in hosts:
        if not host.enabled:
            continue
        dimensions[_host_cpu_dimension(host.host_id)] = host.cpu_cores
        dimensions[_host_memory_dimension(host.host_id)] = host.memory_bytes
        for gpu in host.gpus:
            dimensions[_gpu_vram_dimension(host.host_id, gpu.gpu_id)] = (
                gpu.memory_bytes
            )
    return ResourceCapacity(tuple(dimensions.items()))


@dataclass(slots=True)
class _HostUsage:
    cpu_cores: int = 0
    memory_bytes: int = 0
    pending_cpu_cores: int = 0
    pending_memory_bytes: int = 0
    gpu_allocation_counts: dict[str, int] = field(default_factory=dict)
    gpu_exclusive_counts: dict[str, int] = field(default_factory=dict)
    gpu_memory_reservation_bytes: dict[str, int] = field(default_factory=dict)


def _compute_claim_attributes(claim: NoetriumUnit) -> dict[str, object] | None:
    attrs = dict(claim_field(claim, "attributes"))
    if attrs.get("kind") != "compute":
        return None
    return attrs


def _usage_index(snapshot: AuthoritySnapshot) -> dict[str, _HostUsage]:
    index: dict[str, _HostUsage] = {}
    for claim in snapshot.claims:
        attrs = _compute_claim_attributes(claim)
        if attrs is None:
            continue
        host_id = str(attrs["host_id"])
        usage = index.setdefault(host_id, _HostUsage())
        cpu_cores = int(attrs["cpu_cores"])
        memory_bytes = int(attrs["memory_bytes"])
        gpu_ids = tuple(str(v) for v in attrs.get("gpu_ids", ()))
        reservations = tuple(
            int(v) for v in attrs.get("gpu_memory_reservation_bytes", ())
        )
        sharing = GpuSharingMode(str(attrs["gpu_sharing_mode"]))
        usage.cpu_cores += cpu_cores
        usage.memory_bytes += memory_bytes
        consumer_key = attrs.get("consumer_resource_key")
        consumer_bound = bool(
            isinstance(consumer_key, str)
            and consumer_key
            and snapshot.binding_for(consumer_key) is not None
        )
        if not consumer_bound:
            usage.pending_cpu_cores += cpu_cores
            usage.pending_memory_bytes += memory_bytes
        for index_, gpu_id in enumerate(gpu_ids):
            usage.gpu_allocation_counts[gpu_id] = (
                usage.gpu_allocation_counts.get(gpu_id, 0) + 1
            )
            if sharing is GpuSharingMode.IDLE_ONLY:
                usage.gpu_exclusive_counts[gpu_id] = (
                    usage.gpu_exclusive_counts.get(gpu_id, 0) + 1
                )
            reserved = 0 if not reservations else reservations[index_]
            usage.gpu_memory_reservation_bytes[gpu_id] = (
                usage.gpu_memory_reservation_bytes.get(gpu_id, 0)
                + reserved
            )
    return index


@dataclass(frozen=True, slots=True)
class _GpuRuntimeIndex:
    devices_by_id: dict[str, GpuDeviceStatus]
    process_count_by_uuid: dict[str, int]
    processes_complete: bool


def _gpu_runtime_index(
    snapshot: GpuRuntimeSnapshot | None,
) -> _GpuRuntimeIndex | None:
    if snapshot is None or not snapshot.available:
        return None
    devices_by_id: dict[str, GpuDeviceStatus] = {}
    for device in snapshot.devices:
        devices_by_id.setdefault(device.uuid, device)
        devices_by_id.setdefault(device.index, device)
    process_count_by_uuid: dict[str, int] = {}
    for process in snapshot.processes:
        process_count_by_uuid[process.gpu_uuid] = (
            process_count_by_uuid.get(process.gpu_uuid, 0) + 1
        )
    return _GpuRuntimeIndex(
        devices_by_id,
        process_count_by_uuid,
        snapshot.processes_complete,
    )


def _host_runtime_index(
    snapshot: HostRuntimeSnapshot | None,
) -> dict[str, HostRuntimeStatus] | None:
    if snapshot is None or not snapshot.available:
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
        runtime_total_bytes
        * float(requirement.gpu_admission_headroom_fraction)
    )
    return reservation + headroom


def _placement_failure_diagnostics(
    *,
    requirement: ComputeRequirement,
    inventory_hosts: tuple[ComputeHost, ...],
    source_hosts: tuple[ComputeHost, ...],
    usage_by_host: dict[str, _HostUsage],
    runtime_index: _GpuRuntimeIndex | None,
    host_runtime_index: dict[str, HostRuntimeStatus] | None,
    excluded_gpus: frozenset[tuple[str, str]],
) -> dict[str, object]:
    """Explain one immutable placement cut without inventing new authority truth."""

    requirement_doc = {
        "cpu_cores": requirement.cpu_cores,
        "memory_bytes": requirement.memory_bytes,
        "gpu_count": requirement.gpu_count,
        "minimum_gpu_memory_bytes": requirement.minimum_gpu_memory_bytes,
        "required_gpu_free_memory_bytes": requirement.required_gpu_free_memory_bytes,
        "required_gpu_memory_fraction": requirement.required_gpu_memory_fraction,
        "gpu_admission_headroom_fraction": requirement.gpu_admission_headroom_fraction,
        "max_gpu_utilization_percent": requirement.max_gpu_utilization_percent,
        "cpu_headroom_cores": requirement.cpu_headroom_cores,
        "memory_headroom_bytes": requirement.memory_headroom_bytes,
        "max_cpu_load_ratio": requirement.max_cpu_load_ratio,
        "require_host_runtime": requirement.require_host_runtime,
        "gpu_sharing_mode": requirement.gpu_sharing_mode.value,
        "required_labels": tuple(requirement.required_labels),
    }
    host_rows: list[dict[str, object]] = []
    for host in source_hosts:
        usage = usage_by_host.get(host.host_id, _HostUsage())
        live = (
            None
            if host_runtime_index is None
            else host_runtime_index.get(host.host_id)
        )
        gpu_rows: list[dict[str, object]] = []
        for gpu in host.gpus:
            device = (
                None
                if runtime_index is None
                else runtime_index.devices_by_id.get(gpu.gpu_id)
            )
            logical_reserved = usage.gpu_memory_reservation_bytes.get(
                gpu.gpu_id,
                0,
            )
            row: dict[str, object] = {
                "gpu_id": gpu.gpu_id,
                "inventory_memory_bytes": gpu.memory_bytes,
                "logical_reserved_bytes": logical_reserved,
                "allocation_count": usage.gpu_allocation_counts.get(gpu.gpu_id, 0),
                "exclusive_count": usage.gpu_exclusive_counts.get(gpu.gpu_id, 0),
                "excluded": (host.host_id, gpu.gpu_id) in excluded_gpus,
            }
            if device is None:
                row["runtime_observed"] = False
            else:
                required_admission = _required_gpu_admission_free_bytes(
                    gpu,
                    requirement,
                    device,
                )
                runtime_total = device.memory_total_mb * 1024 * 1024
                physical_free = max(0, device.memory_free_mb * 1024 * 1024)
                observable_free = min(
                    physical_free,
                    min(gpu.memory_bytes, runtime_total),
                )
                effective_free = max(0, observable_free - logical_reserved)
                process_count = (
                    0
                    if runtime_index is None
                    else runtime_index.process_count_by_uuid.get(device.uuid, 0)
                )
                row.update(
                    {
                        "runtime_observed": True,
                        "runtime_index": device.index,
                        "runtime_uuid": device.uuid,
                        "runtime_total_bytes": runtime_total,
                        "runtime_used_bytes": device.memory_used_mb * 1024 * 1024,
                        "runtime_free_bytes": physical_free,
                        "effective_free_bytes": effective_free,
                        "utilization_percent": device.utilization_percent,
                        "process_count": process_count,
                        "required_admission_free_bytes": required_admission,
                        "memory_admissible": effective_free >= required_admission,
                        "utilization_admissible": (
                            device.utilization_percent
                            <= requirement.max_gpu_utilization_percent
                        ),
                    }
                )
            gpu_rows.append(row)
        host_rows.append(
            {
                "host_id": host.host_id,
                "cpu_cores": host.cpu_cores,
                "memory_bytes": host.memory_bytes,
                "reserved_cpu_cores": usage.cpu_cores,
                "reserved_memory_bytes": usage.memory_bytes,
                "pending_cpu_cores": usage.pending_cpu_cores,
                "pending_memory_bytes": usage.pending_memory_bytes,
                "host_runtime": (
                    None
                    if live is None
                    else {
                        "effective_cpu_cores": live.effective_cpu_cores,
                        "cpu_load_1m": live.cpu_load_1m,
                        "available_memory_bytes": live.available_memory_bytes,
                        "available_pids": live.available_pids,
                        "available_fds": live.available_fds,
                    }
                ),
                "gpus": tuple(gpu_rows),
            }
        )
    return {
        "inventory_host_count": len(inventory_hosts),
        "eligible_host_count": len(source_hosts),
        "gpu_runtime_observed": runtime_index is not None,
        "gpu_process_visibility_complete": (
            None if runtime_index is None else runtime_index.processes_complete
        ),
        "host_runtime_observed": host_runtime_index is not None,
        "requirement": requirement_doc,
        "hosts": tuple(host_rows),
    }


def _runtime_rank(
    gpu,
    requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
    *,
    logical_reserved_bytes: int,
):
    if runtime_index is None:
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


def _gpu_quality_key(rank):
    shared, utilization, free_excess, gpu_excess, _gpu_id = rank
    if shared:
        return (shared, -free_excess, utilization, gpu_excess)
    return (shared, utilization, free_excess, gpu_excess)


def _gpu_selection_key(rank):
    return (*_gpu_quality_key(rank), rank[-1])


def _gpu_numa_node(gpu) -> str | None:
    value = dict(gpu.labels).get("numa_node")
    return None if value is None or not str(value).strip() else str(value).strip()


def _select_topology_equivalent_gpus(
    eligible,
    gpu_count: int,
):
    """Choose the exact original quality optimum, then minimize NUMA spread.

    The runtime placement objective is additive per GPU.  Topology must not
    trade away a better live-pressure/memory rank, so first freeze the optimal
    quality-key multiset.  Only the cutoff equivalence class is topology-free.
    Within that class, choosing from already-used NUMA domains first and then
    from the largest remaining domains minimizes the number of NUMA domains
    exactly.  The quality cutoff uses bounded selection rather than sorting
    all eligible GPUs, giving O(G log k) work for k requested GPUs plus the
    exact NUMA tie-break over the cutoff class.
    """
    top_rows = heapq.nsmallest(
        gpu_count,
        eligible,
        key=lambda item: _gpu_selection_key(item[0]),
    )
    cutoff = _gpu_quality_key(top_rows[-1][0])
    mandatory = [
        row for row in eligible
        if _gpu_quality_key(row[0]) < cutoff
    ]
    mandatory.sort(key=lambda item: _gpu_selection_key(item[0]))
    needed = gpu_count - len(mandatory)
    if needed <= 0:
        return tuple(mandatory[:gpu_count])

    tied = [
        row for row in eligible
        if _gpu_quality_key(row[0]) == cutoff
    ]
    selected = list(mandatory)
    selected_numa = {
        numa
        for _rank, gpu in selected
        if (numa := _gpu_numa_node(gpu)) is not None
    }

    # Reuse already-paid NUMA domains first.
    same_domain_rows = [
        row for row in tied
        if _gpu_numa_node(row[1]) in selected_numa
    ]
    take = min(needed, len(same_domain_rows))
    selected.extend(
        heapq.nsmallest(
            take,
            same_domain_rows,
            key=lambda row: row[1].gpu_id,
        )
    )
    needed -= take
    if needed == 0:
        return tuple(selected)

    used_ids = {gpu.gpu_id for _rank, gpu in selected}
    groups: dict[str, list] = {}
    unknown: list = []
    for row in tied:
        if row[1].gpu_id in used_ids:
            continue
        numa = _gpu_numa_node(row[1])
        if numa is None:
            unknown.append(row)
            continue
        groups.setdefault(numa, []).append(row)

    # Minimum number of new NUMA domains is obtained greedily by domain
    # cardinality because every row in this cutoff class has identical primary
    # quality. Deterministic domain/id ordering resolves equal-cardinality ties.
    group_heap = [
        (-len(rows), numa, rows)
        for numa, rows in groups.items()
    ]
    heapq.heapify(group_heap)
    while needed > 0 and group_heap:
        _negative_size, _numa, rows = heapq.heappop(group_heap)
        take = min(needed, len(rows))
        selected.extend(
            heapq.nsmallest(
                take,
                rows,
                key=lambda row: row[1].gpu_id,
            )
        )
        needed -= take
        if needed == 0:
            return tuple(selected)

    # Unknown topology is last because it cannot prove locality. Treat each GPU
    # deterministically rather than inventing a shared domain.
    selected.extend(
        heapq.nsmallest(
            needed,
            unknown,
            key=lambda row: row[1].gpu_id,
        )
    )
    if len(selected) != gpu_count:
        raise RuntimeError("topology-equivalent GPU selection cardinality drift")
    return tuple(selected)


def _eligible_gpus(
    host: ComputeHost,
    usage: _HostUsage,
    requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
    *,
    excluded_gpus: frozenset[tuple[str, str]],
):
    rows = []
    for gpu in host.gpus:
        if (host.host_id, gpu.gpu_id) in excluded_gpus:
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
        if rank is not None:
            rows.append((rank, gpu))
    return tuple(rows)


def _placement_score(
    host: ComputeHost,
    usage: _HostUsage,
    requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
    host_runtime_index: dict[str, HostRuntimeStatus] | None,
    *,
    excluded_gpus: frozenset[tuple[str, str]],
):
    cpu_after = host.cpu_cores - usage.cpu_cores - requirement.cpu_cores
    memory_after = (
        host.memory_bytes - usage.memory_bytes - requirement.memory_bytes
    )
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
        effective_cpu = min(
            float(host.cpu_cores),
            float(live.effective_cpu_cores),
        )
        if effective_cpu <= 0:
            return None
        projected_cpu_load = (
            live.cpu_load_1m
            + usage.pending_cpu_cores
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
            and projected_cpu_load + requirement.cpu_headroom_cores
            > effective_cpu
        ):
            return None
        if (
            usage.pending_memory_bytes
            + requirement.memory_bytes
            + requirement.memory_headroom_bytes
            > live.available_memory_bytes
        ):
            return None
        memory_pressure = 1.0 - min(
            1.0,
            live.available_memory_bytes / max(1, host.memory_bytes),
        )
        runtime_rank = (0, cpu_load_ratio, memory_pressure)

    if requirement.gpu_count == 0:
        accelerator_penalty = 0 if not host.gpus else 1
        accelerator_bytes = sum(gpu.memory_bytes for gpu in host.gpus)
        score = (
            runtime_rank,
            accelerator_penalty,
            accelerator_bytes,
            cpu_after / host.cpu_cores
            + memory_after / host.memory_bytes,
            cpu_after,
            memory_after,
            host.host_id,
        )
        return score, ()

    eligible = _eligible_gpus(
        host,
        usage,
        requirement,
        runtime_index,
        excluded_gpus=excluded_gpus,
    )
    if len(eligible) < requirement.gpu_count:
        return None
    selected_rows = (
        (min(eligible, key=lambda item: _gpu_selection_key(item[0])),)
        if requirement.gpu_count == 1
        else _select_topology_equivalent_gpus(
            eligible,
            requirement.gpu_count,
        )
    )
    selected = tuple(gpu for _rank, gpu in selected_rows)
    shared_count = sum(rank[0] for rank, _gpu in selected_rows)
    utilization = sum(rank[1] for rank, _gpu in selected_rows)
    free_excess = sum(rank[2] for rank, _gpu in selected_rows)
    gpu_excess = sum(
        gpu.memory_bytes - requirement.minimum_gpu_memory_bytes
        for gpu in selected
    )
    selected_memory = sum(gpu.memory_bytes for gpu in selected)
    eligible_memory = sum(gpu.memory_bytes for _rank, gpu in eligible)
    gpu_runtime_score = (
        shared_count,
        -free_excess if shared_count else utilization,
        utilization if shared_count else free_excess,
    )
    score = (
        gpu_runtime_score,
        runtime_rank,
        gpu_excess,
        len(eligible) - requirement.gpu_count,
        eligible_memory - selected_memory,
        cpu_after / host.cpu_cores
        + memory_after / host.memory_bytes,
        cpu_after,
        memory_after,
        host.host_id,
    )
    return score, tuple(gpu.gpu_id for gpu in selected)


def _gpu_memory_reservations(
    host: ComputeHost,
    gpu_ids: tuple[str, ...],
    requirement: ComputeRequirement,
    runtime_index: _GpuRuntimeIndex | None,
) -> tuple[int, ...]:
    if not gpu_ids:
        return ()
    if runtime_index is None:
        raise ComputePlacementUnavailable(requirement)
    gpu_map = {gpu.gpu_id: gpu for gpu in host.gpus}
    reservations = []
    for gpu_id in gpu_ids:
        device = runtime_index.devices_by_id.get(gpu_id)
        if device is None:
            raise ComputePlacementUnavailable(requirement)
        reservations.append(
            _required_gpu_memory_bytes(
                gpu_map[gpu_id],
                requirement,
                device,
            )
        )
    return tuple(reservations)



@dataclass(frozen=True, slots=True)
class ComputePlacement:
    """Read-only projection of one admitted compute claim."""

    claim_id: str
    resource_key: str
    host_id: str
    cpu_cores: int
    memory_bytes: int
    gpu_ids: tuple[str, ...]
    gpu_sharing_mode: GpuSharingMode
    gpu_memory_reservation_bytes: tuple[int, ...]
    consumer_resource_key: str

    def __post_init__(self) -> None:
        if not self.claim_id.strip() or not self.resource_key.strip() or not self.host_id.strip():
            raise ValueError("compute placement identity is required")
        if self.cpu_cores < 1 or self.memory_bytes < 1:
            raise ValueError("compute placement CPU/memory must be positive")
        if len(set(self.gpu_ids)) != len(self.gpu_ids):
            raise ValueError("compute placement GPU ids must be unique")
        if len(self.gpu_memory_reservation_bytes) != len(self.gpu_ids):
            raise ValueError("compute placement GPU reservations must align with ids")
        if any(value < 0 for value in self.gpu_memory_reservation_bytes):
            raise ValueError("compute placement GPU reservations must be non-negative")
        if not isinstance(self.gpu_sharing_mode, GpuSharingMode):
            raise TypeError("compute placement sharing mode must be typed")
        if not self.consumer_resource_key.strip():
            raise ValueError("compute placement consumer resource is required")


def compute_placement_from_claim(claim: NoetriumUnit) -> ComputePlacement:
    if not is_resource_claim(claim):
        raise TypeError("compute placement requires resource.claim Unit")
    attrs = dict(claim_field(claim, "attributes"))
    if attrs.get("kind") != "compute":
        raise ValueError("resource claim is not a compute placement")
    try:
        host_id = str(attrs["host_id"])
        cpu_cores = int(attrs["cpu_cores"])
        memory_bytes = int(attrs["memory_bytes"])
        gpu_ids = tuple(str(value) for value in attrs.get("gpu_ids", ()))
        sharing = GpuSharingMode(str(attrs["gpu_sharing_mode"]))
        reservations = tuple(
            int(value) for value in attrs.get("gpu_memory_reservation_bytes", ())
        )
        consumer = str(attrs["consumer_resource_key"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("compute claim attributes are malformed") from exc
    return ComputePlacement(
        claim_id=claim_field(claim, "claim_id"),
        resource_key=claim_field(claim, "resource_key"),
        host_id=host_id,
        cpu_cores=cpu_cores,
        memory_bytes=memory_bytes,
        gpu_ids=gpu_ids,
        gpu_sharing_mode=sharing,
        gpu_memory_reservation_bytes=reservations,
        consumer_resource_key=consumer,
    )

def compute_claim_candidates(
    *,
    resource_key: str,
    holder_key: str,
    generation: int,
    consumer_resource_key: str,
    requirement: ComputeRequirement,
    hosts: tuple[ComputeHost, ...],
    authority: AuthoritySnapshot,
    placement_scope: NoetriumUnit | None = None,
    gpu_runtime: GpuRuntimeSnapshot | None = None,
    host_runtime: HostRuntimeSnapshot | None = None,
    excluded_gpus: frozenset[tuple[str, str]] = frozenset(),
    owner_scope: NoetriumUnit,
    scope_generation: int,
    scope_lease_id: str | None,
    owner_lease_id: str | None = None,
) -> tuple[NoetriumUnit, ...]:
    if not resource_key.strip() or not holder_key.strip():
        raise ValueError("compute claim identity is required")
    if type(generation) is not int or generation < 1:
        raise ValueError("compute claim generation must be positive")
    if not consumer_resource_key.strip():
        raise ValueError("compute claim consumer resource key is required")
    if not isinstance(requirement, ComputeRequirement):
        raise TypeError("compute claim placement requires ComputeRequirement")
    if type(owner_scope) is not NoetriumUnit:
        raise TypeError("compute claim owner_scope must be NoetriumUnit")
    if type(scope_generation) is not int or scope_generation < 1:
        raise ValueError("compute claim scope_generation must be positive")
    if scope_lease_id is not None and (
        type(scope_lease_id) is not str
        or not scope_lease_id.strip()
        or scope_lease_id != scope_lease_id.strip()
    ):
        raise ValueError("compute claim scope_lease_id must be canonical text or None")
    if owner_lease_id is not None and (
        type(owner_lease_id) is not str
        or not owner_lease_id.strip()
        or owner_lease_id != owner_lease_id.strip()
    ):
        raise ValueError("compute claim owner_lease_id must be canonical text or None")
    required_labels = dict(requirement.required_labels)
    source_hosts = tuple(
        host
        for host in hosts
        if host.enabled
        and (placement_scope is None or host.scope == placement_scope)
        and not any(
            dict(host.labels).get(key) != value
            for key, value in required_labels.items()
        )
    )
    usage_by_host = _usage_index(authority)
    runtime_index = _gpu_runtime_index(gpu_runtime)
    host_runtime_index = _host_runtime_index(host_runtime)
    rows = []
    for host in source_hosts:
        placement = _placement_score(
            host,
            usage_by_host.get(host.host_id, _HostUsage()),
            requirement,
            runtime_index,
            host_runtime_index,
            excluded_gpus=excluded_gpus,
        )
        if placement is None:
            continue
        score, gpu_ids = placement
        rows.append((score, host, gpu_ids))
    rows.sort(key=lambda row: row[0])
    claims: list[NoetriumUnit] = []
    for _score, host, gpu_ids in rows:
        reservations = _gpu_memory_reservations(
            host,
            gpu_ids,
            requirement,
            runtime_index,
        )
        amounts = [
            (_host_cpu_dimension(host.host_id), requirement.cpu_cores),
            (_host_memory_dimension(host.host_id), requirement.memory_bytes),
        ]
        for gpu_id, reservation in zip(
            gpu_ids,
            reservations,
            strict=True,
        ):
            if reservation > 0:
                amounts.append(
                    (
                        _gpu_vram_dimension(host.host_id, gpu_id),
                        reservation,
                    )
                )
        gpu_tokens = tuple(
            _gpu_token(host.host_id, gpu_id) for gpu_id in gpu_ids
        )
        shared = (
            gpu_tokens
            if requirement.gpu_sharing_mode
            is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
            else ()
        )
        exclusive = (
            gpu_tokens
            if requirement.gpu_sharing_mode is GpuSharingMode.IDLE_ONLY
            else ()
        )
        attributes = {
            "kind": "compute",
            "host_id": host.host_id,
            "cpu_cores": requirement.cpu_cores,
            "memory_bytes": requirement.memory_bytes,
            "gpu_ids": list(gpu_ids),
            "gpu_sharing_mode": requirement.gpu_sharing_mode.value,
            "gpu_memory_reservation_bytes": list(reservations),
            "consumer_resource_key": consumer_resource_key,
        }
        if owner_lease_id is not None:
            attributes["owner_lease_id"] = owner_lease_id
        claim_id = "compute:" + canonical_digest(
            {
                "resource_key": resource_key,
                "generation": generation,
                "holder_key": holder_key,
                "attributes": attributes,
            }
        )
        claims.append(
            resource_claim(
                claim_id=claim_id,
                resource_key=resource_key,
                holder_key=holder_key,
                generation=generation,
                owner_scope=owner_scope,
                scope_generation=scope_generation,
                scope_lease_id=scope_lease_id,
                owner_lease_id=owner_lease_id,
                amounts=tuple(amounts),
                shared=shared,
                exclusive=exclusive,
                attributes=attributes,
            )
        )
    if not claims:
        raise ComputePlacementUnavailable(
            requirement,
            diagnostics=_placement_failure_diagnostics(
                requirement=requirement,
                inventory_hosts=hosts,
                source_hosts=source_hosts,
                usage_by_host=usage_by_host,
                runtime_index=runtime_index,
                host_runtime_index=host_runtime_index,
                excluded_gpus=excluded_gpus,
            ),
        )
    return tuple(claims)


__all__ = [
    "ComputePlacement",
    "compute_capacity",
    "compute_claim_candidates",
    "compute_placement_from_claim",
]
