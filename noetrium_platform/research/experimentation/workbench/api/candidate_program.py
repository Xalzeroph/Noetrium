from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.foundation.kernel.kernel import canonical_digest

_HEX = frozenset("0123456789abcdef")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _sha(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return text


def _sha_tuple(
    value: object,
    field_name: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    if not allow_empty and not value:
        raise ValueError(f"{field_name} must be non-empty")
    rows = tuple(_sha(item, field_name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field_name} must be unique")
    return rows


@dataclass(frozen=True, slots=True)
class CandidateProgramIdentity:
    """Immutable identity for one generated/evolved executable candidate.

    This contract does not own search, mutation, selection, promotion or fitness
    semantics. Source bytes remain Artifact-owned; this value only binds those
    bytes to one executable candidate generation and interface.
    """

    candidate_id: str
    generation: int
    source: ArtifactContentIdentity
    language: str
    entrypoint: str
    interface_schema_id: str
    parent_candidate_digests: tuple[str, ...] = ()
    candidate_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate program candidate_id")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("candidate program generation must be non-negative")
        if type(self.source) is not ArtifactContentIdentity:
            raise TypeError(
                "candidate program source must be ArtifactContentIdentity"
            )
        _text(self.language, "candidate program language")
        _text(self.entrypoint, "candidate program entrypoint")
        _text(self.interface_schema_id, "candidate program interface_schema_id")
        parents = _sha_tuple(
            self.parent_candidate_digests,
            "candidate program parent digest",
        )
        object.__setattr__(
            self,
            "parent_candidate_digests",
            tuple(sorted(parents)),
        )
        object.__setattr__(
            self,
            "candidate_digest",
            canonical_digest(
                {
                    "schema": "noetrium.candidate-program.v1",
                    "candidate_id": self.candidate_id,
                    "generation": self.generation,
                    "source": {
                        "artifact_id": self.source.artifact_id,
                        "content_sha256": self.source.content_sha256,
                    },
                    "language": self.language,
                    "entrypoint": self.entrypoint,
                    "interface_schema_id": self.interface_schema_id,
                    "parent_candidate_digests": tuple(sorted(parents)),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateProgramExecutionRequest:
    """Isolation-bound request to execute one exact candidate on one exact cut."""

    candidate: CandidateProgramIdentity
    benchmark_cut_digest: str
    evaluator_digest: str
    isolation_requirement_id: str
    input_artifacts: tuple[ArtifactContentIdentity, ...] = ()
    resource_requirement_digest: str | None = None
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.candidate) is not CandidateProgramIdentity:
            raise TypeError(
                "candidate execution request requires CandidateProgramIdentity"
            )
        _sha(
            self.benchmark_cut_digest,
            "candidate execution benchmark_cut_digest",
        )
        _sha(self.evaluator_digest, "candidate execution evaluator_digest")
        _text(
            self.isolation_requirement_id,
            "candidate execution isolation_requirement_id",
        )
        if type(self.input_artifacts) is not tuple or any(
            type(row) is not ArtifactContentIdentity
            for row in self.input_artifacts
        ):
            raise TypeError(
                "candidate execution input_artifacts must contain "
                "ArtifactContentIdentity"
            )
        artifact_ids = tuple(row.artifact_id for row in self.input_artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError(
                "candidate execution input artifact ids must be unique"
            )
        if self.resource_requirement_digest is not None:
            _sha(
                self.resource_requirement_digest,
                "candidate execution resource_requirement_digest",
            )
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest(
                {
                    "schema": "noetrium.candidate-program-execution-request.v1",
                    "candidate_digest": self.candidate.candidate_digest,
                    "benchmark_cut_digest": self.benchmark_cut_digest,
                    "evaluator_digest": self.evaluator_digest,
                    "isolation_requirement_id": self.isolation_requirement_id,
                    "input_artifacts": tuple(
                        (row.artifact_id, row.content_sha256)
                        for row in self.input_artifacts
                    ),
                    "resource_requirement_digest": (
                        self.resource_requirement_digest
                    ),
                }
            ),
        )


class CandidateProgramExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CandidateProgramExecutionReceipt:
    """Non-authoritative receipt binding execution evidence to one exact request.

    Scientific values remain MeasurementRecord-owned. The receipt carries only
    their immutable digests and therefore cannot redefine metric semantics.
    """

    request_digest: str
    status: CandidateProgramExecutionStatus
    output_artifacts: tuple[ArtifactContentIdentity, ...] = ()
    measurement_record_digests: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    isolation_evidence_digests: tuple[str, ...] = ()
    failure_code: str | None = None
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.request_digest, "candidate execution receipt request_digest")
        if not isinstance(self.status, CandidateProgramExecutionStatus):
            raise TypeError(
                "candidate execution receipt status must be "
                "CandidateProgramExecutionStatus"
            )
        if type(self.output_artifacts) is not tuple or any(
            type(row) is not ArtifactContentIdentity
            for row in self.output_artifacts
        ):
            raise TypeError(
                "candidate execution output_artifacts must contain "
                "ArtifactContentIdentity"
            )
        artifact_ids = tuple(row.artifact_id for row in self.output_artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError(
                "candidate execution output artifact ids must be unique"
            )
        for field_name in (
            "measurement_record_digests",
            "evidence_digests",
            "isolation_evidence_digests",
        ):
            value = _sha_tuple(
                getattr(self, field_name),
                f"candidate execution receipt {field_name}",
            )
            object.__setattr__(self, field_name, tuple(sorted(value)))
        if self.failure_code is not None:
            _text(
                self.failure_code,
                "candidate execution receipt failure_code",
            )
        if (
            self.status is CandidateProgramExecutionStatus.SUCCEEDED
            and self.failure_code is not None
        ):
            raise ValueError(
                "successful candidate execution cannot carry failure_code"
            )
        if (
            self.status is not CandidateProgramExecutionStatus.SUCCEEDED
            and self.failure_code is None
        ):
            raise ValueError(
                "failed/rejected candidate execution requires failure_code"
            )
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(
                {
                    "schema": "noetrium.candidate-program-execution-receipt.v1",
                    "request_digest": self.request_digest,
                    "status": self.status.value,
                    "output_artifacts": tuple(
                        (row.artifact_id, row.content_sha256)
                        for row in self.output_artifacts
                    ),
                    "measurement_record_digests": (
                        self.measurement_record_digests
                    ),
                    "evidence_digests": self.evidence_digests,
                    "isolation_evidence_digests": (
                        self.isolation_evidence_digests
                    ),
                    "failure_code": self.failure_code,
                }
            ),
        )


class CandidateProgramExecutionPort(Protocol):
    """Execution mechanism; owns neither candidate nor measurement authority."""

    def execute(
        self,
        request: CandidateProgramExecutionRequest,
    ) -> CandidateProgramExecutionReceipt: ...


@dataclass(frozen=True, slots=True)
class CandidateProgramMeasurementProjection:
    """Read-only scalar projection tied to one authoritative MeasurementRecord digest."""

    measurement_id: str
    record_digest: str
    scalar: float

    def __post_init__(self) -> None:
        _text(self.measurement_id, "candidate measurement projection measurement_id")
        _sha(self.record_digest, "candidate measurement projection record_digest")
        if isinstance(self.scalar, bool) or not isinstance(self.scalar, (int, float)):
            raise TypeError("candidate measurement projection scalar must be numeric")


class CandidateProgramSourcePublicationPort(Protocol):
    """Publish generated source through Artifact authority and return immutable identity."""

    def publish_source(
        self,
        *,
        candidate_id: str,
        generation: int,
        language: str,
        source_text: str,
    ) -> ArtifactContentIdentity: ...


class CandidateProgramMeasurementProjectionPort(Protocol):
    """Project authoritative measurement records for method-time candidate selection."""

    def project(
        self,
        receipt: CandidateProgramExecutionReceipt,
        *,
        measurement_ids: tuple[str, ...],
    ) -> tuple[CandidateProgramMeasurementProjection, ...]: ...


__all__ = [
    "CandidateProgramExecutionPort",
    "CandidateProgramExecutionReceipt",
    "CandidateProgramExecutionRequest",
    "CandidateProgramExecutionStatus",
    "CandidateProgramIdentity",
    "CandidateProgramMeasurementProjection",
    "CandidateProgramMeasurementProjectionPort",
    "CandidateProgramSourcePublicationPort",
]
