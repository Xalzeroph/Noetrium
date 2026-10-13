"""Scientific Analysis identity over pinned Measurement cuts; storage remains ROLE05-owned."""
from __future__ import annotations


from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.research.execution.api import ArtifactRegistryPort
from noetrium_platform.research.execution.api import ArtifactReference, ArtifactReferencePort
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit

_HEX = frozenset("0123456789abcdef")


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _sha(value: object, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return text


def _digests(value: object, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not tuple or (not allow_empty and not value):
        raise TypeError(f"{field} must be a {'possibly empty ' if allow_empty else 'non-empty '}tuple")
    for row in value:
        _sha(row, field)
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must be unique")
    previous: str | None = None
    for row in value:
        if previous is not None and row <= previous:
            raise ValueError(f"{field} must be canonically ordered")
        previous = row
    return value


class DatasetIdentityProjection(Protocol):
    @property
    def key(self) -> str: ...


class DatasetVersionProjection(Protocol):
    identity: DatasetIdentityProjection
    content_sha256: str
    schema_ref: str | None


class EvidenceStatusProjection(Protocol):
    value: str


class EvidenceManifestProjection(Protocol):
    run_id: str
    status: EvidenceStatusProjection

    @property
    def digest(self) -> str: ...


MEASUREMENT_CUT_TRAIT = "research.measurement-cut"


def measurement_cut_unit(
    *,
    record_digests: tuple[str, ...] = (),
    source_run_digests: tuple[str, ...] = (),
    dataset_versions: tuple[DatasetVersionProjection, ...] = (),
    evidence_manifests: tuple[EvidenceManifestProjection, ...] = (),
) -> NoetriumUnit:
    record_digests = _digests(
        record_digests,
        "measurement cut record_digests",
        allow_empty=True,
    )
    source_run_digests = _digests(
        source_run_digests,
        "measurement cut source_run_digests",
        allow_empty=True,
    )
    if not (record_digests or dataset_versions or evidence_manifests):
        raise ValueError("measurement cut requires Measurement, Dataset, or Evidence inputs")

    dataset_rows: list[tuple[str, str, str | None]] = []
    previous_dataset: str | None = None
    for row in dataset_versions:
        key = getattr(getattr(row, "identity", None), "key", None)
        digest = getattr(row, "content_sha256", None)
        schema_ref = getattr(row, "schema_ref", None)
        if type(key) is not str or not key.strip():
            raise TypeError("measurement cut dataset version requires identity.key")
        digest = _sha(digest, "measurement cut dataset content_sha256")
        if schema_ref is not None and (type(schema_ref) is not str or not schema_ref.strip()):
            raise TypeError("measurement cut dataset schema_ref must be non-empty or None")
        if previous_dataset is not None and key <= previous_dataset:
            raise ValueError("measurement cut dataset versions must be canonically ordered")
        previous_dataset = key
        dataset_rows.append((key, digest, schema_ref))

    evidence_rows: list[tuple[str, str]] = []
    previous_evidence: str | None = None
    for row in evidence_manifests:
        run_id = getattr(row, "run_id", None)
        digest = getattr(row, "digest", None)
        status = getattr(getattr(row, "status", None), "value", None)
        if type(run_id) is not str or not run_id.strip():
            raise TypeError("measurement cut evidence requires run_id")
        digest = _sha(digest, "measurement cut evidence digest")
        if status != "complete":
            raise ValueError("measurement cut evidence must be COMPLETE")
        key = f"{run_id}:{digest}"
        if previous_evidence is not None and key <= previous_evidence:
            raise ValueError("measurement cut evidence manifests must be canonically ordered")
        previous_evidence = key
        evidence_rows.append((run_id, digest))

    return structure_unit(
        "measurement-cut",
        traits=(MEASUREMENT_CUT_TRAIT,),
        parameters={
            "record_digests": record_digests,
            "source_run_digests": source_run_digests,
            "dataset_versions": tuple(dataset_rows),
            "evidence_manifests": tuple(evidence_rows),
        },
    )


def require_measurement_cut(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(MEASUREMENT_CUT_TRAIT):
        raise TypeError("measurement cut must be research.measurement-cut NoetriumUnit")
    return value


def measurement_cut_digest(value: NoetriumUnit) -> str:
    return require_measurement_cut(value).unit_digest


ANALYSIS_DEFINITION_TRAIT = "research.analysis"


def analysis_definition_unit(
    *,
    analysis_id: str,
    projector_id: str,
    projector_version: str,
    implementation_digest: str,
    configuration_digest: str,
    input_cut: NoetriumUnit,
    grouping_dimensions: tuple[str, ...],
    filter_rules_digest: str,
    comparison_rules_digest: str,
    output_schema_id: str,
    predecessor_analysis_digests: tuple[str, ...] = (),
) -> NoetriumUnit:
    for name, value in (
        ("analysis_id", analysis_id),
        ("projector_id", projector_id),
        ("projector_version", projector_version),
        ("output_schema_id", output_schema_id),
    ):
        _text(value, f"analysis {name}")
    for name, value in (
        ("implementation_digest", implementation_digest),
        ("configuration_digest", configuration_digest),
        ("filter_rules_digest", filter_rules_digest),
        ("comparison_rules_digest", comparison_rules_digest),
    ):
        _sha(value, f"analysis {name}")
    input_cut = require_measurement_cut(input_cut)
    if type(grouping_dimensions) is not tuple or any(
        type(row) is not str or not row.strip() for row in grouping_dimensions
    ):
        raise TypeError("analysis grouping_dimensions must contain non-empty strings")
    if len(grouping_dimensions) != len(set(grouping_dimensions)):
        raise ValueError("analysis grouping_dimensions must be unique")
    _digests(
        predecessor_analysis_digests,
        "analysis predecessor digests",
        allow_empty=True,
    )
    return structure_unit(
        analysis_id,
        traits=(ANALYSIS_DEFINITION_TRAIT,),
        parameters={
            "projector_id": projector_id,
            "projector_version": projector_version,
            "implementation_digest": implementation_digest,
            "configuration_digest": configuration_digest,
            "grouping_dimensions": grouping_dimensions,
            "filter_rules_digest": filter_rules_digest,
            "comparison_rules_digest": comparison_rules_digest,
            "output_schema_id": output_schema_id,
            "predecessor_analysis_digests": predecessor_analysis_digests,
        },
        members=(input_cut,),
    )


def require_analysis_definition(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(ANALYSIS_DEFINITION_TRAIT):
        raise TypeError("analysis definition must be research.analysis NoetriumUnit")
    return value


def analysis_definition_digest(value: NoetriumUnit) -> str:
    return require_analysis_definition(value).unit_digest


def analysis_output_schema_id(value: NoetriumUnit) -> str:
    return str(require_analysis_definition(value).parameters["output_schema_id"])



def analysis_input_cut(value: NoetriumUnit) -> NoetriumUnit:
    return require_measurement_cut(require_analysis_definition(value).member("measurement-cut"))


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    analysis_digest: str
    input_cut_digest: str
    output_schema_id: str
    output_content_digest: str
    output_reference: ArtifactReference | None = None
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _sha(self.analysis_digest, "analysis result analysis_digest")
        _sha(self.input_cut_digest, "analysis result input_cut_digest")
        _text(self.output_schema_id, "analysis result output_schema_id")
        _sha(self.output_content_digest, "analysis result output_content_digest")
        if self.output_reference is not None and type(self.output_reference) is not ArtifactReference:
            raise TypeError("analysis result output_reference must be ArtifactReference or None")
        object.__setattr__(self, "result_digest", canonical_digest({
            "analysis_digest": self.analysis_digest,
            "input_cut_digest": self.input_cut_digest,
            "output_schema_id": self.output_schema_id,
            "output_content_digest": self.output_content_digest,
            "output_reference": self.output_reference,
        }))

    def verify_output(self, references: ArtifactReferencePort, artifacts: ArtifactRegistryPort) -> None:
        if self.output_reference is None:
            return
        resolved = references.resolve(self.output_reference.reference_id, self.output_reference.scope)
        if resolved != self.output_reference:
            raise ValueError("analysis result output reference generation drift")
        record = artifacts.get(self.output_reference.artifact_id)
        if record.scope != self.output_reference.scope or record.digest != self.output_content_digest:
            raise ValueError("analysis result output reference does not match immutable content")


__all__ = [
    "ANALYSIS_DEFINITION_TRAIT",
    "MEASUREMENT_CUT_TRAIT",
    "AnalysisResult",
    "DatasetVersionProjection",
    "EvidenceManifestProjection",
    "analysis_definition_unit",
    "analysis_definition_digest",
    "analysis_input_cut",
    "analysis_output_schema_id",
    "measurement_cut_digest",
    "measurement_cut_unit",
    "require_analysis_definition",
    "require_measurement_cut",
]
