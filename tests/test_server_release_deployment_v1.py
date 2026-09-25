from __future__ import annotations

import ast
from pathlib import Path
import shlex

import pytest

from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
    ServerConnectionProfile,
    ServerFileTransferResult,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import (
    ServerReleaseDeploymentError,
    ServerReleaseDeploymentRequest,
    ServerReleaseLayout,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.providers import SSHServerReleasePublisher


class FakeConnection:
    def __init__(self, *, preparation_stdout: str = "") -> None:
        self.profile = ServerConnectionProfile("server-a", "research.example", 60320, "ubuntu")
        self.preparation_stdout = preparation_stdout
        self.commands: list[str] = []

    def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
        del interactive, effect
        self.commands.append(command)
        stdout = self.preparation_stdout if len(self.commands) == 1 else "published\n"
        return ServerCommandResult(self.profile.server_id, command, 0, stdout, "")


class FakeTransfer:
    def __init__(self, *, return_code: int = 0) -> None:
        self.profile = ServerConnectionProfile("server-a", "research.example", 60320, "ubuntu")
        self.return_code = return_code
        self.calls: list[tuple[str, str, bool]] = []

    def upload(self, local_path: str, remote_path: str, *, interactive: bool = False) -> ServerFileTransferResult:
        self.calls.append((local_path, remote_path, interactive))
        return ServerFileTransferResult(
            self.profile.server_id,
            local_path,
            remote_path,
            self.return_code,
            "",
            "" if self.return_code == 0 else "upload failed",
        )


def request(tmp_path: Path) -> ServerReleaseDeploymentRequest:
    package = tmp_path / "release.zip"
    package.write_bytes(b"release")
    return ServerReleaseDeploymentRequest(
        release_digest="a" * 64,
        local_package=package,
        layout=ServerReleaseLayout("/srv/noetrium"),
    )


def test_release_publisher_uploads_verifies_and_publishes_atomically(tmp_path: Path) -> None:
    connection = FakeConnection()
    transfer = FakeTransfer()
    publisher = SSHServerReleasePublisher(connection, transfer, python_executable="/opt/sem/bin/python")

    receipt = publisher.publish(request(tmp_path))

    assert receipt.uploaded
    assert receipt.remote_archive == "/srv/noetrium/incoming/" + "a" * 64 + ".zip"
    assert receipt.remote_release_dir == "/srv/noetrium/releases/" + "a" * 64
    assert len(connection.commands) == 2
    assert len(transfer.calls) == 1
    assert transfer.calls[0][1] == receipt.remote_archive + ".part"
    assert "RELEASE_MANIFEST.json" in connection.commands[1]
    assert ".staging-" in connection.commands[1]
    assert "archive digest mismatch" in connection.commands[1]
    command = shlex.split(connection.commands[1])
    assert command[0] == "/opt/sem/bin/python"
    assert command[1] == "-c"
    embedded = ast.parse(command[2]).body[0].value.args[0].value
    compile(embedded, "<remote-release-extractor>", "exec")


def test_release_publisher_reuses_only_a_matching_published_marker(tmp_path: Path) -> None:
    connection = FakeConnection(preparation_stdout="already-published\n")
    transfer = FakeTransfer()

    receipt = SSHServerReleasePublisher(
        connection, transfer, python_executable="/opt/sem/bin/python"
    ).publish(request(tmp_path))

    assert not receipt.uploaded
    assert transfer.calls == []
    assert receipt.finalization is None


def test_release_publisher_stops_at_transfer_failure_without_finalization(tmp_path: Path) -> None:
    connection = FakeConnection()
    transfer = FakeTransfer(return_code=23)

    with pytest.raises(ServerReleaseDeploymentError, match="transfer"):
        SSHServerReleasePublisher(
            connection, transfer, python_executable="/opt/sem/bin/python"
        ).publish(request(tmp_path))

    assert len(connection.commands) == 1


def test_release_layout_rejects_relative_or_root_target() -> None:
    with pytest.raises(ValueError, match="absolute POSIX"):
        ServerReleaseLayout("srv/noetrium")
    with pytest.raises(ValueError, match="filesystem root"):
        ServerReleaseLayout("/")


def test_release_layout_separates_upload_part_from_authoritative_archive() -> None:
    layout = ServerReleaseLayout("/srv/noetrium")
    digest = "a" * 64
    assert layout.upload_path(digest).endswith(f"{digest}.zip.part")
    assert layout.upload_path(digest) != layout.archive_path(digest)
