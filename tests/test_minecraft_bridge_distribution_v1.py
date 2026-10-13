from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.environment.minecraft.providers.bridge_distribution import (
    MinecraftBridgeRuntimeDistributionCache,
)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_bridge_distribution_discovers_transitive_local_runtime_closure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(source, "package.json", "{}")
    _write(source, "package-lock.json", "{}")
    _write(
        source,
        "bridge.js",
        "require('./resources')\nrequire('./runtime.js')\n",
    )
    _write(source, "resources.js", "require('./world_frontier')\n")
    _write(source, "runtime.js", "'use strict'\n")
    _write(source, "world_frontier.js", "require('./runtime')\n")
    _write(source, "unused.js", "throw new Error('not runtime reachable')\n")

    manifest = dict(
        MinecraftBridgeRuntimeDistributionCache.source_manifest(source)
    )

    assert set(manifest) == {
        "package.json",
        "package-lock.json",
        "bridge.js",
        "resources.js",
        "runtime.js",
        "world_frontier.js",
    }
    assert "unused.js" not in manifest


def test_bridge_distribution_fails_closed_on_missing_local_dependency(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write(source, "package.json", "{}")
    _write(source, "package-lock.json", "{}")
    _write(source, "bridge.js", "require('./missing_runtime')\n")

    with pytest.raises(FileNotFoundError):
        MinecraftBridgeRuntimeDistributionCache.source_manifest(source)


def test_real_mineflayer_bridge_distribution_contains_world_frontier() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "noetrium_platform"
        / "capabilities"
        / "environment"
        / "minecraft"
        / "providers"
        / "assets"
        / "mineflayer_bridge"
    )
    manifest = dict(
        MinecraftBridgeRuntimeDistributionCache.source_manifest(source)
    )

    assert "world_frontier.js" in manifest
    assert "resources.js" in manifest
    assert "movement.js" in manifest
