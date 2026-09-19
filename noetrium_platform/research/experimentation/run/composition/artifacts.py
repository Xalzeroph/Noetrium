from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.research.experimentation.run.runtime.artifacts import DirectoryRunArtifactStore


def build_directory_run_artifact_store(
    root: Path | str,
    *,
    run_id: str,
    task_group: TaskGroupPort,
    queue_capacity: int | None = None,
) -> DirectoryRunArtifactStore:
    resolved = Path(root).expanduser().resolve()
    identity = hashlib.sha256(f"{run_id}:{resolved}".encode("utf-8")).hexdigest()[:16]
    actor = task_group.open_serial_actor(
        f"run-artifacts:{identity}",
        lane_id=f"run-artifact-writer:{identity}",
        capacity=queue_capacity,
    )
    return DirectoryRunArtifactStore(resolved, run_id=run_id, writer_actor=actor)


__all__ = ["build_directory_run_artifact_store"]
