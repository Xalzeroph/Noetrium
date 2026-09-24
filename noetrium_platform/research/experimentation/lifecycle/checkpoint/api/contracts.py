from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
    durable_carrier_closure_complete,
    durable_carrier_gc_eligible,
    validate_durable_carrier_closures,
)
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


class RunCheckpointPersistenceState(StrEnum):
    COMMITTED = "committed"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class RunCheckpointGcAssessment:
    """Exact proof-backed GC cut for one durable checkpoint generation."""

    checkpoint_id: str
    persistence_state: RunCheckpointPersistenceState
    state_digest: str
    blob_sha256s: tuple[str, ...]
    closures: tuple[DurableCarrierReferenceClosure, ...] = ()
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.checkpoint_id) is not str
            or not self.checkpoint_id.strip()
            or self.checkpoint_id != self.checkpoint_id.strip()
        ):
            raise ValueError("checkpoint GC checkpoint_id must be canonical text")
        if type(self.persistence_state) is not RunCheckpointPersistenceState:
            raise TypeError("checkpoint GC persistence_state must be typed")
        for label, value in (("state_digest", self.state_digest),):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"checkpoint GC {label} must be lowercase sha256")
        if type(self.blob_sha256s) is not tuple or any(
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in self.blob_sha256s
        ):
            raise TypeError("checkpoint GC blob_sha256s must be sha256 tuple")
        if self.blob_sha256s != tuple(sorted(set(self.blob_sha256s))):
            raise ValueError("checkpoint GC blob_sha256s must be unique sorted order")
        validate_durable_carrier_closures(self.closures)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "noetrium.run-checkpoint-gc-assessment.v1",
                    "checkpoint_id": self.checkpoint_id,
                    "persistence_state": self.persistence_state.value,
                    "state_digest": self.state_digest,
                    "blob_sha256s": list(self.blob_sha256s),
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
    ) -> RunCheckpointGcAssessment: ...

    def purge(
        self,
        checkpoint_id: str,
        *,
        gc: RunCheckpointGcAssessment,
    ) -> bool: ...


__all__ = [
    "RunCheckpointBundle",
    "RunCheckpointConflict",
    "RunCheckpointGcAssessment",
    "RunCheckpointIntegrityError",
    "RunCheckpointManifest",
    "RunCheckpointPersistenceState",
    "RunCheckpointRecoveryRequired",
    "RunCheckpointStore",
    "RunParticipantPayload",
    "RunParticipantSnapshotRef",
]
