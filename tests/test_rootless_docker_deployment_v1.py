from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rootless_docker_manager_is_ordinary_user_and_data_root_bound() -> None:
    script = (ROOT / "deploy" / "rootless-docker.sh").read_text(encoding="utf-8")

    for prerequisite in (
        "dockerd-rootless.sh",
        "rootlesskit",
        "slirp4netns",
        "newuidmap",
        "newgidmap",
    ):
        assert f"require_command {prerequisite}" in script

    assert 'DATA_ROOT="${NOETRIUM_DOCKER_DATA_ROOT:-$STATE_ROOT/docker}"' in script
    assert 'RUNTIME_ROOT="${NOETRIUM_DOCKER_RUNTIME_ROOT:-$STATE_ROOT/docker-runtime}"' in script
    assert '--data-root "$DATA_ROOT"' in script
    assert '--exec-root "$RUNTIME_ROOT/exec"' in script
    assert 'DOCKER_HOST="unix://$SOCKET" docker info' in script
    assert "require_expected_root" in script
    assert "sudo " not in script
    assert "/var/lib/docker" not in script


def test_deploy_doctor_fails_closed_on_docker_root_drift() -> None:
    launcher = (ROOT / "deploy" / "noetrium").read_text(encoding="utf-8")

    assert 'ROOTLESS_DOCKER="$ROOT/deploy/rootless-docker.sh"' in launcher
    assert 'NOETRIUM_DOCKER_DATA_ROOT=/data/noetrium/docker' in launcher
    assert "docker info --format '{{.DockerRootDir}}'" in launcher
    assert "active DockerRootDir does not match NOETRIUM_DOCKER_DATA_ROOT" in launcher
    assert 'docker)' in launcher
    assert '"$ROOTLESS_DOCKER" "$@"' in launcher


def test_rootless_docker_configuration_is_documented_without_becoming_secret_state() -> None:
    example = (ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")

    assert "# NOETRIUM_DOCKER_DATA_ROOT=/data/noetrium/docker" in example
    assert "# NOETRIUM_DOCKER_RUNTIME_ROOT=/data/noetrium/docker-runtime" in example
