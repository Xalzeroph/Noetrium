from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonValue, OperationResult

from .contracts import RunCheckpointBundle, RunCheckpointManifest


@dataclass(frozen=True, slots=True)
class RunCheckpointResult:
    manifest: RunCheckpointManifest
    operation_results: tuple[OperationResult[JsonValue], ...]


@dataclass(frozen=True, slots=True)
class RunRestoreResult:
    bundle: RunCheckpointBundle
    operation_results: tuple[OperationResult[JsonValue], ...]


__all__ = ["RunCheckpointResult", "RunRestoreResult"]
