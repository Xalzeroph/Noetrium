from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Mapping

from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandResult,
    LocalCommandRunnerPort,
    LocalCommandStartError,
    LocalCommandTimeoutError,
)

from ..api import ProcessCommandRunnerPort


class AsyncLocalCommandRunner(LocalCommandRunnerPort):
    """Local-command port over the unified async process supervision authority."""

    def __init__(
        self,
        process_runner: ProcessCommandRunnerPort,
        *,
        default_timeout_seconds: float = 3600.0,
    ) -> None:
        if not math.isfinite(float(default_timeout_seconds)) or default_timeout_seconds <= 0:
            raise ValueError("local command default timeout must be finite and positive")
        self._process_runner = process_runner
        self._default_timeout_seconds = float(default_timeout_seconds)

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> LocalCommandResult:
        if not argv:
            raise ValueError("local command argv must be non-empty")
        effective_timeout = (
            self._default_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        if not math.isfinite(effective_timeout) or effective_timeout <= 0:
            raise ValueError("local command timeout must be finite and positive")
        process_environment = None
        if environment is not None:
            process_environment = os.environ.copy()
            process_environment.update({str(key): str(value) for key, value in environment.items()})
        completed = self._process_runner.execute(
            argv,
            cwd=str(cwd) if cwd is not None else None,
            environment=process_environment,
            timeout_seconds=effective_timeout,
        ).result()
        if completed.timed_out:
            raise LocalCommandTimeoutError(
                "local-command",
                f"execution exceeded {effective_timeout:g}s",
            )
        if completed.spawn_error is not None:
            raise LocalCommandStartError(
                "local-command",
                "could not start process",
            )
        return LocalCommandResult(
            argv=argv,
            returncode=completed.return_code,
            stdout=completed.stdout.decode("utf-8", errors="replace"),
            stderr=completed.stderr.decode("utf-8", errors="replace"),
        )


__all__ = ["AsyncLocalCommandRunner"]
