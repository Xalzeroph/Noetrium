from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskHandlePort

from .contracts import ProcessCommandResult, ProcessExitReceipt, ProcessTerminationPolicy


class SupervisedProcessPort(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class ProcessCommandRunnerPort(Protocol):
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
    ) -> TaskHandlePort[ProcessCommandResult]: ...


class ProcessSupervisorPort(Protocol):
    def await_exit(
        self,
        supervision_id: str,
        process: SupervisedProcessPort,
        *,
        deadline: Deadline,
    ) -> TaskHandlePort[ProcessExitReceipt]: ...

    def terminate(
        self,
        supervision_id: str,
        process: SupervisedProcessPort,
        *,
        deadline: Deadline,
        policy: ProcessTerminationPolicy | None = None,
    ) -> TaskHandlePort[ProcessExitReceipt]: ...


__all__ = ["ProcessCommandRunnerPort", "ProcessSupervisorPort", "SupervisedProcessPort"]
