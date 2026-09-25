"""Content-authority composition for verifier regrading."""

from __future__ import annotations

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactContentIdentityResolverPort,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.regrade import (
    TaskVerifierArtifactBinding,
    TaskVerifierRegradeDefinition,
    TaskVerifierRegradeNotReady,
    TaskVerifierRegradeProof,
)
from noetrium_platform.research.experimentation.lifecycle.study.api.trial import (
    TrialExecutionReceipt,
)


def build_task_verifier_regrade_proof(
    definition: TaskVerifierRegradeDefinition,
    source_receipt: TrialExecutionReceipt,
    content_identities: ArtifactContentIdentityResolverPort,
) -> TaskVerifierRegradeProof:
    """Prove a target verifier's declared inputs against immutable Artifact truth."""

    if type(definition) is not TaskVerifierRegradeDefinition:
        raise TypeError(
            "verifier regrade proof requires TaskVerifierRegradeDefinition"
        )
    if type(source_receipt) is not TrialExecutionReceipt:
        raise TypeError("verifier regrade proof requires TrialExecutionReceipt")
    if not isinstance(content_identities, ArtifactContentIdentityResolverPort):
        raise TypeError(
            "verifier regrade proof requires ArtifactContentIdentityResolverPort"
        )
    if source_receipt.receipt_digest != definition.source_trial_receipt_digest:
        raise TaskVerifierRegradeNotReady(
            "SOURCE_RECEIPT_DRIFT",
            "source Trial receipt does not match frozen regrade definition",
        )
    artifact_cut = source_receipt.verifier_artifact_cut
    if artifact_cut is None:
        raise TaskVerifierRegradeNotReady(
            "ARTIFACT_CUT_MISSING",
            "source Trial did not preserve an artifact-only verifier input cut",
        )
    if artifact_cut.cut_digest != definition.source_artifact_cut_digest:
        raise TaskVerifierRegradeNotReady(
            "ARTIFACT_CUT_DRIFT",
            "source verifier artifact cut does not match frozen regrade definition",
        )

    by_id = {
        row.declaration.artifact_id: row
        for row in artifact_cut.artifacts
    }
    bindings: list[TaskVerifierArtifactBinding] = []
    for required in definition.required_artifacts:
        source = by_id.get(required.artifact_id)
        if source is None:
            raise TaskVerifierRegradeNotReady(
                "ARTIFACT_MISSING",
                f"required verifier artifact {required.artifact_id!r} is absent "
                "from the source record",
            )
        if source.declaration != required:
            raise TaskVerifierRegradeNotReady(
                "ARTIFACT_DECLARATION_DRIFT",
                f"required verifier artifact {required.artifact_id!r} changed "
                "path/required semantics",
            )
        identity = content_identities.snapshot_reference(
            source.reference.reference_id,
            source.reference.scope,
        )
        if identity.artifact_id != source.reference.artifact_id:
            raise TaskVerifierRegradeNotReady(
                "ARTIFACT_REFERENCE_DRIFT",
                f"artifact reference for {required.artifact_id!r} resolves to "
                "foreign immutable content",
            )
        bindings.append(
            TaskVerifierArtifactBinding(
                required,
                source.reference,
                identity,
            )
        )

    return TaskVerifierRegradeProof(
        definition_digest=definition.definition_digest,
        source_trial_receipt_digest=source_receipt.receipt_digest,
        source_artifact_cut_digest=artifact_cut.cut_digest,
        artifact_bindings=tuple(bindings),
    )


__all__ = ["build_task_verifier_regrade_proof"]
