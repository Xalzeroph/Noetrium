from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.research.experimentation.checkpoint.api import (
    WorkloadCheckpointRestoreError,
    WorkloadExecutionCut,
    WorkloadRestoreStateCertainty,
)
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryWorkloadCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.runtime import WorkloadCheckpointCoordinator
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@dataclass
class _Component:
    component_id: str
    value: bytes
    codec_id: str = "test.codec"
    schema_version: str = "1"
    fail_payload: bytes | None = None

    def capture(self) -> bytes:
        return self.value

    def restore(self, payload: bytes) -> None:
        self.value = payload
        if payload == self.fail_payload:
            raise RuntimeError(f"restore failed: {self.component_id}")


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

    def __init__(self, components: tuple[_Component, ...]) -> None:
        self.components = components

    def checkpoint_components(self):
        return self.components


def _context() -> ExecutionContext:
    return ExecutionContext(
        "run-1",
        "trace-1",
        "span-1",
        study_id="study-1",
        branch_id="branch-1",
    )


class _CaptureFailComponent(_Component):
    fail_capture = False

    def capture(self) -> bytes:
        if self.fail_capture:
            raise RuntimeError(f"capture failed: {self.component_id}")
        return super().capture()


def _coordinator(tmp_path) -> WorkloadCheckpointCoordinator:
    return WorkloadCheckpointCoordinator(
        DirectoryWorkloadCheckpointStore(tmp_path / "checkpoints")
    )


def _checkpoint(coordinator, binding) -> str:
    manifest = coordinator.capture(
        binding=binding,
        context=_context(),
        execution_cut=WorkloadExecutionCut(("task-1",)),
    )
    return manifest.checkpoint_id


def test_restore_rolls_back_every_mutated_component_on_failure(tmp_path) -> None:
    first = _Component("first", b"snapshot-first")
    second = _Component("second", b"snapshot-second")
    binding = _Binding((first, second))
    coordinator = _coordinator(tmp_path)
    checkpoint_id = _checkpoint(coordinator, binding)
    first.value = b"live-first"
    second.value = b"live-second"
    second.fail_payload = b"snapshot-second"

    with pytest.raises(WorkloadCheckpointRestoreError) as caught:
        coordinator.restore(checkpoint_id, binding=binding, context=_context())

    assert caught.value.component_id == "second"
    assert caught.value.state_certainty is WorkloadRestoreStateCertainty.ROLLED_BACK
    assert caught.value.rollback_errors == ()
    assert first.value == b"live-first"
    assert second.value == b"live-second"


def test_preimage_failure_reports_unchanged_before_restore_mutation(tmp_path) -> None:
    first = _Component("first", b"snapshot-first")
    second = _CaptureFailComponent("second", b"snapshot-second")
    binding = _Binding((first, second))
    coordinator = _coordinator(tmp_path)
    checkpoint_id = _checkpoint(coordinator, binding)
    first.value = b"live-first"
    second.value = b"live-second"
    second.fail_capture = True

    with pytest.raises(WorkloadCheckpointRestoreError) as caught:
        coordinator.restore(checkpoint_id, binding=binding, context=_context())

    assert caught.value.component_id == "second"
    assert caught.value.state_certainty is WorkloadRestoreStateCertainty.UNCHANGED
    assert first.value == b"live-first"
    assert second.value == b"live-second"


def test_rollback_failure_reports_unknown_state(tmp_path) -> None:
    first = _Component("first", b"snapshot-first")
    second = _Component("second", b"snapshot-second")
    binding = _Binding((first, second))
    coordinator = _coordinator(tmp_path)
    checkpoint_id = _checkpoint(coordinator, binding)

    first.value = b"live-first"
    second.value = b"live-second"
    first.fail_payload = b"live-first"
    second.fail_payload = b"snapshot-second"

    with pytest.raises(WorkloadCheckpointRestoreError) as caught:
        coordinator.restore(checkpoint_id, binding=binding, context=_context())

    assert caught.value.component_id == "second"
    assert caught.value.state_certainty is WorkloadRestoreStateCertainty.UNKNOWN
    assert tuple(component_id for component_id, _ in caught.value.rollback_errors) == ("first",)
