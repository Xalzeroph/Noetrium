from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


class TmuxCommandTimeout(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TmuxCommandResult:
    returncode: int
    stdout: str
    stderr: str


class TmuxCommandRunner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        effect: str = "unknown",
    ) -> TmuxCommandResult: ...


__all__ = ["TmuxCommandResult", "TmuxCommandRunner", "TmuxCommandTimeout"]
