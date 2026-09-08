from __future__ import annotations

from pathlib import Path

from noetrium.contracts.environment import (
    EnvironmentCapability,
    EnvironmentProviderPort,
)
from noetrium.platform import (
    MinecraftEnvironmentBinding,
    bind_bundled_minecraft_environment,
)


def test_bundled_minecraft_binding_is_public_provider_without_private_path(tmp_path: Path) -> None:
    binding = bind_bundled_minecraft_environment(
        node_executable="node",
        action_recovery_root=str((tmp_path / "recovery").resolve()),
        task_group_id="test-public-minecraft-binding",
    )
    try:
        assert isinstance(binding, MinecraftEnvironmentBinding)
        assert isinstance(binding, EnvironmentProviderPort)
        assert binding.identity.environment_id == "minecraft"
        assert binding.capabilities.supports(EnvironmentCapability.RECONCILE)
        assert binding.capabilities.supports(EnvironmentCapability.DIAGNOSTICS)
        assert binding.capabilities.supports(EnvironmentCapability.QUERY)
        assert not binding.capabilities.supports(EnvironmentCapability.SNAPSHOT)
    finally:
        binding.close()


def test_bundled_minecraft_binding_locates_packaged_bridge_asset(tmp_path: Path) -> None:
    binding = bind_bundled_minecraft_environment(
        node_executable="node",
        action_recovery_root=str((tmp_path / "recovery").resolve()),
        task_group_id="test-public-minecraft-assets",
    )
    try:
        spec = binding.spec
        assert Path(spec.bridge.command[1]).name == "bridge.js"
        assert "noetrium_platform" in spec.bridge.command[1]
        assert spec.bridge.action_recovery_root == str((tmp_path / "recovery").resolve())
    finally:
        binding.close()
