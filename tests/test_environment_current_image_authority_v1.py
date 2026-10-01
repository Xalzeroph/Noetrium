from __future__ import annotations

import json

import pytest

from noetrium_platform.composition.environment_image_runtime import (
    current_environment_image_tag,
    resolve_current_environment_image,
)
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult


class _Runner:
    def __init__(self, result: LocalCommandResult) -> None:
        self.result = result
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, *, cwd=None, environment=None, timeout_seconds=None):
        del cwd, environment
        self.calls.append(tuple(argv))
        assert timeout_seconds == 30.0
        return self.result


def _inspect(*, profile_id="minecraft", category_id="minecraft", tag_category_id=None, digest="a" * 64):
    tag = current_environment_image_tag(category_id if tag_category_id is None else tag_category_id)
    payload = [{
        "Id": "sha256:" + digest,
        "RepoTags": [tag, f"noetrium-env-{profile_id}:immutable"],
        "Config": {
            "Labels": {
                "org.opencontainers.image.noetrium.environment.profile-id": profile_id,
                "org.opencontainers.image.noetrium.environment.category-id": category_id,
                "org.opencontainers.image.noetrium.environment.profile-revision": "b" * 64,
                "org.opencontainers.image.noetrium.environment.build-input.sha256": "c" * 64,
            }
        },
    }]
    return LocalCommandResult(("docker",), 0, json.dumps(payload), "")


def test_current_environment_image_resolves_only_current_alias() -> None:
    runner = _Runner(_inspect())
    assert resolve_current_environment_image(
        runner,
        category_id="minecraft",
    ) == ("noetrium-env-category-minecraft:current", "a" * 64)
    assert runner.calls == [
        ("docker", "image", "inspect", "noetrium-env-category-minecraft:current")
    ]


def test_current_environment_image_rejects_wrong_provenance() -> None:
    runner = _Runner(_inspect(category_id="web", tag_category_id="minecraft"))
    with pytest.raises(RuntimeError, match="provenance mismatch"):
        resolve_current_environment_image(
            runner,
            category_id="minecraft",
        )


def test_current_environment_image_requires_published_alias() -> None:
    runner = _Runner(LocalCommandResult(("docker",), 1, "", "not found"))
    with pytest.raises(RuntimeError, match="current environment image is unavailable"):
        resolve_current_environment_image(
            runner,
            category_id="minecraft",
        )
