from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandRunnerPort,
    LocalCommandStartError,
    LocalCommandTimeoutError,
)
from noetrium_platform.infrastructure.resources.compute.api.probe import (
    CommandProbeError,
    CommandProbeResult,
)


class LocalCommandResourceProbe:
    def __init__(self, runner: LocalCommandRunnerPort) -> None:
        self._runner = runner

    def run(self, argv: tuple[str, ...], *, timeout_seconds: float | None = None) -> CommandProbeResult:
        try:
            result = self._runner.run(argv, timeout_seconds=timeout_seconds)
        except (LocalCommandStartError, LocalCommandTimeoutError, OSError) as exc:
            raise CommandProbeError(str(exc)) from exc
        return CommandProbeResult(
            argv=result.argv,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


__all__ = ["LocalCommandResourceProbe"]
