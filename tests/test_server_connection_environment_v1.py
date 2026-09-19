from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessCommandResult
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
    ServerFileTransferResult,
    ServerIdentityConfigurationError,
    ServerTransportFailureKind,
    server_environment_prefix,
)
from noetrium_platform.infrastructure.lifecycle.server.health.api import ServerRuntimeHealthSpec
from noetrium_platform.infrastructure.lifecycle.server.health.providers import SSHServerHealthProbe
from noetrium_platform.infrastructure.lifecycle.server.identity.providers import (
    EnvironmentSSHServerConnectionFactory,
    EnvironmentSSHServerFileTransferFactory,
    SSHServerConnection,
    SSHServerFileTransfer,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from noetrium_platform.composition.platform_meta import build_in_memory_platform_meta
from noetrium_platform.infrastructure.lifecycle.host.composition import compose_local_host
from noetrium_platform.infrastructure.lifecycle.server.identity.composition import (
    compose_environment_server_identity,
)


OS_ROUTE = LocalOperatingSystemRoute()


class _ImmediateHandle:
    def __init__(self, value):
        self._value = value
        self.result_timeouts: list[float | None] = []

    def result(self, timeout=None):
        self.result_timeouts.append(timeout)
        return self._value


class _ProcessRunner:
    def __init__(self, result: ProcessCommandResult) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
        self.handles: list[_ImmediateHandle] = []

    def execute(self, argv: tuple[str, ...], **kwargs):
        self.calls.append((argv, dict(kwargs)))
        handle = _ImmediateHandle(self.result)
        self.handles.append(handle)
        return handle


def test_server_identity_composition_records_the_host_route_binding() -> None:
    meta = build_in_memory_platform_meta()
    host = compose_local_host(planner=meta.capability_composition)
    concurrency_runtime = build_concurrency_runtime()
    task_group = concurrency_runtime.open_task_group("test-server-identity-composition")
    composed = compose_environment_server_identity(
        operating_system=host.operating_system,
        host_operating_system_offer=host.operating_system_offer,
        planner=meta.capability_composition,
        task_group=task_group,
    )
    connection = composed.connection_factory.from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    )
    assert connection.profile.destination == "ubuntu@research.example"
    assert len(composed.plan.edges) == 1
    assert composed.plan.edges[0].offer.offer_id == host.operating_system_offer.offer_id
    concurrency_runtime.close()


def test_environment_profile_materializes_without_secret_or_address_in_source(tmp_path: Path) -> None:
    prefix = server_environment_prefix("server-a")
    key_path = tmp_path / "research.key"
    key_path.write_text("test-key-material", encoding="utf-8")
    connection = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            f"{prefix}_HOST": "research.example",
            f"{prefix}_PORT": "60320",
            f"{prefix}_USER": "ubuntu",
            f"{prefix}_KEY_PATH": str(key_path),
        },
    )
    assert connection.profile.destination == "ubuntu@research.example"
    assert connection.profile.port == 60320


def test_environment_profile_rejects_missing_required_fields() -> None:
    with pytest.raises(ServerIdentityConfigurationError, match="_HOST"):
        EnvironmentSSHServerConnectionFactory(OS_ROUTE).from_environment(
            "server-a",
            environ={
                "RP_SERVER_SERVER_A_PORT": "22",
                "RP_SERVER_SERVER_A_USER": "ubuntu",
            },
        )


def test_ssh_provider_builds_argv_without_password_or_local_shell() -> None:
    captured: list[tuple[tuple[str, ...], bool]] = []

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerCommandResult:
        captured.append((argv, interactive))
        return ServerCommandResult("server-a", "hostname", 0, "host=box\n", "")

    connection = SSHServerConnection(
        EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
            "server-a",
            environ={
                "RP_SERVER_SERVER_A_HOST": "research.example",
                "RP_SERVER_SERVER_A_PORT": "60320",
                "RP_SERVER_SERVER_A_USER": "ubuntu",
            },
        ).profile,
        operating_system=OS_ROUTE,
        runner=runner,
    )
    result = connection.execute("hostname")
    assert result.succeeded
    assert captured == [
        (
            (
                "ssh-test",
                "-p",
                "60320",
                "-o",
                "ConnectTimeout=15",
                "-o",
                "ConnectionAttempts=1",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=3",
                "-o",
                "BatchMode=yes",
                "-o",
                "PasswordAuthentication=no",
                "-o",
                "KbdInteractiveAuthentication=no",
                "-o",
                "NumberOfPasswordPrompts=0",
                "-o",
                "PreferredAuthentications=publickey",
                "-o",
                "GSSAPIAuthentication=no",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ControlMaster=no",
                "-o",
                "ControlPath=none",
                "ubuntu@research.example",
                "hostname",
            ),
            False,
        )
    ]


def test_ssh_interactive_argv_is_reserved_for_explicit_operator_terminal() -> None:
    captured: list[tuple[tuple[str, ...], bool]] = []

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerCommandResult:
        captured.append((argv, interactive))
        return ServerCommandResult("server-a", "hostname", 0, "", "")

    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    ).profile
    SSHServerConnection(profile, operating_system=OS_ROUTE, runner=runner).execute(
        "hostname", interactive=True
    )
    argv = captured[0][0]
    assert "BatchMode=yes" not in argv
    assert "PasswordAuthentication=no" not in argv
    assert argv[1] == "-tt"



def test_ssh_foreground_operator_session_uses_process_supervision_authority() -> None:
    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    ).profile
    process_runner = _ProcessRunner(ProcessCommandResult(0))
    connection = SSHServerConnection(
        profile,
        operating_system=OS_ROUTE,
        process_runner=process_runner,
    )
    argv = connection.interactive_argv("bash -lc true", allocate_tty=True)

    assert connection.run_interactive(argv) == 0
    assert len(process_runner.calls) == 1
    submitted_argv, options = process_runner.calls[0]
    assert submitted_argv == argv
    assert options["timeout_seconds"] == profile.interactive_timeout_seconds
    assert options["inherit_stdin"] is True
    assert options["inherit_output"] is True
    assert process_runner.handles[0].result_timeouts == [None]



def test_ssh_interactive_timeout_is_finite_identity_and_environment_configurable() -> None:
    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
            "RP_SERVER_SERVER_A_SSH_INTERACTIVE_TIMEOUT_SECONDS": "7200",
        },
    ).profile
    assert profile.interactive_timeout_seconds == 7200.0

    for invalid in ("inf", "nan", "0", "-1"):
        with pytest.raises(ServerIdentityConfigurationError, match="finite and positive"):
            EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
                "server-a",
                environ={
                    "RP_SERVER_SERVER_A_HOST": "research.example",
                    "RP_SERVER_SERVER_A_PORT": "60320",
                    "RP_SERVER_SERVER_A_USER": "ubuntu",
                    "RP_SERVER_SERVER_A_SSH_INTERACTIVE_TIMEOUT_SECONDS": invalid,
                },
            )

def test_ssh_provider_reuses_one_explicit_control_path_for_interactive_operations(tmp_path: Path) -> None:
    captured: list[tuple[tuple[str, ...], bool]] = []

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerCommandResult:
        captured.append((argv, interactive))
        return ServerCommandResult("server-a", "hostname", 0, "host=box\n", "")

    connection = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
            "RP_SERVER_SERVER_A_SSH_CONTROL_PATH": str((Path(Path.cwd().anchor) / "rp-ssh-%C").resolve()),
            "RP_SERVER_SERVER_A_SSH_CONTROL_PERSIST_SECONDS": "900",
        },
    )
    SSHServerConnection(connection.profile, operating_system=OS_ROUTE, runner=runner).execute(
        "hostname", interactive=True
    )
    argv = captured[0][0]
    assert "ControlMaster=auto" in argv
    assert "ControlPersist=900" in argv
    assert any(arg.startswith("ControlPath=") and arg.endswith("rp-ssh-%C") for arg in argv)


def test_ssh_provider_never_reuses_control_channel_for_automation() -> None:
    captured: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerCommandResult:
        assert interactive is False
        captured.append(argv)
        return ServerCommandResult("server-a", "hostname", 0, "", "")

    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
            "RP_SERVER_SERVER_A_SSH_CONTROL_PATH": str((Path(Path.cwd().anchor) / "rp-ssh-%C").resolve()),
        },
    ).profile
    SSHServerConnection(profile, operating_system=OS_ROUTE, runner=runner).execute("hostname")
    argv = captured[0]
    assert "ControlMaster=no" in argv
    assert "ControlPath=none" in argv
    assert "ControlMaster=auto" not in argv
    assert "ControlPath=/tmp/rp-ssh-%C" not in argv
    assert "PreferredAuthentications=publickey" in argv
    assert "GSSAPIAuthentication=no" in argv


def test_health_parses_machine_facts_from_one_remote_command() -> None:
    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    ).profile

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerCommandResult:
        return ServerCommandResult(
            "server-a",
            argv[-1],
            0,
            "host=box\npython=Python 3.11.9\ngit=git version 2.43.0\ntmux=tmux 3.4\n",
            "",
        )

    report = SSHServerHealthProbe().probe(
        SSHServerConnection(profile, operating_system=OS_ROUTE, runner=runner)
    )
    assert report.reachable
    assert report.host_name == "box"
    assert report.python_version == "Python 3.11.9"
    assert report.tmux_version == "tmux 3.4"


def test_managed_health_verifies_python_package_identity() -> None:
    package_digest = "b" * 64
    specification = ServerRuntimeHealthSpec(
        platform_root="/srv/noetrium",
        release_root="/srv/noetrium/releases",
        repository_root="/srv/noetrium/repositories",
        remote_home="/home/ubuntu",
        python_executable="/srv/noetrium/envs/sem/bin/python",
        python_binary_sha256="c" * 64,
        python_packages_sha256=package_digest,
        node_executable="/srv/toolchains/node/bin/node",
        node_binary_sha256="d" * 64,
        java_executable="/srv/toolchains/java/bin/java",
        java_binary_sha256="e" * 64,
        platform_management_executable="/srv/noetrium/bin/noetrium-manage",
        platform_management_binary_sha256="f" * 64,
        tmux_executable="/usr/local/bin/tmux",
        sha256sum_executable="/usr/bin/sha256sum",
        tmux_binary_sha256="a" * 64,
    )

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerCommandResult:
        return ServerCommandResult(
            "server-a",
            argv[-1],
            0,
            "host=box\n"
            "python_version=Python 3.11.15\n"
            "python_packages_status=0\n"
            "inotify_watch_authority=available\n"
            f"python_packages_digest={package_digest}  -\n"
            "python_binary_digest=" + "c" * 64 + "  /srv/noetrium/envs/sem/bin/python\n"
            "node_binary_digest=" + "d" * 64 + "  /srv/toolchains/node/bin/node\n"
            "java_binary_digest=" + "e" * 64 + "  /srv/toolchains/java/bin/java\n"
            "platform_management_binary_digest=" + "f" * 64 + "  /srv/noetrium/bin/noetrium-manage\n"
            "tmux_digest=" + "a" * 64 + "  /usr/local/bin/tmux\n"
            "remote_home=present\nplatform_root=present\nrelease_root=present\nrepository_root=present\n"
            "python_executable=present\nnode_executable=present\njava_executable=present\n"
            "platform_management_executable=present\ntmux_executable=present\nsha256sum_executable=present\n",
            "",
        )

    report = SSHServerHealthProbe().probe(
        SSHServerConnection(
            EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
                "server-a",
                environ={
                    "RP_SERVER_SERVER_A_HOST": "research.example",
                    "RP_SERVER_SERVER_A_PORT": "60320",
                    "RP_SERVER_SERVER_A_USER": "ubuntu",
                },
            ).profile,
            operating_system=OS_ROUTE,
            runner=runner,
        ),
        specification=specification,
    )
    assert report.platform_ready
    assert dict(report.checks)["python_packages_identity"] == "verified"


def test_managed_health_preserves_empty_transport_output_as_health_mismatch() -> None:
    specification = ServerRuntimeHealthSpec(
        platform_root="/srv/noetrium",
        release_root="/srv/noetrium/releases",
        repository_root="/srv/noetrium/repositories",
        remote_home="/home/ubuntu",
        python_executable="/srv/noetrium/envs/sem/bin/python",
        python_binary_sha256="c" * 64,
        python_packages_sha256="b" * 64,
        node_executable="/srv/toolchains/node/bin/node",
        node_binary_sha256="d" * 64,
        java_executable="/srv/toolchains/java/bin/java",
        java_binary_sha256="e" * 64,
        platform_management_executable="/srv/noetrium/bin/noetrium-manage",
        platform_management_binary_sha256="f" * 64,
        tmux_executable="/usr/local/bin/tmux",
        sha256sum_executable="/usr/bin/sha256sum",
        tmux_binary_sha256="a" * 64,
    )

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerCommandResult:
        del argv, interactive
        return ServerCommandResult(
            "server-a",
            "health",
            255,
            "",
            "Permission denied (publickey,password).\n",
            failure_kind=ServerTransportFailureKind.AUTHENTICATION,
        )

    report = SSHServerHealthProbe().probe(
        SSHServerConnection(
            EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
                "server-a",
                environ={
                    "RP_SERVER_SERVER_A_HOST": "research.example",
                    "RP_SERVER_SERVER_A_PORT": "60320",
                    "RP_SERVER_SERVER_A_USER": "ubuntu",
                },
            ).profile,
            operating_system=OS_ROUTE,
            runner=runner,
        ),
        specification=specification,
    )

    assert not report.reachable
    assert not report.platform_ready
    assert "python_packages_identity" in report.issues
    assert report.raw.failure_kind == ServerTransportFailureKind.AUTHENTICATION


def test_scp_transfer_builds_argv_without_password_and_requires_absolute_posix_target(tmp_path: Path) -> None:
    local = tmp_path / "release.zip"
    local.write_bytes(b"release")
    captured: list[tuple[tuple[str, ...], bool]] = []

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerFileTransferResult:
        captured.append((argv, interactive))
        return ServerFileTransferResult("server-a", str(local), "/srv/releases/release.zip", 0, "", "")

    profile = EnvironmentSSHServerFileTransferFactory(OS_ROUTE, scp_executable="scp-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    ).profile
    transfer = SSHServerFileTransfer(
        profile,
        operating_system=OS_ROUTE,
        scp_executable="scp-test",
        runner=runner,
    )
    result = transfer.upload(str(local), "/srv/releases/release.zip")
    assert result.succeeded
    assert transfer.executable == "scp-test"
    assert captured == [
        (
            (
                "scp-test",
                "-P",
                "60320",
                "-o",
                "ConnectTimeout=15",
                "-o",
                "ConnectionAttempts=1",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=3",
                "-B",
                "-o",
                "PasswordAuthentication=no",
                "-o",
                "KbdInteractiveAuthentication=no",
                "-o",
                "NumberOfPasswordPrompts=0",
                "-o",
                "PreferredAuthentications=publickey",
                "-o",
                "GSSAPIAuthentication=no",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ControlMaster=no",
                "-o",
                "ControlPath=none",
                str(local),
                "ubuntu@research.example:/srv/releases/release.zip",
            ),
            False,
        )
    ]
    with pytest.raises(ValueError, match="absolute POSIX"):
        transfer.upload(str(local), "relative/release.zip")


def test_scp_download_builds_reverse_argv_and_requires_absolute_local_target(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    captured: list[tuple[tuple[str, ...], bool]] = []

    def runner(argv: tuple[str, ...], *, interactive: bool) -> ServerFileTransferResult:
        captured.append((argv, interactive))
        Path(argv[-1]).write_bytes(b"downloaded")
        return ServerFileTransferResult("server-a", str(target), "/data/results/result.json", 0, "", "")

    profile = EnvironmentSSHServerFileTransferFactory(OS_ROUTE, scp_executable="scp-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    ).profile
    transfer = SSHServerFileTransfer(
        profile,
        operating_system=OS_ROUTE,
        scp_executable="scp-test",
        runner=runner,
    )
    result = transfer.download("/data/results/result.json", str(target))
    assert result.succeeded
    assert len(captured) == 1
    argv, interactive = captured[0]
    assert argv[:28] == (
        "scp-test",
        "-P",
        "60320",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-B",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "KbdInteractiveAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=0",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "GSSAPIAuthentication=no",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
    )
    assert argv[28] == "ubuntu@research.example:/data/results/result.json"
    assert Path(argv[-1]).name.startswith(f".{target.name}.")
    assert Path(argv[-1]).suffix == ".part"
    assert interactive is False
    assert target.read_bytes() == b"downloaded"
    assert result.local_path == str(target)
    with pytest.raises(ValueError, match="absolute local"):
        transfer.download("/data/results/result.json", "relative/result.json")


def test_ssh_timeout_is_structured_without_collapsing_into_remote_exit() -> None:
    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
            "RP_SERVER_SERVER_A_SSH_COMMAND_TIMEOUT_SECONDS": "0.5",
        },
    ).profile
    process_runner = _ProcessRunner(
        ProcessCommandResult(124, b"partial", b"waiting", timed_out=True)
    )
    result = SSHServerConnection(
        profile, operating_system=OS_ROUTE, process_runner=process_runner
    ).execute("hostname")
    assert not result.succeeded
    assert result.failure_kind == ServerTransportFailureKind.TIMEOUT
    assert result.return_code == 124
    assert "timeout" in result.stderr


def test_scp_uses_a_separate_longer_transfer_timeout(tmp_path: Path) -> None:
    local = tmp_path / "artifact.bin"
    local.write_bytes(b"artifact")
    transfer = EnvironmentSSHServerFileTransferFactory(
        OS_ROUTE,
        scp_executable="scp-test",
    ).from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
            "RP_SERVER_SERVER_A_SSH_COMMAND_TIMEOUT_SECONDS": "0.5",
            "RP_SERVER_SERVER_A_SSH_TRANSFER_TIMEOUT_SECONDS": "900",
        },
    )
    process_runner = _ProcessRunner(
        ProcessCommandResult(124, b"", b"waiting", timed_out=True)
    )
    transfer = SSHServerFileTransfer(
        transfer.profile,
        operating_system=OS_ROUTE,
        scp_executable="scp-test",
        process_runner=process_runner,
    )
    result = transfer.upload(str(local), "/data/artifact.bin")
    assert result.failure_kind == ServerTransportFailureKind.TIMEOUT
    assert process_runner.calls[0][1]["timeout_seconds"] == 900.0
    assert "900s" in result.stderr


def test_repository_command_uses_a_separate_longer_timeout() -> None:
    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
            "RP_SERVER_SERVER_A_SSH_COMMAND_TIMEOUT_SECONDS": "0.5",
            "RP_SERVER_SERVER_A_SSH_REPOSITORY_TIMEOUT_SECONDS": "900",
        },
    ).profile
    process_runner = _ProcessRunner(
        ProcessCommandResult(124, b"", b"cloning", timed_out=True)
    )
    result = SSHServerConnection(
        profile, operating_system=OS_ROUTE, process_runner=process_runner
    ).execute("git clone", timeout_seconds=profile.repository_timeout_seconds)
    assert result.failure_kind == ServerTransportFailureKind.TIMEOUT
    assert process_runner.calls[0][1]["timeout_seconds"] == 900.0
    assert "900s" in result.stderr


def test_ssh_process_spawn_failure_is_distinct_from_remote_exit() -> None:
    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="/missing/ssh").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    ).profile
    process_runner = _ProcessRunner(
        ProcessCommandResult(
            127,
            b"",
            b"OSError: executable missing",
            spawn_error="OSError: executable missing",
        )
    )
    result = SSHServerConnection(
        profile, operating_system=OS_ROUTE, process_runner=process_runner
    ).execute("hostname")
    assert not result.succeeded
    assert result.failure_kind == ServerTransportFailureKind.SPAWN_ERROR
    assert result.return_code == 127


def test_ssh_exit_255_is_split_into_authentication_and_network_classes() -> None:
    profile = EnvironmentSSHServerConnectionFactory(OS_ROUTE, ssh_executable="ssh-test").from_environment(
        "server-a",
        environ={
            "RP_SERVER_SERVER_A_HOST": "research.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
        },
    ).profile
    auth_runner = _ProcessRunner(
        ProcessCommandResult(255, b"", b"Permission denied (publickey,password).\n")
    )
    result = SSHServerConnection(
        profile, operating_system=OS_ROUTE, process_runner=auth_runner
    ).execute("hostname")
    assert result.failure_kind == ServerTransportFailureKind.AUTHENTICATION

    network_runner = _ProcessRunner(
        ProcessCommandResult(
            255, b"", b"ssh: connect to host research.example port 60320: Connection refused\n"
        )
    )
    result = SSHServerConnection(
        profile, operating_system=OS_ROUTE, process_runner=network_runner
    ).execute("hostname")
    assert result.failure_kind == ServerTransportFailureKind.NETWORK

    banner_runner = _ProcessRunner(
        ProcessCommandResult(
            255, b"", b"banner exchange: Connection to UNKNOWN port -1: Permission denied\n"
        )
    )
    result = SSHServerConnection(
        profile, operating_system=OS_ROUTE, process_runner=banner_runner
    ).execute("hostname")
    assert result.failure_kind == ServerTransportFailureKind.NETWORK
