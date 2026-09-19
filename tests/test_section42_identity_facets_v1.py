from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from noetrium_platform.evidence.artifact.content.api import ArtifactStorageBinding
from noetrium_platform.evidence.artifact.content.providers import FilesystemArtifactStoragePlacementVerifier
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity, DatasetVersion
from noetrium_platform.research.experimentation.run.api import RunArtifactKind, RunArtifactSnapshotReceipt
from noetrium_platform.research.experimentation.run.manifest.api import EvidenceBundleManifest, EvidenceBundleStatus, EvidenceStreamDescriptor
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind

from noetrium_platform.research.experimentation.run.api import ExperimentRunSpec
from noetrium_platform.research.experimentation.study.api import (
    AnalysisDefinition,
    AnalysisResult,
    BenchmarkTaskSet,
    MeasurementCut,
    TaskDefinition,
    TaskGraph,
    TaskGraphEdge,
    TaskGraphRelation,
    TaskSetSplit,
    TrialBudget,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64

def _run(artifact_root: str) -> ExperimentRunSpec:
    return ExperimentRunSpec(
        run_id="run-1",
        project_id="project-1",
        experiment_id="experiment-1",
        study_id="study-1",
        execution_profile="standard",
        task_manifest_digest="1" * 64,
        seed_schedule_digest="2" * 64,
        repetitions=2,
        artifact_root=artifact_root,
        environment_identity_digest="3" * 64,
        model_roles_digest="4" * 64,
    )


def test_storage_relocation_changes_placement_not_scientific_run_identity() -> None:
    windows = _run(r"E:\runs\project-1\run-1")
    server = _run("/data/hdd1/runs/project-1/run-1")
    assert windows.scientific_identity_digest() == server.scientific_identity_digest()
    assert windows.execution_placement_digest() != server.execution_placement_digest()
    assert windows.identity_digest() != server.identity_digest()

def _benchmark() -> BenchmarkTaskSet:
    tasks = (
        TaskDefinition("task-a", "rev-1", "family-a", "task.v1", SHA_A),
        TaskDefinition("task-b", "rev-1", "family-b", "task.v1", SHA_B),
    )
    graph = TaskGraph((TaskGraphEdge("task-a", "task-b", TaskGraphRelation.PREREQUISITE),))
    return BenchmarkTaskSet(
        benchmark_id="benchmark-1",
        revision_id="rev-1",
        source_digest=SHA_C,
        task_schema_id="task.v1",
        tasks=tasks,
        task_graph=graph,
        splits=(TaskSetSplit("held-out", ("task-b",)),),
        selection_policy_digest=SHA_D,
    )


def test_task_content_graph_and_budget_have_independent_identities() -> None:
    base = _benchmark()
    changed_task = replace(base, tasks=(
        replace(base.tasks[0], content_digest=SHA_D),
        base.tasks[1],
    ))
    assert base.cut_digest != changed_task.cut_digest
    graph_only = replace(base, task_graph=TaskGraph())
    assert base.cut_digest != graph_only.cut_digest

    budget = TrialBudget("budget-v1", max_steps=10, max_seconds=60.0)
    changed_budget = replace(budget, max_steps=20)
    assert budget.budget_digest != changed_budget.budget_digest
    assert base.cut_digest == _benchmark().cut_digest

def test_benchmark_rejects_unknown_graph_membership_and_nondeterministic_order() -> None:
    task = TaskDefinition("task-a", "rev-1", "family", "task.v1", SHA_A)
    with pytest.raises(ValueError, match="unknown task"):
        BenchmarkTaskSet(
            "benchmark", "rev", SHA_B, "task.v1", (task,),
            task_graph=TaskGraph((TaskGraphEdge("task-a", "task-missing", TaskGraphRelation.PREREQUISITE),)),
        )
    task_b = TaskDefinition("task-b", "rev-1", "family", "task.v1", SHA_B)
    with pytest.raises(ValueError, match="canonically ordered"):
        BenchmarkTaskSet("benchmark", "rev", SHA_C, "task.v1", (task_b, task))


def _analysis(cut: MeasurementCut, implementation: str = SHA_A) -> AnalysisDefinition:
    return AnalysisDefinition(
        analysis_id="analysis-1",
        projector_id="mean-by-variant",
        projector_version="1",
        implementation_digest=implementation,
        configuration_digest=SHA_B,
        input_cut=cut,
        grouping_dimensions=("variant_id",),
        filter_rules_digest=SHA_C,
        comparison_rules_digest=SHA_D,
        output_schema_id="analysis.table.v1",
    )

def test_analysis_identity_changes_without_mutating_raw_measurement_cut() -> None:
    cut = MeasurementCut((SHA_A, SHA_B), (SHA_C, SHA_D))
    base = _analysis(cut)
    changed_algorithm = _analysis(cut, implementation="e" * 64)
    assert base.input_cut == changed_algorithm.input_cut
    assert base.input_cut.cut_digest == changed_algorithm.input_cut.cut_digest
    assert base.analysis_digest != changed_algorithm.analysis_digest
    result = AnalysisResult(base.analysis_digest, cut.cut_digest, "analysis.table.v1", "f" * 64)
    assert len(result.result_digest) == 64
    assert result.analysis_digest == base.analysis_digest


def test_measurement_cut_requires_exact_canonical_membership() -> None:
    with pytest.raises(ValueError, match="canonically ordered"):
        MeasurementCut((SHA_B, SHA_A), (SHA_C, SHA_D))
    with pytest.raises(ValueError, match="unique"):
        MeasurementCut((SHA_A, SHA_A), (SHA_C, SHA_D))


def test_measurement_cut_consumes_portable_dataset_and_real_storage_verification(tmp_path) -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "project-1")
    identity = DatasetIdentity("results", "v1")
    dataset = DatasetVersion(identity, scope, SHA_A, "result.v1")
    receipt = RunArtifactSnapshotReceipt("run-1", "streams/actions.jsonl", RunArtifactKind.EVIDENCE, SHA_B, SHA_C, 12, 1)
    stream = EvidenceStreamDescriptor("actions", "actions", "1", receipt, True, True)
    evidence = EvidenceBundleManifest("2", "bundle-1", "run-1", SHA_D, EvidenceBundleStatus.COMPLETE, None, (stream,))
    cut = MeasurementCut(dataset_versions=(dataset,), evidence_manifests=(evidence,))
    metadata_only = replace(dataset, tags=("relocated",))
    assert cut.cut_digest == MeasurementCut(dataset_versions=(metadata_only,), evidence_manifests=(evidence,)).cut_digest

    payload = b"section42-artifact-content"
    path = tmp_path / "artifact.bin"
    path.write_bytes(payload)
    content_sha = hashlib.sha256(payload).hexdigest()
    binding = ArtifactStorageBinding("artifact-1", content_sha, "artifact.filesystem", str(path), 1)
    proof = FilesystemArtifactStoragePlacementVerifier().verify(artifact_id=binding.artifact_id, content_sha256=binding.content_sha256, storage_provider_id=binding.storage_provider_id, location=binding.location)
    assert proof.content_sha256 == binding.content_sha256
    relocated = replace(binding, location=str(tmp_path / "other" / "artifact.bin"), generation=2)
    assert relocated.content_sha256 == binding.content_sha256
    assert cut.cut_digest == MeasurementCut(dataset_versions=(dataset,), evidence_manifests=(evidence,)).cut_digest

    failed = replace(evidence, status=EvidenceBundleStatus.FAILED)
    with pytest.raises(ValueError, match="COMPLETE"):
        MeasurementCut(evidence_manifests=(failed,))
