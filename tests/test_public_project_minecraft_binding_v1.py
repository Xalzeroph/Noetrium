from __future__ import annotations

from pathlib import Path

from noetrium.platform import bind_bundled_minecraft_environment
from noetrium_platform.capabilities.environment.api import (
    EnvironmentCapability,
    EnvironmentProviderPort,
)


def test_bundled_minecraft_binding_is_public_environment_provider() -> None:
    binding = bind_bundled_minecraft_environment(
        host="127.0.0.1",
        port=25565,
        username="ResearchBot",
        task_group_id="test:public-minecraft-binding",
    )
    try:
        assert isinstance(binding, EnvironmentProviderPort)
        assert binding.identity.environment_id == "minecraft"
        assert binding.capabilities.supports(EnvironmentCapability.RECONCILE)
        assert binding.capabilities.supports(EnvironmentCapability.DIAGNOSTICS)
        assert binding.capabilities.supports(EnvironmentCapability.QUERY)
        assert not binding.capabilities.supports(EnvironmentCapability.SNAPSHOT)
        assert not binding.capabilities.supports(EnvironmentCapability.RESTORE)

        bridge_script = Path(binding.spec.bridge.command[-1])
        assert bridge_script.name == "bridge.js"
        assert bridge_script.is_file()
        assert Path(binding.spec.bridge.cwd) == bridge_script.parent
    finally:
        binding.close()
