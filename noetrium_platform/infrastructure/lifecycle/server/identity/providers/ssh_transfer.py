from __future__ import annotations

from pathlib import Path
import posixpath
import time
from uuid import uuid4

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import durable_replace_file
from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessCommandRunnerPort

from ..api import ServerConnectionProfile, ServerFileTransferPort, ServerFileTransferResult, ServerTransportFailureKind
from .ssh_policy import OpenSSHArgumentPolicy
from .ssh_result import bounded_output_text, classify_transport_failure


class SSHServerFileTransfer(ServerFileTransferPort):
    """SCP transfer provider with atomic local publication for downloads."""

    def __init__(
        self,
        profile: ServerConnectionProfile,
        *,
        operating_system: OperatingSystemRoute,
        scp_executable: str = "scp",
        process_runner: ProcessCommandRunnerPort | None = None,
        runner: object | None = None,
    ) -> None:
        if not scp_executable.strip():
            raise ValueError("scp executable must be non-empty")
        self._profile = profile
        self._operating_system = operating_system
        self._scp_executable = scp_executable
        self._process_runner = process_runner
        self._runner = runner
        self._policy = OpenSSHArgumentPolicy(profile)

    @property
    def profile(self) -> ServerConnectionProfile:
        return self._profile

    @property
    def executable(self) -> str:
        return self._scp_executable

    def _argv(self, local_path: Path, remote_path: str, *, interactive: bool) -> tuple[str, ...]:
        return self._policy.upload(self._scp_executable, local_path, remote_path, interactive=interactive)

    def _download_argv(self, remote_path: str, local_path: Path, *, interactive: bool) -> tuple[str, ...]:
        return self._policy.download(self._scp_executable, remote_path, local_path, interactive=interactive)

    @staticmethod
    def _validate_remote_path(remote_path: str) -> str:
        remote = str(remote_path)
        if not posixpath.isabs(remote) or any(char in remote for char in "\x00\r\n"):
            raise ValueError("SSH remote_path must be an absolute POSIX path without control characters")
        return remote

    def _run_transfer(self, argv: tuple[str, ...], *, local_path: str, remote_path: str, interactive: bool) -> ServerFileTransferResult:
        self._policy.prepare_control_path()
        process_runner = self._process_runner
        if process_runner is None:
            raise RuntimeError("SCP execution requires an injected async process command runner")
        started = time.perf_counter()
        completed = process_runner.execute(
            argv,
            timeout_seconds=self._profile.transfer_timeout_seconds,
            inherit_stdin=interactive,
            output_limit_bytes=self._profile.output_limit_bytes,
        ).result()
        stdout, stdout_bytes = bounded_output_text(
            completed.stdout, limit=self._profile.output_limit_bytes,
            total_bytes=completed.stdout_bytes, truncated=completed.stdout_truncated,
        )
        stderr, stderr_bytes = bounded_output_text(
            completed.stderr, limit=self._profile.output_limit_bytes,
            total_bytes=completed.stderr_bytes, truncated=completed.stderr_truncated,
        )
        if completed.timed_out:
            stderr = (stderr + "\n" if stderr else "") + f"SCP transfer exceeded {self._profile.transfer_timeout_seconds:g}s timeout"
            stderr_bytes = len(stderr.encode("utf-8", errors="replace"))
            failure_kind = ServerTransportFailureKind.TIMEOUT
            return_code = 124
        elif completed.spawn_error is not None:
            failure_kind = ServerTransportFailureKind.SPAWN_ERROR
            return_code = 127
        else:
            failure_kind = classify_transport_failure(completed.return_code, stderr)
            return_code = completed.return_code
        return ServerFileTransferResult(
            self._profile.server_id, local_path, remote_path, return_code, stdout, stderr,
            failure_kind, time.perf_counter() - started, stdout_bytes, stderr_bytes,
        )

    def upload(self, local_path: str, remote_path: str, *, interactive: bool = False) -> ServerFileTransferResult:
        local = Path(local_path).expanduser().resolve(strict=True)
        if not local.is_file():
            raise ValueError("SSH upload local_path must be a regular file")
        remote = self._validate_remote_path(remote_path)
        argv = self._argv(local, remote, interactive=interactive)
        if self._runner is None:
            return self._run_transfer(argv, local_path=str(local), remote_path=remote, interactive=interactive)
        completed = self._runner(argv, interactive=interactive)
        if not isinstance(completed, ServerFileTransferResult):
            raise TypeError("injected SCP runner must return ServerFileTransferResult")
        return completed

    def download(self, remote_path: str, local_path: str, *, interactive: bool = False) -> ServerFileTransferResult:
        remote = self._validate_remote_path(remote_path)
        local = Path(local_path).expanduser()
        if not local.is_absolute():
            raise ValueError("SSH download local_path must be an absolute local target path")
        if any(char in str(local) for char in "\x00\r\n"):
            raise ValueError("SSH download local_path contains control characters")
        if local.exists() and local.is_dir():
            raise ValueError("SSH download local_path must be a file target, not a directory")
        if not local.parent.is_dir():
            raise ValueError("SSH download local_path parent directory must exist")
        temporary = local.with_name(f".{local.name}.{uuid4().hex}.part")
        argv = self._download_argv(remote, temporary, interactive=interactive)
        try:
            if self._runner is None:
                result = self._run_transfer(argv, local_path=str(temporary), remote_path=remote, interactive=interactive)
            else:
                result = self._runner(argv, interactive=interactive)
                if not isinstance(result, ServerFileTransferResult):
                    raise TypeError("injected SCP runner must return ServerFileTransferResult")
            if not result.succeeded:
                return ServerFileTransferResult(
                    self._profile.server_id, str(local), remote, result.return_code,
                    result.stdout, result.stderr, result.failure_kind,
                    result.duration_seconds, result.stdout_bytes, result.stderr_bytes,
                )
            if not temporary.is_file():
                raise RuntimeError("SCP reported success but its temporary download is missing")
            durable_replace_file(temporary, local)
            return ServerFileTransferResult(
                self._profile.server_id, str(local), remote, result.return_code,
                result.stdout, result.stderr, result.failure_kind,
                result.duration_seconds, result.stdout_bytes, result.stderr_bytes,
            )
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


__all__ = ["SSHServerFileTransfer"]
