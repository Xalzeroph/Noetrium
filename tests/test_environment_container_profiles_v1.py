from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from scripts.build_environment_images import (
    _default_active_profile_ids,
    _image_runtime_identity_digest,
    _parse_profile_build_input_overrides,
    _prepare_qualification_instance,
    _profile_build_input_digest,
    _profile_map,
    _profile_revision,
    _require_profile_build_intent,
    validate_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
ENV_ROOT = ROOT / "deploy" / "environments"


def _catalog() -> dict:
    return json.loads((ENV_ROOT / "catalog.json").read_text(encoding="utf-8"))


def test_environment_profile_registry_is_dynamic_and_lifecycle_driven() -> None:
    data = _catalog()
    assert data["schema"] == "noetrium.environment-profile-registry.v3"
    profiles = data["profiles"]
    assert profiles
    profile_ids = [row["profile_id"] for row in profiles]
    assert len(profile_ids) == len(set(profile_ids))

    active_categories = {
        row["category_id"]
        for row in profiles
        if row["lifecycle"] == "active"
    }
    defaults = {
        row["category_id"]: row["profile_id"]
        for row in profiles
        if row.get("default_for_category")
    }
    assert set(defaults) == active_categories
    assert {row["lifecycle"] for row in profiles} <= {"active", "draining", "retired"}

    builder = (ROOT / "scripts" / "build_environment_images.py").read_text(encoding="utf-8")
    assert "EXPECTED_PROFILES" not in builder
    assert "_default_active_profile_ids" in builder
    assert "--allow-draining" in builder
    assert "--allow-retired" in builder


def test_environment_registry_accepts_parallel_retired_revision_without_code_change() -> None:
    data = deepcopy(_catalog())
    current = next(
        row for row in data["profiles"] if row["category_id"] == "minecraft"
    )
    retired = deepcopy(current)
    retired["profile_id"] = "minecraft-r0"
    retired["lifecycle"] = "retired"
    retired["default_for_category"] = False
    data["profiles"].append(retired)

    profiles = _profile_map(data)
    result = validate_catalog(data, profiles)

    assert result["retired_profile_count"] == 1
    assert "minecraft-r0" not in _default_active_profile_ids(profiles)
    assert _profile_revision(retired) != _profile_revision(current)


def test_environment_profile_lifecycle_blocks_new_work_without_recovery_intent() -> None:
    profiles = {
        "active": {"lifecycle": "active"},
        "draining": {"lifecycle": "draining"},
        "retired": {"lifecycle": "retired"},
    }
    _require_profile_build_intent(
        profiles,
        ("active",),
        allow_draining=False,
        allow_retired=False,
    )

    import pytest

    with pytest.raises(RuntimeError, match="allow-draining"):
        _require_profile_build_intent(
            profiles,
            ("draining",),
            allow_draining=False,
            allow_retired=False,
        )
    _require_profile_build_intent(
        profiles,
        ("draining",),
        allow_draining=True,
        allow_retired=False,
    )

    with pytest.raises(RuntimeError, match="allow-retired"):
        _require_profile_build_intent(
            profiles,
            ("retired",),
            allow_draining=False,
            allow_retired=False,
        )
    _require_profile_build_intent(
        profiles,
        ("retired",),
        allow_draining=False,
        allow_retired=True,
    )


def test_environment_build_receipt_uses_concrete_content_addressed_runtime_identity() -> None:
    digest = "a" * 64
    assert _image_runtime_identity_digest({"id": "sha256:" + digest}) == digest

    builder = (ROOT / "scripts" / "build_environment_images.py").read_text(
        encoding="utf-8"
    )
    assert '"schema": "noetrium.environment-image-build.v4"' in builder
    assert '"runtime_identity_digest"' in builder


def test_environment_profile_build_input_changes_with_runtime_sources() -> None:
    web = {"profile_id": "web", "category_id": "web"}
    empty_inputs = {"images": {}, "parameters": {}}
    first = _profile_build_input_digest(
        web,
        profile_revision="a" * 64,
        base_runtime_identity_digest="b" * 64,
        resolved_build_inputs=empty_inputs,
    )
    changed_base = _profile_build_input_digest(
        web,
        profile_revision="a" * 64,
        base_runtime_identity_digest="c" * 64,
        resolved_build_inputs=empty_inputs,
    )
    assert first != changed_base

    minecraft = {"profile_id": "minecraft", "category_id": "minecraft"}
    mc_inputs = {
        "images": {
            "java_runtime": {
                "runtime_identity_digest": "a" * 64,
            },
            "node_runtime": {
                "runtime_identity_digest": "b" * 64,
            },
        },
        "parameters": {},
    }
    mc_first = _profile_build_input_digest(
        minecraft,
        profile_revision="d" * 64,
        base_runtime_identity_digest="e" * 64,
        resolved_build_inputs=mc_inputs,
    )
    mc_java_changed_inputs = deepcopy(mc_inputs)
    mc_java_changed_inputs["images"]["java_runtime"][
        "runtime_identity_digest"
    ] = "b" * 64
    mc_java_changed = _profile_build_input_digest(
        minecraft,
        profile_revision="d" * 64,
        base_runtime_identity_digest="e" * 64,
        resolved_build_inputs=mc_java_changed_inputs,
    )
    mc_node_changed_inputs = deepcopy(mc_inputs)
    mc_node_changed_inputs["images"]["node_runtime"][
        "runtime_identity_digest"
    ] = "c" * 64
    mc_node_changed = _profile_build_input_digest(
        minecraft,
        profile_revision="d" * 64,
        base_runtime_identity_digest="e" * 64,
        resolved_build_inputs=mc_node_changed_inputs,
    )
    assert mc_first != mc_java_changed
    assert mc_first != mc_node_changed


def test_environment_profile_build_inputs_are_registry_driven() -> None:
    data = _catalog()
    minecraft = next(
        row for row in data["profiles"] if row["profile_id"] == "minecraft"
    )
    inputs = minecraft["build_inputs"]
    assert inputs["images"] == [
        {
            "name": "java_runtime",
            "environment_variable": "JAVA_RUNTIME_IMAGE",
            "canonical_image": "eclipse-temurin:21-jre-jammy",
        },
        {
            "name": "node_runtime",
            "environment_variable": "NODE_RUNTIME_IMAGE",
            "canonical_image": "node:22.22.2-bookworm-slim",
        },
    ]
    assert inputs["parameters"] == []

    builder = (ROOT / "scripts" / "build_environment_images.py").read_text(
        encoding="utf-8"
    )
    assert 'row["category_id"] == "minecraft"' not in builder
    assert "--java-runtime-image" not in builder
    assert "--node-version" not in builder
    assert "--build-input" in builder
    assert "_resolve_profile_build_inputs" in builder
    assert '"profile_build_inputs"' in builder
    minecraft_dockerfile = (
        ROOT / "deploy" / "environments" / "minecraft" / "Dockerfile"
    ).read_text(encoding="utf-8")
    assert "ARG NODE_RUNTIME_IMAGE=node:22.22.2-bookworm-slim" in minecraft_dockerfile
    assert "FROM ${NODE_RUNTIME_IMAGE} AS node-runtime" in minecraft_dockerfile
    assert "curl -fsSLO" not in minecraft_dockerfile
    assert "apt-get install" not in minecraft_dockerfile


def test_environment_profile_build_input_override_parser_fails_closed() -> None:
    assert _parse_profile_build_input_overrides(
        ("JAVA_RUNTIME_IMAGE=mirror/java@sha256:abc",)
    ) == {
        "JAVA_RUNTIME_IMAGE": "mirror/java@sha256:abc",
    }

    import pytest

    with pytest.raises(ValueError, match="ENVIRONMENT_VARIABLE=value"):
        _parse_profile_build_input_overrides(("not-an-assignment",))
    with pytest.raises(ValueError, match="duplicate"):
        _parse_profile_build_input_overrides(
            ("NODE_VERSION=22.22.2", "NODE_VERSION=22.23.0")
        )


def test_environment_registry_declares_share_vs_isolate_policy() -> None:
    data = _catalog()
    policy = data["sharing_policy"]
    assert "share immutable content" in policy["principle"]
    assert "runtime-state" in policy["private_per_execution"]
    assert "workspace" in policy["private_per_execution"]
    assert "content-addressed-assets" in policy["shared_read_only"]
    assert "zero active/resumable references" in policy["gc_rule"]

    required_private = {
        "workspace", "tmp", "runtime-state", "secrets",
        "process-namespace", "network-namespace", "ports",
    }
    for row in data["profiles"]:
        isolation = row["isolation"]
        assert isolation["shared_read_only"]
        assert required_private <= set(isolation["private_writable"])
        assert isolation["cleanliness"] == "destroy-overlay-or-verified-reset"


def test_environment_images_extend_qualified_base_and_install_local_doctors() -> None:
    data = _catalog()
    for row in data["profiles"]:
        if row.get("build_mode") == "base-only":
            continue
        dockerfile = ROOT / row["dockerfile"]
        compose = ROOT / row["compose"]
        hook = ENV_ROOT / row["profile_id"] / "doctor.sh"
        assert dockerfile.is_file()
        assert compose.is_file()
        assert hook.is_file()
        text = dockerfile.read_text(encoding="utf-8")
        assert "ARG PLATFORM_BASE_IMAGE" in text
        assert "FROM ${PLATFORM_BASE_IMAGE}" in text
        assert "environment-doctor.d" in text
        assert f"/environment-doctor.d/{row['category_id']}" in text
        assert "org.opencontainers.image.noetrium.environment.profile-id" in text
        assert "org.opencontainers.image.noetrium.environment.category-id" in text
        assert "org.opencontainers.image.noetrium.environment.profile-revision" in text
        assert "org.opencontainers.image.noetrium.environment.build-input.sha256" in text
        lowered = text.lower()
        for forbidden in ("copy research", "copy benchmarks", "copy datasets", "copy checkpoints", "copy experiments"):
            assert forbidden not in lowered


def test_environment_doctor_dispatch_is_profile_extensible() -> None:
    entrypoint = (ROOT / "deploy" / "container-entrypoint.sh").read_text(encoding="utf-8")
    assert "environment-doctor.d" in entrypoint
    assert 'local hook="$PROFILE_DOCTOR_ROOT/$profile"' in entrypoint
    for profile_id in ("minecraft", "embodied", "gui", "web", "software"):
        assert f"{profile_id}_doctor()" not in entrypoint


def test_environment_compose_overlays_have_profile_doctors() -> None:
    data = _catalog()
    for row in data["profiles"]:
        compose_path = row.get("compose")
        if compose_path is None:
            continue
        text = (ROOT / compose_path).read_text(encoding="utf-8")
        assert "environment-doctor" in text
        assert row["category_id"] in text


def test_environment_writable_state_is_instance_scoped() -> None:
    base = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    minecraft = (ROOT / "deploy" / "environments" / "minecraft" / "compose.yaml").read_text(encoding="utf-8")
    assert "PLATFORM_RUNTIME_STATE_ROOT" in base
    assert "PLATFORM_ENVIRONMENT_INSTANCE_ROOT" in minecraft
    assert "set PLATFORM_RUNTIME_STATE_ROOT to a per-instance writable directory" in base
    assert "set PLATFORM_ENVIRONMENT_INSTANCE_ROOT to a per-instance writable directory" in minecraft
    assert "${PLATFORM_HOST_DATA_ROOT:-./.runtime}/minecraft" not in minecraft
    assert "instances/unscoped" not in minecraft
    builder = (ROOT / "scripts" / "build_environment_images.py").read_text(encoding="utf-8")
    assert "qualification_instance" in builder
    assert "PLATFORM_ENVIRONMENT_INSTANCE_ROOT" in builder
    assert "qualification_instance_cleaned" in builder


def test_base_compose_does_not_rebuild_mutable_checkout() -> None:
    text = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    runtime_block = text.split("  platform-runtime:", 1)[1].split("\n  platform-test:", 1)[0]
    assert "build:" not in runtime_block
    assert "PLATFORM_IMAGE" in runtime_block
    assert "/usr/local/bin/noetrium-entrypoint" in runtime_block


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


def test_qualification_precreates_runtime_and_profile_bind_sources(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        """
services:
  platform-runtime:
    volumes:
      - type: bind
        source: ${PLATFORM_ENVIRONMENT_INSTANCE_ROOT:?required}/minecraft
        target: /var/lib/minecraft
      - type: bind
        source: ${PLATFORM_ENVIRONMENT_INSTANCE_ROOT}/browser/profile
        target: /home/platform/profile
""".strip()
        + "\n",
        encoding="utf-8",
    )
    instance = tmp_path / "instance"

    _prepare_qualification_instance(instance, compose_path=compose)

    for relative in ("platform-state", "minecraft", "browser/profile"):
        target = instance / relative
        assert target.is_dir()
        assert target.stat().st_mode & 0o777 == 0o777


def test_deployment_runtime_images_are_source_configurable_without_remote_frontend() -> None:
    base = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_environment_images.py").read_text(encoding="utf-8")
    assert "ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim-bookworm" in base
    assert "FROM ${PYTHON_RUNTIME_IMAGE}" in base
    assert "--python-runtime-image" in builder
    assert "--python-runtime-canonical-image" in builder
    assert "--build-input" in builder
    assert "--java-runtime-image" not in builder
    assert "--java-runtime-canonical-image" not in builder
    assert "--node-version" not in builder
    assert '"base_runtime_source"' in builder
    assert '"profile_build_inputs"' in builder
    assert "PLATFORM_PYTHON_RUNTIME_IDENTITY_DIGEST" in builder
    assert "NOETRIUM_ENVIRONMENT_BUILD_INPUT_DIGEST" in builder
    assert "profile_revision" in builder
    assert "_verified_profile_image_identity" in builder
    for dockerfile in (ROOT / "deploy").rglob("Dockerfile"):
        text = dockerfile.read_text(encoding="utf-8")
        assert "# syntax=docker/dockerfile:" not in text


def test_environment_bootstrap_reaps_nested_qualification_orphans() -> None:
    bootstrap = (ROOT / "deploy" / "build-environments.sh").read_text(encoding="utf-8")
    builder = (ROOT / "scripts" / "build_environment_images.py").read_text(encoding="utf-8")

    assert 'BOOTSTRAP_CHILD_LABEL="io.noetrium.bootstrap-child"' in bootstrap
    assert "reconcile_bootstrap_children" in bootstrap
    assert "cleanup_owned_bootstrap_children" in bootstrap
    assert "NOETRIUM_BOOTSTRAP_OWNER_PID" in bootstrap
    assert "NOETRIUM_BOOTSTRAP_OWNER_BOOT" in bootstrap
    assert "NOETRIUM_BOOTSTRAP_OWNER_START" in bootstrap
    assert 'label=$OWNER_PID_LABEL=$$"' in bootstrap
    assert "NOETRIUM_BOOTSTRAP_OWNER_PID=$$ -e" in bootstrap
    assert "NOETRIUM_BOOTSTRAP_OWNER_PID=$ -e" not in bootstrap
    assert "io.noetrium.bootstrap-child=qualification-v1" in builder
    assert "_qualification_label_args()" in builder



def test_environment_bootstrap_orphan_reaper_fails_closed_on_unknown_docker_state() -> None:
    bootstrap = (ROOT / "deploy" / "build-environments.sh").read_text(
        encoding="utf-8"
    )

    assert "bootstrap_container_absent" in bootstrap
    assert "remove_bootstrap_container_exact" in bootstrap
    assert "Unable to prove bootstrap container absence" in bootstrap
    assert "Failed to remove bootstrap container and absence is unproven" in bootstrap

    managed_reconcile = bootstrap.split(
        "reconcile_bootstrap_containers() {", 1
    )[1].split("reconcile_bootstrap_children() {", 1)[0]
    child_reconcile = bootstrap.split(
        "reconcile_bootstrap_children() {", 1
    )[1].split("cleanup_owned_bootstrap_children() {", 1)[0]

    for block in (managed_reconcile, child_reconcile):
        assert "docker ps -aq --no-trunc" in block
        assert "remove_bootstrap_container_exact" in block
        assert "docker ps -aq" not in block.replace(
            "docker ps -aq --no-trunc", ""
        )
        assert "|| true" not in block


def test_environment_bootstrap_signal_cleanup_uses_exact_ids_and_surfaces_failure() -> None:
    bootstrap = (ROOT / "deploy" / "build-environments.sh").read_text(
        encoding="utf-8"
    )

    child_cleanup = bootstrap.split(
        "cleanup_owned_bootstrap_children() {", 1
    )[1].split("cleanup_owned_bootstrap_container() {", 1)[0]
    owner_cleanup = bootstrap.split(
        "cleanup_owned_bootstrap_container() {", 1
    )[1].split("bootstrap_cleanup() {", 1)[0]
    trap_cleanup = bootstrap.split(
        "bootstrap_cleanup() {", 1
    )[1].split("run_bootstrap_container() {", 1)[0]

    for block in (child_cleanup, owner_cleanup):
        assert "docker ps -aq --no-trunc" in block
        assert "remove_bootstrap_container_exact" in block
        assert "|| true" not in block

    assert 'docker rm -f "$BOOTSTRAP_CONTAINER_NAME"' not in trap_cleanup
    assert "cleanup_owned_bootstrap_container || cleanup_failed=1" in trap_cleanup
    assert "cleanup_owned_bootstrap_children || cleanup_failed=1" in trap_cleanup
    assert "Bootstrap cleanup did not prove physical convergence." in trap_cleanup
    assert '[ "$status" -ne 0 ] || status=1' in trap_cleanup
