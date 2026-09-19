from __future__ import annotations

from pathlib import Path

from noetrium_platform.research.experimentation.checkpoint.api import RunCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryRunCheckpointStore


def build_project_run_checkpoint_store(project_state_root: str | Path) -> RunCheckpointStore:
    """Build the durable acceleration-checkpoint store for one project root."""
    if type(project_state_root) is str and not project_state_root.strip():
        raise ValueError("project_state_root must be non-empty")
    if not isinstance(project_state_root, (str, Path)):
        raise TypeError("project_state_root must be str or Path")
    return DirectoryRunCheckpointStore(Path(project_state_root) / "checkpoints")


__all__ = ["build_project_run_checkpoint_store"]
