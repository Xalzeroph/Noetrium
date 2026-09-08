from __future__ import annotations

from pathlib import Path

from noetrium_platform.research.experimentation.checkpoint.api import (
    RunCheckpointStore,
    WorkloadCheckpointCoordinatorPort,
    WorkloadCheckpointPublicationPort,
    WorkloadCheckpointedBatchExecutorPort,
)
from noetrium_platform.research.experimentation.checkpoint.runtime.workload_batch import (
    CheckpointedWorkloadBatchExecutor,
)
from noetrium_platform.research.experimentation.workload.runtime import GenericWorkloadBatchExecutor
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryRunCheckpointStore


def build_project_run_checkpoint_store(project_state_root: str | Path) -> RunCheckpointStore:
    """Build the owner-defined durable checkpoint store for one project state root."""

    if type(project_state_root) is str and not project_state_root.strip():
        raise ValueError("project_state_root must be non-empty")
    if not isinstance(project_state_root, (str, Path)):
        raise TypeError("project_state_root must be str or Path")
    return DirectoryRunCheckpointStore(Path(project_state_root) / "checkpoints")


def build_checkpointed_workload_batch_executor(
    coordinator: WorkloadCheckpointCoordinatorPort,
    *,
    publication: WorkloadCheckpointPublicationPort | None = None,
) -> WorkloadCheckpointedBatchExecutorPort:
    """Compose checkpoint semantics with the generic workload executor implementation."""

    return CheckpointedWorkloadBatchExecutor(
        coordinator,
        GenericWorkloadBatchExecutor(),
        publication=publication,
    )


__all__ = [
    "build_checkpointed_workload_batch_executor",
    "build_project_run_checkpoint_store",
]
