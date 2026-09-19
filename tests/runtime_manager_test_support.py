from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.launch_control.history import RuntimeHistory
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_history_storage import FileRuntimeHistoryStorage
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_state_storage import FileRuntimeControlStateStore
from noetrium_platform.infrastructure.lifecycle.launch_control.state import RuntimeControlStore


def runtime_history_path(state_path: Path) -> Path:
    return state_path.with_name(state_path.name + ".history.jsonl")


def make_runtime_control_store(path: Path) -> RuntimeControlStore:
    return RuntimeControlStore(
        FileRuntimeControlStateStore(path),
        RuntimeHistory(FileRuntimeHistoryStorage(runtime_history_path(path))),
    )


__all__ = ["make_runtime_control_store", "runtime_history_path"]
