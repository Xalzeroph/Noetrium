from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.evidence.observability.logging.storage.runtime.jsonl import JsonlLogStore


def build_jsonl_log_store(
    path: Path | str,
    *,
    task_group: TaskGroupPort,
    max_bytes: int = 64 * 1024 * 1024,
    max_segments: int = 8,
    queue_capacity: int | None = None,
) -> JsonlLogStore:
    resolved = JsonlLogStore.logical_path(path)
    identity = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    actor = task_group.open_serial_actor(
        f"jsonl-log:{identity}",
        lane_id=f"jsonl-log-writer:{identity}",
        capacity=queue_capacity,
    )
    return JsonlLogStore(
        resolved,
        writer_actor=actor,
        max_bytes=max_bytes,
        max_segments=max_segments,
    )


__all__ = ["build_jsonl_log_store"]
