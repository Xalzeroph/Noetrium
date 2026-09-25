from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class LocalCommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class LocalCommandExecutionError(RuntimeError):
    """Stable process-boundary failure without exposing command arguments."""

    def __init__(self, operation: str, detail: str) -> None:
        self.operation = operation
        self.detail = detail
        super().__init__(f"{operation}: {detail}")


class LocalCommandTimeoutError(LocalCommandExecutionError):
    pass


class LocalCommandStartError(LocalCommandExecutionError):
    pass


class LocalCommandRunnerPort(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> LocalCommandResult: ...


__all__ = [
    "LocalCommandExecutionError",
    "LocalCommandResult",
    "LocalCommandRunnerPort",
    "LocalCommandStartError",
    "LocalCommandTimeoutError",
]
