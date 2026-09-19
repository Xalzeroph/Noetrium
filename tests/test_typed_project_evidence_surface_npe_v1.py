from __future__ import annotations

import pytest

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.catalog.api import (
    ArtifactKind,
    ArtifactRecord,
    ArtifactRetention,
)
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity, DatasetVersion
from noetrium_platform.evidence.data.fact.api import DurableFact, FactCriticality, FactDecoderPort, FactSchema
from noetrium_platform.evidence.data.fact.runtime import FactDecoderRegistry
from noetrium_platform.evidence.data.record.api import ExecutionRecordPlane
from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.evidence.observability.status.api import HealthState, SubsystemSnapshot
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_bytes, canonical_digest
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


def _run_scope() -> ScopeIdentity:
    return ScopeIdentity(ScopeKind.RUN, "run-npe")


def test_public_artifact_record_carries_content_identity_and_run_lineage() -> None:
    digest = canonical_digest({"evidence": "result-v1"})
    record = ArtifactRecord(
        artifact_id="evidence/result.json",
        kind=ArtifactKind.SCIENTIFIC,
        scope=_run_scope(),
        digest=digest,
        producer_component_id="project.method",
        producer_operation_id="operation-finalize",
        lineage=(ArtifactContentIdentity("artifact:input", "a" * 64),),
        retention=ArtifactRetention.RUN,
        media_type="application/json",
    )

    assert record.scope.kind is ScopeKind.RUN
    assert record.scope.scope_id == "run-npe"
    assert record.digest == digest and len(record.digest) == 64
    assert record.producer_operation_id == "operation-finalize"
    assert record.lineage == (ArtifactContentIdentity("artifact:input", "a" * 64),)


def test_public_dataset_version_carries_portable_content_identity_and_scope() -> None:
    digest = canonical_digest({"dataset": [1, 2, 3]})
    dataset = DatasetVersion(
        identity=DatasetIdentity("project-eval", "v1"),
        scope=_run_scope(),
        content_sha256=digest,
        schema_ref="schema:project-eval.v1",
        parent_versions=(DatasetIdentity("project-source", "v1"),),
    )

    assert dataset.scope == _run_scope()
    assert dataset.content_sha256 == digest
    assert dataset.identity.key == "project-eval@v1"
    assert dataset.parent_versions == (DatasetIdentity("project-source", "v1"),)
    assert not hasattr(dataset, "location")


def test_observability_event_is_explicitly_side_plane_not_authority() -> None:
    event = EventEnvelope(
        event_id="event-npe-1",
        event_type="project.environment.ready",
        context=ExecutionContext("run-npe", "trace-npe", "span-npe"),
        component_id="project.environment",
        payload={"ready": True},
        artifact_refs=("evidence/result.json",),
    )

    assert event.record_plane is ExecutionRecordPlane.SIDE_PLANE_OBSERVATION
    assert event.context.run_id == "run-npe"
    assert event.artifact_refs == ("evidence/result.json",)


def test_project_status_is_read_only_projection_with_evidence_refs() -> None:
    snapshot = SubsystemSnapshot(
        subsystem="environment.reference-counter",
        state=HealthState.READY,
        summary="reference environment ready",
        evidence=("artifact:evidence/result.json",),
        reason_codes=("environment.ready",),
        next_commands=("project inspect evidence",),
    )

    assert snapshot.state is HealthState.READY
    assert snapshot.evidence == ("artifact:evidence/result.json",)
    assert snapshot.reason_codes == ("environment.ready",)


def test_public_artifact_record_rejects_untyped_duplicate_noncanonical_and_self_lineage() -> None:
    base = dict(
        artifact_id="evidence/result.json", kind=ArtifactKind.SCIENTIFIC, scope=_run_scope(),
        digest="a" * 64, producer_component_id="project.method",
    )
    with pytest.raises(TypeError, match="ArtifactContentIdentity"):
        ArtifactRecord(**base, lineage=("artifact:one",))  # type: ignore[arg-type]
    one = ArtifactContentIdentity("artifact:one", "b" * 64)
    two = ArtifactContentIdentity("artifact:two", "c" * 64)
    with pytest.raises(ValueError, match="unique"):
        ArtifactRecord(**base, lineage=(one, one))
    with pytest.raises(ValueError, match="canonically ordered"):
        ArtifactRecord(**base, lineage=(two, one))
    with pytest.raises(ValueError, match="cannot contain the artifact itself"):
        ArtifactRecord(**base, lineage=(ArtifactContentIdentity("evidence/result.json", "d" * 64),))


def test_public_artifact_record_rejects_metadata_corruption() -> None:
    with pytest.raises(ValueError, match="metadata keys"):
        ArtifactRecord(
            artifact_id="evidence/result.json", kind=ArtifactKind.SCIENTIFIC, scope=_run_scope(),
            digest="a" * 64, producer_component_id="project.method", metadata=(("one", "1"), ("two", "2"), ("", "3")),
        )


def test_public_dataset_version_rejects_duplicate_parent_tag_and_metadata_authority() -> None:
    parent = DatasetIdentity("source", "v1")
    with pytest.raises(ValueError, match="parent_versions"):
        DatasetVersion(
            DatasetIdentity("project-eval", "v1"), _run_scope(), "b" * 64,
            parent_versions=(parent, parent),
        )
    with pytest.raises(ValueError, match="tags"):
        DatasetVersion(
            DatasetIdentity("project-eval", "v1"), _run_scope(), "b" * 64,
            tags=("one", "two", ""),
        )
    with pytest.raises(ValueError, match="metadata keys"):
        DatasetVersion(
            DatasetIdentity("project-eval", "v1"), _run_scope(), "b" * 64,
            metadata=(("one", "1"), ("two", "2"), ("", "3")),
        )
    with pytest.raises(ValueError, match="cannot contain the dataset itself"):
        DatasetVersion(
            DatasetIdentity("project-eval", "v1"), _run_scope(), "b" * 64,
            parent_versions=(DatasetIdentity("project-eval", "v1"),),
        )


def test_fact_decoder_is_schema_bound_and_typed() -> None:
    class IntFactDecoder:
        schema = FactSchema[int]("project.score", "v1")

        def decode(self, fact: DurableFact) -> int:
            value = fact.payload.get("value")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("project.score value must be an integer")
            return value

    decoder = IntFactDecoder()
    assert isinstance(decoder, FactDecoderPort)
    registry = FactDecoderRegistry((decoder,))
    fact = DurableFact(
        "score-1", "project.score", "v1", FactCriticality.REQUIRED, {"value": 7}
    )
    schema = FactSchema[int]("project.score", "v1")
    assert registry.decoder_for(schema) is decoder
    assert registry.decode_as(fact, schema) == 7


def test_fact_decoder_rejects_schema_mismatch_before_decode() -> None:
    class IntFactDecoder:
        schema = FactSchema[int]("project.score", "v1")

        def decode(self, fact: DurableFact) -> int:
            raise RuntimeError("decoder must not be invoked for a mismatched schema")

    registry = FactDecoderRegistry((IntFactDecoder(),))
    fact = DurableFact(
        "score-2", "project.score", "v2", FactCriticality.REQUIRED, {"value": 9}
    )
    with pytest.raises(ValueError, match="does not match requested typed schema"):
        registry.decode_as(fact, FactSchema[int]("project.score", "v1"))


def test_role05_canonical_encoding_uses_kernel_exact_bytes() -> None:
    from noetrium_platform.evidence.data._canonical import canonical_bytes as data_canonical_bytes
    payload = {"b": (2, 3), "a": {"nested": True}, "finite": 1.25}
    expected = b'{"a":{"nested":true},"b":[2,3],"finite":1.25}'
    assert canonical_bytes(payload) == expected
    assert data_canonical_bytes(payload) == expected


def test_data_strict_decoder_rejects_duplicate_keys_and_nonfinite_constants() -> None:
    from noetrium_platform.evidence.data._canonical import DataCanonicalDecodingError, strict_json_loads
    from noetrium_platform.foundation.kernel.kernel import CanonicalDecodingFailureKind

    with pytest.raises(DataCanonicalDecodingError) as duplicate:
        strict_json_loads('{"a":1,"a":2}')
    assert duplicate.value.kind is CanonicalDecodingFailureKind.DUPLICATE_KEY

    with pytest.raises(DataCanonicalDecodingError) as non_finite:
        strict_json_loads('{"value":NaN}')
    assert non_finite.value.kind is CanonicalDecodingFailureKind.NON_FINITE
