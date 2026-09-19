from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.research.experimentation.checkpoint.api import WorkloadExecutionCut
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryWorkloadCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.runtime import (
    WorkloadCheckpointCoordinator,
    WorkloadCheckpointIdentityMismatch,
)
from noetrium_platform.research.experimentation.identity import OptionalIdentityFacet, ReplayLevel
from noetrium_platform.research.experimentation.run.manifest.api import RunResearchSemanticsReference
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@dataclass
class _ProjectLocalComponent:
    value: bytes
    component_id: str = "project.local.adaptive-policy"
    codec_id: str = "project.local.bytes"
    schema_version: str = "1"

    def capture(self) -> bytes:
        return self.value

    def restore(self, payload: bytes) -> None:
        self.value = payload


def _semantics(
    plan_tag: str,
    *,
    measurement_tag: str = "c",
    revision_tag: str = "1",
    implementation_tag: str = "7",
    replay: ReplayLevel = ReplayLevel.CHECKPOINT,
) -> RunResearchSemanticsReference:
    return RunResearchSemanticsReference(
        research_plan_digest=plan_tag * 64,
        study_plan_digest="b" * 64,
        measurement_protocol_digest=measurement_tag * 64,
        trial_protocol_digest="d" * 64,
        method_implementation_digest=implementation_tag * 64,
        intervention=OptionalIdentityFacet("e" * 64),
        topology=OptionalIdentityFacet("f" * 64),
        participant_schedule=OptionalIdentityFacet("2" * 64),
        revision=OptionalIdentityFacet(revision_tag * 64),
        replay_level=replay,
    )


class _Binding:
    run_id = "run-1"
    study_id = "study-1"
    workload_id = "workload-1"
    branch_id = "branch-1"
    source_cut_id = "cut-1"
    environment_generation = "env-1"
    method_generation = "method-1"
    task_manifest_digest = "tasks-1"

    def __init__(self, semantics: RunResearchSemanticsReference, value: bytes) -> None:
        self.checkpoint_compatibility_digest = semantics.checkpoint_compatibility_digest
        self.component = _ProjectLocalComponent(value)

    def checkpoint_components(self):
        return (self.component,)


def _context() -> ExecutionContext:
    return ExecutionContext(
        "run-1", "trace-1", "span-1", study_id="study-1", branch_id="branch-1"
    )


def _capture(coordinator, binding):
    return coordinator.capture(
        binding=binding,
        context=_context(),
        execution_cut=WorkloadExecutionCut(("task-1",)),
    )


def test_project_local_component_round_trips_under_checkpoint_compatibility(tmp_path) -> None:
    semantics = _semantics("a")
    binding = _Binding(semantics, b"before")
    coordinator = WorkloadCheckpointCoordinator(
        DirectoryWorkloadCheckpointStore(tmp_path / "checkpoints")
    )
    manifest = _capture(coordinator, binding)
    assert manifest.schema_version == "3"
    assert manifest.checkpoint_compatibility_digest == semantics.checkpoint_compatibility_digest
    binding.component.value = b"mutated"
    coordinator.restore(manifest.checkpoint_id, binding=binding, context=_context())
    assert binding.component.value == b"before"


def test_measurement_or_analysis_only_drift_does_not_false_reject_restore(tmp_path) -> None:
    captured_semantics = _semantics("a", measurement_tag="c")
    reopened_semantics = _semantics("9", measurement_tag="8")
    assert captured_semantics.digest() != reopened_semantics.digest()
    assert (
        captured_semantics.checkpoint_compatibility_digest
        == reopened_semantics.checkpoint_compatibility_digest
    )
    coordinator = WorkloadCheckpointCoordinator(
        DirectoryWorkloadCheckpointStore(tmp_path / "checkpoints")
    )
    manifest = _capture(coordinator, _Binding(captured_semantics, b"captured"))
    reopened = _Binding(reopened_semantics, b"sentinel")
    coordinator.restore(manifest.checkpoint_id, binding=reopened, context=_context())
    assert reopened.component.value == b"captured"


@pytest.mark.parametrize(
    "drifted",
    (
        _semantics("a", revision_tag="9"),
        _semantics("a", implementation_tag="8"),
        _semantics("a", replay=ReplayLevel.OBSERVATIONAL),
    ),
)
def test_restore_rejects_state_relevant_revision_implementation_or_replay_drift_before_mutation(
    tmp_path, drifted
) -> None:
    captured = _Binding(_semantics("a"), b"captured")
    coordinator = WorkloadCheckpointCoordinator(
        DirectoryWorkloadCheckpointStore(tmp_path / "checkpoints")
    )
    manifest = _capture(coordinator, captured)
    reopened = _Binding(drifted, b"sentinel")
    with pytest.raises(WorkloadCheckpointIdentityMismatch, match="identity mismatch"):
        coordinator.restore(manifest.checkpoint_id, binding=reopened, context=_context())
    assert reopened.component.value == b"sentinel"
