"""Cold independent parent pulls overlap; every result is joined before use."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess


_SOURCE = Path(__file__).resolve().parents[1] / "deploy" / "build-environments.sh"


def _pull_fragment() -> str:
    script = _SOURCE.read_text(encoding="utf-8")
    start = script.index("# Independent missing bootstrap parents")
    end = script.index("BOOTSTRAP_INPUT_DIGEST=", start)
    return script[start:end]


def _run(tmp_path, *, existing=(), fail="", barrier=False):
    for name in existing:
        (tmp_path / f"{name}.ready").touch()
    wrapper = """
set -eu
DOCKER_CLI_IMAGE=cli
PYTHON_RUNTIME_IMAGE=python
docker_image_id() {
    if [ -f "$MARKER/$1.ready" ]; then
        printf 'sha256:%064d\n' 0
    else
        return 1
    fi
}
docker() {
    [ "$1" = pull ] || return 2
    image="$2"
    : > "$MARKER/$image.started"
    if [ "$image" = "$FAIL_IMAGE" ]; then return 19; fi
    if [ "$BARRIER" = 1 ]; then
        other=cli
        [ "$image" = cli ] && other=python
        attempt=0
        until [ -f "$MARKER/$other.started" ]; do
            attempt=$((attempt + 1))
            [ "$attempt" -lt 100 ] || return 22
            sleep 0.01
        done
    fi
    sleep 0.03
    : > "$MARKER/$image.ready"
}
""" + _pull_fragment() + """
printf 'VERIFIED=%s,%s\n' "$DOCKER_CLI_IMAGE_ID" "$PYTHON_RUNTIME_IMAGE_ID"
"""
    return subprocess.run(
        ["sh", "-eu", "-c", wrapper],
        text=True, capture_output=True, timeout=4,
        env={
            **os.environ, "MARKER": str(tmp_path),
            "FAIL_IMAGE": fail, "BARRIER": "1" if barrier else "0",
        },
    )


def test_two_cold_parent_pulls_run_concurrently_and_publish_only_after_both(tmp_path):
    result = _run(tmp_path, barrier=True)
    assert result.returncode == 0, result.stderr
    assert "VERIFIED=sha256:" in result.stdout
    assert (tmp_path / "cli.started").is_file()
    assert (tmp_path / "python.started").is_file()
    assert (tmp_path / "cli.ready").is_file()
    assert (tmp_path / "python.ready").is_file()


def test_hot_parents_skip_network_but_still_verify_identities(tmp_path):
    result = _run(tmp_path, existing=("cli", "python"))
    assert result.returncode == 0, result.stderr
    assert "VERIFIED=sha256:" in result.stdout
    assert not (tmp_path / "cli.started").exists()
    assert not (tmp_path / "python.started").exists()


def test_partial_cache_pulls_only_missing_parent(tmp_path):
    result = _run(tmp_path, existing=("cli",))
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "cli.started").exists()
    assert (tmp_path / "python.ready").is_file()


def test_failed_parent_prevents_bootstrap_even_if_sibling_succeeds(tmp_path):
    result = _run(tmp_path, fail="cli")
    assert result.returncode != 0
    assert "Docker CLI bootstrap parent pull failed" in result.stderr
    assert (tmp_path / "python.ready").is_file()
    assert "VERIFIED=" not in result.stdout


def test_second_parent_failure_also_blocks_publication(tmp_path):
    result = _run(tmp_path, fail="python")
    assert result.returncode != 0
    assert "Python bootstrap parent pull failed" in result.stderr
    assert (tmp_path / "cli.ready").is_file()
    assert "VERIFIED=" not in result.stdout
