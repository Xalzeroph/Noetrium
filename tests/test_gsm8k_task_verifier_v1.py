from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)
from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    MeasurementDefinition,
    MeasurementProtocol,
    TaskArtifactSpec,
    TaskVerifierArtifact,
    TaskVerifierIsolation,
    TaskVerifierRequest,
)
from research.benchmarks.gsm8k.verifier import GSM8KTaskVerifier


def test_gsm8k_task_verifier_uses_only_declared_completion_artifact(tmp_path: Path) -> None:
    content = compose_research_execution_content(tmp_path / "content")
    task_digest = "1" * 64
    reference = content.publish(
        reference_id="completion:test",
        scope=ScopeIdentity(ScopeKind.RUN, "run-test"),
        payload=b'"The answer is 42"',
        media_type="application/json",
    )
    artifact = TaskVerifierArtifact(
        TaskArtifactSpec("completion", "completion.json"),
        reference,
    )
    protocol = MeasurementProtocol(
        "gsm8k-test",
        (
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="scalar-v1",
                unit="ratio",
                semantic_kind="exact_numeric_answer_success",
                scale="binary",
                domain="gsm8k",
            ),
        ),
    )
    request = TaskVerifierRequest(
        source_trial_request_digest="2" * 64,
        project_id="project",
        study_id="study",
        run_id="run-test",
        assignment_digest="3" * 64,
        variant_id="control",
        intervention=OptionalIdentityFacet(),
        revision=OptionalIdentityFacet(),
        task_digest=task_digest,
        task_package_digest="4" * 64,
        verifier_requirement_id="benchmark.gsm8k.exact-numeric.verifier",
        verifier_isolation=TaskVerifierIsolation.SEPARATE,
        verifier_environment_requirement_id=None,
        measurement_protocol=protocol,
        artifacts=(artifact,),
    )

    verifier = GSM8KTaskVerifier(content, ((task_digest, "42"),))
    receipt = verifier.verify(request)

    assert tuple(row.measurement_id for row in receipt.measurements) == ("task_success",)
    assert receipt.measurements[0].value.scalar == 1.0
    assert receipt.measurements[0].lineage_refs == (reference,)
    assert len(receipt.evidence_refs) == 1
    assert content.read(receipt.evidence_refs[0])
