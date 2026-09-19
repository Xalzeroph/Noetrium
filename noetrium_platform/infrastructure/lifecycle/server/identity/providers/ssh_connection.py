from __future__ import annotations

import math
import time

from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessCommandRunnerPort
from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect

from ..api import ServerCommandResult, ServerConnectionPort, ServerConnectionProfile, ServerTransportFailureKind
from .ssh_policy import OpenSSHArgumentPolicy
from .ssh_result import bounded_output_text, classify_transport_failure


class SSHServerConnection(ServerConnectionPort):
    """OpenSSH command provider; process ownership stays in process supervision."""

    def __init__(
        self,
        profile: ServerConnectionProfile,
        *,
        operating_system: OperatingSystemRoute,
        process_runner: ProcessCommandRunnerPort | None = None,
        runner: object | None = None,
    ) -> None:
        self._profile = profile
        self._operating_system = operating_system
        self._process_runner = process_runner
        self._runner = runner
        self._policy = OpenSSHArgumentPolicy(profile)

    @property
    def profile(self) -> ServerConnectionProfile:
        return self._profile

    def _argv(self, command: str, *, interactive: bool) -> tuple[str, ...]:
        return self._policy.command(command, interactive=interactive)

    def _prepare_control_path(self) -> None:
        self._policy.prepare_control_path()

    def execute(
        self,
        command: str,
        *,
        interactive: bool = False,
        effect: ServerOperationEffect = ServerOperationEffect.UNKNOWN,
        timeout_seconds: float | None = None,
    ) -> ServerCommandResult:
        del effect
        if not command.strip():
            raise ValueError("remote command must be non-empty")
        argv = self._argv(command, interactive=interactive)
        effective_timeout = self._profile.command_timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        if not math.isfinite(effective_timeout) or effective_timeout <= 0:
            raise ValueError("SSH command timeout must be finite and positive")
        if interactive:
            argv = (argv[0], "-tt", *argv[1:])
        runner = self._runner
        if runner is None:
            process_runner = self._process_runner
            if process_runner is None:
                raise RuntimeError("SSH execution requires an injected async process command runner")
            self._prepare_control_path()
            started = time.perf_counter()
            completed = process_runner.execute(
                argv,
                timeout_seconds=effective_timeout,
                inherit_stdin=interactive,
                output_limit_bytes=self._profile.output_limit_bytes,
            ).result()
            stdout, stdout_bytes = bounded_output_text(
                completed.stdout,
                limit=self._profile.output_limit_bytes,
                total_bytes=completed.stdout_bytes,
                truncated=completed.stdout_truncated,
            )
            stderr, stderr_bytes = bounded_output_text(
                completed.stderr,
                limit=self._profile.output_limit_bytes,
                total_bytes=completed.stderr_bytes,
                truncated=completed.stderr_truncated,
            )
            if completed.timed_out:
                stderr = (stderr + "\n" if stderr else "") + f"SSH command exceeded {effective_timeout:g}s timeout"
                stderr_bytes = len(stderr.encode("utf-8", errors="replace"))
                failure_kind = ServerTransportFailureKind.TIMEOUT
                return_code = 124
            elif completed.spawn_error is not None:
                failure_kind = ServerTransportFailureKind.SPAWN_ERROR
                return_code = 127
            else:
                failure_kind = classify_transport_failure(completed.return_code, stderr)
                return_code = completed.return_code
            return ServerCommandResult(
                self._profile.server_id, command, return_code, stdout, stderr, failure_kind,
                time.perf_counter() - started, stdout_bytes, stderr_bytes,
            )
        completed = runner(argv, interactive=interactive)
        if not isinstance(completed, ServerCommandResult):
            raise TypeError("injected SSH runner must return ServerCommandResult")
        return completed

    def interactive_argv(self, command: str, *, allocate_tty: bool = False) -> tuple[str, ...]:
        if not command.strip():
            raise ValueError("interactive remote command must be non-empty")
        argv = list(self._argv(command, interactive=True))
        if allocate_tty:
            argv[1:1] = ["-tt"]
        return tuple(argv)

    def run_interactive(self, argv: tuple[str, ...]) -> int:
        if not argv or argv[0] != self._profile.ssh_executable:
            raise ValueError("interactive SSH argv was not produced by this server identity")
        process_runner = self._process_runner
        if process_runner is None:
            raise RuntimeError("interactive SSH requires an injected async process command runner")
        self._prepare_control_path()
        completed = process_runner.execute(
            argv,
            timeout_seconds=self._profile.interactive_timeout_seconds,
            inherit_stdin=True,
            inherit_output=True,
        ).result()
        if completed.spawn_error is not None:
            return 127
        return completed.return_code


__all__ = ["SSHServerConnection"]
