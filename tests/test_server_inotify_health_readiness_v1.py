from __future__ import annotations

import subprocess
import sys

from noetrium_platform.infrastructure.lifecycle.server.health.api import ServerRuntimeHealthSpec
from noetrium_platform.infrastructure.lifecycle.server.health.providers.ssh_probe import (
    SSHServerHealthProbe,
    _inotify_probe_script,
)
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerCommandResult


def _specification() -> ServerRuntimeHealthSpec:
    return ServerRuntimeHealthSpec(
        platform_root="/srv/platform",
        release_root="/srv/platform/releases",
        repository_root="/srv/platform/repositories",
        remote_home="/home/ubuntu",
        python_executable="/srv/env/bin/python",
        python_binary_sha256="a" * 64,
        python_packages_sha256="b" * 64,
        node_executable="/srv/node/bin/node",
        node_binary_sha256="c" * 64,
        java_executable="/srv/java/bin/java",
        java_binary_sha256="d" * 64,
        platform_management_executable="/srv/platform/bin/manage",
        platform_management_binary_sha256="e" * 64,
        tmux_executable="/usr/bin/tmux",
        sha256sum_executable="/usr/bin/sha256sum",
        tmux_binary_sha256="f" * 64,
    )


def _values(inotify_status: str) -> dict[str, str]:
    values = {
        key: "present"
        for key in (
            "remote_home",
            "platform_root",
            "release_root",
            "repository_root",
            "python_executable",
            "node_executable",
            "java_executable",
            "platform_management_executable",
            "tmux_executable",
            "sha256sum_executable",
        )
    }
    values.update(
        inotify_watch_authority=inotify_status,
        python_packages_status="0",
        python_packages_digest="b" * 64,
        python_binary_digest="a" * 64,
        node_binary_digest="c" * 64,
        java_binary_digest="d" * 64,
        platform_management_binary_digest="e" * 64,
        tmux_digest="f" * 64,
    )
    return values


def test_managed_health_accepts_available_inotify_authority() -> None:
    ready, checks, issues = SSHServerHealthProbe._managed_result(
        _values("available"),
        ServerCommandResult("server-a", "health", 0, "", ""),
        _specification(),
    )
    assert ready
    assert dict(checks)["inotify_watch_authority"] == "available"
    assert "inotify_watch_authority" not in issues


def test_managed_health_fails_closed_when_inotify_authority_is_unavailable() -> None:
    ready, checks, issues = SSHServerHealthProbe._managed_result(
        _values("unavailable"),
        ServerCommandResult("server-a", "health", 0, "", ""),
        _specification(),
    )
    assert not ready
    assert dict(checks)["inotify_watch_authority"] == "unavailable"
    assert "inotify_watch_authority" in issues


def test_managed_health_command_collects_inotify_authority_read_only_fact() -> None:
    command = SSHServerHealthProbe._managed_command(_specification())
    assert "inotify_watch_authority=" in command
    assert "inotify_add_watch" in command
    assert "os.close(fd)" in command


def test_inotify_health_issue_projects_as_stable_typed_diagnostic_code() -> None:
    from noetrium_platform.infrastructure.lifecycle.server.health.api import ServerHealthReport
    from noetrium_platform.infrastructure.lifecycle.server.health.runtime import ServerDiagnosticProjector

    raw = ServerCommandResult("server-a", "health", 0, "", "")
    health = ServerHealthReport(
        "server-a", True, "host", "3.12", None, None, raw,
        platform_ready=False,
        checks=(("inotify_watch_authority", "unavailable"),),
        issues=("inotify_watch_authority",),
    )
    report = ServerDiagnosticProjector().project(
        server_id="server-a",
        profile_digest="profile-a",
        operation_log="/tmp/operations.jsonl",
        health=health,
        pending_operations=(),
        recent_operations=(),
    )
    assert not report.ready_for_mutation
    assert any(issue.code == "health:inotify_watch_authority" for issue in report.issues)


def test_inotify_probe_script_always_returns_bounded_status() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _inotify_probe_script()],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout.strip() in {"available", "unavailable", "not_required"}
