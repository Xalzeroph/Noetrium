from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandProbeResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandProbeError(RuntimeError):
    pass


class CommandProbePort(Protocol):
    def run(self, argv: tuple[str, ...], *, timeout_seconds: float | None = None) -> CommandProbeResult: ...


__all__ = ["CommandProbeError", "CommandProbePort", "CommandProbeResult"]
