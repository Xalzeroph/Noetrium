"""Data-only execution projection contracts owned by benchmark packages.

Benchmark packages describe where public task inputs live inside their immutable
content documents. The Experiment/Trial runtime remains benchmark-agnostic and
uses one shared projection implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _path(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    if any(not part for part in value.split(".")):
        raise ValueError(f"{field_name} must be a dotted field path")
    return value


@dataclass(frozen=True, slots=True)
class RepositoryBenchmarkTaskProjectionSpec:
    """Public task projection metadata; never executes benchmark code."""

    benchmark_id: str
    task_schema_id: str
    objective_path: str
    context_path: str | None = None
    payload_fields: tuple[tuple[str, str], ...] = ()
    projection_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _path(self.benchmark_id, "benchmark projection benchmark_id")
        _path(self.task_schema_id, "benchmark projection task_schema_id")
        _path(self.objective_path, "benchmark projection objective_path")
        if self.context_path is not None:
            _path(self.context_path, "benchmark projection context_path")
        if type(self.payload_fields) is not tuple:
            raise TypeError("benchmark projection payload_fields must be tuple")
        outputs: list[str] = []
        for row in self.payload_fields:
            if type(row) is not tuple or len(row) != 2:
                raise TypeError(
                    "benchmark projection payload field must be (output, path)"
                )
            output, source = row
            _path(output, "benchmark projection payload output")
            _path(source, "benchmark projection payload source")
            outputs.append(output)
        if len(outputs) != len(set(outputs)):
            raise ValueError("benchmark projection payload outputs must be unique")
        object.__setattr__(
            self,
            "projection_digest",
            canonical_digest(
                {
                    "schema": "noetrium.repository-benchmark-task-projection.v1",
                    "benchmark_id": self.benchmark_id,
                    "task_schema_id": self.task_schema_id,
                    "objective_path": self.objective_path,
                    "context_path": self.context_path,
                    "payload_fields": self.payload_fields,
                }
            ),
        )


__all__ = ["RepositoryBenchmarkTaskProjectionSpec"]
