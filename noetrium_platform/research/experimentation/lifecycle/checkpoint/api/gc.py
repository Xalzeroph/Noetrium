from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
    durable_carrier_closure_complete,
    durable_carrier_gc_eligible,
    validate_durable_carrier_closures,
)


class CheckpointNamespace(StrEnum):
    RUN = "run"
    WORKLOAD = "workload"


class CheckpointPersistenceState(StrEnum):
    COMMITTED = "committed"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class CheckpointGcAssessment:
    """Exact proof-backed GC cut for one checkpoint namespace and generation."""

    namespace: CheckpointNamespace
    checkpoint_id: str
    persistence_state: CheckpointPersistenceState
    state_digest: str
    blob_sha256s: tuple[str, ...]
    closures: tuple[DurableCarrierReferenceClosure, ...] = ()
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.namespace) is not CheckpointNamespace:
            raise TypeError("checkpoint GC namespace must be typed")
        if (
            type(self.checkpoint_id) is not str
            or not self.checkpoint_id.strip()
            or self.checkpoint_id != self.checkpoint_id.strip()
        ):
            raise ValueError("checkpoint GC checkpoint_id must be canonical text")
        if type(self.persistence_state) is not CheckpointPersistenceState:
            raise TypeError("checkpoint GC persistence_state must be typed")
        if (
            type(self.state_digest) is not str
            or len(self.state_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.state_digest)
        ):
            raise ValueError("checkpoint GC state_digest must be lowercase sha256")
        if type(self.blob_sha256s) is not tuple or any(
            type(value) is not str
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
            for value in self.blob_sha256s
        ):
            raise TypeError("checkpoint GC blob_sha256s must be sha256 tuple")
        if self.blob_sha256s != tuple(sorted(set(self.blob_sha256s))):
            raise ValueError(
                "checkpoint GC blob_sha256s must be unique sorted order"
            )
        validate_durable_carrier_closures(self.closures)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "noetrium.checkpoint-gc-assessment.v1",
                    "namespace": self.namespace.value,
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


__all__ = [
    "CheckpointGcAssessment",
    "CheckpointNamespace",
    "CheckpointPersistenceState",
]
