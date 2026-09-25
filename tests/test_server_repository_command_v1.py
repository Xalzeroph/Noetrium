from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerCommandResult
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerRepositoryCommandRequest
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.providers import SSHGitRepositoryCommandRunner


REVISION = "b" * 40


def test_repository_command_request_is_pinned_and_confined() -> None:
    request = ServerRepositoryCommandRequest(
        "noetrium",
        REVISION.upper(),
        ("python", "-m", "compileall", "-q", "."),
        "components/example",
    )
    assert request.revision == REVISION
    assert request.relative_cwd == "components/example"


def test_repository_command_request_rejects_escape_and_empty_argv() -> None:
    import pytest

    with pytest.raises(ValueError, match="relative_cwd"):
        ServerRepositoryCommandRequest("repo", REVISION, ("python",), "../outside")
    with pytest.raises(ValueError, match="command_argv"):
        ServerRepositoryCommandRequest("repo", REVISION, ())


def test_repository_command_uses_exact_checkout_and_mutation_observation() -> None:
    captured: list[tuple[str, bool, object]] = []

    class Connection:
        profile = type("Profile", (), {"server_id": "server-a", "repository_timeout_seconds": 1800.0})()

        def execute(self, command: str, *, interactive: bool = False, effect=None, timeout_seconds=None):
            del timeout_seconds
            captured.append((command, interactive, effect))
            return ServerCommandResult("server-a", command, 0, "ok\n", "")

    runner = SSHGitRepositoryCommandRunner(
        Connection(),
        repository_root="/data/noetrium",
        profile_digest="p" * 64,
    )
    receipt = runner.run(
        ServerRepositoryCommandRequest(
            "noetrium",
            REVISION,
            ("python", "-m", "compileall", "-q", "."),
            "components/example",
        ),
        interactive=True,
    )
    command, interactive, effect = captured[0]
    assert interactive is True
    assert str(effect) == "mutation"
    assert f"expected={REVISION}" in command
    assert "cd \"$cwd\"" in command
    assert receipt.target_path == "/data/noetrium/noetrium"
    assert receipt.working_directory == (
        "/data/noetrium/noetrium/components/example"
    )
    assert receipt.succeeded is True
    assert receipt.profile_digest == "p" * 64
