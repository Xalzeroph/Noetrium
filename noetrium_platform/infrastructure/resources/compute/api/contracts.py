from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from noetrium_platform.foundation.scope.api import ScopeIdentity


@dataclass(frozen=True, slots=True)
class ComputeGPU:
    gpu_id: str
    memory_bytes: int
    model: str = ""
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.gpu_id.strip() or self.memory_bytes < 1:
            raise ValueError("GPU identity/memory must be valid")


@dataclass(frozen=True, slots=True)
class ComputeHost:
    host_id: str
    scope: ScopeIdentity
    cpu_cores: int
    memory_bytes: int
    gpus: tuple[ComputeGPU, ...] = ()
    labels: tuple[tuple[str, str], ...] = ()
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.host_id.strip() or self.cpu_cores < 1 or self.memory_bytes < 1:
            raise ValueError("host identity/capacity must be valid")
        if len({gpu.gpu_id for gpu in self.gpus}) != len(self.gpus):
            raise ValueError("GPU identities must be unique within a host")


@dataclass(frozen=True, slots=True)
class ComputeCluster:
    cluster_id: str
    scope: ScopeIdentity
    host_ids: tuple[str, ...]
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.cluster_id.strip():
            raise ValueError("cluster_id must be non-empty")




@dataclass(frozen=True, slots=True)
class ComputeLeasePolicy:
    ttl_seconds: float = 120.0
    renewal_interval_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not math.isfinite(float(self.ttl_seconds)) or self.ttl_seconds <= 0:
            raise ValueError("compute lease ttl_seconds must be finite and > 0")
        if (
            not math.isfinite(float(self.renewal_interval_seconds))
            or self.renewal_interval_seconds <= 0
        ):
            raise ValueError("compute lease renewal_interval_seconds must be finite and > 0")
        if self.renewal_interval_seconds >= self.ttl_seconds:
            raise ValueError("compute lease renewal interval must be shorter than ttl")


DEFAULT_COMPUTE_LEASE_POLICY = ComputeLeasePolicy()

class GpuSharingMode(StrEnum):
    IDLE_ONLY = "idle-only"
    PREFER_IDLE_ALLOW_SHARED = "prefer-idle-allow-shared"


@dataclass(frozen=True, slots=True)
class ComputeRequirement:
    cpu_cores: int = 1
    memory_bytes: int = 1
    gpu_count: int = 0
    minimum_gpu_memory_bytes: int = 0
    required_gpu_free_memory_bytes: int = 0
    max_gpu_utilization_percent: int = 100
    cpu_headroom_cores: int = 0
    memory_headroom_bytes: int = 0
    max_cpu_load_ratio: float = 1.0
    require_host_runtime: bool = False
    gpu_sharing_mode: GpuSharingMode = GpuSharingMode.IDLE_ONLY
    required_labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if (
            self.cpu_cores < 1
            or self.memory_bytes < 1
            or self.gpu_count < 0
            or self.minimum_gpu_memory_bytes < 0
            or self.required_gpu_free_memory_bytes < 0
            or self.cpu_headroom_cores < 0
            or self.memory_headroom_bytes < 0
        ):
            raise ValueError("compute requirements must be non-negative and include CPU/memory")
        if not 0 <= self.max_gpu_utilization_percent <= 100:
            raise ValueError("compute GPU utilization ceiling must be between 0 and 100")
        if (
            isinstance(self.max_cpu_load_ratio, bool)
            or not isinstance(self.max_cpu_load_ratio, (int, float))
            or self.max_cpu_load_ratio <= 0
        ):
            raise ValueError("compute CPU load ratio ceiling must be positive")
        if type(self.require_host_runtime) is not bool:
            raise TypeError("compute require_host_runtime must be bool")
        if not isinstance(self.gpu_sharing_mode, GpuSharingMode):
            raise TypeError("compute gpu_sharing_mode must be GpuSharingMode")
        if (
            self.gpu_count > 0
            and self.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
            and self.required_gpu_free_memory_bytes <= 0
        ):
            raise ValueError("shared GPU scheduling requires positive free-memory reservation")


@dataclass(frozen=True, slots=True)
class ComputeAllocation:
    allocation_id: str
    scope: ScopeIdentity
    host_id: str
    cpu_cores: int
    memory_bytes: int
    gpu_ids: tuple[str, ...] = ()
    lease_fencing_token: int = 1
    lease_expires_at_epoch_s: float | None = None

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.host_id.strip():
            raise ValueError("allocation identity/host must be non-empty")
        if self.lease_fencing_token < 1:
            raise ValueError("compute allocation fencing token must be >= 1")
        if self.lease_expires_at_epoch_s is not None and (
            not math.isfinite(float(self.lease_expires_at_epoch_s))
            or self.lease_expires_at_epoch_s <= 0
        ):
            raise ValueError("compute allocation lease expiry must be finite and positive")

    def expired_at(self, now_epoch_s: float) -> bool:
        if not math.isfinite(float(now_epoch_s)):
            raise ValueError("compute allocation expiry observation must be finite")
        return (
            self.lease_expires_at_epoch_s is not None
            and self.lease_expires_at_epoch_s <= now_epoch_s
        )


__all__ = ["ComputeAllocation", "ComputeCluster", "ComputeGPU", "ComputeHost", "ComputeRequirement", "ComputeLeasePolicy", "DEFAULT_COMPUTE_LEASE_POLICY", "GpuSharingMode"]
