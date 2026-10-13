from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcessTerminationPolicy:
    poll_interval_seconds: float = 0.05
    graceful_timeout_seconds: float = 3.0
    kill_timeout_seconds: float = 2.0

    def __post_init__(self) -> None:
        if min(
            self.poll_interval_seconds,
            self.graceful_timeout_seconds,
            self.kill_timeout_seconds,
        ) <= 0:
            raise ValueError("process supervision timing values must be positive")


@dataclass(frozen=True, slots=True)
class ProcessExitReceipt:
    supervision_id: str
    process_id: int
    exit_code: int
    escalated_to_kill: bool = False

    def __post_init__(self) -> None:
        if not self.supervision_id.strip():
            raise ValueError("process supervision id required")
        if self.process_id <= 0:
            raise ValueError("process id must be positive")


@dataclass(frozen=True, slots=True)
class ProcessCommandResult:
    return_code: int
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False
    spawn_error: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def __post_init__(self) -> None:
        if self.timed_out and self.return_code == 0:
            raise ValueError("timed-out process command cannot report success")
        if self.spawn_error is not None and not self.spawn_error.strip():
            raise ValueError("process command spawn_error must be non-empty when present")
        stdout_bytes = len(self.stdout) if self.stdout_bytes is None else int(self.stdout_bytes)
        stderr_bytes = len(self.stderr) if self.stderr_bytes is None else int(self.stderr_bytes)
        if stdout_bytes < len(self.stdout) or stderr_bytes < len(self.stderr):
            raise ValueError("process command byte counts cannot be smaller than captured output")
        if stdout_bytes < 0 or stderr_bytes < 0:
            raise ValueError("process command byte counts cannot be negative")
        if self.stdout_truncated and stdout_bytes <= len(self.stdout):
            raise ValueError("stdout_truncated requires uncaptured stdout bytes")
        if self.stderr_truncated and stderr_bytes <= len(self.stderr):
            raise ValueError("stderr_truncated requires uncaptured stderr bytes")
        object.__setattr__(self, "stdout_bytes", stdout_bytes)
        object.__setattr__(self, "stderr_bytes", stderr_bytes)


__all__ = ["ProcessCommandResult", "ProcessExitReceipt", "ProcessTerminationPolicy"]
