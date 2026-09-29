from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from pathlib import Path

from noetrium_platform.substrate.api import ScopeIdentity
from noetrium_platform.capabilities.model.asset.api import ManagedModelAsset
from noetrium_platform.substrate.api import GpuDeviceStatus, GpuRuntimeSnapshot


class ModelDesiredState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"


class ModelControllerPhase(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class ModelRuntimeState(StrEnum):
    STOPPED = "stopped"
    RUNNING = "running"
    MISSING = "missing"
    DRIFTED = "drifted"
    UPDATE_PENDING = "update_pending"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ModelDeploymentSpec:
    deployment_id: str
    scope: ScopeIdentity
    service_id: str
    model_id: str
    engine: str
    container_digest: str
    executable: str
    argv: tuple[str, ...]
    cwd: Path
    gpu_devices: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    readiness_url: str | None = None
    readiness_timeout_s: float = 120.0
    stop_timeout_s: float = 30.0
    heartbeat_interval_s: float = 10.0
    desired_state: ModelDesiredState = ModelDesiredState.STOPPED
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.container_digest) is not str
            or len(self.container_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.container_digest)
        ):
            raise ValueError(
                "model deployment container_digest must be lowercase SHA-256"
            )
        for field in ("readiness_timeout_s", "stop_timeout_s", "heartbeat_interval_s"):
            value = getattr(self, field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0
            ):
                raise ValueError(f"model deployment {field} must be finite and positive")


@dataclass(frozen=True, slots=True)
class ModelDeploymentSelector:
    tags: tuple[str, ...] = ()
    model_id: str | None = None
    engine: str | None = None


@dataclass(frozen=True, slots=True)
class ModelDeploymentGeneration:
    """CAS snapshot for one mutable desired/applied deployment identity."""

    deployment_id: str
    desired_spec_digest: str
    applied_runtime_digest: str | None

    def __post_init__(self) -> None:
        if not self.deployment_id.strip():
            raise ValueError("model deployment generation requires deployment_id")
        if (
            len(self.desired_spec_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.desired_spec_digest)
        ):
            raise ValueError("model desired generation must be lowercase SHA-256")
        if self.applied_runtime_digest is not None and (
            len(self.applied_runtime_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.applied_runtime_digest)
        ):
            raise ValueError("model applied runtime generation must be lowercase SHA-256")




@dataclass(frozen=True, slots=True)
class ModelAppliedRuntimeIdentity:
    """Exact read-only identity of one applied model-serving generation."""

    deployment_id: str
    desired_spec_digest: str
    applied_runtime_digest: str
    service_contract_digest: str
    pid: int
    process_start_marker: str
    argv_digest: str

    def __post_init__(self) -> None:
        if type(self.deployment_id) is not str or not self.deployment_id.strip():
            raise ValueError("model applied runtime deployment_id is required")
        for name in (
            "desired_spec_digest",
            "applied_runtime_digest",
            "service_contract_digest",
            "argv_digest",
        ):
            value=getattr(self,name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"model applied runtime {name} must be lowercase SHA-256")
        if type(self.pid) is not int or self.pid <= 0:
            raise ValueError("model applied runtime pid must be positive")
        if (
            type(self.process_start_marker) is not str
            or not self.process_start_marker
        ):
            raise ValueError("model applied runtime process_start_marker is required")

    @property
    def identity_digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ModelDeploymentStatus:
    deployment_id: str
    service_id: str
    desired_state: ModelDesiredState
    runtime_state: ModelRuntimeState
    pid: int | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ModelReconcileCycle:
    cycle_index: int
    completed_at_utc: str
    statuses: tuple[ModelDeploymentStatus, ...]


@dataclass(frozen=True, slots=True)
class ModelControllerState:
    controller_id: str
    phase: ModelControllerPhase
    pid: int | None
    started_at_utc: str
    heartbeat_at_utc: str
    interval_seconds: float
    cycle_count: int
    last_cycle: ModelReconcileCycle | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if (
            isinstance(self.interval_seconds, bool)
            or not isinstance(self.interval_seconds, (int, float))
            or not math.isfinite(float(self.interval_seconds))
            or self.interval_seconds <= 0
        ):
            raise ValueError("model controller interval_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class ModelLogTail:
    deployment_id: str
    stream: str
    path: Path
    bytes_read: int
    text: str


@dataclass(frozen=True, slots=True)
class ModelGpuProcessBinding:
    deployment_id: str
    pid: int
    gpu_uuids: tuple[str, ...]
    used_memory_mb: int


@dataclass(frozen=True, slots=True)
class ModelGpuAllocation:
    deployment_id: str
    gpu_devices: tuple[str, ...]
    desired_state: ModelDesiredState


@dataclass(frozen=True, slots=True)
class ModelGpuConflict:
    gpu_device: str
    deployment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelDeploymentLogs:
    deployment_id: str
    stdout_path: Path
    stderr_path: Path


@dataclass(frozen=True, slots=True)
class ModelControlSnapshot:
    models: tuple[ManagedModelAsset, ...]
    deployment_specs: tuple[ModelDeploymentSpec, ...]
    deployments: tuple[ModelDeploymentStatus, ...]
    gpu_process_bindings: tuple[ModelGpuProcessBinding, ...] = ()
    gpu_allocations: tuple[ModelGpuAllocation, ...] = ()
    gpu_conflicts: tuple[ModelGpuConflict, ...] = ()
    gpu_runtime: GpuRuntimeSnapshot = GpuRuntimeSnapshot(False, detail="not-configured")


__all__ = [
    "ModelAppliedRuntimeIdentity", "ModelControlSnapshot", "ModelControllerPhase", "ModelControllerState", "ModelDeploymentLogs",
    "ModelDeploymentGeneration", "ModelDeploymentSelector", "ModelDeploymentSpec", "ModelDeploymentStatus", "ModelDesiredState",
    "ModelGpuAllocation", "ModelGpuConflict", "ModelGpuProcessBinding",
    "ModelLogTail", "ModelReconcileCycle", "ModelRuntimeState",
]
