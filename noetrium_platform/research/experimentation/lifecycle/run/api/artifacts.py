from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    JsonDocument,
    JsonInput,
    canonical_digest,
    durable_carrier_closure_complete,
    durable_carrier_gc_eligible,
    require_sha256,
    validate_durable_carrier_closures,
)

T = TypeVar("T")
_HEX = frozenset("0123456789abcdef")


def _require_identity(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"run artifact {field} must be a non-empty string")
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError(f"run artifact {field} is invalid")
    return value


def _require_artifact_ref(value: object) -> str:
    if type(value) is not str or not value.strip() or "\\" in value or value.startswith("/"):
        raise ValueError("run artifact ref must be a non-empty run-local path")
    parts = value.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError("run artifact ref contains an unsafe path component")
    return value

def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(ch not in _HEX for ch in value):
        raise ValueError(f"run artifact {field} must be SHA-256")
    return value


def _require_non_negative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"run artifact {field} must be a non-negative integer")
    return value


class RunArtifactKind(StrEnum):
    MANIFEST = "manifest"
    PREFLIGHT = "preflight"
    RESULT = "result"
    LOG = "log"
    CLEANUP = "cleanup"
    CHECKPOINT = "checkpoint"
    EVIDENCE = "evidence"
    MODEL = "model"
    METRIC = "metric"
    METHOD = "method"


class RunArtifactFinalizationError(RuntimeError):
    pass


class RunArtifactVerificationError(RuntimeError):
    pass


class RunArtifactSealedError(RuntimeError):
    pass

@dataclass(frozen=True, slots=True)
class RunArtifactSnapshotReceipt:
    run_id: str
    artifact_ref: str
    artifact_kind: RunArtifactKind
    generation: str
    content_sha256: str
    byte_size: int
    record_count: int | None

    def __post_init__(self) -> None:
        _require_identity(self.run_id, "run_id")
        _require_artifact_ref(self.artifact_ref)
        if type(self.artifact_kind) is not RunArtifactKind:
            raise ValueError("run artifact kind must be RunArtifactKind")
        _require_sha256(self.generation, "generation")
        _require_sha256(self.content_sha256, "content_sha256")
        _require_non_negative_int(self.byte_size, "byte_size")
        if self.record_count is not None:
            _require_non_negative_int(self.record_count, "record_count")


@dataclass(frozen=True, slots=True)
class RunArtifactGcAssessment:
    """Exact fail-closed physical GC cut for one run-local Artifact carrier."""

    run_id: str
    tree_digest: str
    entry_count: int
    total_bytes: int
    closures: tuple[DurableCarrierReferenceClosure, ...] = ()
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _require_identity(self.run_id, "GC run_id")
        require_sha256(self.tree_digest, "run artifact GC tree_digest")
        for field_name, value in (
            ("entry_count", self.entry_count),
            ("total_bytes", self.total_bytes),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"run artifact GC {field_name} must be non-negative"
                )
        validate_durable_carrier_closures(self.closures)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "run-artifact.gc-assessment.v1",
                    "run_id": self.run_id,
                    "tree_digest": self.tree_digest,
                    "entry_count": self.entry_count,
                    "total_bytes": self.total_bytes,
                    "closures": [
                        {
                            "authority": closure.authority.value,
                            "proof_digest": closure.proof_digest,
                            "retained_reference_ids": list(
                                closure.retained_reference_ids
                            ),
                        }
                        for closure in self.closures
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


class RunArtifactFinalizationPort(Protocol):
    def finalize(
        self,
        artifact_ref: str,
        *,
        kind: RunArtifactKind,
        record_stream: bool,
    ) -> RunArtifactSnapshotReceipt: ...


class RunArtifactVerificationPort(Protocol):
    def verify_finalized(self, receipt: RunArtifactSnapshotReceipt) -> RunArtifactSnapshotReceipt: ...

class RunArtifactWriteActorPort(Protocol):
    """Run-local serial owner for mutable durable artifact writes."""

    def call(
        self,
        operation: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> T: ...


@runtime_checkable
class RunArtifactStorePort(RunArtifactFinalizationPort, RunArtifactVerificationPort, Protocol):
    """The only run-owned interface for durable run artifacts."""

    def path(self, name: str, *, kind: RunArtifactKind) -> str: ...

    def directory(self, name: str, *, kind: RunArtifactKind) -> str: ...

    def publish_json(self, name: str, payload: JsonInput | JsonDocument, *, kind: RunArtifactKind) -> str: ...

    def publish_text(self, name: str, content: str, *, kind: RunArtifactKind) -> str: ...

    def append_json(
        self,
        name: str,
        payload: JsonDocument,
        *,
        kind: RunArtifactKind,
    ) -> str: ...

    def assess_gc(
        self,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> RunArtifactGcAssessment: ...

    def purge(
        self,
        *,
        gc: RunArtifactGcAssessment,
    ) -> bool: ...


__all__ = [
    "RunArtifactFinalizationError",
    "RunArtifactFinalizationPort",
    "RunArtifactGcAssessment",
    "RunArtifactKind",
    "RunArtifactSnapshotReceipt",
    "RunArtifactSealedError",
    "RunArtifactStorePort",
    "RunArtifactVerificationError",
    "RunArtifactVerificationPort",
    "RunArtifactWriteActorPort",
]
