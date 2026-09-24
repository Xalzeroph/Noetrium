from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Lock
from typing import Callable
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)

from ..api import ProcessExitReceipt, ProcessSupervisorPort, ProcessTerminationPolicy, SupervisedProcessPort
from .windows_job import WindowsProcessJob, suspended_creation_flag


class _PosixGroupOwnedProcess:
    """Popen facade whose PID is the exact owned process-group guardian."""

    def __init__(self, delegate: subprocess.Popen[str]) -> None:
        self._delegate = delegate
        self.pid = int(delegate.pid)
        self.stdin = delegate.stdin
        self.stdout = delegate.stdout
        self.stderr = delegate.stderr

    def poll(self) -> int | None:
        return self._delegate.poll()

    def wait(self, timeout: float | None = None) -> int:
        return int(self._delegate.wait(timeout=timeout))

    def _signal_guardian(self, sig: signal.Signals) -> None:
        if self._delegate.poll() is not None:
            return
        try:
            if os.getpgid(self.pid) != self.pid:
                raise RuntimeError(
                    "interactive guardian process-group identity drifted; refusing signal"
                )
            os.kill(self.pid, sig)
        except ProcessLookupError:
            if self._delegate.poll() is None:
                raise

    def terminate(self) -> None:
        # Guardian forwards TERM to the target group but stays alive until the
        # target really exits, so supervisor escalation cannot lose authority.
        self._signal_guardian(signal.SIGTERM)

    def kill(self) -> None:
        # SIGUSR1 is guardian-private force cleanup: it SIGKILLs the target
        # process group while preserving the guardian until wait/poll observes
        # target convergence.
        self._signal_guardian(signal.SIGUSR1)


class _WindowsJobOwnedProcess:
    """Popen facade retaining a kill-on-owner-close Windows Job Object."""

    def __init__(
        self,
        delegate: subprocess.Popen[str],
        job: WindowsProcessJob,
    ) -> None:
        self._delegate = delegate
        self._job = job
        self.pid = int(delegate.pid)
        self.stdin = delegate.stdin
        self.stdout = delegate.stdout
        self.stderr = delegate.stderr
        self._job_closed = False

    def _retire_job_if_exited(self, code: int | None) -> int | None:
        if code is not None and not self._job_closed:
            self._job.close()
            self._job_closed = True
        return code

    def poll(self) -> int | None:
        return self._retire_job_if_exited(self._delegate.poll())

    def wait(self, timeout: float | None = None) -> int:
        code = int(self._delegate.wait(timeout=timeout))
        self._retire_job_if_exited(code)
        return code

    def terminate(self) -> None:
        if self.poll() is None:
            self._job.terminate(143)

    def kill(self) -> None:
        if self.poll() is None:
            self._job.terminate(137)


class AsyncProcessSupervisor(ProcessSupervisorPort):
    """Task-group-owned process watcher without thread-per-process waiting.

    The supervisor polls non-blocking ``process.poll()`` calls from the process-
    level ASYNC_IO event loop.  Hundreds of watched processes therefore share
    one event-loop thread.  Termination uses terminate -> async poll -> kill ->
    async poll and never blocks a Python worker on ``Popen.wait()``.
    """

    def __init__(
        self,
        task_group: TaskGroupPort,
        policy: ProcessTerminationPolicy | None = None,
        termination_hook: Callable[[SupervisedProcessPort, bool], None] | None = None,
        task_namespace: str | None = None,
    ) -> None:
        self._task_group = task_group
        self._policy = policy or ProcessTerminationPolicy()
        self._termination_hook = termination_hook
        namespace = str(task_namespace).strip() if task_namespace is not None else uuid4().hex
        if not namespace:
            raise ValueError("process supervisor task namespace required")
        self._task_namespace = namespace
        self._lock = Lock()
        self._sequence = 0

    def _task_id(self, supervision_id: str, operation: str) -> str:
        resolved = str(supervision_id).strip()
        if not resolved:
            raise ValueError("process supervision id required")
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        return f"process-supervision:{self._task_namespace}:{resolved}:{operation}:{sequence}"

    def spawn_interactive(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str,
        environment: dict[str, str],
        start_new_session: bool,
        creationflags: int = 0,
    ) -> SupervisedProcessPort:
        """Spawn a pipe-backed child under the lifecycle/process authority."""
        if (
            type(argv) is not tuple
            or not argv
            or any(type(item) is not str or not item.strip() for item in argv)
        ):
            raise ValueError("interactive process argv must be non-empty canonical text")
        if type(cwd) is not str or not cwd.strip():
            raise ValueError("interactive process cwd must be non-empty text")
        if (
            type(environment) is not dict
            or any(
                type(key) is not str
                or not key
                or type(value) is not str
                for key, value in environment.items()
            )
        ):
            raise TypeError("interactive process environment must contain text pairs")
        if type(start_new_session) is not bool:
            raise TypeError("interactive process start_new_session must be bool")
        if type(creationflags) is not int or creationflags < 0:
            raise ValueError("interactive process creationflags must be a non-negative integer")
        command = list(argv)
        options: dict[str, object] = {
            "cwd": cwd,
            "env": dict(environment),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "bufsize": 1,
            "start_new_session": start_new_session,
        }

        if os.name == "posix" and start_new_session:
            # A fresh Python guardian avoids the well-known multithreaded
            # preexec_fn deadlock class. It remains the session leader, watches
            # owner liveness, and forwards termination to the complete process
            # group. Linux additionally uses PR_SET_PDEATHSIG inside the fresh
            # interpreter for immediate owner-death convergence.
            guardian = Path(__file__).with_name("parent_bound_child.py")
            command = [
                sys.executable,
                str(guardian),
                "--parent-pid",
                str(os.getpid()),
                "--",
                *command,
            ]
            return _PosixGroupOwnedProcess(
                subprocess.Popen(command, **options)
            )

        if os.name == "nt":
            flags = int(creationflags) | suspended_creation_flag()
            options["creationflags"] = flags
            process = subprocess.Popen(command, **options)
            try:
                job = WindowsProcessJob.attach_suspended(int(process.pid))
            except BaseException:
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except BaseException:
                    pass
                raise
            return _WindowsJobOwnedProcess(process, job)

        if creationflags:
            options["creationflags"] = creationflags
        return subprocess.Popen(command, **options)


    async def _await_exit(self, context, supervision_id: str, process: SupervisedProcessPort, escalated: bool):
        while True:
            context.checkpoint()
            code = process.poll()
            if code is not None:
                return ProcessExitReceipt(
                    supervision_id=supervision_id,
                    process_id=int(process.pid),
                    exit_code=int(code),
                    escalated_to_kill=escalated,
                )
            remaining = context.remaining_seconds
            delay = self._policy.poll_interval_seconds
            if remaining is not None:
                delay = min(delay, max(0.0, remaining))
            if delay <= 0:
                context.checkpoint()
            await asyncio.sleep(delay)

    def await_exit(
        self,
        supervision_id: str,
        process: SupervisedProcessPort,
        *,
        deadline: Deadline,
    ):
        task_id = self._task_id(supervision_id, "await-exit")
        return self._task_group.submit(
            ExecutionSpec(
                task_id=task_id,
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            self._await_exit,
            str(supervision_id).strip(),
            process,
            False,
            deadline=deadline,
        )

    async def _terminate(
        self,
        context,
        supervision_id: str,
        process: SupervisedProcessPort,
        policy: ProcessTerminationPolicy,
    ):
        code = process.poll()
        if code is not None:
            return ProcessExitReceipt(supervision_id, int(process.pid), int(code), False)

        try:
            if self._termination_hook is None:
                process.terminate()
            else:
                self._termination_hook(process, False)
        except ProcessLookupError:
            # The process can legitimately disappear between the non-blocking
            # poll above and SIGTERM delivery.  Only that exact race is benign;
            # all other termination failures remain visible to the caller.
            code = process.poll()
            if code is not None:
                return ProcessExitReceipt(supervision_id, int(process.pid), int(code), False)
            raise
        graceful_deadline = Deadline.after(policy.graceful_timeout_seconds)
        while True:
            context.checkpoint()
            code = process.poll()
            if code is not None:
                return ProcessExitReceipt(supervision_id, int(process.pid), int(code), False)
            if graceful_deadline.expired:
                break
            await asyncio.sleep(min(policy.poll_interval_seconds, graceful_deadline.remaining_seconds))

        if self._termination_hook is None:
            process.kill()
        else:
            self._termination_hook(process, True)
        kill_deadline = Deadline.after(policy.kill_timeout_seconds)
        while True:
            context.checkpoint()
            code = process.poll()
            if code is not None:
                return ProcessExitReceipt(supervision_id, int(process.pid), int(code), True)
            if kill_deadline.expired:
                raise TimeoutError(
                    f"process did not terminate after kill: {supervision_id} pid={process.pid}"
                )
            await asyncio.sleep(min(policy.poll_interval_seconds, kill_deadline.remaining_seconds))

    def terminate(
        self,
        supervision_id: str,
        process: SupervisedProcessPort,
        *,
        deadline: Deadline,
        policy: ProcessTerminationPolicy | None = None,
    ):
        task_id = self._task_id(supervision_id, "terminate")
        return self._task_group.submit(
            ExecutionSpec(
                task_id=task_id,
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            self._terminate,
            str(supervision_id).strip(),
            process,
            policy or self._policy,
            deadline=deadline,
        )


__all__ = ["AsyncProcessSupervisor"]
