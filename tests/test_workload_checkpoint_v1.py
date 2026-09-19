from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.experimentation.checkpoint.api import WorkloadExecutionCut
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryWorkloadCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.runtime import (
    WorkloadCheckpointCoordinator,
    WorkloadCheckpointIdentityMismatch,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@dataclass
class _Component:
    component_id: str
    value: bytes
    codec_id: str = "test.codec"
    schema_version: str = "1"

    def capture(self) -> bytes:
        return self.value

    def restore(self, payload: bytes) -> None:
        self.value = payload


class _Binding:
    run_id = "run-1"
    study_id = "study-1"
    workload_id = "workload-1"
    branch_id = "branch-1"
    source_cut_id = "cut-1"
    environment_generation = "env-1"
    method_generation = "method-1"
    task_manifest_digest = "tasks-1"
    checkpoint_compatibility_digest = "a" * 64

    def __init__(self) -> None:
        self.component = _Component("session", b"before")

    def checkpoint_components(self):
        return (self.component,)


def test_workload_checkpoint_round_trip_and_identity_guard(tmp_path) -> None:
    binding = _Binding()
    context = ExecutionContext(
        "run-1",
        "trace-1",
        "span-1",
        study_id="study-1",
        branch_id="branch-1",
    )
    coordinator = WorkloadCheckpointCoordinator(
        DirectoryWorkloadCheckpointStore(tmp_path / "checkpoints")
    )
    manifest = coordinator.capture(
        binding=binding,
        context=context,
        execution_cut=WorkloadExecutionCut(("task-1",)),
    )
    binding.component.value = b"after"
    restored = coordinator.restore(manifest.checkpoint_id, binding=binding, context=context)

    assert restored.manifest.execution_cut.completed_task_ids == ("task-1",)
    assert binding.component.value == b"before"

    wrong_context = ExecutionContext(
        "other-run",
        "trace-2",
        "span-2",
        study_id="study-1",
        branch_id="branch-1",
    )
    try:
        coordinator.restore(manifest.checkpoint_id, binding=binding, context=wrong_context)
    except WorkloadCheckpointIdentityMismatch:
        pass
    else:
        raise AssertionError("checkpoint restore accepted a different run identity")
