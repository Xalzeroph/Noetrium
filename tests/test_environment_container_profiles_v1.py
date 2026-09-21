from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_ROOT = ROOT / "deploy" / "environments"


def _catalog() -> dict:
    return json.loads((ENV_ROOT / "catalog.json").read_text(encoding="utf-8"))


def test_environment_profile_catalog_matches_canonical_categories() -> None:
    data = _catalog()
    assert data["schema"] == "noetrium.environment-container-profiles.v1"
    profiles = {row["profile_id"]: row for row in data["profiles"]}
    assert set(profiles) == {"minecraft", "embodied", "gui", "web", "software", "text_world"}
    assert {row["category_id"] for row in profiles.values()} == set(profiles)
    assert profiles["text_world"]["build_mode"] == "base-only"


def test_environment_images_extend_qualified_base_only() -> None:
    data = _catalog()
    for row in data["profiles"]:
        if row.get("build_mode") == "base-only":
            continue
        dockerfile = ROOT / row["dockerfile"]
        compose = ROOT / row["compose"]
        assert dockerfile.is_file()
        assert compose.is_file()
        text = dockerfile.read_text(encoding="utf-8")
        assert "ARG PLATFORM_BASE_IMAGE" in text
        assert "FROM ${PLATFORM_BASE_IMAGE}" in text
        lowered = text.lower()
        for forbidden in (
            "copy research",
            "copy benchmarks",
            "copy datasets",
            "copy checkpoints",
            "copy experiments",
        ):
            assert forbidden not in lowered


def test_environment_compose_overlays_have_profile_doctors() -> None:
    data = _catalog()
    for row in data["profiles"]:
        compose_path = row.get("compose")
        if compose_path is None:
            continue
        text = (ROOT / compose_path).read_text(encoding="utf-8")
        assert "environment-doctor" in text
        assert row["profile_id"] in text


def test_base_compose_does_not_rebuild_mutable_checkout() -> None:
    text = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    assert "build:" not in text
    assert "PLATFORM_IMAGE" in text
    assert "/usr/local/bin/noetrium-entrypoint" in text


def test_environment_catalog_keeps_scientific_assets_downstream() -> None:
    data = _catalog()
    boundary = data["boundary"].lower()
    assert "benchmarks" in boundary
    assert "paper methods" in boundary
    assert "downstream-owned" in boundary


def test_environment_bootstrap_supports_linked_git_worktrees_without_host_git() -> None:
    text = (ROOT / "deploy" / "build-environments.sh").read_text(encoding="utf-8")
    assert 'if [ -f "$ROOT/.git" ]; then' in text
    assert "gitdir: " in text
    assert 'if [ -f "$GITDIR/commondir" ]; then' in text
    assert 'GIT_METADATA_ARGS="-v $GIT_METADATA_ROOT:$GIT_METADATA_ROOT:ro"' in text
    assert "$GIT_METADATA_ARGS -v $ROOT:$ROOT:ro" in text
    assert "git rev-parse" not in text
    prefix = text.split("docker build", 1)[0].lower()
    assert "python3" not in prefix
    assert "python -m" not in prefix


def test_deployment_runtime_images_are_source_configurable_without_remote_frontend() -> None:
    base = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_environment_images.py").read_text(
        encoding="utf-8"
    )
    assert "ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim-bookworm" in base
    assert "FROM ${PYTHON_RUNTIME_IMAGE}" in base
    assert "--python-runtime-image" in builder
    assert "--python-runtime-canonical-image" in builder
    assert "--java-runtime-image" in builder
    assert "--java-runtime-canonical-image" in builder
    assert '"runtime_image_sources"' in builder
    for dockerfile in (ROOT / "deploy").rglob("Dockerfile"):
        text = dockerfile.read_text(encoding="utf-8")
        assert "# syntax=docker/dockerfile:" not in text
