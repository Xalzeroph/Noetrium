from __future__ import annotations

import asyncio
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
