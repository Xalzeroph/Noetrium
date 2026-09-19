from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.infrastructure.resources.compute.api import GpuSharingMode
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority


class ModelCapacityMode(StrEnum):
    QUALIFIED_SHARED = "qualified-shared"


def _labels(value: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    if type(value) is not tuple:
        raise TypeError("resource labels must be a tuple")
    rows: list[tuple[str, str]] = []
    for row in value:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError("resource labels must contain key/value pairs")
        key, item = row
        if type(key) is not str or not key.strip() or type(item) is not str or not item.strip():
            raise ValueError("resource labels must contain non-empty strings")
        rows.append((key, item))
    if len({key for key, _ in rows}) != len(rows):
        raise ValueError("resource label keys must be unique")
    if tuple(sorted(rows)) != value:
        raise ValueError("resource labels must be canonically sorted")
    return value


@dataclass(frozen=True, slots=True)
class ComputeDemand:
    cpu_cores: int = 1
    memory_bytes: int = 1
    gpu_count: int = 0
    minimum_gpu_memory_bytes: int = 0
    gpu_memory_reservation_bytes_per_device: int = 0
    gpu_memory_headroom_bytes: int = 0
    max_gpu_utilization_percent: int = 100
    gpu_sharing_mode: GpuSharingMode = GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
    cpu_headroom_cores: int = 0
    memory_headroom_bytes: int = 0
    max_cpu_load_ratio: float = 1.0
    require_host_runtime: bool = True
    required_labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if type(self.cpu_cores) is not int or self.cpu_cores < 1:
            raise ValueError("compute demand cpu_cores must be positive")
        if type(self.memory_bytes) is not int or self.memory_bytes < 1:
            raise ValueError("compute demand memory_bytes must be positive")
        if type(self.gpu_count) is not int or self.gpu_count < 0:
            raise ValueError("compute demand gpu_count must be non-negative")
        if type(self.minimum_gpu_memory_bytes) is not int or self.minimum_gpu_memory_bytes < 0:
            raise ValueError("compute demand minimum_gpu_memory_bytes must be non-negative")
        if (
            type(self.gpu_memory_reservation_bytes_per_device) is not int
            or self.gpu_memory_reservation_bytes_per_device < 0
            or type(self.gpu_memory_headroom_bytes) is not int
            or self.gpu_memory_headroom_bytes < 0
        ):
            raise ValueError("compute demand GPU reservation/headroom must be non-negative")
        if not 0 <= self.max_gpu_utilization_percent <= 100:
            raise ValueError("compute demand max_gpu_utilization_percent must be between 0 and 100")
        if type(self.cpu_headroom_cores) is not int or self.cpu_headroom_cores < 0:
            raise ValueError("compute demand cpu_headroom_cores must be non-negative")
        if type(self.memory_headroom_bytes) is not int or self.memory_headroom_bytes < 0:
            raise ValueError("compute demand memory_headroom_bytes must be non-negative")
        if (
            isinstance(self.max_cpu_load_ratio, bool)
            or not isinstance(self.max_cpu_load_ratio, (int, float))
            or self.max_cpu_load_ratio <= 0
        ):
            raise ValueError("compute demand max_cpu_load_ratio must be positive")
        if type(self.require_host_runtime) is not bool:
            raise TypeError("compute demand require_host_runtime must be bool")
        if not isinstance(self.gpu_sharing_mode, GpuSharingMode):
            raise TypeError("compute demand gpu_sharing_mode must be GpuSharingMode")
        if self.gpu_count == 0 and (
            self.gpu_memory_reservation_bytes_per_device or self.gpu_memory_headroom_bytes
        ):
            raise ValueError("compute demand without GPUs cannot reserve GPU memory")
        if (
            self.gpu_count > 0
            and self.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
            and self.gpu_memory_reservation_bytes_per_device <= 0
        ):
            raise ValueError("shared GPU demand requires a positive per-device memory reservation")
        _labels(self.required_labels)


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    policy_id: str
    compute: ComputeDemand | None = None
    model_capacity_mode: ModelCapacityMode = ModelCapacityMode.QUALIFIED_SHARED
    execution_priority: ExecutionPriority = ExecutionPriority.NORMAL
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.policy_id) is not str or not self.policy_id.strip():
            raise ValueError("resource policy_id must be non-empty")
        if self.compute is not None and not isinstance(self.compute, ComputeDemand):
            raise TypeError("resource policy compute must be ComputeDemand or None")
        if not isinstance(self.model_capacity_mode, ModelCapacityMode):
            raise TypeError("resource policy model_capacity_mode must be ModelCapacityMode")
        if not isinstance(self.execution_priority, ExecutionPriority):
            raise TypeError("resource policy execution_priority must be ExecutionPriority")
        object.__setattr__(self, "policy_digest", canonical_digest({
            "policy_id": self.policy_id,
            "compute": self.compute,
            "model_capacity_mode": self.model_capacity_mode.value,
            "execution_priority": self.execution_priority.value,
        }))


@dataclass(frozen=True, slots=True)
class ResourceAllocationReceipt:
    policy_digest: str
    owner_scope: ScopeIdentity
    placement_scope: ScopeIdentity | None
    allocation_id: str | None = None
    host_id: str | None = None
    cpu_cores: int = 0
    memory_bytes: int = 0
    gpu_ids: tuple[str, ...] = ()
    lease_fencing_token: int | None = None
    lease_expires_at_epoch_s: float | None = None
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if len(self.policy_digest) != 64:
            raise ValueError("resource allocation policy_digest must be SHA-256")
        if not isinstance(self.owner_scope, ScopeIdentity):
            raise TypeError("resource allocation owner_scope must be ScopeIdentity")
        if self.placement_scope is not None and not isinstance(self.placement_scope, ScopeIdentity):
            raise TypeError("resource allocation placement_scope must be ScopeIdentity or None")
        allocated = self.allocation_id is not None
        if allocated != (self.host_id is not None):
            raise ValueError("resource allocation identity and host must appear together")
        if allocated and (not self.allocation_id.strip() or not self.host_id.strip()):
            raise ValueError("resource allocation identity and host must be non-empty")
        if min(self.cpu_cores, self.memory_bytes) < 0:
            raise ValueError("resource allocation CPU/memory cannot be negative")
        if not allocated and (
            self.cpu_cores or self.memory_bytes or self.gpu_ids
            or self.lease_fencing_token is not None or self.lease_expires_at_epoch_s is not None
        ):
            raise ValueError("unallocated resource receipt cannot carry physical resources")
        if allocated and self.lease_fencing_token is not None and self.lease_fencing_token < 1:
            raise ValueError("resource allocation fencing token must be >= 1")
        object.__setattr__(self, "receipt_digest", canonical_digest({
            "policy_digest": self.policy_digest,
            "owner_scope": self.owner_scope,
            "placement_scope": self.placement_scope,
            "allocation_id": self.allocation_id,
            "host_id": self.host_id,
            "cpu_cores": self.cpu_cores,
            "memory_bytes": self.memory_bytes,
            "gpu_ids": self.gpu_ids,
            "lease_fencing_token": self.lease_fencing_token,
            "lease_expires_at_epoch_s": self.lease_expires_at_epoch_s,
        }))


__all__ = ["ComputeDemand", "ModelCapacityMode", "ResourceAllocationReceipt", "ResourcePolicy"]
