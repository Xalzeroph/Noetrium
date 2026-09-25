from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from noetrium_platform.research.experimentation.api.construction import (
    ProjectRunDefinition,
)
from noetrium_platform.research.experimentation.lifecycle.run.api import (
    ExperimentRunResult,
    RunArtifactKind,
    RunArtifactSealedError,
    RunArtifactSnapshotReceipt,
    RunArtifactStorePort,
)
from noetrium_platform.research.experimentation.lifecycle.run.api.manifest_evidence import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EvidenceBundleManifest,
    EvidenceBundleReceipt,
    EvidenceBundleStatus,
    EvidenceStreamDescriptor,
)
from noetrium_platform.research.experimentation.lifecycle.run.runtime.manifest_evidence import (
    RunArtifactEvidenceBundlePublisher,
)


class ExperimentRunEvidenceFinalizer:
    """Seal one completed experiment result into authoritative run evidence.

    Execution, scientific matching, and lifecycle promotion remain outside this
    class.  It only converts an already completed typed run result into durable
    record streams and an EvidenceBundle bound to the exact RunLaunchManifest.
    """

    def __init__(self, artifacts: RunArtifactStorePort) -> None:
        if not isinstance(artifacts, RunArtifactStorePort):
            raise TypeError(
                "experiment run evidence finalizer requires RunArtifactStorePort"
            )
        self._artifacts = artifacts
        self._publisher = RunArtifactEvidenceBundlePublisher(artifacts)

    @staticmethod
    def _jsonl(rows: tuple[object, ...]) -> str:
        return b"".join(
            canonical_bytes(row) + b"\n"
            for row in rows
        ).decode("utf-8")

    def _seal_stream(
        self,
        artifact_ref: str,
        rows: tuple[object, ...],
    ) -> RunArtifactSnapshotReceipt:
        body = self._jsonl(rows)
        try:
            self._artifacts.publish_text(
                artifact_ref,
                body,
                kind=RunArtifactKind.EVIDENCE,
            )
        except RunArtifactSealedError:
            # Retry is safe only because finalize() verifies the durable seal
            # against the current bytes before returning the prior receipt.
            pass
        receipt = self._artifacts.finalize(
            artifact_ref,
            kind=RunArtifactKind.EVIDENCE,
            record_stream=True,
        )
        return self._artifacts.verify_finalized(receipt)

    @staticmethod
    def _validate_run(
        definition: ProjectRunDefinition,
        result: ExperimentRunResult,
    ) -> None:
        if type(definition) is not ProjectRunDefinition:
            raise TypeError(
                "experiment run evidence requires ProjectRunDefinition"
            )
        if type(result) is not ExperimentRunResult:
            raise TypeError(
                "experiment run evidence requires ExperimentRunResult"
            )
        if result.run_spec_digest != definition.run.identity_digest():
            raise ValueError(
                "experiment result belongs to another ExperimentRunSpec"
            )
        if result.protocol_digest != definition.study.protocol_digest:
            raise ValueError(
                "experiment result belongs to another StudyProtocol"
            )
        semantics = definition.manifest.research_semantics
        if result.plan_digest != semantics.study_plan_digest:
            raise ValueError(
                "experiment result plan does not match RunLaunchManifest"
            )

    def finalize(
        self,
        *,
        definition: ProjectRunDefinition,
        result: ExperimentRunResult,
        bundle_id: str = "study-results-v1",
        source_checkpoint_id: str | None = None,
    ) -> EvidenceBundleReceipt:
        self._validate_run(definition, result)
        observations = result.study_report.observations
        if not observations:
            raise ValueError(
                "complete experiment evidence requires study observations"
            )
        aggregates = result.study_report.aggregates

        prefix = f"evidence/{bundle_id}"
        aggregate_receipt = self._seal_stream(
            f"{prefix}/study-aggregates.jsonl",
            aggregates,
        )
        observation_receipt = self._seal_stream(
            f"{prefix}/study-observations.jsonl",
            observations,
        )
        streams = (
            EvidenceStreamDescriptor(
                stream_id="study-aggregates",
                family="study.aggregate",
                schema_version="1",
                artifact_receipt=aggregate_receipt,
                required=False,
                source_of_truth=False,
            ),
            EvidenceStreamDescriptor(
                stream_id="study-observations",
                family="study.observation",
                schema_version="1",
                artifact_receipt=observation_receipt,
                required=True,
                source_of_truth=True,
            ),
        )
        manifest = EvidenceBundleManifest(
            schema_version=EVIDENCE_BUNDLE_SCHEMA_VERSION,
            bundle_id=bundle_id,
            run_id=definition.identity.run_id,
            run_manifest_digest=definition.run_manifest_digest,
            status=EvidenceBundleStatus.COMPLETE,
            source_checkpoint_id=source_checkpoint_id,
            streams=streams,
        )
        return self._publisher.publish(manifest)


def build_experiment_run_evidence_finalizer(
    artifacts: RunArtifactStorePort,
) -> ExperimentRunEvidenceFinalizer:
    return ExperimentRunEvidenceFinalizer(artifacts)


__all__ = [
    "ExperimentRunEvidenceFinalizer",
    "build_experiment_run_evidence_finalizer",
]
