from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api import ProjectRunDefinition
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.identity import (
    OptionalIdentityFacet,
    ReplayLevel,
)
from noetrium_platform.research.experimentation.run.api import (
    ExperimentRunResult,
    ExperimentRunSpec,
)
from noetrium_platform.research.experimentation.run.composition import (
    ExperimentRunEvidenceFinalizer,
)
from noetrium_platform.research.experimentation.run.api.identity import RunIdentity
from noetrium_platform.research.experimentation.run.api.manifest import (
    CompositionPlanReference,
    RunLaunchManifest,
    RunResearchSemanticsReference,
)
from noetrium_platform.research.experimentation.run.runtime import (
    DirectoryRunArtifactStore,
)
from noetrium_platform.research.experimentation.study.api import (
    StudyAssignment,
    StudyConcurrencyPolicy,
    StudyMatrixExecutionReport,
    StudyMetricAggregate,
    StudyMetricObservation,
    StudyProtocol,
    StudyVariantSpec,
    VariantKind,
)
from tests_support import model_role_for_test


class _Actor:
    def call(self, operation, fn, /, *args, **kwargs):
        del operation
        return fn(*args, **kwargs)


@dataclass(frozen=True)
class _ProjectIdentity:
    project_id: str


@dataclass(frozen=True)
class _ProjectManifest:
    identity: _ProjectIdentity
    semantic_digest: str
    study_ids: tuple[str, ...]


def _definition() -> ProjectRunDefinition:
    seed = "e" * 64
    tasks = "f" * 64
    experiment = ExperimentSpec(
        "experiment-1",
        "study-1",
        "project-1",
        (),
        (model_role_for_test(),),
        "b" * 64,
        seed,
        1,
        "workflow.v1",
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    )
    study = StudyProtocol(
        "study-1",
        "workload-1",
        (
            StudyVariantSpec(
                "treatment",
                VariantKind.TREATMENT,
                "impl",
                "d" * 64,
            ),
        ),
        1,
        seed,
        ("score",),
        tasks,
        ("standard",),
        StudyConcurrencyPolicy.serial_shared_v1(
            repetition_timeout_seconds=60.0
        ),
    )
    run = ExperimentRunSpec(
        "run-1",
        "project-1",
        "experiment-1",
        "study-1",
        "test",
        tasks,
        seed,
        1,
        "runs/run-1",
        "7" * 64,
        experiment.model_roles_digest,
    )
    identity = RunIdentity("run-1", "session-1", "trace-1")
    project_manifest = _ProjectManifest(
        _ProjectIdentity("project-1"),
        "9" * 64,
        ("study-1",),
    )
    manifest = RunLaunchManifest(
        "release",
        "prompt-generation",
        "prompt-promotion",
        "models",
        (),
        "host",
        "participant-impl",
        "participant-runtime",
        "participant-bindings",
        project_manifest.semantic_digest,
        experiment.identity_digest(),
        RunResearchSemanticsReference(
            research_plan_digest="1" * 64,
            study_plan_digest="2" * 64,
            measurement_protocol_digest="3" * 64,
            trial_protocol_digest="4" * 64,
            method_implementation_digest="0" * 64,
            intervention=OptionalIdentityFacet("5" * 64),
            topology=OptionalIdentityFacet(),
            participant_schedule=OptionalIdentityFacet(),
            revision=OptionalIdentityFacet("6" * 64),
            replay_level=ReplayLevel.EXACT,
        ),
        ("python", "-m", "demo"),
        "a" * 64,
        "b" * 64,
        (("project", "config"),),
        "seed-0",
        (
            CompositionPlanReference(
                "plan",
                "owner",
                "scope",
                "c" * 64,
            ),
        ),
    )
    return ProjectRunDefinition(
        project_manifest,
        experiment,
        study,
        run,
        identity,
        manifest,
    )


def _result(definition: ProjectRunDefinition) -> ExperimentRunResult:
    assignment = StudyAssignment(
        "study-1",
        "treatment",
        0,
        "seed-0",
        "task-1",
    )
    report = StudyMatrixExecutionReport(
        protocol_digest=definition.study.protocol_digest,
        observations=(
            StudyMetricObservation(
                assignment,
                (("score", 1.0),),
            ),
        ),
        aggregates=(
            StudyMetricAggregate(
                "study-1",
                "treatment",
                "score",
                1,
                1.0,
                0.0,
                0.0,
            ),
        ),
        binding_digest="8" * 64,
        plan_digest=definition.manifest.research_semantics.study_plan_digest,
    )
    return ExperimentRunResult(
        run_spec_digest=definition.run.identity_digest(),
        protocol_digest=definition.study.protocol_digest,
        plan_digest=definition.manifest.research_semantics.study_plan_digest,
        binding_digest="8" * 64,
        study_report=report,
    )


def _store(tmp_path: Path) -> DirectoryRunArtifactStore:
    return DirectoryRunArtifactStore(
        tmp_path / "run",
        run_id="run-1",
        writer_actor=_Actor(),
    )


def test_completed_run_finalizes_observation_and_aggregate_streams(
    tmp_path: Path,
) -> None:
    definition = _definition()
    store = _store(tmp_path)
    receipt = ExperimentRunEvidenceFinalizer(store).finalize(
        definition=definition,
        result=_result(definition),
    )

    assert receipt.run_id == "run-1"
    assert receipt.run_manifest_digest == definition.run_manifest_digest
    assert receipt.manifest_ref == (
        "evidence/study-results-v1/manifest.json"
    )

    manifest = json.loads(
        (
            tmp_path
            / "run/evidence/study-results-v1/manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert [row["stream_id"] for row in manifest["streams"]] == [
        "study-aggregates",
        "study-observations",
    ]
    assert [
        row["artifact_receipt"]["record_count"]
        for row in manifest["streams"]
    ] == [1, 1]
    assert manifest["streams"][1]["required"] is True
    assert manifest["streams"][1]["source_of_truth"] is True


def test_completed_run_evidence_finalization_is_idempotent(
    tmp_path: Path,
) -> None:
    definition = _definition()
    store = _store(tmp_path)
    finalizer = ExperimentRunEvidenceFinalizer(store)
    result = _result(definition)

    first = finalizer.finalize(definition=definition, result=result)
    second = finalizer.finalize(definition=definition, result=result)
    assert second == first


def test_completed_run_evidence_rejects_manifest_plan_drift(
    tmp_path: Path,
) -> None:
    definition = _definition()
    result = _result(definition)
    drifted = ExperimentRunResult(
        run_spec_digest=result.run_spec_digest,
        protocol_digest=result.protocol_digest,
        plan_digest=canonical_digest("different-plan"),
        binding_digest=result.binding_digest,
        study_report=StudyMatrixExecutionReport(
            result.study_report.protocol_digest,
            result.study_report.observations,
            result.study_report.aggregates,
            result.study_report.binding_digest,
            canonical_digest("different-plan"),
        ),
    )
    with pytest.raises(ValueError, match="RunLaunchManifest"):
        ExperimentRunEvidenceFinalizer(_store(tmp_path)).finalize(
            definition=definition,
            result=drifted,
        )


def test_completed_run_evidence_requires_observations(
    tmp_path: Path,
) -> None:
    definition = _definition()
    result = _result(definition)
    empty = ExperimentRunResult(
        run_spec_digest=result.run_spec_digest,
        protocol_digest=result.protocol_digest,
        plan_digest=result.plan_digest,
        binding_digest=result.binding_digest,
        study_report=StudyMatrixExecutionReport(
            result.study_report.protocol_digest,
            (),
            (),
            result.study_report.binding_digest,
            result.study_report.plan_digest,
        ),
    )
    with pytest.raises(ValueError, match="requires study observations"):
        ExperimentRunEvidenceFinalizer(_store(tmp_path)).finalize(
            definition=definition,
            result=empty,
        )
