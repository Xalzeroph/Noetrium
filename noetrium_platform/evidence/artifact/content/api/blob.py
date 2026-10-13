from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ContextManager, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierReferenceClosure,
    canonical_digest,
    durable_carrier_gc_eligible,
    require_sha256,
    validate_durable_carrier_closures,
)


@dataclass(frozen=True, slots=True)
class ArtifactBlobRef:
    content_sha256: str
    size_bytes: int
    media_type: str

    def __post_init__(self) -> None:
        require_sha256(self.content_sha256, "artifact blob content_sha256")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("artifact blob size_bytes must be a non-negative integer")
        if type(self.media_type) is not str or not self.media_type.strip():
            raise ValueError("artifact blob media_type must be non-empty")


class ArtifactBlobLifecycleState(StrEnum):
    ACTIVE = "active"
    RETIRING = "retiring"
    PURGED = "purged"


@dataclass(frozen=True, slots=True)
class ArtifactBlobGcAssessment:
    """Typed proof binding physical blob GC to one exact CAS generation."""

    content_sha256: str
    size_bytes: int
    generation: int
    closures: tuple[DurableCarrierReferenceClosure, ...] = ()
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(
            self.content_sha256,
            "artifact blob GC content_sha256",
        )
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 0
        ):
            raise ValueError(
                "artifact blob GC size_bytes must be a non-negative integer"
            )
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation <= 0
        ):
            raise ValueError(
                "artifact blob GC generation must be a positive integer"
            )
        validate_durable_carrier_closures(self.closures)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "artifact.blob-gc-assessment.v1",
                    "content_sha256": self.content_sha256,
                    "size_bytes": self.size_bytes,
                    "generation": self.generation,
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
    def eligible(self) -> bool:
        return durable_carrier_gc_eligible(self.closures)


@dataclass(frozen=True, slots=True)
class ArtifactBlobGeneration:
    content_sha256: str
    generation: int
    state: ArtifactBlobLifecycleState
    gc_proof_digest: str | None = None

    def __post_init__(self) -> None:
        require_sha256(
            self.content_sha256,
            "artifact blob generation content_sha256",
        )
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation <= 0
        ):
            raise ValueError(
                "artifact blob generation must be a positive integer"
            )
        if type(self.state) is not ArtifactBlobLifecycleState:
            raise TypeError("artifact blob lifecycle state must be typed")
        if self.gc_proof_digest is not None:
            require_sha256(
                self.gc_proof_digest,
                "artifact blob generation gc_proof_digest",
            )
        if (
            self.state is ArtifactBlobLifecycleState.ACTIVE
            and self.gc_proof_digest is not None
        ):
            raise ValueError(
                "active artifact blob generation cannot retain a GC proof"
            )
        if (
            self.state is not ArtifactBlobLifecycleState.ACTIVE
            and self.gc_proof_digest is None
        ):
            raise ValueError(
                "retiring/purged artifact blob generation requires a GC proof"
            )


@runtime_checkable
class ArtifactBlobFencePort(Protocol):
    ref: ArtifactBlobRef
    generation: ArtifactBlobGeneration

    def read(self) -> bytes: ...

    def assess_gc(
        self,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> ArtifactBlobGcAssessment: ...

    def purge(
        self,
        *,
        gc: ArtifactBlobGcAssessment,
    ) -> ArtifactBlobGeneration: ...


@runtime_checkable
class ArtifactBlobLifecyclePort(Protocol):
    """Physical generation/fencing authority for a content-addressed blob."""

    def publish_fenced(
        self,
        payload: bytes,
        *,
        media_type: str,
    ) -> ContextManager[ArtifactBlobRef]: ...

    def fence(
        self,
        ref: ArtifactBlobRef,
    ) -> ContextManager[ArtifactBlobFencePort]: ...

    def generation(
        self,
        ref: ArtifactBlobRef,
    ) -> ArtifactBlobGeneration: ...

    def assess_gc(
        self,
        ref: ArtifactBlobRef,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> ArtifactBlobGcAssessment: ...

    def purge(
        self,
        ref: ArtifactBlobRef,
        *,
        gc: ArtifactBlobGcAssessment,
    ) -> ArtifactBlobGeneration: ...


class ArtifactBlobStoreError(RuntimeError):
    pass

@runtime_checkable
class ArtifactBlobResolverPort(Protocol):
    """Resolve already-materialized blob identity without host-path knowledge."""

    def resolve(
        self,
        content_sha256: str,
        *,
        media_type: str,
    ) -> ArtifactBlobRef: ...


@runtime_checkable
class ArtifactBlobStorePort(Protocol):
    durability: str

    def put_many(
        self,
        items: tuple[tuple[bytes, str], ...],
    ) -> tuple[ArtifactBlobRef, ...]: ...
    def put(self, payload: bytes, *, media_type: str) -> ArtifactBlobRef: ...

    def get(self, ref: ArtifactBlobRef) -> bytes: ...

    def verify(self, ref: ArtifactBlobRef) -> bool: ...


__all__ = [
    "ArtifactBlobFencePort",
    "ArtifactBlobGcAssessment",
    "ArtifactBlobGeneration",
    "ArtifactBlobLifecyclePort",
    "ArtifactBlobLifecycleState",
    "ArtifactBlobRef",
    "ArtifactBlobResolverPort",
    "ArtifactBlobStoreError",
    "ArtifactBlobStorePort",
]
