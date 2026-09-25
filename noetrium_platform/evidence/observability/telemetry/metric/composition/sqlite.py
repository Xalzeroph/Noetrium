from __future__ import annotations

import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.evidence.observability.telemetry.metric.providers.sqlite_backend import TelemetrySQLiteBackend


def build_telemetry_sqlite_backend(
    path: Path,
    *,
    task_group: TaskGroupPort,
    queue_capacity: int | None = None,
) -> TelemetrySQLiteBackend:
    """Bind telemetry SQLite mutation to one task-group-owned serial actor."""

    resolved = Path(path)
    identity = hashlib.sha256(str(resolved.resolve()).encode("utf-8")).hexdigest()[:16]
    actor = task_group.open_serial_actor(
        f"telemetry-sqlite:{identity}",
        lane_id=f"telemetry-sqlite-writer:{identity}",
        capacity=queue_capacity,
    )
    return TelemetrySQLiteBackend(resolved, writer_actor=actor)


__all__ = ["build_telemetry_sqlite_backend"]
