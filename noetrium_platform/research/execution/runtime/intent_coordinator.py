from __future__ import annotations

from noetrium_platform.research.execution.api.intent import (
    ExecutionIntentReceipt,
    ExecutionOperationIntent,
)
from noetrium_platform.research.execution.command.api import CommandIntentPort
from noetrium_platform.research.execution.operation.api import OperationSubmissionPort


class ExecutionIntentCoordinator:
    """Orders durable command publication before operation binding.

    A crash after command publication is recoverable by replaying the same immutable
    command and stable operation identity. The coordinator never deletes command truth
    to compensate for an operation-store failure.
    """

    def __init__(self, commands: CommandIntentPort, operations: OperationSubmissionPort) -> None:
        self._commands = commands
        self._operations = operations

    def submit(self, intent: ExecutionOperationIntent) -> ExecutionIntentReceipt:
        command, command_created = self._commands.submit(intent.command)
        operation, operation_created = self._operations.submit(
            command.command_id,
            operation_id=intent.operation_id,
            parent_operation_id=intent.parent_operation_id,
            effect_profile=intent.effect_profile,
            effect_id=intent.effect_id,
            effect_request_id=intent.effect_request_id,
            effect_request_digest=intent.effect_request_digest,
            now_unix=command.submitted_at_unix,
        )
        return ExecutionIntentReceipt(
            command=command,
            operation=operation,
            command_created=command_created,
            operation_created=operation_created,
        )


__all__ = ["ExecutionIntentCoordinator"]
