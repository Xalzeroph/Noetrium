from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import math

from noetrium_platform.foundation.kernel.unit import NoetriumUnit


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
    scope: NoetriumUnit
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
    scope: NoetriumUnit
    host_ids: tuple[str, ...]
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.cluster_id.strip():
            raise ValueError("cluster_id must be non-empty")








class ComputePlacementUnavailable(RuntimeError):
    """Expected capacity exhaustion for one exact compute placement request."""

    def __init__(
        self,
        requirement: "ComputeRequirement",
        *,
        diagnostics: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(requirement, ComputeRequirement):
            raise TypeError("compute placement failure requires ComputeRequirement")
        if diagnostics is not None and not isinstance(diagnostics, Mapping):
            raise TypeError("compute placement diagnostics must be a mapping or None")
        self.requirement = requirement
        self.diagnostics = dict(diagnostics or {})
        super().__init__("no compute host satisfies requirement")

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
    required_gpu_memory_fraction: float | None = None
    gpu_admission_headroom_fraction: float = 0.0
    max_gpu_utilization_percent: int = 100
    cpu_headroom_cores: int = 0
    memory_headroom_bytes: int = 0
    max_cpu_load_ratio: float | None = None
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
        if self.required_gpu_memory_fraction is not None and (
            isinstance(self.required_gpu_memory_fraction, bool)
            or not isinstance(self.required_gpu_memory_fraction, (int, float))
            or not math.isfinite(float(self.required_gpu_memory_fraction))
            or not 0.0 < float(self.required_gpu_memory_fraction) <= 1.0
        ):
            raise ValueError(
                "compute required_gpu_memory_fraction must be finite in (0, 1]"
            )
        if (
            isinstance(self.gpu_admission_headroom_fraction, bool)
            or not isinstance(self.gpu_admission_headroom_fraction, (int, float))
            or not math.isfinite(float(self.gpu_admission_headroom_fraction))
            or not 0.0 <= float(self.gpu_admission_headroom_fraction) < 1.0
        ):
            raise ValueError(
                "compute GPU admission headroom fraction must be finite in [0, 1)"
            )
        if not 0 <= self.max_gpu_utilization_percent <= 100:
            raise ValueError("compute GPU utilization ceiling must be between 0 and 100")
        if self.max_cpu_load_ratio is not None and (
            isinstance(self.max_cpu_load_ratio, bool)
            or not isinstance(self.max_cpu_load_ratio, (int, float))
            or not math.isfinite(float(self.max_cpu_load_ratio))
            or self.max_cpu_load_ratio <= 0
        ):
            raise ValueError(
                "compute CPU load ratio ceiling must be finite/positive or None"
            )
        if type(self.require_host_runtime) is not bool:
            raise TypeError("compute require_host_runtime must be bool")
        if not isinstance(self.gpu_sharing_mode, GpuSharingMode):
            raise TypeError("compute gpu_sharing_mode must be GpuSharingMode")


__all__ = [
    "ComputeCluster",
    "ComputeGPU",
    "ComputeHost",
    "ComputePlacementUnavailable",
    "ComputeRequirement",
    "GpuSharingMode",
]
