from __future__ import annotations

import inspect
from pathlib import Path

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftEndpointSpec,
    MinecraftRconEndpoint,
    MinecraftServerSpec,
)
from noetrium_platform.capabilities.model.deployment.runtime.templates import (
    sglang_deployment,
    vllm_deployment,
)


def test_environment_templates_do_not_preselect_physical_ports() -> None:
    assert MinecraftEndpointSpec().port is None
    assert MinecraftRconEndpoint().port is None
    assert MinecraftServerSpec(
        jar_path="/opt/minecraft/server.jar",
        workdir="/var/lib/noetrium/minecraft",
        java_executable="/usr/bin/java",
    ).port is None


def test_model_serving_templates_require_resource_assigned_port() -> None:
    for factory in (sglang_deployment, vllm_deployment):
        port = inspect.signature(factory).parameters["port"]
        assert port.default is inspect.Parameter.empty


def test_mineflayer_bridge_has_no_default_physical_port_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (
        root
        / "noetrium_platform"
        / "capabilities"
        / "environment"
        / "minecraft"
        / "providers"
        / "assets"
        / "mineflayer_bridge"
        / "bridge.js"
    ).read_text(encoding="utf-8")
    assert "25565" not in source
    assert "Resource-assigned port" in source


def test_minecraft_capability_does_not_own_port_availability_probe() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (
        root
        / "noetrium_platform"
        / "capabilities"
        / "environment"
        / "minecraft"
        / "providers"
        / "server_files.py"
    ).read_text(encoding="utf-8")
    assert "ensure_port_available" not in source
    assert "socket.bind" not in source
