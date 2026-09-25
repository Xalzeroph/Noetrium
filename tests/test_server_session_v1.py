from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerCommandResult, server_environment_prefix
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.api import ServerRemoteProfile
from noetrium_platform.infrastructure.lifecycle.server.providers import ProfileBoundServerConnection
from noetrium_platform.infrastructure.lifecycle.session.providers import (
    SSHRemoteTmuxCommandRunner,
    SSHRemoteTmuxSessionControl,
)


def _environment(root: Path) -> dict[str, str]:
    prefix = server_environment_prefix("server-a")
    return {
        f"{prefix}_PLATFORM_ROOT": "/srv/noetrium",
        f"{prefix}_RELEASE_ROOT": "/srv/noetrium/releases",
        f"{prefix}_OPERATOR_CWD": "/srv/noetrium",
        f"{prefix}_REPOSITORY_ROOT": "/srv/noetrium/repositories",
        f"{prefix}_OPERATOR_SHELL": "/usr/bin/bash",
        f"{prefix}_OPERATOR_SHELL_ARGS": "-il",
        f"{prefix}_REMOTE_ENV": "/usr/bin/env",
        f"{prefix}_SHA256SUM": "/usr/bin/sha256sum",
        f"{prefix}_PYTHON": "/srv/noetrium/envs/sem/bin/python",
        f"{prefix}_PYTHON_SHA256": "c" * 64,
        f"{prefix}_PYTHON_PACKAGES_SHA256": "b" * 64,
        f"{prefix}_NODE": "/srv/noetrium/toolchains/node/bin/node",
        f"{prefix}_NODE_SHA256": "d" * 64,
        f"{prefix}_JAVA": "/srv/noetrium/toolchains/java/bin/java",
        f"{prefix}_JAVA_SHA256": "e" * 64,
        f"{prefix}_PLATFORM_MANAGE": "/srv/noetrium/envs/sem/bin/noetrium-manage",
        f"{prefix}_PLATFORM_MANAGE_SHA256": "f" * 64,
        f"{prefix}_TMUX": "/usr/local/bin/tmux",
        f"{prefix}_TMUX_SHA256": "a" * 64,
        f"{prefix}_TMUX_SERVER_LABEL": "noetrium",
        f"{prefix}_TMUX_CONFIG": "/dev/null",
        f"{prefix}_TMUX_SOCKET_DIRECTORY": "/tmp",
        f"{prefix}_SESSION_NAME": "noetrium-shell",
        f"{prefix}_LOCAL_BINDING_ROOT": str(root),
        f"{prefix}_REMOTE_HOME": "/data/users/ubuntu",
        f"{prefix}_REMOTE_PATH": "/usr/local/bin:/usr/bin:/bin",
        f"{prefix}_TERM": "xterm-256color",
    }


def test_remote_profile_requires_explicit_runtime_paths(tmp_path: Path) -> None:
    values = _environment(tmp_path)
    values.pop("RP_SERVER_SERVER_A_TMUX_SHA256")
    with pytest.raises(ValueError, match="TMUX_SHA256"):
        ServerRemoteProfile.from_environment("server-a", environ=values)


def test_remote_profile_materializes_one_non_secret_runtime_identity(tmp_path: Path) -> None:
    profile = ServerRemoteProfile.from_environment(
        "server-a", environ=_environment(tmp_path)
    )
    assert profile.platform_root == "/srv/noetrium"
    assert profile.repository_root == "/srv/noetrium/repositories"
    assert profile.session_environment == (
        ("HOME", "/data/users/ubuntu"),
        ("LANG", "C.UTF-8"),
        ("LC_ALL", "C"),
        ("PATH", "/usr/local/bin:/usr/bin:/bin"),
        ("TERM", "xterm-256color"),
    )


def test_profile_bound_connection_applies_the_declared_toolchain_to_direct_commands(tmp_path: Path) -> None:
    profile = ServerRemoteProfile.from_environment(
        "server-a", environ=_environment(tmp_path)
    )
    captured: list[tuple[str, bool, object]] = []

    class Connection:
        profile = type("Profile", (), {"server_id": "server-a"})()

        def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
            captured.append((command, interactive, effect))
            return ServerCommandResult("server-a", command, 0, "ok\n", "")

        def interactive_argv(self, command: str, *, allocate_tty: bool = False) -> tuple[str, ...]:
            return ("ssh-test", command, str(allocate_tty))

        def run_interactive(self, argv: tuple[str, ...]) -> int:
            return 0

    command = "cd /srv/work && npm ci --no-audit"
    result = ProfileBoundServerConnection(Connection(), profile).execute(command)

    assert result.command == command
    assert captured[0][0].startswith(
        "/usr/bin/env HOME=/data/users/ubuntu LANG=C.UTF-8 LC_ALL=C PATH=/usr/local/bin:/usr/bin:/bin TERM=xterm-256color"
    )
    assert "/usr/bin/bash -lc" in captured[0][0]
    assert "npm ci --no-audit" in captured[0][0]


def test_remote_tmux_runner_uses_argv_shaped_command_without_local_shell(tmp_path: Path) -> None:
    captured: list[tuple[str, bool, str]] = []

    class Connection:
        def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
            captured.append((command, interactive, str(effect)))
            return ServerCommandResult("server-a", command, 0, "ok\n", "")

    runner = SSHRemoteTmuxCommandRunner(
        Connection(),
        remote_env_executable="/usr/bin/env",
        base_environment={"HOME": "/home/ubuntu", "PATH": "/usr/bin"},
    )
    result = runner.run(
        ("/usr/local/bin/tmux", "-L", "noetrium", "has-session", "-t", "=shell"),
        environment={"LC_ALL": "C"},
        effect="observation",
    )
    assert result.returncode == 0
    assert captured[0][0].startswith("/usr/bin/env -i")
    assert "shell" in captured[0][0]
    assert captured[0][1] is False
    assert captured[0][2] == "observation"


def test_remote_tmux_runner_marks_session_mutations_for_server_recovery() -> None:
    captured: list[str] = []

    class Connection:
        def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
            del command, interactive
            captured.append(str(effect))
            return ServerCommandResult("server-a", "tmux", 0, "", "")

    runner = SSHRemoteTmuxCommandRunner(
        Connection(),
        remote_env_executable="/usr/bin/env",
        base_environment={},
    )
    runner.run(
        ("/usr/local/bin/tmux", "-f", "/dev/null", "-L", "noetrium", "new-session", "-d"),
        environment={},
        effect="mutation",
    )
    assert captured == ["mutation"]


def test_remote_tmux_control_attests_binary_and_allocates_tty(tmp_path: Path) -> None:
    captured: list[tuple[str, bool, str]] = []

    class Connection:
        def execute(self, command: str, *, interactive: bool = False, effect=None) -> ServerCommandResult:
            captured.append((command, interactive, str(effect)))
            if "sha256sum" in command:
                return ServerCommandResult("server-a", command, 0, "a" * 64 + "  /usr/local/bin/tmux\n", "")
            return ServerCommandResult("server-a", command, 1, "", "missing session")

        def interactive_argv(self, command: str, *, allocate_tty: bool = False) -> tuple[str, ...]:
            return ("ssh", "-tt" if allocate_tty else "-T", command)

    control = SSHRemoteTmuxSessionControl(
        Connection(),
        tmux_executable="/usr/local/bin/tmux",
        binary_identity_digest="a" * 64,
        server_label="noetrium",
        config_file="/dev/null",
        socket_directory="/tmp",
        remote_env_executable="/usr/bin/env",
        sha256sum_executable="/usr/bin/sha256sum",
        session_environment=(("HOME", "/home/ubuntu"), ("PATH", "/usr/bin")),
    )
    assert control.identity_verified
    assert control.attach_argv("noetrium-shell")[1] == "-tt"
    assert captured[0][2] == "observation"
