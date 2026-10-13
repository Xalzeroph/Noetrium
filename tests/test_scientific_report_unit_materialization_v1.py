"""Current Unit-typed scientific evidence must materialize without lossy coercion."""
from noetrium_platform.composition.research_scientific_analysis import (
    _artifact_reference,
    _assignment_row,
    _observation_row,
)
from noetrium_platform.foundation.governance.api import ScopeKind, scope_unit
from noetrium_platform.foundation.kernel.unit_codec import unit_document
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    assignment_workload,
    study_assignment,
    study_assignment_digest,
)


def test_assignment_document_preserves_exact_scientific_identity():
    assignment = study_assignment(
        study_id="study-A",
        variant_id="variant-B",
        variant_index=0,
        repetition=2,
        seed="seed-42",
        workload=assignment_workload(("task-a", "task-b")),
    )
    row = _assignment_row(unit_document(assignment))
    assert row["assignment_digest"] == study_assignment_digest(assignment)
    assert row["study_id"] == "study-A"
    assert row["variant_id"] == "variant-B"
    assert row["repetition"] == 2
    assert row["seed"] == "seed-42"
    assert set(row["workload_task_ids"].split("|")) == {"task-a", "task-b"}
    observation = _observation_row({"metrics": (("success", True),)}, row)
    assert observation["success"] is True
    assert observation["assignment_digest"] == row["assignment_digest"]


def test_trial_and_report_scope_encoding_resolve_to_same_canonical_scope():
    owner = scope_unit(ScopeKind.RUN, "run-42")
    common = {"reference_id": "receipt", "artifact_id": "art", "generation": 1}
    trial = _artifact_reference(
        {**common, "scope": unit_document(owner)}, "trial reference"
    )
    report = _artifact_reference(
        {**common, "scope": {"kind": "run", "scope_id": "run-42"}},
        "report reference",
    )
    assert trial == report
    assert trial.scope == owner


def test_scientific_measurement_cannot_invent_or_rebind_assignment():
    import pytest
    from noetrium_platform.composition.research_scientific_analysis import (
        _measurement_row,
    )

    record = {
        "value": {"kind": "scalar", "scalar": 1.0},
        "assignment_digest": "a" * 64,
        "study_id": "study-A",
        "variant_id": "variant-B",
    }
    with pytest.raises(ValueError, match="absent"):
        _measurement_row(record, {})
    with pytest.raises(ValueError, match="drifted"):
        _measurement_row(
            record, {"a" * 64: {"study_id": "study-WRONG", "variant_id": "variant-B"}}
        )


def test_metric_cannot_overwrite_provenance_identity():
    import pytest
    with pytest.raises(ValueError, match="collides"):
        _observation_row(
            {"metrics": (("study_id", "forged"),)},
            {"study_id": "study-A", "assignment_digest": "a" * 64},
        )


def test_scientific_artifact_declared_sha256_is_enforced():
    from hashlib import sha256
    import pytest
    from noetrium_platform.composition.research_scientific_analysis import (
        _read_json_artifact,
    )

    class Reader:
        def read(self, _reference):
            return b'{"result":true}'

    ref = {
        "reference_id": "r", "artifact_id": "a", "generation": 1,
        "scope": {"kind": "run", "scope_id": "one"},
        "content_sha256": sha256(b'{"result":true}').hexdigest(),
    }
    assert _read_json_artifact(Reader(), ref, "research artifact")["result"] is True
    with pytest.raises(ValueError, match="content digest drifted"):
        _read_json_artifact(Reader(), {**ref, "content_sha256": "0" * 64}, "research artifact")
