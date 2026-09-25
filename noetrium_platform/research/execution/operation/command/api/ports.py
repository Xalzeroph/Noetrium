from __future__ import annotations

from typing import Protocol

from .contracts import CommandDeduplicationKey, CommandId, ExecutionCommand


class CommandConflict(RuntimeError):
    pass


class CommandCorruption(RuntimeError):
    pass


class CommandStorePort(Protocol):
    @property
    def durability(self) -> str: ...
    def create_or_get(self, command: ExecutionCommand) -> tuple[ExecutionCommand, bool]: ...
    def load(self, command_id: CommandId) -> ExecutionCommand | None: ...
    def load_by_deduplication_key(self, key: CommandDeduplicationKey) -> ExecutionCommand | None: ...


class CommandIntentPort(Protocol):
    def submit(self, command: ExecutionCommand) -> tuple[ExecutionCommand, bool]: ...
    def require(self, command_id: CommandId) -> ExecutionCommand: ...
    def find_by_deduplication_key(self, key: CommandDeduplicationKey) -> ExecutionCommand | None: ...


__all__ = ["CommandConflict", "CommandCorruption", "CommandIntentPort", "CommandStorePort"]
