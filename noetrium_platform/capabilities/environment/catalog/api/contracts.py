from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.substrate.api import ScopeIdentity
from noetrium_platform.substrate.api import ResolutionPolicy


class EnvironmentProfileLifecycle(StrEnum):
    ACTIVE = "active"
    DRAINING = "draining"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class EnvironmentProfileRevision:
    profile_id: str
    category_id: str
    profile_revision: str
    lifecycle: EnvironmentProfileLifecycle = EnvironmentProfileLifecycle.ACTIVE

    def __post_init__(self) -> None:
        for field_name, value in (
            ("profile_id", self.profile_id),
            ("category_id", self.category_id),
        ):
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    f"environment profile {field_name} must be canonical non-empty text"
                )
        revision = self.profile_revision
        if (
            type(revision) is not str
            or len(revision) != 64
            or any(ch not in "0123456789abcdef" for ch in revision)
        ):
            raise ValueError(
                "environment profile revision must be lowercase sha256"
            )
        if type(self.lifecycle) is not EnvironmentProfileLifecycle:
            raise TypeError(
                "environment profile lifecycle must be EnvironmentProfileLifecycle"
            )


class EnvironmentInstanceState(StrEnum):
    CLEAN = "clean"
    IN_USE = "in_use"
    DIRTY = "dirty"
    DESTROYED = "destroyed"


class EnvironmentCleanlinessKind(StrEnum):
    OVERLAY_DESTROYED = "overlay_destroyed"
    PROVIDER_RESET_VERIFIED = "provider_reset_verified"


class ExecutionEnvironmentKind(StrEnum):
    PYTHON = "python"
    CONDA = "conda"
    MAMBA = "mamba"
    NODE = "node"
    CONTAINER = "container"
    NATIVE = "native"
    REMOTE = "remote"


@dataclass(frozen=True, slots=True)
class EnvironmentTemplate:
    template_id: str
    kind: ExecutionEnvironmentKind
    scope: ScopeIdentity
    base_spec_id: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    spec_id: str
    kind: ExecutionEnvironmentKind
    scope: ScopeIdentity
    parent_spec_id: str | None = None
    template_id: str | None = None
    requirements: tuple[tuple[str, str], ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EnvironmentOverlay:
    overlay_id: str
    target_spec_id: str
    scope: ScopeIdentity
    requirements: tuple[tuple[str, str], ...] = ()
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class EnvironmentAssignment:
    name: str
    spec_id: str
    scope: ScopeIdentity
    policy: ResolutionPolicy = ResolutionPolicy.INHERIT


@dataclass(frozen=True, slots=True)
class ResolvedEnvironmentSpec:
    spec_id: str
    kind: ExecutionEnvironmentKind
    requested_scope: ScopeIdentity
    source_scopes: tuple[ScopeIdentity, ...]
    source_spec_ids: tuple[str, ...]
    applied_overlay_ids: tuple[str, ...]
    requirements: tuple[tuple[str, str], ...]
    environment: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class EnvironmentInstance:
    instance_id: str
    resolved_spec_digest: str
    backend: str
    runtime_reference: str
    runtime_identity_digest: str
    scope: ScopeIdentity
    profile_id: str
    profile_revision: str
    state: EnvironmentInstanceState = EnvironmentInstanceState.CLEAN
    generation: int = 0
    cleanliness_proof_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.instance_id.strip():
            raise ValueError("environment instance_id must be non-empty")
        if not self.profile_id.strip():
            raise ValueError("environment instance profile_id must be non-empty")
        for field_name, value in (
            ("resolved_spec_digest", self.resolved_spec_digest),
            ("runtime_identity_digest", self.runtime_identity_digest),
            ("profile_revision", self.profile_revision),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"environment instance {field_name} must be lowercase sha256"
                )
        for field_name, value in (
            ("backend", self.backend),
            ("runtime_reference", self.runtime_reference),
        ):
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError(
                    f"environment instance {field_name} must be canonical non-empty text"
                )
        if type(self.state) is not EnvironmentInstanceState:
            raise TypeError("environment instance state must be EnvironmentInstanceState")
        if isinstance(self.generation, bool) or self.generation < 0:
            raise ValueError("environment instance generation must be non-negative")
        proof = self.cleanliness_proof_digest
        if proof is not None and (
            len(proof) != 64
            or any(ch not in "0123456789abcdef" for ch in proof)
        ):
            raise ValueError(
                "environment cleanliness proof digest must be lowercase sha256"
            )
        if self.state is EnvironmentInstanceState.DESTROYED and proof is not None:
            raise ValueError("destroyed environment instance cannot retain cleanliness proof")


@dataclass(frozen=True, slots=True)
class EnvironmentCleanlinessProof:
    instance_id: str
    profile_revision: str
    runtime_identity_digest: str
    generation: int
    kind: EnvironmentCleanlinessKind
    proof_digest: str

    def __post_init__(self) -> None:
        if not self.instance_id.strip():
            raise ValueError("environment cleanliness proof instance_id must be non-empty")
        for label, value in (
            ("profile_revision", self.profile_revision),
            ("runtime_identity_digest", self.runtime_identity_digest),
            ("proof_digest", self.proof_digest),
        ):
            if (
                len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(
                    f"environment cleanliness {label} must be lowercase sha256"
                )
        if type(self.kind) is not EnvironmentCleanlinessKind:
            raise TypeError(
                "environment cleanliness kind must be EnvironmentCleanlinessKind"
            )
        if isinstance(self.generation, bool) or self.generation <= 0:
            raise ValueError(
                "environment cleanliness generation must identify an acquired generation"
            )


@dataclass(frozen=True, slots=True)
class EnvironmentProfileReferenceSummary:
    profile_id: str
    profile_revision: str
    instance_ids: tuple[str, ...]
    bound_instance_ids: tuple[str, ...]
    reusable_instance_ids: tuple[str, ...]
    blocking_instance_ids: tuple[str, ...]

    @property
    def locally_gc_eligible(self) -> bool:
        return not self.bound_instance_ids and not self.blocking_instance_ids


@dataclass(frozen=True, slots=True)
class EnvironmentProfileGcAssessment:
    """Fail-closed profile-GC decision across local, execution and evidence truth."""

    profile_id: str
    profile_revision: str
    local: EnvironmentProfileReferenceSummary
    resumable_execution_ids: tuple[str, ...] | None = None
    retained_evidence_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.local.profile_id != self.profile_id:
            raise ValueError("environment GC local profile identity drifted")
        if self.local.profile_revision != self.profile_revision:
            raise ValueError("environment GC local profile revision drifted")
        for field_name in (
            "resumable_execution_ids",
            "retained_evidence_ids",
        ):
            values = getattr(self, field_name)
            if values is None:
                continue
            if type(values) is not tuple or any(
                type(value) is not str
                or not value.strip()
                or value != value.strip()
                for value in values
            ):
                raise TypeError(
                    f"environment GC {field_name} must be canonical text tuple"
                )
            if values != tuple(sorted(set(values))):
                raise ValueError(
                    f"environment GC {field_name} must be unique sorted order"
                )

    @property
    def external_reference_closure_complete(self) -> bool:
        return (
            self.resumable_execution_ids is not None
            and self.retained_evidence_ids is not None
        )

    @property
    def eligible(self) -> bool:
        return (
            self.local.locally_gc_eligible
            and self.external_reference_closure_complete
            and not self.resumable_execution_ids
            and not self.retained_evidence_ids
        )


@dataclass(frozen=True, slots=True)
class EnvironmentBinding:
    binding_id: str
    scope: ScopeIdentity
    role: str
    instance_id: str


@dataclass(frozen=True, slots=True)
class EnvironmentInstanceAcquisition:
    """One atomically selected and generation-fenced reusable instance binding."""

    binding: EnvironmentBinding
    instance: EnvironmentInstance

    def __post_init__(self) -> None:
        if type(self.binding) is not EnvironmentBinding:
            raise TypeError("environment acquisition binding must be EnvironmentBinding")
        if type(self.instance) is not EnvironmentInstance:
            raise TypeError("environment acquisition instance must be EnvironmentInstance")
        if self.binding.instance_id != self.instance.instance_id:
            raise ValueError("environment acquisition binding instance drifted")
        if self.instance.state is not EnvironmentInstanceState.IN_USE:
            raise ValueError("environment acquisition instance must be IN_USE")
        if self.instance.generation <= 0:
            raise ValueError("environment acquisition requires a fenced generation")


__all__ = [
    "EnvironmentAssignment",
    "EnvironmentBinding",
    "EnvironmentCleanlinessKind",
    "EnvironmentCleanlinessProof",
    "EnvironmentInstance",
    "EnvironmentInstanceAcquisition",
    "EnvironmentInstanceState",
    "EnvironmentProfileGcAssessment",
    "EnvironmentProfileLifecycle",
    "EnvironmentProfileRevision",
    "EnvironmentProfileReferenceSummary",
    "EnvironmentOverlay",
    "EnvironmentSpec",
    "EnvironmentTemplate",
    "ExecutionEnvironmentKind",
    "ResolvedEnvironmentSpec",
]
