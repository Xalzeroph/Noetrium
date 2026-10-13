from __future__ import annotations

from noetrium_platform.foundation.scope.api import scope_unit
from dataclasses import replace

import pytest

from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementContentReference,
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
)
from noetrium_platform.foundation.scope.api import NoetriumUnit, ScopeKind
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    measurement_definitions,
    measurement_id,
    measurement_protocol_semantic_digest,
    measurement_schema_id,
    measurement_semantic_digest,
)
from tests_support import measurement_for_test, measurement_protocol_for_test

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _protocol(*, unit: str | None = None, description: str = "") -> NoetriumUnit:
    return measurement_protocol_for_test(
        measurement_for_test(
            "score",
            schema_id="scalar.v1",
            value_kind=MeasurementValueKind.SCALAR.value,
            unit=unit,
            description=description,
        ),
        protocol_id="paper-general.v2",
    )


def _record(protocol: NoetriumUnit, value: MeasurementValue) -> MeasurementRecord:
    definition = next(
        row for row in measurement_definitions(protocol)
        if measurement_id(row) == "score"
    )
    lineage = ArtifactReference("evidence-raw", scope_unit(ScopeKind.RUN, "run"), "artifact-raw", 1)
    return MeasurementRecord(
        project_id="project", study_id="study", run_id="run",
        assignment_digest=SHA_A, variant_id="treatment", producer_id="producer",
        producer_revision_digest=SHA_B, measurement_id="score", schema_id=measurement_schema_id(definition),
        measurement_semantic_digest=measurement_semantic_digest(definition),
        measurement_protocol_semantic_digest=measurement_protocol_semantic_digest(protocol),
        value=value, logical_time="step:7",
        intervention=SHA_C, revision=SHA_D,
        lineage_refs=(lineage,),
    )


def test_measurement_semantic_identity_ignores_description_but_binds_unit() -> None:
    base = _protocol(unit="meters", description="display A")
    wording = _protocol(unit="meters", description="display B")
    drift = _protocol(unit="seconds", description="display A")
    assert base.semantic_digest == wording.semantic_digest
    assert base.unit_digest != wording.unit_digest
    assert base.semantic_digest != drift.semantic_digest
    record = _record(base, MeasurementValue(MeasurementValueKind.SCALAR, scalar=0.75))
    record.validate_against(wording)
    with pytest.raises(ValueError, match="protocol semantics"):
        record.validate_against(drift)


def test_measurement_record_binds_exact_definition_semantics() -> None:
    protocol = _protocol(unit="meters")
    record = _record(protocol, MeasurementValue(MeasurementValueKind.SCALAR, scalar=1.0))
    bad = replace(record, measurement_semantic_digest=SHA_C)
    with pytest.raises(ValueError, match="semantic definition"):
        bad.validate_against(protocol)


def test_paper_general_value_families_are_distinct_and_validated() -> None:
    values = (
        MeasurementValue(MeasurementValueKind.SCALAR, scalar=1),
        MeasurementValue(MeasurementValueKind.BOOLEAN, boolean=True),
        MeasurementValue(MeasurementValueKind.CATEGORICAL, categorical="pass"),
        MeasurementValue(MeasurementValueKind.STRUCTURED, structured={"x": 1}),
        MeasurementValue(MeasurementValueKind.SEQUENCE, sequence=(1, {"step": 2})),
        MeasurementValue(MeasurementValueKind.DISTRIBUTION, distribution=((0.0, 0.25), (1.0, 0.75))),
        MeasurementValue(MeasurementValueKind.MATRIX, matrix=((1.0, 2.0), (3.0, 4.0))),
        MeasurementValue(MeasurementValueKind.TEXT_JUDGEMENT, text_judgement="acceptable"),
    )
    assert tuple(value.kind for value in values) == tuple(MeasurementValueKind)[:-1]
    assert len({value.digest() for value in values}) == len(values)
    with pytest.raises(ValueError, match="finite"):
        MeasurementValue(MeasurementValueKind.SCALAR, scalar=float("nan"))
    with pytest.raises(ValueError, match="rectangular"):
        MeasurementValue(MeasurementValueKind.MATRIX, matrix=((1.0,), (2.0, 3.0)))


def test_structured_measurement_freezes_nested_input() -> None:
    source = {"nested": {"x": 1}}
    value = MeasurementValue(MeasurementValueKind.STRUCTURED, structured=source)
    source["nested"]["x"] = 9
    assert value.structured["nested"]["x"] == 1
    with pytest.raises(TypeError):
        value.structured["new"] = 2


def test_content_reference_requires_typed_generation_and_verified_content() -> None:
    scope = scope_unit(ScopeKind.RUN, "run")
    reference = ArtifactReference("ref-1", scope, "artifact-1", 2)
    content = MeasurementContentReference(reference, SHA_A, "tensor.v1", "application/x-tensor")
    value = MeasurementValue(MeasurementValueKind.CONTENT_REFERENCE, content_reference=content)

    class References:
        def resolve(self, reference_id, requested_scope):
            assert (reference_id, requested_scope) == ("ref-1", scope)
            return reference

    class Artifacts:
        def get(self, artifact_id):
            assert artifact_id == "artifact-1"
            return type("Artifact", (), {"digest": SHA_A})()

    content.verify(References(), Artifacts())
    assert len(value.digest()) == 64
    with pytest.raises(TypeError, match="exactly one|content-reference"):
        MeasurementValue(MeasurementValueKind.CONTENT_REFERENCE, categorical="opaque-path")


def test_protocol_rejects_duplicate_measurement_ids() -> None:
    definition = measurement_for_test(
        "score",
        schema_id="scalar.v1",
        value_kind=MeasurementValueKind.SCALAR.value,
    )
    with pytest.raises(ValueError, match="unique"):
        measurement_protocol_for_test(
            definition,
            definition,
            protocol_id="duplicate",
        )
