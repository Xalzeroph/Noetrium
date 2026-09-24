from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
)
from .gc import CheckpointGcAssessment, CheckpointNamespace
from noetrium_platform.research.execution.api import ParticipantCheckpoint, ParticipantCheckpointRef


def _require_manifest_identity(values: tuple[object, ...]) -> None:
    if any(type(value) is not str or not value.strip() for value in values):
        raise ValueError("RunCheckpointManifest identity fields must be non-empty strings")


@dataclass(frozen=True, slots=True)
class RunParticipantSnapshotRef:
    """Run-level metadata around a generic participant checkpoint identity."""

    checkpoint: ParticipantCheckpointRef
    generation: str | None = None

    def __post_init__(self) -> None:
        if type(self.checkpoint) is not ParticipantCheckpointRef:
            raise ValueError("run participant snapshot checkpoint must be ParticipantCheckpointRef")
        if self.generation is not None and (
            type(self.generation) is not str or not self.generation.strip()
        ):
            raise ValueError("run participant snapshot generation must be a non-empty string or None")

    @property
    def role(self) -> str:
        return self.checkpoint.role


def _require_snapshot_topology(values: object) -> tuple[RunParticipantSnapshotRef, ...]:
    if type(values) is not tuple or any(type(row) is not RunParticipantSnapshotRef for row in values):
        raise ValueError("participant snapshots must be an immutable tuple of RunParticipantSnapshotRef values")
    roles = tuple(row.role for row in values)
    if len(roles) != len(set(roles)):
        raise ValueError("participant snapshot roles must be unique")
    return values


@dataclass(frozen=True, slots=True)
class RunParticipantPayload:
    ref: RunParticipantSnapshotRef
    checkpoint: ParticipantCheckpoint

    def __post_init__(self) -> None:
        if type(self.ref) is not RunParticipantSnapshotRef:
            raise ValueError("run participant payload ref must be RunParticipantSnapshotRef")
        if type(self.checkpoint) is not ParticipantCheckpoint:
            raise ValueError("run participant payload checkpoint must be ParticipantCheckpoint")
        if self.ref.checkpoint != self.checkpoint.ref:
            raise ValueError("run participant checkpoint ref does not match checkpoint envelope")


@dataclass(frozen=True, slots=True)
class RunCheckpointManifest:
    checkpoint_id: str
    schema_version: str
    experiment_spec_digest: str
    run_id: str
    session_id: str
    decision_cycle_id: str
    cycle_identity_digest: str
    participant_snapshots: tuple[RunParticipantSnapshotRef, ...]

    def __post_init__(self) -> None:
        required = (
            self.checkpoint_id,
            self.schema_version,
            self.experiment_spec_digest,
            self.run_id,
            self.session_id,
            self.decision_cycle_id,
            self.cycle_identity_digest,
        )
        _require_manifest_identity(required)
        _require_snapshot_topology(self.participant_snapshots)

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class RunCheckpointBundle:
    manifest: RunCheckpointManifest
    participant_payloads: tuple[RunParticipantPayload, ...]

    def __post_init__(self) -> None:
        if type(self.manifest) is not RunCheckpointManifest:
            raise ValueError("run checkpoint bundle manifest must be RunCheckpointManifest")
        if type(self.participant_payloads) is not tuple or any(
            type(row) is not RunParticipantPayload for row in self.participant_payloads
        ):
            raise ValueError("run checkpoint bundle participant payloads must be an immutable typed tuple")
        manifest_roles = {row.role for row in self.manifest.participant_snapshots}
        payload_roles = tuple(row.ref.role for row in self.participant_payloads)
        if len(payload_roles) != len(set(payload_roles)):
            raise ValueError("run checkpoint bundle participant payload roles must be unique")
        if set(payload_roles) != manifest_roles:
            raise ValueError("run checkpoint bundle payload roles must match the manifest")


class RunCheckpointConflict(RuntimeError):
    pass


class RunCheckpointIntegrityError(RuntimeError):
    pass


class RunCheckpointRecoveryRequired(RuntimeError):
    """A durable checkpoint publication exists but has not committed its manifest."""

    def __init__(
        self,
        checkpoint_id: str,
        *,
        namespace: str,
        manifest_sha256: str,
        blob_sha256s: tuple[str, ...],
    ) -> None:
        self.checkpoint_id = checkpoint_id
        self.namespace = namespace
        self.manifest_sha256 = manifest_sha256
        self.blob_sha256s = blob_sha256s
        super().__init__(
            "checkpoint publication requires recovery before lookup can "
            f"resolve: {namespace}:{checkpoint_id}"
        )

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        return (
            f"checkpoint-publication:{self.namespace}:{self.checkpoint_id}",
            f"checkpoint-manifest-sha256:{self.manifest_sha256}",
        )


@runtime_checkable
class RunCheckpointStore(Protocol):
    durability: str

    def publish(
        self,
        manifest: RunCheckpointManifest,
        participant_payloads: tuple[RunParticipantPayload, ...],
    ) -> RunCheckpointManifest: ...

    def load(self, checkpoint_id: str) -> RunCheckpointBundle: ...

    def assess_gc(
        self,
        checkpoint_id: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> CheckpointGcAssessment: ...

    def purge(
        self,
        checkpoint_id: str,
        *,
        gc: CheckpointGcAssessment,
    ) -> bool: ...


__all__ = [
    "RunCheckpointBundle",
    "RunCheckpointConflict",
    "CheckpointGcAssessment",
    "CheckpointNamespace",
    "RunCheckpointIntegrityError",
    "RunCheckpointManifest",
    "RunCheckpointRecoveryRequired",
    "RunCheckpointStore",
    "RunParticipantPayload",
    "RunParticipantSnapshotRef",
]
