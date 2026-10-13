from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "deploy/noetrium"


@pytest.mark.parametrize(
    "path",
    [
        [],
        ["help"],
        ["run", "--help"],
        ["help", "research", "resume"],
        ["workspace", "init", "--help"],
        ["project", "create", "--help"],
        ["help", "infra", "docker", "start"],
        ["help", "infra", "env", "build"],
        ["help", "infra", "manage", "model"],
        ["help", "diagnose", "failure", "why"],
        ["help", "diagnose", "evidence", "timeline"],
        ["dev", "architecture", "gate", "--help"],
        ["dev", "algorithm", "scan", "--help"],
        ["dev", "boundary", "audit", "--help"],
    ],
)
def test_shell_help_is_the_public_tree_and_never_touches_docker_or_state(
    path, tmp_path
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "docker-called"
    docker = fake_bin / "docker"
    docker.write_text('#!/bin/sh\nprintf called > "$MARKER"\nexit 97\n')
    docker.chmod(0o755)
    state = tmp_path / "state-must-not-exist"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": str(fake_bin) + os.pathsep + environment["PATH"],
            "MARKER": str(marker),
            "NOETRIUM_DATA_ROOT": str(state),
            "NOETRIUM_WORKSPACE_FILE": str(tmp_path / "missing.json"),
        }
    )
    result = subprocess.run(
        (str(CLI), *path),
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "noetrium" in result.stdout
    assert not marker.exists()
    assert not state.exists()


def test_shell_and_installed_entry_name_the_same_composition():
    import tomllib

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["scripts"] == {
        "noetrium": "noetrium_platform.composition.operator.wiring.entrypoint:main"
    }
    assert "noetrium_platform.composition.operator.wiring.entrypoint" in CLI.read_text()


def test_removed_flat_command_never_reaches_the_private_backend(tmp_path):
    state = tmp_path / "untouched"
    env = os.environ.copy()
    env["NOETRIUM_DATA_ROOT"] = str(state)
    result = subprocess.run(
        (str(CLI), "doctor"),
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert not state.exists()
