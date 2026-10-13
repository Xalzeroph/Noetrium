from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.api import ArtifactContentIdentity
from noetrium_platform.capabilities.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    JsonInput,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def _sha(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    require_sha256(text, field_name)
    return text


def _sha_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    rows = tuple(_sha(item, field_name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field_name} must be unique")
    return rows


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    rows = tuple(_text(item, field_name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field_name} must be unique")
    return rows


def _artifact_tuple(
    value: object,
    field_name: str,
) -> tuple[ArtifactContentIdentity, ...]:
    if type(value) is not tuple or any(
        type(row) is not ArtifactContentIdentity for row in value
    ):
        raise TypeError(
            f"{field_name} must be a tuple of ArtifactContentIdentity"
        )
    rows = tuple(value)
    artifact_ids = tuple(row.artifact_id for row in rows)
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError(f"{field_name} artifact ids must be unique")
    return rows


@dataclass(frozen=True, slots=True)
class PublishedExecutableUnitSource:
    """Artifact-owned logical identity plus content-addressed executable bytes."""

    identity: ArtifactContentIdentity
    content: ArtifactBlobRef

    def __post_init__(self) -> None:
        if type(self.identity) is not ArtifactContentIdentity:
            raise TypeError(
                "published executable source identity must be ArtifactContentIdentity"
            )
        if type(self.content) is not ArtifactBlobRef:
            raise TypeError(
                "published executable source content must be ArtifactBlobRef"
            )
        if self.identity.content_sha256 != self.content.content_sha256:
            raise ValueError(
                "published executable source identity/content digest mismatch"
            )


EXECUTABLE_PROGRAM_TRAIT = "execution.executable-program"


def executable_program_unit(
    *,
    program_id: str,
    source: PublishedExecutableUnitSource,
    language: str,
    entrypoint: str,
    interface_schema_id: str,
    parent_program_digests: tuple[str, ...] = (),
) -> NoetriumUnit:
    """Freeze executable program semantics while Artifact authority owns bytes."""

    program_id = _text(program_id, "executable program program_id")
    if type(source) is not PublishedExecutableUnitSource:
        raise TypeError(
            "executable program source must be PublishedExecutableUnitSource"
        )
    language = _text(language, "executable program language")
    entrypoint = _text(entrypoint, "executable program entrypoint")
    interface_schema_id = _text(
        interface_schema_id,
        "executable program interface_schema_id",
    )
    parents = tuple(
        sorted(
            _sha_tuple(
                parent_program_digests,
                "executable program parent digest",
            )
        )
    )
    return structure_unit(
        program_id,
        traits=(EXECUTABLE_PROGRAM_TRAIT,),
        parameters={
            "source_artifact_id": source.identity.artifact_id,
            "source_content_sha256": source.identity.content_sha256,
            "source_size_bytes": source.content.size_bytes,
            "source_media_type": source.content.media_type,
            "language": language,
            "entrypoint": entrypoint,
            "interface_schema_id": interface_schema_id,
            "parent_program_digests": parents,
        },
    )


def require_executable_program(value: NoetriumUnit) -> NoetriumUnit:
    if (
        type(value) is not NoetriumUnit
        or not value.has_trait(EXECUTABLE_PROGRAM_TRAIT)
    ):
        raise TypeError(
            "executable program must be execution.executable-program NoetriumUnit"
        )
    return value


def executable_program_field(value: NoetriumUnit, name: str):
    value = require_executable_program(value)
    if name == "program_id":
        return value.unit_id
    if name == "program_digest":
        return value.unit_digest
    return value.parameters[name]


def executable_program_source_matches(
    value: NoetriumUnit,
    source: PublishedExecutableUnitSource,
) -> bool:
    value = require_executable_program(value)
    if type(source) is not PublishedExecutableUnitSource:
        return False
    return (
        value.parameters["source_artifact_id"] == source.identity.artifact_id
        and value.parameters["source_content_sha256"]
        == source.identity.content_sha256
        and value.parameters["source_size_bytes"] == source.content.size_bytes
        and value.parameters["source_media_type"] == source.content.media_type
    )


@dataclass(frozen=True, slots=True)
class ProgramExecutionRequest:
    """One exact executable program invocation at a qualified execution seam.

    The request freezes the allowed capability surface separately from the
    target binding. A provider may implement the mechanics with a process,
    container, VM, WASI runtime, remote worker, or another qualified mechanism;
    none of those choices become program semantics.
    """

    program: NoetriumUnit
    source: PublishedExecutableUnitSource
    capability_surface_id: str
    capability_surface_digest: str
    execution_target_digest: str
    isolation_requirement_id: str
    invocation: JsonObject
    capability_ids: tuple[str, ...] = ()
    input_artifacts: tuple[ArtifactContentIdentity, ...] = ()
    resource_requirement_digest: str | None = None
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_executable_program(self.program)
        if type(self.source) is not PublishedExecutableUnitSource:
            raise TypeError(
                "program execution request requires PublishedExecutableUnitSource"
            )
        if not executable_program_source_matches(self.program, self.source):
            raise ValueError(
                "program execution source handle does not match executable program Unit"
            )
        _text(
            self.capability_surface_id,
            "program execution capability_surface_id",
        )
        _sha(
            self.capability_surface_digest,
            "program execution capability_surface_digest",
        )
        _sha(
            self.execution_target_digest,
            "program execution execution_target_digest",
        )
        _text(
            self.isolation_requirement_id,
            "program execution isolation_requirement_id",
        )
        capability_ids = _text_tuple(
            self.capability_ids,
            "program execution capability_ids",
        )
        if not isinstance(self.invocation, Mapping):
            raise TypeError("program execution invocation must be a mapping")
        frozen = freeze_json(self.invocation)
        if not isinstance(frozen, Mapping):
            raise TypeError("program execution invocation must freeze to object")
        object.__setattr__(self, "invocation", frozen)
        artifacts = _artifact_tuple(
            self.input_artifacts,
            "program execution input_artifacts",
        )
        object.__setattr__(self, "input_artifacts", artifacts)
        if self.resource_requirement_digest is not None:
            _sha(
                self.resource_requirement_digest,
                "program execution resource_requirement_digest",
            )
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest(
                {
                    "schema": "noetrium.program-execution-request.v1",
                    "program_digest": self.program.unit_digest,
                    "capability_surface_id": self.capability_surface_id,
                    "capability_surface_digest": self.capability_surface_digest,
                    "execution_target_digest": self.execution_target_digest,
                    "isolation_requirement_id": self.isolation_requirement_id,
                    "invocation": frozen,
                    "capability_ids": capability_ids,
                    "input_artifacts": tuple(
                        (row.artifact_id, row.content_sha256)
                        for row in artifacts
                    ),
                    "resource_requirement_digest": (
                        self.resource_requirement_digest
                    ),
                }
            ),
        )


@runtime_checkable
class ExecutableUnitSourcePublicationPort(Protocol):
    """Publish exact generated source bytes into immutable Artifact authority."""

    def publish_source(
        self,
        *,
        program_id: str,
        language: str,
        source_text: str,
    ) -> PublishedExecutableUnitSource: ...


class ProgramExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ProgramExecutionReceipt:
    """Evidence references for one exact program-execution request.

    Environment/effect truth remains owned by the existing effect authorities.
    This receipt links to those receipts and to Artifact/Evidence identities
    rather than copying mutable world state into Execution authority.
    """

    request_digest: str
    status: ProgramExecutionStatus
    effect_certainty: EffectCertainty
    result: JsonValue = None
    output_artifacts: tuple[ArtifactContentIdentity, ...] = ()
    effect_receipt_digests: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    isolation_evidence_digests: tuple[str, ...] = ()
    failure_code: str | None = None
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.request_digest, "program execution receipt request_digest")
        if not isinstance(self.status, ProgramExecutionStatus):
            raise TypeError(
                "program execution receipt status must be ProgramExecutionStatus"
            )
        if not isinstance(self.effect_certainty, EffectCertainty):
            raise TypeError(
                "program execution receipt effect_certainty must be EffectCertainty"
            )
        if (
            self.status is ProgramExecutionStatus.REJECTED
            and self.effect_certainty is not EffectCertainty.EFFECT_REJECTED
        ):
            raise ValueError(
                "rejected program execution requires EFFECT_REJECTED certainty"
            )
        object.__setattr__(self, "result", freeze_json(self.result))
        artifacts = _artifact_tuple(
            self.output_artifacts,
            "program execution output_artifacts",
        )
        object.__setattr__(self, "output_artifacts", artifacts)
        for field_name in (
            "effect_receipt_digests",
            "evidence_digests",
            "isolation_evidence_digests",
        ):
            rows = tuple(
                sorted(
                    _sha_tuple(
                        getattr(self, field_name),
                        f"program execution receipt {field_name}",
                    )
                )
            )
            object.__setattr__(self, field_name, rows)
        if self.failure_code is not None:
            _text(self.failure_code, "program execution receipt failure_code")
        if (
            self.status is ProgramExecutionStatus.SUCCEEDED
            and self.failure_code is not None
        ):
            raise ValueError(
                "successful program execution cannot carry failure_code"
            )
        if (
            self.status is not ProgramExecutionStatus.SUCCEEDED
            and self.failure_code is None
        ):
            raise ValueError(
                "failed/rejected program execution requires failure_code"
            )
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_digest(
                {
                    "schema": "noetrium.program-execution-receipt.v1",
                    "request_digest": self.request_digest,
                    "status": self.status.value,
                    "effect_certainty": self.effect_certainty.value,
                    "result": self.result,
                    "output_artifacts": tuple(
                        (row.artifact_id, row.content_sha256)
                        for row in artifacts
                    ),
                    "effect_receipt_digests": self.effect_receipt_digests,
                    "evidence_digests": self.evidence_digests,
                    "isolation_evidence_digests": (
                        self.isolation_evidence_digests
                    ),
                    "failure_code": self.failure_code,
                }
            ),
        )


class ProgramExecutionReconciliationDisposition(StrEnum):
    APPLIED = "applied"
    REJECTED = "rejected"
    NOT_APPLIED = "not_applied"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProgramExecutionReconciliationResult:
    request_digest: str
    disposition: ProgramExecutionReconciliationDisposition
    receipt: ProgramExecutionReceipt | None = None
    evidence_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _sha(
            self.request_digest,
            "program execution reconciliation request_digest",
        )
        if not isinstance(
            self.disposition,
            ProgramExecutionReconciliationDisposition,
        ):
            raise TypeError(
                "program execution reconciliation disposition is invalid"
            )
        if self.receipt is not None:
            if not isinstance(self.receipt, ProgramExecutionReceipt):
                raise TypeError(
                    "program execution reconciliation receipt must be typed"
                )
            if self.receipt.request_digest != self.request_digest:
                raise ValueError(
                    "program execution reconciliation receipt identity mismatch"
                )
        evidence = tuple(
            sorted(
                _sha_tuple(
                    self.evidence_digests,
                    "program execution reconciliation evidence digest",
                )
            )
        )
        object.__setattr__(self, "evidence_digests", evidence)
        if (
            self.disposition
            in {
                ProgramExecutionReconciliationDisposition.APPLIED,
                ProgramExecutionReconciliationDisposition.REJECTED,
            }
            and self.receipt is None
        ):
            raise ValueError(
                "applied/rejected program reconciliation requires receipt"
            )
        if (
            self.disposition
            is ProgramExecutionReconciliationDisposition.NOT_APPLIED
            and self.receipt is not None
        ):
            raise ValueError(
                "not-applied program reconciliation cannot carry receipt"
            )


@runtime_checkable
class ProgramExecutionRecoveryPort(Protocol):
    """Crash-durable recovery seam for an effectful program executor."""

    @property
    def effect_recovery_durability(self) -> str: ...

    def reconcile(
        self,
        request: ProgramExecutionRequest,
    ) -> ProgramExecutionReconciliationResult: ...


@runtime_checkable
class ProgramExecutionPort(Protocol):
    """Provider seam for qualified execution of one immutable program request."""

    def execute(
        self,
        request: ProgramExecutionRequest,
    ) -> ProgramExecutionReceipt: ...


__all__ = [
    "EXECUTABLE_PROGRAM_TRAIT",
    "executable_program_unit",
    "executable_program_field",
    "executable_program_source_matches",
    "require_executable_program",
    "ExecutableUnitSourcePublicationPort",
    "PublishedExecutableUnitSource",
    "ProgramExecutionPort",
    "ProgramExecutionRecoveryPort",
    "ProgramExecutionReconciliationDisposition",
    "ProgramExecutionReconciliationResult",
    "ProgramExecutionReceipt",
    "ProgramExecutionRequest",
    "ProgramExecutionStatus",
]
