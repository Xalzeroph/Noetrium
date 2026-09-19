"""Composition-time deployment qualification contracts.

The contracts deliberately describe facts and a plan, not a mutable package
manager or a live model process.  Host facts are observations imported from
the resource/environment compositions; deployment owns the interpretation of
those facts for one exact model-serving request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from pathlib import Path
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest


class CandidateDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class QualificationMaterializationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class DeploymentRuntimeQualificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


DEFAULT_DEPLOYMENT_PROBE_TIMEOUT_SECONDS = 90.0
DEFAULT_PACKAGE_INDEX_URL = "https://pypi.org/simple"


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    text = _require_text(value, field_name)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return text


def _require_string_tuple(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(not isinstance(item, str) for item in values):
        raise ValueError(f"{field_name} must be a tuple of strings")
    return values


def native_cuda_runtime_package_names(cuda_version: str | None) -> tuple[str, ...]:
    """Return observed NVIDIA runtime provider names in preference order.

    CUDA 13's current NVIDIA Python distribution uses the unsuffixed runtime
    name, while CUDA 11/12 and some mirrors expose the CUDA-major suffix. The
    resolver may consider only names actually observed on the configured
    indexes; this helper defines the deterministic provider-family order and
    does not declare any package compatible by itself.
    """

    if not cuda_version:
        return ()
    major = cuda_version.split(".", 1)[0].strip()
    if major not in {"11", "12", "13"}:
        return ()
    if major == "13":
        return ("nvidia-cuda-runtime", "nvidia-cuda-runtime-cu13")
    return (f"nvidia-cuda-runtime-cu{major}",)


@dataclass(frozen=True, slots=True)
class OperatingSystemFacts:
    system: str
    distribution: str
    distribution_version: str
    kernel: str
    machine: str


@dataclass(frozen=True, slots=True)
class CudaFacts:
    driver_version: str | None
    driver_cuda_version: str | None
    toolkit_version: str | None
    nvrtc_versions: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    nvml_version: str | None = None
    runtime_library_versions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GpuCapabilityFacts:
    index: str
    uuid: str
    name: str
    total_memory_mb: int
    free_memory_mb: int
    compute_capability: str | None
    pci_bus_id: str | None = None
    numa_node: int | None = None
    power_limit_watts: float | None = None

    def __post_init__(self) -> None:
        if self.power_limit_watts is not None and (
            isinstance(self.power_limit_watts, bool)
            or not isinstance(self.power_limit_watts, (int, float))
            or not math.isfinite(float(self.power_limit_watts))
            or self.power_limit_watts < 0
        ):
            raise ValueError("GPU power_limit_watts must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class HostExecutionFacts:
    """Host limits and capacity that can change deployment feasibility."""

    hostname: str
    cpu_architecture: str
    logical_cpu_count: int
    physical_memory_bytes: int | None = None
    available_memory_bytes: int | None = None
    libc: str | None = None
    libc_version: str | None = None
    cgroup_memory_limit_bytes: int | None = None
    cgroup_memory_current_bytes: int | None = None
    nofile_soft: int | None = None
    nofile_hard: int | None = None
    pids_limit: int | None = None
    container_runtime: str | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GpuFabricFacts:
    """Observed multi-GPU topology and communication runtime evidence."""

    topology: tuple[str, ...] = ()
    nccl_version: str | None = None
    nccl_library: str | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StorageCapabilityFacts:
    """Capacity and access facts for the requested model path."""

    path: str
    total_bytes: int | None = None
    free_bytes: int | None = None
    free_inodes: int | None = None
    filesystem: str | None = None
    device_identity: str | None = None
    readable: bool = False
    writable: bool = False
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PythonRuntimeFacts:
    executable: str
    version: str
    pip_version: str | None
    ensurepip_available: bool
    venv_available: bool
    site_packages: str | None
    torch_version: str | None
    torch_cuda_version: str | None
    kernel_architectures: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    python_abi: str | None = None
    platform_tag: str | None = None
    native_library_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelArtifactFacts:
    model_id: str
    model_path: str
    model_type: str | None
    architectures: tuple[str, ...]
    torch_dtype: str | None
    context_length: int | None
    config_present: bool
    error: str | None = None
    artifact_bytes: int | None = None
    file_count: int | None = None
    shard_count: int | None = None
    required_disk_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class PackageArtifactFacts:
    """Metadata for a candidate artifact without downloading the artifact."""

    filename: str
    version: str
    kind: str
    sha256: str | None = None
    python_tags: tuple[str, ...] = ()
    abi_tags: tuple[str, ...] = ()
    platform_tags: tuple[str, ...] = ()
    requires_python: str | None = None
    metadata_sha256: str | None = None
    dependency_requirements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageDependencyNodeFacts:
    """One metadata-resolved node in a package dependency closure."""

    package: str
    version: str
    index_url: str
    artifact: PackageArtifactFacts


@dataclass(frozen=True, slots=True)
class PackageIndexFacts:
    package: str
    index_url: str
    available_versions: tuple[str, ...] = ()
    error: str | None = None
    selected_version: str | None = None
    artifacts: tuple[PackageArtifactFacts, ...] = ()
    compatibility_error: str | None = None
    dependency_nodes: tuple[PackageDependencyNodeFacts, ...] = ()
    dependency_closure_complete: bool = False
    dependency_closure_error: str | None = None

    @property
    def latest(self) -> str | None:
        return self.available_versions[0] if self.available_versions else None


@dataclass(frozen=True, slots=True)
class DeploymentCapabilityFacts:
    captured_at_unix: float
    operating_system: OperatingSystemFacts
    cuda: CudaFacts
    gpus: tuple[GpuCapabilityFacts, ...]
    python: PythonRuntimeFacts
    model: ModelArtifactFacts
    package_indexes: tuple[PackageIndexFacts, ...]
    probe_errors: tuple[str, ...] = ()
    host: HostExecutionFacts = field(
        default_factory=lambda: HostExecutionFacts("unknown", "unknown", 0)
    )
    fabric: GpuFabricFacts = field(default_factory=GpuFabricFacts)
    storage: StorageCapabilityFacts = field(default_factory=lambda: StorageCapabilityFacts("unknown"))

    def __post_init__(self) -> None:
        if (
            isinstance(self.captured_at_unix, bool)
            or not isinstance(self.captured_at_unix, (int, float))
            or not math.isfinite(float(self.captured_at_unix))
            or self.captured_at_unix < 0
        ):
            raise ValueError("deployment capability captured_at_unix must be finite and non-negative")

    def digest(self) -> str:
        return canonical_digest(self)

    def package_index(self, package: str, index_url: str) -> PackageIndexFacts | None:
        for item in self.package_indexes:
            if item.package == package and item.index_url == index_url:
                return item
        return None


@dataclass(frozen=True, slots=True)
class DeploymentQualificationRequest:
    model_id: str
    model_path: Path
    python_executable: Path
    python_environment_id: str | None = None
    backends: tuple[str, ...] = ("sglang", "vllm")
    tensor_parallel: int = 1
    # Empty means derive the primary/extra indexes from the target interpreter;
    # the probe falls back to public PyPI only when the environment exposes no
    # configured index.
    package_index_urls: tuple[str, ...] = ()
    probe_timeout_seconds: float = DEFAULT_DEPLOYMENT_PROBE_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("deployment qualification model_id is required")
        if self.tensor_parallel < 1:
            raise ValueError("deployment qualification tensor_parallel must be positive")
        if self.python_environment_id is not None and not self.python_environment_id.strip():
            raise ValueError("deployment qualification python_environment_id must be non-empty")
        if not self.backends or any(not value.strip() for value in self.backends):
            raise ValueError("deployment qualification requires at least one backend")
        if (
            isinstance(self.probe_timeout_seconds, bool)
            or not isinstance(self.probe_timeout_seconds, (int, float))
            or not math.isfinite(float(self.probe_timeout_seconds))
            or self.probe_timeout_seconds <= 0
        ):
            raise ValueError("deployment qualification probe timeout must be finite and positive")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class InstallPackage:
    name: str
    version: str
    index_url: str

    def __post_init__(self) -> None:
        _require_text(self.name, "install package name")
        _require_text(self.version, "install package version")
        _require_text(self.index_url, "install package index_url")


@dataclass(frozen=True, slots=True)
class BackendCandidatePlan:
    backend: str
    decision: CandidateDecision
    version: str | None
    packages: tuple[InstallPackage, ...]
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.backend, "qualification backend")
        if not isinstance(self.decision, CandidateDecision):
            raise ValueError("qualification candidate decision is invalid")
        if self.version is not None:
            _require_text(self.version, "qualification backend version")
        if not isinstance(self.packages, tuple) or any(
            not isinstance(item, InstallPackage) for item in self.packages
        ):
            raise ValueError("qualification packages must be typed InstallPackage values")
        _require_string_tuple(self.reasons, "qualification candidate reasons")
        _require_string_tuple(self.evidence_refs, "qualification candidate evidence_refs")


@dataclass(frozen=True, slots=True)
class DeploymentQualificationPlan:
    request_digest: str
    facts_digest: str
    candidates: tuple[BackendCandidatePlan, ...]
    selected_backend: str | None
    plan_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_sha256(self.request_digest, "qualification request_digest")
        _require_sha256(self.facts_digest, "qualification facts_digest")
        if not isinstance(self.candidates, tuple) or not self.candidates or any(
            not isinstance(item, BackendCandidatePlan) for item in self.candidates
        ):
            raise ValueError("qualification plan requires typed backend candidates")
        accepted = [item.backend for item in self.candidates if item.decision is CandidateDecision.ACCEPTED]
        if self.selected_backend is not None:
            _require_text(self.selected_backend, "qualification selected_backend")
        if self.selected_backend is not None and self.selected_backend not in accepted:
            raise ValueError("selected backend must be an accepted candidate")
        object.__setattr__(
            self,
            "plan_digest",
            canonical_digest(
                {
                    "request_digest": self.request_digest,
                    "facts_digest": self.facts_digest,
                    "candidates": self.candidates,
                    "selected_backend": self.selected_backend,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class DeploymentQualificationEvidenceRecord:
    """Immutable join of one request, its captured facts and its plan."""

    captured_at_unix: float
    request: DeploymentQualificationRequest
    facts: DeploymentCapabilityFacts
    plan: DeploymentQualificationPlan
    record_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.captured_at_unix, bool)
            or not isinstance(self.captured_at_unix, (int, float))
            or not math.isfinite(float(self.captured_at_unix))
            or self.captured_at_unix < 0
        ):
            raise ValueError("qualification evidence captured_at_unix must be finite and non-negative")
        if self.plan.request_digest != self.request.digest():
            raise ValueError("qualification evidence request digest does not match plan")
        if self.plan.facts_digest != self.facts.digest():
            raise ValueError("qualification evidence facts digest does not match plan")
        object.__setattr__(
            self,
            "record_digest",
            canonical_digest(
                {
                    "captured_at_unix": self.captured_at_unix,
                    "request": self.request,
                    "facts": self.facts,
                    "plan": self.plan,
                }
            ),
        )


class DeploymentCapabilityProbePort(Protocol):
    def capture(self, request: DeploymentQualificationRequest) -> DeploymentCapabilityFacts: ...


class DeploymentQualificationPort(Protocol):
    def qualify(self, request: DeploymentQualificationRequest) -> DeploymentQualificationPlan: ...


class DeploymentQualificationEvidenceStorePort(Protocol):
    def publish(self, record: DeploymentQualificationEvidenceRecord) -> DeploymentQualificationEvidenceRecord: ...
    def get(self, plan_digest: str) -> DeploymentQualificationEvidenceRecord: ...


@dataclass(frozen=True, slots=True)
class DeploymentQualificationApplicationRequest:
    """Request to materialize one already-persisted plan into one environment."""

    plan_digest: str
    environment_id: str

    def __post_init__(self) -> None:
        if len(self.plan_digest) != 64 or any(char not in "0123456789abcdef" for char in self.plan_digest):
            raise ValueError("qualification application requires a lowercase plan digest")
        if not self.environment_id.strip():
            raise ValueError("qualification application environment_id is required")


@dataclass(frozen=True, slots=True)
class QualificationCommandReceipt:
    operation: str
    command_digest: str
    return_code: int
    stdout_digest: str
    stderr_digest: str

    def __post_init__(self) -> None:
        _require_text(self.operation, "qualification command operation")
        _require_sha256(self.command_digest, "qualification command_digest")
        if isinstance(self.return_code, bool) or not isinstance(self.return_code, int):
            raise ValueError("qualification command return_code must be an integer")
        _require_sha256(self.stdout_digest, "qualification stdout_digest")
        _require_sha256(self.stderr_digest, "qualification stderr_digest")


@dataclass(frozen=True, slots=True)
class DeploymentQualificationApplicationReceipt:
    plan_digest: str
    environment_id: str
    backend: str | None
    packages: tuple[InstallPackage, ...]
    install_commands: tuple[QualificationCommandReceipt, ...]
    check_command: QualificationCommandReceipt | None
    status: QualificationMaterializationStatus
    reasons: tuple[str, ...] = ()
    application_digest: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate every package/command/reason before issuing the application digest.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the number of variable-length packages, command receipts, and reason strings that must each be type-checked before this durable qualification receipt is trusted.
        """
        _require_sha256(self.plan_digest, "qualification application plan_digest")
        _require_text(self.environment_id, "qualification application environment_id")
        if self.backend is not None:
            _require_text(self.backend, "qualification application backend")
        if not isinstance(self.packages, tuple) or any(
            not isinstance(item, InstallPackage) for item in self.packages
        ):
            raise ValueError("qualification application packages must be typed")
        if not isinstance(self.install_commands, tuple) or any(
            not isinstance(item, QualificationCommandReceipt) for item in self.install_commands
        ):
            raise ValueError("qualification install_commands must be typed receipts")
        if self.check_command is not None and not isinstance(
            self.check_command, QualificationCommandReceipt
        ):
            raise ValueError("qualification check_command must be a typed receipt")
        if not isinstance(self.status, QualificationMaterializationStatus):
            raise ValueError("qualification application status is invalid")
        _require_string_tuple(self.reasons, "qualification application reasons")
        object.__setattr__(
            self,
            "application_digest",
            canonical_digest(
                {
                    "plan_digest": self.plan_digest,
                    "environment_id": self.environment_id,
                    "backend": self.backend,
                    "packages": self.packages,
                    "install_commands": self.install_commands,
                    "check_command": self.check_command,
                    "status": self.status,
                    "reasons": self.reasons,
                }
            ),
        )


class DeploymentQualificationApplicationPort(Protocol):
    def apply(
        self,
        request: DeploymentQualificationApplicationRequest,
    ) -> DeploymentQualificationApplicationReceipt: ...


class QualificationPackageInstallerPort(Protocol):
    def install(
        self,
        environment_id: str,
        packages: tuple[InstallPackage, ...],
    ) -> tuple[QualificationCommandReceipt, ...]: ...

    def check(self, environment_id: str) -> QualificationCommandReceipt: ...


class DeploymentQualificationApplicationStorePort(Protocol):
    def publish(
        self,
        receipt: DeploymentQualificationApplicationReceipt,
    ) -> DeploymentQualificationApplicationReceipt: ...

    def get(self, application_digest: str) -> DeploymentQualificationApplicationReceipt: ...


@dataclass(frozen=True, slots=True)
class DeploymentQualificationRuntimeRequest:
    application_digest: str

    def __post_init__(self) -> None:
        if len(self.application_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.application_digest
        ):
            raise ValueError("runtime qualification requires a lowercase application digest")


@dataclass(frozen=True, slots=True)
class RuntimeCheckReceipt:
    check: str
    command_digest: str
    return_code: int
    stdout_digest: str
    stderr_digest: str
    stdout_preview: str = ""
    stderr_preview: str = ""

    def __post_init__(self) -> None:
        _require_text(self.check, "runtime qualification check")
        _require_sha256(self.command_digest, "runtime qualification command_digest")
        if isinstance(self.return_code, bool) or not isinstance(self.return_code, int):
            raise ValueError("runtime qualification return_code must be an integer")
        _require_sha256(self.stdout_digest, "runtime qualification stdout_digest")
        _require_sha256(self.stderr_digest, "runtime qualification stderr_digest")
        if not isinstance(self.stdout_preview, str) or not isinstance(self.stderr_preview, str):
            raise ValueError("runtime qualification previews must be strings")


@dataclass(frozen=True, slots=True)
class DeploymentQualificationRuntimeReceipt:
    application_digest: str
    plan_digest: str
    environment_id: str
    backend: str | None
    checks: tuple[RuntimeCheckReceipt, ...]
    status: DeploymentRuntimeQualificationStatus
    reasons: tuple[str, ...] = ()
    runtime_digest: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate every runtime check/reason before issuing the runtime digest.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the number of runtime checks and reason strings carried by the receipt; fail-closed construction must inspect every variable-length typed element.
        """
        _require_sha256(self.application_digest, "runtime qualification application_digest")
        _require_sha256(self.plan_digest, "runtime qualification plan_digest")
        _require_text(self.environment_id, "runtime qualification environment_id")
        if self.backend is not None:
            _require_text(self.backend, "runtime qualification backend")
        if not isinstance(self.checks, tuple) or any(
            not isinstance(item, RuntimeCheckReceipt) for item in self.checks
        ):
            raise ValueError("runtime qualification checks must be typed receipts")
        if not isinstance(self.status, DeploymentRuntimeQualificationStatus):
            raise ValueError("runtime qualification status is invalid")
        _require_string_tuple(self.reasons, "runtime qualification reasons")
        object.__setattr__(
            self,
            "runtime_digest",
            canonical_digest(
                {
                    "application_digest": self.application_digest,
                    "plan_digest": self.plan_digest,
                    "environment_id": self.environment_id,
                    "backend": self.backend,
                    "checks": self.checks,
                    "status": self.status,
                    "reasons": self.reasons,
                }
            ),
        )


class DeploymentQualificationRuntimePort(Protocol):
    def qualify(
        self,
        request: DeploymentQualificationRuntimeRequest,
    ) -> DeploymentQualificationRuntimeReceipt: ...


class QualificationRuntimeProbePort(Protocol):
    def probe(
        self,
        environment_id: str,
        backend: str,
        model_path: Path,
        tensor_parallel: int,
    ) -> tuple[RuntimeCheckReceipt, ...]: ...


class DeploymentQualificationRuntimeStorePort(Protocol):
    def publish(
        self,
        receipt: DeploymentQualificationRuntimeReceipt,
    ) -> DeploymentQualificationRuntimeReceipt: ...

    def get(self, runtime_digest: str) -> DeploymentQualificationRuntimeReceipt: ...


__all__ = [
    "BackendCandidatePlan",
    "CandidateDecision",
    "DeploymentQualificationApplicationPort",
    "DeploymentQualificationApplicationReceipt",
    "DeploymentQualificationApplicationRequest",
    "DeploymentQualificationApplicationStorePort",
    "DeploymentQualificationRuntimePort",
    "DeploymentQualificationRuntimeReceipt",
    "DeploymentQualificationRuntimeRequest",
    "DeploymentQualificationRuntimeStorePort",
    "CudaFacts",
    "DEFAULT_DEPLOYMENT_PROBE_TIMEOUT_SECONDS",
    "DEFAULT_PACKAGE_INDEX_URL",
    "native_cuda_runtime_package_names",
    "DeploymentCapabilityFacts",
    "DeploymentCapabilityProbePort",
    "DeploymentQualificationPlan",
    "DeploymentQualificationEvidenceRecord",
    "DeploymentQualificationEvidenceStorePort",
    "DeploymentQualificationPort",
    "DeploymentQualificationRequest",
    "GpuCapabilityFacts",
    "GpuFabricFacts",
    "HostExecutionFacts",
    "InstallPackage",
    "ModelArtifactFacts",
    "OperatingSystemFacts",
    "PackageArtifactFacts",
    "PackageDependencyNodeFacts",
    "PackageIndexFacts",
    "PythonRuntimeFacts",
    "StorageCapabilityFacts",
    "QualificationCommandReceipt",
    "QualificationMaterializationStatus",
    "QualificationPackageInstallerPort",
    "DeploymentRuntimeQualificationStatus",
    "QualificationRuntimeProbePort",
    "RuntimeCheckReceipt",
]
