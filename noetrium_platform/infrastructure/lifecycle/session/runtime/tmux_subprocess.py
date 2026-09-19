from __future__ import annotations

import math
from typing import Mapping

from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessCommandRunnerPort

from .tmux_contracts import TmuxCommandResult, TmuxCommandTimeout


class SubprocessTmuxCommandRunner:
    """Tmux command adapter over the platform async process-command authority."""

    def __init__(self, process_runner: ProcessCommandRunnerPort, timeout_s: float = 5.0) -> None:
        if not math.isfinite(float(timeout_s)) or timeout_s <= 0:
            raise ValueError("tmux command timeout must be finite and positive")
        self._process_runner = process_runner
        self.timeout_s = float(timeout_s)

    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: Mapping[str, str],
        effect: str = "unknown",
    ) -> TmuxCommandResult:
        del effect
        completed = self._process_runner.execute(
            argv,
            environment=dict(environment),
            timeout_seconds=self.timeout_s,
            output_limit_bytes=1024 * 1024,
        ).result()
        if completed.timed_out:
            raise TmuxCommandTimeout(
                f"tmux command exceeded {self.timeout_s:.3f}s timeout"
            )
        if completed.spawn_error is not None:
            raise OSError(completed.spawn_error)
        return TmuxCommandResult(
            completed.return_code,
            completed.stdout.decode("utf-8", errors="replace"),
            completed.stderr.decode("utf-8", errors="replace"),
        )


__all__ = ["SubprocessTmuxCommandRunner"]
