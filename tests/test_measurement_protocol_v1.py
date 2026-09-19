from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.study.api import (
    MeasurementContentReference,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _protocol(*, unit: str | None = None, description: str = "") -> MeasurementProtocol:
    return MeasurementProtocol(
        "paper-general.v2",
        (
            MeasurementDefinition(
                "score", "scalar.v1", MeasurementValueKind.SCALAR,
                unit=unit, description=description,
            ),
        ),
    )


def _record(protocol: MeasurementProtocol, value: MeasurementValue) -> MeasurementRecord:
    definition = protocol.definition("score")
    lineage = ArtifactReference("evidence-raw", ScopeIdentity(ScopeKind.RUN, "run"), "artifact-raw", 1)
    return MeasurementRecord(
        project_id="project", study_id="study", run_id="run",
        assignment_digest=SHA_A, variant_id="treatment", producer_id="producer",
        producer_revision_digest=SHA_B, measurement_id="score", schema_id=definition.schema_id,
        measurement_semantic_digest=definition.semantic_contract_digest,
        measurement_protocol_semantic_digest=protocol.semantic_digest,
        value=value, logical_time="step:7",
        intervention=OptionalIdentityFacet(SHA_C), revision=OptionalIdentityFacet(SHA_D),
        lineage_refs=(lineage,),
    )


def test_measurement_semantic_identity_ignores_description_but_binds_unit() -> None:
    base = _protocol(unit="meters", description="display A")
    wording = _protocol(unit="meters", description="display B")
    drift = _protocol(unit="seconds", description="display A")
    assert base.semantic_digest == wording.semantic_digest
    assert base.protocol_digest != wording.protocol_digest
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
    scope = ScopeIdentity(ScopeKind.RUN, "run")
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
    definition = MeasurementDefinition("score", "scalar.v1", MeasurementValueKind.SCALAR)
    with pytest.raises(ValueError, match="unique"):
        MeasurementProtocol("duplicate", (definition, definition))
