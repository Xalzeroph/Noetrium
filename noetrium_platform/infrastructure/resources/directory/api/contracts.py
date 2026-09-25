from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from noetrium_platform.foundation.governance.api import ScopeIdentity, scope_to_data
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
    durable_carrier_closure_complete,
    durable_carrier_gc_eligible,
    validate_durable_carrier_closures,
)


class WorkspaceMetadataFailureCode(StrEnum):
    DOCUMENT_INTEGRITY = "document-integrity"
    PAYLOAD_SHAPE = "payload-shape"
    IDENTITY_MISMATCH = "identity-mismatch"


class WorkspaceMetadataError(RuntimeError):
    """Machine-classified durable workspace metadata failure."""

    def __init__(self, code: WorkspaceMetadataFailureCode) -> None:
        self.code = code
        super().__init__(f"workspace metadata failure: {code.value}")

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        return (f"resource-workspace-metadata:{self.code.value}",)


@dataclass(frozen=True, slots=True)
class WorkspaceGcAssessment:
    """Exact fail-closed GC cut for one durable recovery workspace."""

    workspace_id: str
    scope: ScopeIdentity
    category: str
    closures: tuple[DurableCarrierReferenceClosure, ...] = ()
    workspace_identity_digest: str = field(init=False)
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("workspace_id", self.workspace_id),
            ("category", self.category),
            ("scope_id", self.scope.scope_id),
        ):
            if (
                type(value) is not str
                or not value
                or value in {".", ".."}
                or "/" in value
                or "\\" in value
            ):
                raise ValueError(f"invalid workspace GC {label}")
        validate_durable_carrier_closures(self.closures)

        identity_digest = canonical_digest(
            {
                "schema": "resource.workspace-identity.v1",
                "scope": scope_to_data(self.scope),
                "category": self.category,
                "workspace_id": self.workspace_id,
            }
        )
        object.__setattr__(self, "workspace_identity_digest", identity_digest)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "resource.workspace-gc-assessment.v1",
                    "workspace_identity_digest": identity_digest,
                    "closures": [
                        {
                            "authority": value.authority.value,
                            "proof_digest": value.proof_digest,
                            "retained_reference_ids": list(
                                value.retained_reference_ids
                            ),
                        }
                        for value in self.closures
                    ],
                }
            ),
        )

    @property
    def closure_complete(self) -> bool:
        return durable_carrier_closure_complete(self.closures)

    @property
    def eligible(self) -> bool:
        return durable_carrier_gc_eligible(self.closures)


class ManagedDirectoryKind(StrEnum):
    RELEASES = "releases"
    RUNTIME = "runtime"
    STATE = "state"
    LOGS = "logs"
    MODEL_ARTIFACTS = "model_artifacts"
    PYTHON_ENVIRONMENTS = "python_environments"
    CACHE = "cache"
    TEMP = "temp"
    LOCKS = "locks"
    WORKSPACES = "workspaces"


@dataclass(frozen=True, slots=True)
class DirectoryLayout:
    releases: Path
    runtime: Path
    state: Path
    logs: Path
    model_artifacts: Path
    python_environments: Path
    cache: Path
    temp: Path
    locks: Path
    workspaces: Path

    def path_for(self, kind: ManagedDirectoryKind) -> Path:
        return getattr(self, kind.value)

    def entries(self) -> tuple[tuple[ManagedDirectoryKind, Path], ...]:
        return tuple((kind, self.path_for(kind)) for kind in ManagedDirectoryKind)


@dataclass(frozen=True, slots=True)
class WorkspaceAllocation:
    workspace_id: str
    scope: ScopeIdentity
    category: str
    path: Path
    owner: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class DirectoryContentStats:
    path: Path
    files: int
    directories: int
    bytes: int


@dataclass(frozen=True, slots=True)
class DirectoryUsage:
    path: Path
    total_bytes: int
    used_bytes: int
    free_bytes: int
    total_inodes: int | None = None
    free_inodes: int | None = None


@dataclass(frozen=True, slots=True)
class DirectoryOverview:
    path: Path
    top_level_entries: int
    total_bytes: int
    used_bytes: int
    free_bytes: int
    total_inodes: int | None = None
    free_inodes: int | None = None


@dataclass(frozen=True, slots=True)
class DirectoryEntryStats:
    path: Path
    files: int
    directories: int
    bytes: int


@dataclass(frozen=True, slots=True)
class DirectoryCleanupCandidate:
    path: Path
    modified_at: float
    files: int
    directories: int
    bytes: int
    device: int
    inode: int
    change_time_ns: int


__all__ = [
    "DirectoryCleanupCandidate",
    "DirectoryContentStats",
    "DirectoryEntryStats",
    "DirectoryLayout",
    "DirectoryOverview",
    "DirectoryUsage",
    "ManagedDirectoryKind",
    "WorkspaceAllocation",
    "WorkspaceGcAssessment",
    "WorkspaceMetadataError",
    "WorkspaceMetadataFailureCode",
]
