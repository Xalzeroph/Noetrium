from __future__ import annotations

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerCommandResult, ServerConnectionProfile
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerReleaseLayout
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.providers import SSHServerReleaseDirectory


class FakeConnection:
    profile = ServerConnectionProfile("server-a", "research.example", 60320, "ubuntu")

    def __init__(self, *, success: bool = True) -> None:
        self.success = success
        self.commands: list[tuple[str, object]] = []

    def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
        del interactive
        self.commands.append((command, effect))
        release = "/srv/noetrium/releases/" + "a" * 64
        return ServerCommandResult(
            "server-a",
            command,
            0 if self.success else 1,
            f"release={release}\n" if self.success else "",
            "" if self.success else "missing",
        )


def test_remote_release_directory_is_verified_through_observation_port() -> None:
    connection = FakeConnection()
    layout = ServerReleaseLayout("/srv/noetrium")
    provider = SSHServerReleaseDirectory(connection, layout)
    expected = layout.release_path("a" * 64)
    assert provider.require_release_dir("a" * 64) == expected
    assert connection.commands[0][1].value == "observation"
    assert "test -d" in connection.commands[0][0]


def test_remote_release_directory_failure_is_fail_closed() -> None:
    from noetrium_platform.infrastructure.lifecycle.server.lifecycle.runtime import ServerReleaseLayoutError

    provider = SSHServerReleaseDirectory(
        FakeConnection(success=False),
        ServerReleaseLayout("/srv/noetrium"),
    )
    try:
        provider.require_release_dir("a" * 64)
    except ServerReleaseLayoutError:
        pass
    else:
        raise AssertionError("missing remote release directory was accepted")
