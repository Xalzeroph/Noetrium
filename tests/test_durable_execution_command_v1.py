from pathlib import Path
import sqlite3

from noetrium_platform.research.execution.command.api import CommandConflict, CommandCorruption, CommandId, ExecutionCommand
from noetrium_platform.research.execution.command.providers import SQLiteCommandStore
from noetrium_platform.research.execution.command.runtime import CommandIntentOwner


def _command(*, command_id: str = "cmd-1", command_type: str = "environment.action") -> ExecutionCommand:
    return ExecutionCommand.create(
        command_id=command_id,
        command_type=command_type,
        payload_schema="action.v1",
        payload_digest="c" * 64,
        deduplication_key="request-1",
        now_unix=10.0,
        deadline_unix=30.0,
    )


def test_command_reopens_with_complete_immutable_envelope(tmp_path: Path):
    path = tmp_path / "commands.sqlite3"
    first = CommandIntentOwner(SQLiteCommandStore(path))
    saved, created = first.submit(_command())
    assert created
    second = CommandIntentOwner(SQLiteCommandStore(path))
    replayed, created = second.submit(_command())
    assert not created
    assert replayed == saved
    assert second.require(CommandId("cmd-1")) == saved


def test_command_identity_semantic_drift_fails_closed(tmp_path: Path):
    owner = CommandIntentOwner(SQLiteCommandStore(tmp_path / "commands.sqlite3"))
    owner.submit(_command())
    try:
        owner.submit(_command(command_type="different.action"))
    except CommandConflict:
        pass
    else:
        raise AssertionError("same command identity cannot change immutable intent")


def test_deduplication_key_cannot_move_to_new_command_identity(tmp_path: Path):
    owner = CommandIntentOwner(SQLiteCommandStore(tmp_path / "commands.sqlite3"))
    owner.submit(_command())
    try:
        owner.submit(_command(command_id="cmd-2"))
    except CommandConflict:
        pass
    else:
        raise AssertionError("deduplication key cannot be rebound to another command")


def test_command_store_rejects_corrupt_numeric_coercion(tmp_path: Path):
    path = tmp_path / "commands-corrupt.sqlite3"
    owner = CommandIntentOwner(SQLiteCommandStore(path))
    owner.submit(_command())
    with sqlite3.connect(path) as db:
        db.execute("UPDATE commands SET submitted_at=? WHERE command_id=?", ("not-a-number", "cmd-1"))
    try:
        SQLiteCommandStore(path).load(CommandId("cmd-1"))
    except CommandCorruption:
        pass
    else:
        raise AssertionError("corrupt command row must fail closed")


def test_command_store_rejects_incompatible_existing_schema(tmp_path: Path):
    path = tmp_path / "commands-old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE commands (command_id TEXT PRIMARY KEY)")
    try:
        SQLiteCommandStore(path)
    except CommandCorruption:
        pass
    else:
        raise AssertionError("incompatible command schema must fail closed")
