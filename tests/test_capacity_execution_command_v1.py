from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from noetrium_platform.research.execution.command.api import ExecutionCommand
from noetrium_platform.research.execution.command.providers import SQLiteCommandStore
from noetrium_platform.research.execution.command.runtime import CommandIntentOwner


def test_concurrent_replay_creates_one_durable_command(tmp_path: Path):
    path = tmp_path / "commands.sqlite3"
    command = ExecutionCommand.create(
        command_id="cmd-1",
        command_type="environment.action",
        payload_schema="action.v1",
        payload_digest="d" * 64,
        deduplication_key="request-42",
        now_unix=10.0,
    )

    def submit(_: int):
        owner = CommandIntentOwner(SQLiteCommandStore(path))
        return owner.submit(command)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(submit, range(16)))
    assert {saved.command_id.value for saved, _ in results} == {"cmd-1"}
    assert sum(1 for _, created in results if created) == 1
