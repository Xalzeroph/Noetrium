from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import OperationExecutor
from noetrium_platform.infrastructure.reliability.forensics.composition import ForensicStore
from noetrium_platform.research.execution.operation.command.providers import SQLiteCommandStore
from noetrium_platform.research.execution.operation.command.runtime import CommandIntentOwner
from noetrium_platform.research.execution.operation.providers import SQLiteOperationStore
from noetrium_platform.research.execution.operation.runtime import OperationOwner
from noetrium_platform.research.execution.workflow.runtime import (
    DurableKernelOperationDispatcher,
    KernelOperationDispatcher,
)

from .operation_forensics import OperationForensicFailureSink


@dataclass(slots=True)
class ManagedOperationRuntime:
    """One process-owned Operation/Failure authority bundle."""

    commands: CommandIntentOwner
    operations: OperationOwner
    forensics: ForensicStore
    dispatcher: DurableKernelOperationDispatcher
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.operations.close()
        finally:
            try:
                self.commands.close()
            finally:
                self.forensics.close()
                self._closed = True


def build_managed_operation_runtime(
    root: Path,
    *,
    task_group: TaskGroupPort,
) -> ManagedOperationRuntime:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    commands = CommandIntentOwner(SQLiteCommandStore(root / "commands.sqlite"))
    operations = OperationOwner(SQLiteOperationStore(root / "operations.sqlite"))
    forensics = ForensicStore(
        root / "forensics",
        read_only=False,
        task_group=task_group,
    )
    kernel = KernelOperationDispatcher(
        OperationExecutor(OperationForensicFailureSink(forensics))
    )
    dispatcher = DurableKernelOperationDispatcher(
        kernel,
        commands=commands,
        submissions=operations,
        admissions=operations,
        operations=operations,
    )
    return ManagedOperationRuntime(
        commands=commands,
        operations=operations,
        forensics=forensics,
        dispatcher=dispatcher,
    )


__all__ = ["ManagedOperationRuntime", "build_managed_operation_runtime"]
