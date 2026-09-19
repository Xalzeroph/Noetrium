from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Protocol

@dataclass(frozen=True, slots=True)
class GpuDeviceStatus:
    index: str
    uuid: str
    name: str
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    utilization_percent: int

@dataclass(frozen=True, slots=True)
class GpuProcessStatus:
    pid: int
    gpu_uuid: str
    used_memory_mb: int
    process_name: str

@dataclass(frozen=True, slots=True)
class GpuRuntimeSnapshot:
    available: bool
    devices: tuple[GpuDeviceStatus, ...] = ()
    processes: tuple[GpuProcessStatus, ...] = ()
    detail: str = ""
    processes_complete: bool = True


@dataclass(frozen=True, slots=True)
class HostRuntimeStatus:
    host_id: str
    available: bool
    effective_cpu_cores: float = 0.0
    cpu_load_1m: float = 0.0
    available_memory_bytes: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.host_id.strip():
            raise ValueError("host runtime host_id must be non-empty")
        for name, value in (("effective_cpu_cores", self.effective_cpu_cores), ("cpu_load_1m", self.cpu_load_1m)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"host runtime {name} must be finite and non-negative")
        if type(self.available_memory_bytes) is not int or self.available_memory_bytes < 0:
            raise ValueError("host runtime available_memory_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class HostRuntimeSnapshot:
    available: bool
    hosts: tuple[HostRuntimeStatus, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        if len({item.host_id for item in self.hosts}) != len(self.hosts):
            raise ValueError("host runtime snapshot contains duplicate host identities")


class HostRuntimeObserverPort(Protocol):
    def snapshot(self) -> HostRuntimeSnapshot: ...

class GpuRuntimeObserverPort(Protocol):
    def snapshot(self) -> GpuRuntimeSnapshot: ...

__all__ = ["GpuDeviceStatus", "GpuProcessStatus", "GpuRuntimeObserverPort", "GpuRuntimeSnapshot", "HostRuntimeObserverPort", "HostRuntimeSnapshot", "HostRuntimeStatus"]
