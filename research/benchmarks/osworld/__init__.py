"""Pinned OSWorld benchmark adapter for GUI-agent reproductions."""

from .cut import (
    OSWORLD_BENCHMARK_ID,
    OSWORLD_REPOSITORY,
    OSWORLD_TASK_SCHEMA_ID,
    OSWorldTaskRecord,
    build_osworld_source,
    build_osworld_task_set,
    osworld_revision,
)

__all__ = [
    "OSWORLD_BENCHMARK_ID",
    "OSWORLD_REPOSITORY",
    "OSWORLD_TASK_SCHEMA_ID",
    "OSWorldTaskRecord",
    "build_osworld_source",
    "build_osworld_task_set",
    "osworld_revision",
]
