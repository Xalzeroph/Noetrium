"""Paper-general measurement contracts.

Measurements are typed run outputs, not telemetry aliases and not statistics.
Small values are frozen inline; large values carry a durable content reference id
owned by the Artifact/Data systems.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import math

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRegistryPort
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference, ArtifactReferencePort
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json

_HEX = frozenset("0123456789abcdef")


def _text(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _sha(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return text


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{field_name} must be a tuple")
    if any(type(item) is not str or not item.strip() for item in value):
        raise TypeError(f"{field_name} must contain non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field_name} must be unique")
    return value




class MeasurementValueKind(StrEnum):
    SCALAR = "scalar"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"
    STRUCTURED = "structured"
    SEQUENCE = "sequence"
    DISTRIBUTION = "distribution"
    MATRIX = "matrix"
    TEXT_JUDGEMENT = "text_judgement"
    CONTENT_REFERENCE = "content_reference"


@dataclass(frozen=True, slots=True)
class MeasurementContentReference:
    reference: ArtifactReference
    content_digest: str
    schema_id: str
    media_type: str
    reference_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.reference) is not ArtifactReference:
            raise TypeError("measurement content reference must use ArtifactReference")
        _sha(self.content_digest, "measurement content content_digest")
        _text(self.schema_id, "measurement content schema_id")
        _text(self.media_type, "measurement content media_type")
        object.__setattr__(self, "reference_digest", canonical_digest({"reference": self.reference, "content_digest": self.content_digest, "schema_id": self.schema_id, "media_type": self.media_type}))

    def verify(self, references: ArtifactReferencePort, artifacts: ArtifactRegistryPort) -> None:
        resolved = references.resolve(self.reference.reference_id, self.reference.scope)
        if resolved != self.reference:
            raise ValueError("measurement content reference generation drift")
        record = artifacts.get(self.reference.artifact_id)
        if record.digest != self.content_digest:
            raise ValueError("measurement content digest mismatch")

@dataclass(frozen=True, slots=True)
class MeasurementDefinition:
    measurement_id: str
    schema_id: str
    value_kind: MeasurementValueKind
    unit: str | None = None
    description: str = ""
    semantic_kind: str = "measurement"
    scale: str | None = None
    domain: str | None = None
    semantic_contract_digest: str = field(init=False)
    definition_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.measurement_id, "measurement definition measurement_id")
        _text(self.schema_id, "measurement definition schema_id")
        _text(self.semantic_kind, "measurement definition semantic_kind")
        if not isinstance(self.value_kind, MeasurementValueKind):
            raise TypeError("measurement definition value_kind must be MeasurementValueKind")
        for name, value in (("unit", self.unit), ("scale", self.scale), ("domain", self.domain)):
            if value is not None:
                _text(value, f"measurement definition {name}")
        if type(self.description) is not str:
            raise TypeError("measurement definition description must be a string")
        semantic = canonical_digest({"measurement_id": self.measurement_id, "schema_id": self.schema_id, "semantic_kind": self.semantic_kind, "value_kind": self.value_kind.value, "unit": self.unit, "scale": self.scale, "domain": self.domain})
        object.__setattr__(self, "semantic_contract_digest", semantic)
        object.__setattr__(self, "definition_digest", canonical_digest({"semantic_contract_digest": semantic, "description": self.description}))

    @classmethod
    def scalar(
        cls,
        measurement_id: str,
        *,
        schema_id: str,
        unit: str | None = None,
        description: str = "",
        semantic_kind: str = "measurement",
        scale: str | None = None,
        domain: str | None = None,
    ) -> "MeasurementDefinition":
        """Construct the common scalar measurement without exposing value-kind plumbing."""
        return cls(
            measurement_id=measurement_id,
            schema_id=schema_id,
            value_kind=MeasurementValueKind.SCALAR,
            unit=unit,
            description=description,
            semantic_kind=semantic_kind,
            scale=scale,
            domain=domain,
        )


@dataclass(frozen=True, slots=True)
class MeasurementProtocol:
    protocol_id: str
    definitions: tuple[MeasurementDefinition, ...]
    schema_version: str = "2"
    semantic_digest: str = field(init=False)
    protocol_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.protocol_id, "measurement protocol protocol_id")
        _text(self.schema_version, "measurement protocol schema_version")
        if type(self.definitions) is not tuple or not self.definitions:
            raise TypeError("measurement protocol definitions must be a non-empty tuple")
        if any(type(item) is not MeasurementDefinition for item in self.definitions):
            raise TypeError("measurement protocol definitions must be MeasurementDefinition")
        ids = tuple(item.measurement_id for item in self.definitions)
        if len(ids) != len(set(ids)):
            raise ValueError("measurement protocol measurement ids must be unique")
        semantic = canonical_digest({"protocol_id": self.protocol_id, "schema_version": self.schema_version, "definitions": tuple(item.semantic_contract_digest for item in self.definitions)})
        object.__setattr__(self, "semantic_digest", semantic)
        object.__setattr__(self, "protocol_digest", canonical_digest({"semantic_digest": semantic, "definitions": tuple(item.definition_digest for item in self.definitions)}))

    def definition(self, measurement_id: str) -> MeasurementDefinition:
        matches = tuple(item for item in self.definitions if item.measurement_id == measurement_id)
        if len(matches) != 1:
            raise KeyError(f"measurement protocol has no unique {measurement_id!r}")
        return matches[0]


@dataclass(frozen=True, slots=True)
class MeasurementValue:
    kind: MeasurementValueKind
    scalar: float | None = None
    boolean: bool | None = None
    categorical: str | None = None
    structured: Mapping[str, JsonValue] | None = None
    sequence: tuple[JsonValue, ...] | None = None
    distribution: tuple[tuple[float, float], ...] | None = None
    matrix: tuple[tuple[float, ...], ...] | None = None
    text_judgement: str | None = None
    content_reference: MeasurementContentReference | None = None

    def __post_init__(self) -> None:
        """Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the populated carrier size; exactly one carrier is active and each distribution row or matrix cell is validated once.
        """
        if not isinstance(self.kind, MeasurementValueKind):
            raise TypeError("measurement value kind must be MeasurementValueKind")
        carriers = (self.scalar, self.boolean, self.categorical, self.structured, self.sequence, self.distribution, self.matrix, self.text_judgement, self.content_reference)
        if sum(value is not None for value in carriers) != 1:
            raise ValueError("measurement value must populate exactly one carrier")
        if self.kind is MeasurementValueKind.SCALAR:
            if isinstance(self.scalar, bool) or not isinstance(self.scalar, (int, float)) or not math.isfinite(float(self.scalar)):
                raise ValueError("scalar measurement must be finite numeric")
            object.__setattr__(self, "scalar", float(self.scalar))
        elif self.kind is MeasurementValueKind.BOOLEAN:
            if type(self.boolean) is not bool:
                raise TypeError("boolean measurement must be boolean")
        elif self.kind is MeasurementValueKind.CATEGORICAL:
            _text(self.categorical, "categorical measurement value")
        elif self.kind is MeasurementValueKind.STRUCTURED:
            if not isinstance(self.structured, Mapping):
                raise TypeError("structured measurement value must be a mapping")
            object.__setattr__(self, "structured", freeze_json(self.structured))
        elif self.kind is MeasurementValueKind.SEQUENCE:
            if type(self.sequence) is not tuple:
                raise TypeError("sequence measurement value must be a tuple")
            object.__setattr__(self, "sequence", freeze_json(self.sequence))
        elif self.kind is MeasurementValueKind.DISTRIBUTION:
            if type(self.distribution) is not tuple or not self.distribution:
                raise TypeError("distribution measurement must be a non-empty tuple")
            total = 0.0
            for row in self.distribution:
                if type(row) is not tuple or len(row) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in row):
                    raise TypeError("distribution rows must be finite numeric value/probability pairs")
                if row[1] < 0:
                    raise ValueError("distribution probabilities cannot be negative")
                total += float(row[1])
            if total <= 0:
                raise ValueError("distribution probability mass must be positive")
        elif self.kind is MeasurementValueKind.MATRIX:
            if type(self.matrix) is not tuple or not self.matrix or any(type(row) is not tuple or not row for row in self.matrix):
                raise TypeError("matrix measurement must be a non-empty rectangular tuple")
            width = len(self.matrix[0])
            if any(len(row) != width for row in self.matrix) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) for row in self.matrix for v in row):
                raise ValueError("matrix measurement must be rectangular and finite numeric")
        elif self.kind is MeasurementValueKind.TEXT_JUDGEMENT:
            _text(self.text_judgement, "text judgement measurement")
        elif self.kind is MeasurementValueKind.CONTENT_REFERENCE:
            if type(self.content_reference) is not MeasurementContentReference:
                raise TypeError("content-reference measurement requires MeasurementContentReference")
        expected = {MeasurementValueKind.SCALAR:self.scalar, MeasurementValueKind.BOOLEAN:self.boolean, MeasurementValueKind.CATEGORICAL:self.categorical, MeasurementValueKind.STRUCTURED:self.structured, MeasurementValueKind.SEQUENCE:self.sequence, MeasurementValueKind.DISTRIBUTION:self.distribution, MeasurementValueKind.MATRIX:self.matrix, MeasurementValueKind.TEXT_JUDGEMENT:self.text_judgement, MeasurementValueKind.CONTENT_REFERENCE:self.content_reference}
        if expected[self.kind] is None:
            raise ValueError("measurement value carrier does not match its kind")

    def digest(self) -> str:
        payload = {MeasurementValueKind.SCALAR:self.scalar, MeasurementValueKind.BOOLEAN:self.boolean, MeasurementValueKind.CATEGORICAL:self.categorical, MeasurementValueKind.STRUCTURED:self.structured, MeasurementValueKind.SEQUENCE:self.sequence, MeasurementValueKind.DISTRIBUTION:self.distribution, MeasurementValueKind.MATRIX:self.matrix, MeasurementValueKind.TEXT_JUDGEMENT:self.text_judgement, MeasurementValueKind.CONTENT_REFERENCE:self.content_reference.reference_digest if self.content_reference else None}[self.kind]
        return canonical_digest({"kind": self.kind.value, "value": payload})


@dataclass(frozen=True, slots=True)
class MeasurementRecord:
    project_id: str
    study_id: str
    run_id: str
    assignment_digest: str
    variant_id: str
    producer_id: str
    producer_revision_digest: str
    measurement_id: str
    schema_id: str
    measurement_semantic_digest: str
    measurement_protocol_semantic_digest: str
    value: MeasurementValue
    logical_time: str
    intervention: OptionalIdentityFacet
    revision: OptionalIdentityFacet
    lineage_refs: tuple[ArtifactReference, ...] = ()
    record_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name, value in (("project_id", self.project_id), ("study_id", self.study_id), ("run_id", self.run_id), ("variant_id", self.variant_id), ("producer_id", self.producer_id), ("measurement_id", self.measurement_id), ("schema_id", self.schema_id), ("logical_time", self.logical_time)):
            _text(value, f"measurement record {field_name}")
        for field_name, value in (("assignment_digest", self.assignment_digest), ("producer_revision_digest", self.producer_revision_digest), ("measurement_semantic_digest", self.measurement_semantic_digest), ("measurement_protocol_semantic_digest", self.measurement_protocol_semantic_digest)):
            _sha(value, f"measurement record {field_name}")
        if type(self.intervention) is not OptionalIdentityFacet or type(self.revision) is not OptionalIdentityFacet:
            raise TypeError("measurement record intervention/revision must be OptionalIdentityFacet")
        if type(self.value) is not MeasurementValue:
            raise TypeError("measurement record value must be MeasurementValue")
        if type(self.lineage_refs) is not tuple or any(type(row) is not ArtifactReference for row in self.lineage_refs):
            raise TypeError("measurement record lineage_refs must contain ArtifactReference")
        if len(self.lineage_refs) != len(set(self.lineage_refs)):
            raise ValueError("measurement record lineage_refs must be unique")
        object.__setattr__(self, "record_digest", canonical_digest({"project_id":self.project_id, "study_id":self.study_id, "run_id":self.run_id, "assignment_digest":self.assignment_digest, "variant_id":self.variant_id, "producer_id":self.producer_id, "producer_revision_digest":self.producer_revision_digest, "measurement_id":self.measurement_id, "schema_id":self.schema_id, "measurement_semantic_digest":self.measurement_semantic_digest, "measurement_protocol_semantic_digest":self.measurement_protocol_semantic_digest, "value_digest":self.value.digest(), "logical_time":self.logical_time, "intervention":self.intervention, "revision":self.revision, "lineage_refs":self.lineage_refs}))

    def validate_against(self, protocol: MeasurementProtocol) -> None:
        if type(protocol) is not MeasurementProtocol:
            raise TypeError("measurement protocol must be MeasurementProtocol")
        if protocol.semantic_digest != self.measurement_protocol_semantic_digest:
            raise ValueError("measurement record protocol semantics do not match")
        definition = protocol.definition(self.measurement_id)
        if definition.semantic_contract_digest != self.measurement_semantic_digest:
            raise ValueError("measurement record semantic definition does not match protocol")
        if definition.schema_id != self.schema_id:
            raise ValueError("measurement record schema does not match protocol")
        if definition.value_kind is not self.value.kind:
            raise ValueError("measurement record value kind does not match protocol")




__all__ = [
    "MeasurementContentReference",
    "MeasurementDefinition",
    "MeasurementProtocol",
    "MeasurementRecord",
    "MeasurementValue",
    "MeasurementValueKind",
]
