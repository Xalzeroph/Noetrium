from __future__ import annotations

import json
import re

from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort


_PROFILE_ID_LABEL = "org.opencontainers.image.noetrium.environment.profile-id"
_CATEGORY_ID_LABEL = "org.opencontainers.image.noetrium.environment.category-id"
_PROFILE_REVISION_LABEL = "org.opencontainers.image.noetrium.environment.profile-revision"
_BUILD_INPUT_LABEL = "org.opencontainers.image.noetrium.environment.build-input.sha256"
_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def current_environment_image_tag(category_id: str) -> str:
    if type(category_id) is not str or _TOKEN.fullmatch(category_id) is None:
        raise ValueError("environment category id must be a deployment token")
    return f"noetrium-env-category-{category_id}:current"


def resolve_current_environment_image(
    runner: LocalCommandRunnerPort,
    *,
    category_id: str,
) -> tuple[str, str]:
    if type(category_id) is not str or _TOKEN.fullmatch(category_id) is None:
        raise ValueError("environment category id must be a deployment token")
    tag = current_environment_image_tag(category_id)
    result = runner.run(
        ("docker", "image", "inspect", tag),
        timeout_seconds=30.0,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"current environment image is unavailable for category {category_id!r}"
        )
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("current environment image inspect returned invalid JSON") from exc
    if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
        raise RuntimeError("current environment image inspect must resolve exactly one image")
    row = rows[0]
    raw_id = row.get("Id")
    if type(raw_id) is not str or not raw_id.startswith("sha256:"):
        raise RuntimeError("current environment image identity is not sha256")
    digest = raw_id.removeprefix("sha256:")
    if _SHA256.fullmatch(digest) is None:
        raise RuntimeError("current environment image identity is not sha256")
    repo_tags = row.get("RepoTags")
    if type(repo_tags) is not list or tag not in repo_tags:
        raise RuntimeError("current environment image alias is not attached to inspected image")
    config = row.get("Config")
    labels = config.get("Labels") if type(config) is dict else None
    if type(labels) is not dict:
        raise RuntimeError("current environment image has no provenance labels")
    profile_id = labels.get(_PROFILE_ID_LABEL)
    if type(profile_id) is not str or _TOKEN.fullmatch(profile_id) is None:
        raise RuntimeError("current environment image profile identity is invalid")
    expected = {_CATEGORY_ID_LABEL: category_id}
    mismatches = {
        key: (value, labels.get(key))
        for key, value in expected.items()
        if labels.get(key) != value
    }
    if mismatches:
        raise RuntimeError(
            f"current environment image provenance mismatch: {mismatches!r}"
        )
    for label in (_PROFILE_REVISION_LABEL, _BUILD_INPUT_LABEL):
        value = labels.get(label)
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            raise RuntimeError(
                f"current environment image provenance label {label!r} is not sha256"
            )
    return tag, digest


__all__ = [
    "current_environment_image_tag",
    "resolve_current_environment_image",
]
