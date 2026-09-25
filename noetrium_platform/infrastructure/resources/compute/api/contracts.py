from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re

from noetrium_platform.foundation.governance.api import ScopeIdentity
from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _canonical_text_values(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{field_name} must be tuple")
    if any(type(value) is not str or not value.strip() or value != value.strip() for value in values):
        raise ValueError(f"{field_name} entries must be canonical text")
    canonical = tuple(sorted(values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} entries must be unique")
    return canonical


def _canonical_labels(labels: tuple[tuple[str, str], ...], field_name: str) -> tuple[tuple[str, str], ...]:
    if type(labels) is not tuple:
        raise TypeError(f"{field_name} must be tuple")
    normalized: list[tuple[str, str]] = []
    for row in labels:
        if type(row) is not tuple or len(row) != 2:
            raise TypeError(f"{field_name} entries must be (key, value) tuples")
        key, value = row
        if type(key) is not str or type(value) is not str:
            raise TypeError(f"{field_name} keys and values must be str")
        if not key.strip() or key != key.strip() or value != value.strip():
            raise ValueError(f"{field_name} entries must be canonical text")
        normalized.append((key, value))
    normalized.sort()
    if len({key for key, _value in normalized}) != len(normalized):
        raise ValueError(f"{field_name} keys must be unique")
    return tuple(normalized)


class ComputeDeviceHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ComputeGPU:
    gpu_id: str
    memory_bytes: int
    model: str = ""
    labels: tuple[tuple[str, str], ...] = ()
    health: ComputeDeviceHealth = ComputeDeviceHealth.HEALTHY
    reserved_memory_bytes: int = 0

    def __post_init__(self) -> None:
        if not self.gpu_id.strip() or self.memory_bytes < 1:
            raise ValueError("GPU identity/memory must be valid")
        if type(self.health) is not ComputeDeviceHealth:
            raise TypeError("GPU health must be ComputeDeviceHealth")
        if type(self.reserved_memory_bytes) is not int or not 0 <= self.reserved_memory_bytes < self.memory_bytes:
            raise ValueError("GPU reserved_memory_bytes must be an integer below device memory")
        object.__setattr__(self, "labels", _canonical_labels(self.labels, "GPU labels"))

    @property
    def schedulable_memory_bytes(self) -> int:
        return self.memory_bytes - self.reserved_memory_bytes


class ComputeHostSchedulingState(StrEnum):
    ACTIVE = "active"
    DRAINING = "draining"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class ComputeHost:
    host_id: str
    scope: ScopeIdentity
    cpu_cores: int
    memory_bytes: int
    gpus: tuple[ComputeGPU, ...] = ()
    labels: tuple[tuple[str, str], ...] = ()
    enabled: bool = True
    scheduling_state: ComputeHostSchedulingState = ComputeHostSchedulingState.ACTIVE
    reserved_cpu_cores: int = 0
    reserved_memory_bytes: int = 0

    def __post_init__(self) -> None:
        if not self.host_id.strip() or self.cpu_cores < 1 or self.memory_bytes < 1:
            raise ValueError("host identity/capacity must be valid")
        if len({gpu.gpu_id for gpu in self.gpus}) != len(self.gpus):
            raise ValueError("GPU identities must be unique within a host")
        if type(self.enabled) is not bool:
            raise TypeError("host enabled must be bool")
        if type(self.scheduling_state) is not ComputeHostSchedulingState:
            raise TypeError("host scheduling_state must be ComputeHostSchedulingState")
        if type(self.reserved_cpu_cores) is not int or not 0 <= self.reserved_cpu_cores < self.cpu_cores:
            raise ValueError("host reserved_cpu_cores must be an integer below total CPU capacity")
        if type(self.reserved_memory_bytes) is not int or not 0 <= self.reserved_memory_bytes < self.memory_bytes:
            raise ValueError("host reserved_memory_bytes must be an integer below total memory capacity")
        object.__setattr__(self, "labels", _canonical_labels(self.labels, "host labels"))

    @property
    def accepts_new_allocations(self) -> bool:
        return self.enabled and self.scheduling_state is ComputeHostSchedulingState.ACTIVE

    @property
    def schedulable_cpu_cores(self) -> int:
        return self.cpu_cores - self.reserved_cpu_cores

    @property
    def schedulable_memory_bytes(self) -> int:
        return self.memory_bytes - self.reserved_memory_bytes


@dataclass(frozen=True, slots=True)
class ComputeCluster:
    cluster_id: str
    scope: ScopeIdentity
    host_ids: tuple[str, ...]
    labels: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.cluster_id.strip():
            raise ValueError("cluster_id must be non-empty")
        if len(set(self.host_ids)) != len(self.host_ids):
            raise ValueError("cluster host_ids must be unique")
        object.__setattr__(self, "labels", _canonical_labels(self.labels, "cluster labels"))




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


class ComputeInventoryConflict(RuntimeError):
    """Exact observed inventory generation no longer matches authority."""


class ComputePlacementUnavailable(RuntimeError):
    """Expected capacity exhaustion for one exact compute placement request."""

    def __init__(self, requirement: "ComputeRequirement") -> None:
        if not isinstance(requirement, ComputeRequirement):
            raise TypeError("compute placement failure requires ComputeRequirement")
        self.requirement = requirement
        super().__init__("no compute host satisfies requirement")

class GpuSharingMode(StrEnum):
    IDLE_ONLY = "idle-only"
    PREFER_IDLE_ALLOW_SHARED = "prefer-idle-allow-shared"


class ComputePlacementPreference(StrEnum):
    PACK = "pack"
    SPREAD = "spread"


@dataclass(frozen=True, slots=True)
class ComputeRequirement:
    cpu_cores: int = 1
    memory_bytes: int = 1
    gpu_count: int = 0
    minimum_gpu_memory_bytes: int = 0
    required_gpu_free_memory_bytes: int = 0
    required_gpu_memory_fraction: float | None = None
    max_gpu_utilization_percent: int = 100
    cpu_headroom_cores: int = 0
    memory_headroom_bytes: int = 0
    max_cpu_load_ratio: float | None = None
    require_host_runtime: bool = False
    gpu_sharing_mode: GpuSharingMode = GpuSharingMode.IDLE_ONLY
    required_labels: tuple[tuple[str, str], ...] = ()
    required_gpu_labels: tuple[tuple[str, str], ...] = ()
    forbidden_host_labels: tuple[tuple[str, str], ...] = ()
    preferred_host_labels: tuple[tuple[str, str], ...] = ()
    allowed_host_ids: tuple[str, ...] = ()
    forbidden_host_ids: tuple[str, ...] = ()
    placement_preference: ComputePlacementPreference = ComputePlacementPreference.PACK
    gpu_colocation_label: str | None = None
    max_runtime_observation_age_seconds: float | None = None

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
        if type(self.placement_preference) is not ComputePlacementPreference:
            raise TypeError("compute placement_preference must be ComputePlacementPreference")
        if self.gpu_colocation_label is not None and (
            type(self.gpu_colocation_label) is not str
            or not self.gpu_colocation_label.strip()
            or self.gpu_colocation_label != self.gpu_colocation_label.strip()
        ):
            raise ValueError("compute gpu_colocation_label must be canonical text or None")
        if self.max_runtime_observation_age_seconds is not None and (
            isinstance(self.max_runtime_observation_age_seconds, bool)
            or not isinstance(self.max_runtime_observation_age_seconds, (int, float))
            or not math.isfinite(float(self.max_runtime_observation_age_seconds))
            or self.max_runtime_observation_age_seconds <= 0
        ):
            raise ValueError("compute runtime observation age must be finite and positive or None")
        object.__setattr__(self, "required_labels", _canonical_labels(self.required_labels, "compute required host labels"))
        object.__setattr__(self, "required_gpu_labels", _canonical_labels(self.required_gpu_labels, "compute required GPU labels"))
        object.__setattr__(self, "forbidden_host_labels", _canonical_labels(self.forbidden_host_labels, "compute forbidden host labels"))
        object.__setattr__(self, "preferred_host_labels", _canonical_labels(self.preferred_host_labels, "compute preferred host labels"))
        object.__setattr__(self, "allowed_host_ids", _canonical_text_values(self.allowed_host_ids, "compute allowed host ids"))
        object.__setattr__(self, "forbidden_host_ids", _canonical_text_values(self.forbidden_host_ids, "compute forbidden host ids"))
        if set(self.allowed_host_ids) & set(self.forbidden_host_ids):
            raise ValueError("compute allowed/forbidden host ids must be disjoint")


_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ComputeAllocationRequest:
    allocation_id: str
    scope: ScopeIdentity
    requirement: ComputeRequirement
    placement_scope: ScopeIdentity | None = None

    def __post_init__(self) -> None:
        if type(self.allocation_id) is not str or not self.allocation_id.strip() or self.allocation_id != self.allocation_id.strip():
            raise ValueError("compute allocation request id must be canonical text")
        if type(self.scope) is not ScopeIdentity:
            raise TypeError("compute allocation request scope must be ScopeIdentity")
        if type(self.requirement) is not ComputeRequirement:
            raise TypeError("compute allocation request requirement must be ComputeRequirement")
        if self.placement_scope is not None and type(self.placement_scope) is not ScopeIdentity:
            raise TypeError("compute allocation request placement_scope must be ScopeIdentity or None")

    @property
    def request_digest(self) -> str:
        return canonical_digest(self)


class ComputeBatchPlacementStrategy(StrEnum):
    INDEPENDENT = "independent"
    PACK = "pack"
    STRICT_PACK = "strict-pack"
    SPREAD = "spread"
    STRICT_SPREAD = "strict-spread"


@dataclass(frozen=True, slots=True)
class ComputeAllocationBatch:
    batch_id: str
    requests: tuple[ComputeAllocationRequest, ...]
    placement_strategy: ComputeBatchPlacementStrategy = ComputeBatchPlacementStrategy.INDEPENDENT

    def __post_init__(self) -> None:
        if type(self.batch_id) is not str or not self.batch_id.strip() or self.batch_id != self.batch_id.strip():
            raise ValueError("compute allocation batch id must be canonical text")
        if type(self.requests) is not tuple or not self.requests:
            raise ValueError("compute allocation batch requires requests")
        if any(type(row) is not ComputeAllocationRequest for row in self.requests):
            raise TypeError("compute allocation batch requests must be typed")
        if type(self.placement_strategy) is not ComputeBatchPlacementStrategy:
            raise TypeError("compute allocation batch placement_strategy must be ComputeBatchPlacementStrategy")
        canonical = tuple(sorted(self.requests, key=lambda row: row.allocation_id))
        if len({row.allocation_id for row in canonical}) != len(canonical):
            raise ValueError("compute allocation batch allocation ids must be unique")
        object.__setattr__(self, "requests", canonical)

    @property
    def batch_digest(self) -> str:
        return canonical_digest({
            "batch_id": self.batch_id,
            "placement_strategy": self.placement_strategy.value,
            "request_digests": tuple(row.request_digest for row in self.requests),
        })


class ComputeBatchPlacementUnavailable(RuntimeError):
    """Atomic compute batch cannot satisfy its group placement contract."""

    def __init__(self, batch: ComputeAllocationBatch) -> None:
        if type(batch) is not ComputeAllocationBatch:
            raise TypeError("compute batch placement failure requires ComputeAllocationBatch")
        self.batch = batch
        super().__init__(
            f"compute allocation batch cannot satisfy {batch.placement_strategy.value}: "
            f"{batch.batch_id}"
        )


@dataclass(frozen=True, slots=True)
class ComputeBindingProof:
    """Attest that one compute reservation is physically owned by an exact runtime generation."""

    allocation_id: str
    host_id: str
    gpu_ids: tuple[str, ...]
    lease_fencing_token: int
    binder_identity_digest: str
    observed_at_epoch_s: float
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.allocation_id.strip() or not self.host_id.strip():
            raise ValueError("compute binding proof allocation/host identity is required")
        if self.lease_fencing_token < 1:
            raise ValueError("compute binding proof fencing token must be >= 1")
        if (
            not _SHA256.fullmatch(self.binder_identity_digest)
        ):
            raise ValueError(
                "compute binder identity must be a canonical lowercase SHA-256 digest"
            )
        if (
            not math.isfinite(float(self.observed_at_epoch_s))
            or self.observed_at_epoch_s <= 0
        ):
            raise ValueError(
                "compute binding observation timestamp must be finite and positive"
            )
        if not self.evidence_ref.strip():
            raise ValueError("compute binding evidence reference is required")
        if len(set(self.gpu_ids)) != len(self.gpu_ids):
            raise ValueError("compute binding proof GPU ids must be unique")

    def digest(self) -> str:
        return canonical_digest(self)


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
    binding_proof_digest: str | None = None
    binding_binder_identity_digest: str | None = None
    binding_evidence_ref: str | None = None
    bound_at_epoch_s: float | None = None
    gpu_sharing_mode: GpuSharingMode = GpuSharingMode.IDLE_ONLY
    gpu_memory_reservation_bytes: tuple[int, ...] = ()

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
        if self.bound_at_epoch_s is not None and (
            not math.isfinite(float(self.bound_at_epoch_s))
            or self.bound_at_epoch_s <= 0
        ):
            raise ValueError("compute allocation bound timestamp must be finite and positive")
        if not isinstance(self.gpu_sharing_mode, GpuSharingMode):
            raise TypeError("compute allocation gpu_sharing_mode must be GpuSharingMode")
        if (
            not isinstance(self.gpu_memory_reservation_bytes, tuple)
            or any(
                type(value) is not int or value < 0
                for value in self.gpu_memory_reservation_bytes
            )
        ):
            raise ValueError(
                "compute allocation GPU memory reservations must be non-negative integers"
            )
        if self.gpu_memory_reservation_bytes and (
            len(self.gpu_memory_reservation_bytes) != len(self.gpu_ids)
        ):
            raise ValueError(
                "compute allocation GPU memory reservations must align with gpu_ids"
            )
        if (
            self.gpu_sharing_mode is GpuSharingMode.PREFER_IDLE_ALLOW_SHARED
            and self.gpu_ids
            and (
                len(self.gpu_memory_reservation_bytes) != len(self.gpu_ids)
                or any(value <= 0 for value in self.gpu_memory_reservation_bytes)
            )
        ):
            raise ValueError(
                "shared compute allocation requires positive per-device VRAM reservations"
            )
        for value, field in (
            (self.binding_proof_digest, "compute allocation binding proof"),
            (
                self.binding_binder_identity_digest,
                "compute allocation binder identity",
            ),
        ):
            if value is not None and not _SHA256.fullmatch(value):
                raise ValueError(f"{field} must be a canonical lowercase SHA-256 digest")
        if (
            self.binding_evidence_ref is not None
            and not self.binding_evidence_ref.strip()
        ):
            raise ValueError(
                "compute allocation binding evidence reference must be non-empty"
            )
        presence = (
            self.binding_proof_digest is not None,
            self.binding_binder_identity_digest is not None,
            self.binding_evidence_ref is not None,
            self.bound_at_epoch_s is not None,
        )
        if any(presence) and not all(presence):
            raise ValueError(
                "compute allocation binding metadata must be complete or absent"
            )

    @property
    def is_bound(self) -> bool:
        return self.binding_proof_digest is not None

    def expired_at(self, now_epoch_s: float) -> bool:
        if not math.isfinite(float(now_epoch_s)):
            raise ValueError("compute allocation expiry observation must be finite")
        return (
            self.lease_expires_at_epoch_s is not None
            and self.lease_expires_at_epoch_s <= now_epoch_s
        )


__all__ = ["ComputeAllocation", "ComputeAllocationBatch", "ComputeBatchPlacementStrategy", "ComputeBatchPlacementUnavailable", "ComputeAllocationRequest", "ComputeDeviceHealth", "ComputeBindingProof", "ComputeCluster", "ComputeGPU", "ComputeHost", "ComputeHostSchedulingState", "ComputeInventoryConflict", "ComputePlacementPreference", "ComputePlacementUnavailable", "ComputeRequirement", "ComputeLeasePolicy", "DEFAULT_COMPUTE_LEASE_POLICY", "GpuSharingMode"]
