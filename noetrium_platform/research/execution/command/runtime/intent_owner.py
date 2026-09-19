from __future__ import annotations

from noetrium_platform.research.execution.command.api import (
    CommandDeduplicationKey,
    CommandId,
    CommandStorePort,
    ExecutionCommand,
)


class CommandIntentOwner:
    """Single durable authority for immutable execution command intents."""

    def __init__(self, store: CommandStorePort) -> None:
        self._store = store

    @property
    def durability(self) -> str:
        return self._store.durability

    def submit(self, command: ExecutionCommand) -> tuple[ExecutionCommand, bool]:
        return self._store.create_or_get(command)

    def require(self, command_id: CommandId) -> ExecutionCommand:
        command = self._store.load(command_id)
        if command is None:
            raise KeyError(f"command not found: {command_id.value}")
        return command

    def find_by_deduplication_key(
        self,
        key: CommandDeduplicationKey,
    ) -> ExecutionCommand | None:
        return self._store.load_by_deduplication_key(key)


__all__ = ["CommandIntentOwner"]
