from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
    ServerTransportFailureKind,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import (
    ServerRepositorySyncError,
    ServerRepositorySyncRequest,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.providers import SSHGitRepositorySynchronizer


REVISION = "a" * 40
URL = "https://github.com/Xalzeroph/noetrium.git"


def test_repository_request_requires_exact_github_revision() -> None:
    request = ServerRepositorySyncRequest(URL, "noetrium", REVISION)
    assert request.revision == REVISION


def test_repository_request_rejects_unsafe_source_and_revision() -> None:
    import pytest

    with pytest.raises(ValueError, match="GitHub"):
        ServerRepositorySyncRequest("https://example.com/repo.git", "repo", REVISION)
    with pytest.raises(ValueError, match="revision"):
        ServerRepositorySyncRequest(URL, "repo", "not-a-commit")
    with pytest.raises(ValueError, match="repository_name"):
        ServerRepositorySyncRequest(URL, "../repo", REVISION)


def test_repository_sync_uses_profile_owned_root_and_pinned_checkout() -> None:
    captured: list[tuple[str, bool, object]] = []

    class Connection:
        profile = type("Profile", (), {"server_id": "server-a", "repository_timeout_seconds": 1800.0, "git_transport_timeout_seconds": 120.0})()

        def execute(self, command: str, *, interactive: bool = False, effect=None, timeout_seconds=None):
            del timeout_seconds
            captured.append((command, interactive, effect))
            return ServerCommandResult("server-a", command, 0, "", "")

    synchronizer = SSHGitRepositorySynchronizer(
        Connection(),
        repository_root="/data/noetrium",
        profile_digest="p" * 64,
    )
    receipt = synchronizer.sync(
        ServerRepositorySyncRequest(URL, "noetrium", REVISION),
        interactive=True,
    )
    command, interactive, effect = captured[0]
    assert interactive is True
    assert str(effect) == "mutation"
    assert "git clone --branch master --single-branch" in command
    assert "GIT_TERMINAL_PROMPT=0" in command
    assert "GIT_ASKPASS=/bin/false" in command
    assert "SSH_ASKPASS=/bin/false" in command
    assert "credential.interactive=false" in command
    assert "command -v timeout" in command
    assert "timeout --foreground --signal=TERM --kill-after=10s 120s git clone" in command
    assert "http.connectTimeout=15" in command
    assert "http.lowSpeedLimit=1024" in command
    assert "http.lowSpeedTime=60" in command
    assert "checkout --detach" in command
    assert REVISION in command
    assert receipt.target_path == "/data/noetrium/noetrium"
    assert receipt.profile_digest == "p" * 64


def test_repository_status_reads_only_the_profile_owned_checkout() -> None:
    captured: list[tuple[str, bool, object]] = []

    class Connection:
        profile = type("Profile", (), {"server_id": "server-a", "repository_timeout_seconds": 1800.0, "git_transport_timeout_seconds": 120.0})()

        def execute(self, command: str, *, interactive: bool = False, effect=None, timeout_seconds=None):
            del timeout_seconds
            captured.append((command, interactive, effect))
            return ServerCommandResult(
                "server-a",
                command,
                0,
                "target_kind=git\nexists=1\nhead="
                + REVISION
                + "\norigin="
                + URL
                + "\ndirty=0\nstaging_kind=absent\nstaging=0\ntarget_children=\n",
                "",
            )

    synchronizer = SSHGitRepositorySynchronizer(
        Connection(), repository_root="/data/noetrium"
    )
    status = synchronizer.inspect("noetrium", staging_revision=REVISION)
    assert status.exists is True
    assert status.head == REVISION
    assert status.dirty is False
    assert status.staging_exists is False
    assert status.target_kind == "git"
    assert status.staging_kind == "absent"
    assert status.target_children == ()
    assert captured[0][2].value == "observation"


def test_repository_status_without_staging_revision_does_not_probe_target_as_staging() -> None:
    captured: list[str] = []

    class Connection:
        profile = type("Profile", (), {"server_id": "server-a", "repository_timeout_seconds": 1800.0, "git_transport_timeout_seconds": 120.0})()

        def execute(self, command: str, *, interactive: bool = False, effect=None, timeout_seconds=None):
            del interactive, effect, timeout_seconds
            captured.append(command)
            return ServerCommandResult(
                "server-a",
                command,
                0,
                "target_kind=git\nexists=1\nhead="
                + REVISION
                + "\norigin="
                + URL
                + "\ndirty=0\nstaging_kind=absent\nstaging=0\ntarget_children=\n",
                "",
            )

    status = SSHGitRepositorySynchronizer(
        Connection(), repository_root="/data/noetrium/repositories"
    ).inspect("noetrium")
    assert status.staging_exists is False
    assert status.staging_kind == "absent"
    assert "staging=$target" not in captured[0]
    assert "staging_kind=absent" in captured[0]


def test_repository_status_distinguishes_a_non_git_target_directory() -> None:
    class Connection:
        profile = type("Profile", (), {"server_id": "server-a", "repository_timeout_seconds": 1800.0, "git_transport_timeout_seconds": 120.0})()

        def execute(self, command: str, *, interactive: bool = False, effect=None, timeout_seconds=None):
            del timeout_seconds
            return ServerCommandResult(
                "server-a",
                command,
                0,
                "target_kind=directory\nexists=0\nhead=\norigin=\n"
                "dirty=\nstaging_kind=absent\nstaging=0\n"
                "target_children=envs,models,runs\n",
                "",
            )

    status = SSHGitRepositorySynchronizer(
        Connection(), repository_root="/data/noetrium/repositories"
    ).inspect("noetrium", staging_revision=REVISION)
    assert status.exists is False
    assert status.target_kind == "directory"
    assert status.target_children == ("envs", "models", "runs")
    assert status.staging_kind == "absent"


def test_repository_sync_preserves_structured_transport_failure() -> None:
    class Connection:
        profile = type("Profile", (), {"server_id": "server-a", "repository_timeout_seconds": 1800.0, "git_transport_timeout_seconds": 120.0})()

        def execute(self, command: str, *, interactive: bool = False, effect=None, timeout_seconds=None):
            del timeout_seconds
            return ServerCommandResult(
                "server-a",
                command,
                255,
                "",
                "connection closed",
                ServerTransportFailureKind.NETWORK,
            )

    synchronizer = SSHGitRepositorySynchronizer(
        Connection(), repository_root="/data/noetrium"
    )
    import pytest

    with pytest.raises(ServerRepositorySyncError, match="network"):
        synchronizer.sync(ServerRepositorySyncRequest(URL, "repo", REVISION))
