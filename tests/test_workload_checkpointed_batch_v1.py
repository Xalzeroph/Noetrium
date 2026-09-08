from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryWorkloadCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.api import CheckpointedWorkloadBatchResult
from noetrium_platform.research.experimentation.checkpoint.runtime import (
    CheckpointedWorkloadBatchExecutor,
    WorkloadCheckpointCoordinator,
)
from noetrium_platform.research.experimentation.workload.runtime import GenericWorkloadBatchExecutor
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTaskSpec,
    ExperimentWorkloadFailure,
    FailureScope,
)
from noetrium_platform.research.experimentation.workload import WorkloadBatchResult, WorkloadTaskResult
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


@dataclass
class _StateComponent:
    component_id: str = "test.session"
    codec_id: str = "test.session.bytes"
    schema_version: str = "1"
    value: bytes = b"initial"

    def capture(self) -> bytes:
        return self.value

    def restore(self, payload: bytes) -> None:
        self.value = payload


class _CheckpointBinding:
    run_id = "run-1"
    study_id = "study-1"
    workload_id = "workload-1"
    branch_id = "branch-1"
    source_cut_id = "cut-1"
    environment_generation = "env-1"
    method_generation = "method-1"
    task_manifest_digest = "tasks-1"
    checkpoint_compatibility_digest = "a" * 64

    def __init__(self, component: _StateComponent) -> None:
        self.component = component

    def checkpoint_components(self):
        return (self.component,)


class _Runner:
    def __init__(self, task_id: str, calls: list[str], *, abort: bool = False) -> None:
        self.task_id = task_id
        self.calls = calls
        self.abort = abort

    def run(self, task: ExperimentTaskSpec, context: ExecutionContext) -> WorkloadTaskResult:
        del context
        self.calls.append(task.task_id)
        if self.abort:
            raise ExperimentWorkloadFailure(
                "execute",
                "TEST_BRANCH_ABORT",
                "simulated interruption after the committed prefix",
                scope=FailureScope.BRANCH,
            )
        return WorkloadTaskResult(
            task_id=task.task_id,
            family=task.family,
            success=True,
            utility=1.0,
            steps=1,
            duration_s=0.01,
            lineage_id=task.lineage_id,
            planner_actions=({"tool": "finish"},),
            diagnostics={"receipt": task.task_id},
        )


class _BatchBinding:
    def __init__(
        self,
        component: _StateComponent,
        calls: list[str],
        *,
        abort_second: bool = False,
    ) -> None:
        self.context = ExecutionContext(
            "run-1",
            "trace-1",
            "span-1",
            study_id="study-1",
            branch_id="branch-1",
        )
        self.tasks = (
            ExperimentTaskSpec("task-1", "family", "first"),
            ExperimentTaskSpec("task-2", "family", "second", depends_on_task_ids=("task-1",)),
        )
        self.component = component
        self.calls = calls
        self.abort_second = abort_second
        self.closed = False
        self.recorded: list[str] = []

    def runner_for(self, task: ExperimentTaskSpec) -> _Runner:
        return _Runner(
            task.task_id,
            self.calls,
            abort=self.abort_second and task.task_id == "task-2",
        )

    def record_result(self, *, task, result, context) -> None:
        del context
        self.recorded.append(task.task_id)
        self.component.value = task.task_id.encode("utf-8")

    def close(self) -> None:
        self.closed = True


class _RecordingCoordinator:
    def __init__(self, inner: WorkloadCheckpointCoordinator) -> None:
        self.inner = inner
        self.captured = []
        self.restored = []

    def capture(self, **kwargs):
        manifest = self.inner.capture(**kwargs)
        self.captured.append(manifest)
        return manifest

    def restore(self, checkpoint_id, **kwargs):
        self.restored.append(checkpoint_id)
        return self.inner.restore(checkpoint_id, **kwargs)


class _CheckpointPublication:
    def __init__(self) -> None:
        self.manifests = []

    def published(self, manifest) -> None:
        self.manifests.append(manifest)


def test_checkpointed_batch_resumes_exact_committed_prefix(tmp_path) -> None:
    recorder = _RecordingCoordinator(
        WorkloadCheckpointCoordinator(DirectoryWorkloadCheckpointStore(tmp_path / "cp"))
    )

    publication = _CheckpointPublication()
    first_state = _StateComponent()
    first_calls: list[str] = []
    first_batch = _BatchBinding(first_state, first_calls, abort_second=True)
    with pytest.raises(ExperimentWorkloadFailure):
        CheckpointedWorkloadBatchExecutor(recorder, GenericWorkloadBatchExecutor(), publication=publication).execute(
            first_batch,
            checkpoint_binding=_CheckpointBinding(first_state),
        )

    assert first_calls == ["task-1", "task-2"]
    assert first_batch.recorded == ["task-1"]
    assert first_batch.closed is True
    assert len(recorder.captured) == 1
    assert publication.manifests == recorder.captured
    checkpoint_id = recorder.captured[0].checkpoint_id
    assert recorder.captured[0].execution_cut.completed_task_ids == ("task-1",)

    resumed_state = _StateComponent(value=b"fresh")
    resumed_calls: list[str] = []
    resumed_batch = _BatchBinding(resumed_state, resumed_calls)
    outcome = CheckpointedWorkloadBatchExecutor(
        recorder,
        GenericWorkloadBatchExecutor(),
        publication=publication,
    ).execute(
        resumed_batch,
        checkpoint_binding=_CheckpointBinding(resumed_state),
        resume_checkpoint_id=checkpoint_id,
    )

    assert resumed_calls == ["task-2"]
    assert resumed_batch.recorded == ["task-2"]
    assert tuple(item.task_id for item in outcome.batch.task_results) == ("task-1", "task-2")
    assert outcome.resumed_from_checkpoint_id == checkpoint_id
    assert outcome.latest_checkpoint_id is not None
    assert publication.manifests == recorder.captured
    assert resumed_batch.closed is True
    # Restore first proves the component snapshot was task-1; task-2 then advances it.
    assert resumed_state.value == b"task-2"


@pytest.mark.parametrize("bad_checkpoint_id", ["", " ", 1, True])
def test_checkpointed_batch_rejects_malformed_resume_id_before_restore(tmp_path, bad_checkpoint_id) -> None:
    state = _StateComponent()
    calls: list[str] = []
    batch = _BatchBinding(state, calls)
    coordinator = _RecordingCoordinator(
        WorkloadCheckpointCoordinator(DirectoryWorkloadCheckpointStore(tmp_path / "cp"))
    )
    with pytest.raises(ValueError, match="resume_checkpoint_id"):
        CheckpointedWorkloadBatchExecutor(coordinator, GenericWorkloadBatchExecutor()).execute(
            batch, checkpoint_binding=_CheckpointBinding(state), resume_checkpoint_id=bad_checkpoint_id
        )
    assert coordinator.restored == []
    assert calls == []


@pytest.mark.parametrize("field", ["latest_checkpoint_id", "resumed_from_checkpoint_id"])
def test_checkpointed_batch_result_rejects_malformed_checkpoint_ids(field) -> None:
    batch = WorkloadBatchResult(())
    values = {"batch": batch, "latest_checkpoint_id": None, "resumed_from_checkpoint_id": None}
    values[field] = " "
    with pytest.raises(ValueError, match=field):
        CheckpointedWorkloadBatchResult(**values)
