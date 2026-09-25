from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import os
import signal
import subprocess
from threading import Lock
from typing import Mapping

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)

from ..api import ProcessCommandResult, ProcessCommandRunnerPort


@dataclass(slots=True)
class _BoundedPipeCollector:
    limit: int
    captured: bytearray = field(default_factory=bytearray)
    total_bytes: int = 0

    async def drain(self, reader: asyncio.StreamReader | None) -> None:
        if reader is None:
            return
        while True:
            chunk = await reader.read(64 * 1024)
            if not chunk:
                return
            self.total_bytes += len(chunk)
            remaining = self.limit - len(self.captured)
            if remaining > 0:
                self.captured.extend(chunk[:remaining])

    @property
    def value(self) -> bytes:
        return bytes(self.captured)

    @property
    def truncated(self) -> bool:
        return self.total_bytes > len(self.captured)


class AsyncProcessCommandRunner(ProcessCommandRunnerPort):
    """Task-group-owned local command runner with bounded pipe retention.

    Child count is governed by the structured ASYNC_IO lane.  Pipe memory is
    governed independently: stdout/stderr continue to be drained after their
    retention limit is reached so the child cannot deadlock on a full pipe, but
    excess bytes are discarded while exact total-byte accounting is retained.
    """

    def __init__(
        self,
        task_group: TaskGroupPort,
        *,
        cleanup_timeout_seconds: float = 2.0,
        default_output_limit_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if not math.isfinite(float(cleanup_timeout_seconds)) or cleanup_timeout_seconds <= 0:
            raise ValueError("process command cleanup timeout must be finite and positive")
        if default_output_limit_bytes <= 0:
            raise ValueError("process command output limit must be positive")
        self._task_group = task_group
        self._cleanup_timeout_seconds = float(cleanup_timeout_seconds)
        self._default_output_limit_bytes = int(default_output_limit_bytes)
        # A task deadline must outlive child cleanup so the coroutine can reap
        # the complete process tree before its structured owner becomes terminal.
        self._cleanup_reserve_seconds = (2.0 * self._cleanup_timeout_seconds) + 0.1
        self._lock = Lock()
        self._sequence = 0

    def _task_id(self, argv: tuple[str, ...]) -> str:
        if not argv or not str(argv[0]).strip():
            raise ValueError("process command argv must be non-empty")
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        executable = str(argv[0]).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return f"process-command:{executable}:{sequence}"

    @staticmethod
    def _signal_process(
        process: asyncio.subprocess.Process,
        *,
        force: bool,
        windows_job=None,
    ) -> None:
        if os.name == "posix":
            try:
                os.killpg(
                    int(process.pid),
                    signal.SIGKILL if force else signal.SIGTERM,
                )
            except ProcessLookupError:
                return
            return
        if force and windows_job is not None:
            windows_job.terminate(124)
            return
        if process.returncode is not None:
            return
        try:
            if force:
                process.kill()
                return
            ctrl_break = getattr(signal, "CTRL_BREAK_EVENT", None)
            if ctrl_break is not None:
                process.send_signal(ctrl_break)
            else:
                process.terminate()
        except (ProcessLookupError, OSError, ValueError):
            if process.returncode is None:
                process.terminate()

    @staticmethod
    async def _drain_and_wait(
        process: asyncio.subprocess.Process,
        stdout: _BoundedPipeCollector,
        stderr: _BoundedPipeCollector,
    ) -> None:
        await asyncio.gather(
            stdout.drain(process.stdout),
            stderr.drain(process.stderr),
            process.wait(),
        )

    async def _terminate_and_drain(
        self,
        process: asyncio.subprocess.Process,
        stdout: _BoundedPipeCollector,
        stderr: _BoundedPipeCollector,
        *,
        windows_job=None,
    ) -> None:
        if process.returncode is None:
            self._signal_process(process, force=False, windows_job=windows_job)
        try:
            await asyncio.wait_for(
                self._drain_and_wait(process, stdout, stderr),
                timeout=self._cleanup_timeout_seconds,
            )
            return
        except asyncio.TimeoutError:
            pass
        # The root may already have exited while a descendant still owns one of
        # its inherited pipe handles. Tree-level force cleanup must therefore
        # run even when ``process.returncode`` is already populated.
        self._signal_process(process, force=True, windows_job=windows_job)
        await asyncio.wait_for(
            self._drain_and_wait(process, stdout, stderr),
            timeout=self._cleanup_timeout_seconds,
        )

    @staticmethod
    async def _reap_failed_attach(process: asyncio.subprocess.Process) -> str | None:
        """Kill/reap a Windows root that could not enter its ownership Job.

        Cancellation is never converted into a spawn error. Once cancellation is
        observed, the owned root is still physically reaped and the cancellation
        is re-raised to the structured task owner.
        """

        cleanup_error: Exception | None = None
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except (OSError, ValueError) as exc:
                cleanup_error = exc
        try:
            await process.wait()
        except asyncio.CancelledError:
            if process.returncode is None:
                try:
                    process.kill()
                except (ProcessLookupError, OSError, ValueError):
                    pass
            await process.wait()
            raise
        except Exception as exc:
            cleanup_error = cleanup_error or exc
        if cleanup_error is None:
            return None
        return f"{type(cleanup_error).__name__}: {cleanup_error}"

    @staticmethod
    def _result(
        process: asyncio.subprocess.Process,
        stdout: _BoundedPipeCollector,
        stderr: _BoundedPipeCollector,
        *,
        return_code: int | None = None,
        timed_out: bool = False,
    ) -> ProcessCommandResult:
        resolved_code = int(process.returncode if return_code is None else return_code)
        return ProcessCommandResult(
            resolved_code,
            stdout.value,
            stderr.value,
            timed_out=timed_out,
            stdout_bytes=stdout.total_bytes,
            stderr_bytes=stderr.total_bytes,
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
        )

    async def _execute(
        self,
        context,
        argv: tuple[str, ...],
        timeout_seconds: float,
        environment: Mapping[str, str] | None,
        cwd: str | None,
        inherit_stdin: bool,
        inherit_output: bool,
        output_limit_bytes: int,
    ) -> ProcessCommandResult:
        context.checkpoint()
        remaining = context.remaining_seconds
        if remaining is None:
            raise RuntimeError("process command execution requires a structured deadline")
        runtime_budget = min(
            float(timeout_seconds),
            max(0.0, remaining - self._cleanup_reserve_seconds),
        )
        if runtime_budget <= 0:
            return ProcessCommandResult(
                124,
                b"",
                b"process command deadline expired before spawn",
                timed_out=True,
            )
        windows_job = None
        creationflags = 0
        if os.name == "nt":
            from .windows_job import suspended_creation_flag

            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | suspended_creation_flag()
            )
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=None if environment is None else dict(environment),
                stdin=None if inherit_stdin else asyncio.subprocess.DEVNULL,
                stdout=None if inherit_output else asyncio.subprocess.PIPE,
                stderr=None if inherit_output else asyncio.subprocess.PIPE,
                start_new_session=(os.name == "posix"),
                creationflags=creationflags,
            )
        except OSError as exc:
            return ProcessCommandResult(
                127,
                b"",
                f"{type(exc).__name__}: {exc}".encode("utf-8", errors="replace"),
                spawn_error=f"{type(exc).__name__}: {exc}",
            )
        if os.name == "nt":
            try:
                from .windows_job import WindowsProcessJob

                windows_job = WindowsProcessJob.attach_suspended(int(process.pid))
            except Exception as exc:
                cleanup_error = await self._reap_failed_attach(process)
                detail = f"{type(exc).__name__}: {exc}"
                if cleanup_error is not None:
                    detail = f"{detail}; cleanup={cleanup_error}"
                return ProcessCommandResult(
                    127,
                    b"",
                    detail.encode("utf-8", errors="replace"),
                    spawn_error=detail,
                )

        stdout = _BoundedPipeCollector(output_limit_bytes)
        stderr = _BoundedPipeCollector(output_limit_bytes)
        try:
            try:
                remaining = context.remaining_seconds
                if remaining is None:
                    raise RuntimeError("process command execution lost its structured deadline")
                runtime_budget = min(
                    float(timeout_seconds),
                    max(0.0, remaining - self._cleanup_reserve_seconds),
                )
                if runtime_budget <= 0:
                    await self._terminate_and_drain(
                        process, stdout, stderr, windows_job=windows_job
                    )
                    return self._result(
                        process, stdout, stderr, return_code=124, timed_out=True
                    )
                await asyncio.wait_for(
                    self._drain_and_wait(process, stdout, stderr),
                    timeout=runtime_budget,
                )
            except asyncio.TimeoutError:
                await self._terminate_and_drain(process, stdout, stderr, windows_job=windows_job)
                return self._result(process, stdout, stderr, return_code=124, timed_out=True)
            context.checkpoint()
            return self._result(process, stdout, stderr)
        except asyncio.CancelledError:
            # A structured cancellation must still physically reap the child and
            # drain its pipes.  After catching the cancellation Python permits
            # cleanup awaits; re-raise only after the owned process has converged.
            await self._terminate_and_drain(process, stdout, stderr, windows_job=windows_job)
            raise
        finally:
            if windows_job is not None:
                windows_job.close()

    def execute(
        self,
        argv: tuple[str, ...],
        *,
        timeout_seconds: float,
        environment: dict[str, str] | None = None,
        cwd: str | None = None,
        inherit_stdin: bool = False,
        inherit_output: bool = False,
        output_limit_bytes: int | None = None,
    ):
        if timeout_seconds is None or not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("process command timeout must be finite and positive")
        resolved_limit = (
            self._default_output_limit_bytes
            if output_limit_bytes is None
            else int(output_limit_bytes)
        )
        if resolved_limit <= 0:
            raise ValueError("process command output limit must be positive")
        task_id = self._task_id(argv)
        # ``timeout_seconds`` is the command's end-to-end execution budget.
        # The task deadline also bounds ASYNC_IO admission.  A cleanup reserve is
        # added outside that budget so timeout/cancellation can terminate and reap
        # the process tree before ownership is released.
        return self._task_group.submit(
            ExecutionSpec(
                task_id=task_id,
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            self._execute,
            tuple(str(item) for item in argv),
            float(timeout_seconds),
            environment,
            cwd,
            bool(inherit_stdin),
            bool(inherit_output),
            resolved_limit,
            deadline=Deadline.after(float(timeout_seconds) + self._cleanup_reserve_seconds),
        )


__all__ = ["AsyncProcessCommandRunner"]
