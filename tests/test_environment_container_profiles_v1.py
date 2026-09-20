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
        for forbidden in ("copy research", "copy benchmarks", "openha", "osworld", "webarena", "libero", "calvin", "robotwin", "swe-bench"):
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
