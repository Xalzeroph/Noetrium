from __future__ import annotations

from typing import Protocol


class DockerCommandResultPort(Protocol):
    returncode: int
    stdout: str
    stderr: str


class DockerCommandRunnerPort(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout_seconds: float,
    ) -> DockerCommandResultPort: ...


__all__ = ["DockerCommandRunnerPort", "DockerCommandResultPort"]
