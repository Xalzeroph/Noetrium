from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import MinecraftConsoleCommandResult
from noetrium_platform.composition.environment_capabilities.minecraft_local import _DockerMinecraftServer


class _ConsoleServer:
    prepare_scientific_player_join = _DockerMinecraftServer.prepare_scientific_player_join

    def __init__(self, workdir, responses):
        self.spec = SimpleNamespace(
            workdir=str(workdir),
            rcon_endpoint=SimpleNamespace(host="127.0.0.1", port=25575),
        )
        self._rcon_password = "test-secret"
        self.responses = responses


def test_scientific_player_join_proves_zero_spawn_radius_before_agent_join(monkeypatch, tmp_path):
    commands = []

    def execute(endpoint, *, password, command, timeout_s):
        del endpoint, password, timeout_s
        commands.append(command)
        responses = {
            "gamerule spawnRadius 0": "Gamerule spawnRadius is now set to: 0",
            "gamerule spawnRadius": "spawnRadius = 0",
        }
        return MinecraftConsoleCommandResult(command, responses[command], f"evidence:{len(commands)}")

    class Console:
        def __init__(self, endpoint, *, secret_provider):
            del endpoint, secret_provider

        def execute(self, command, *, timeout_s):
            return execute(None, password="test-secret", command=command, timeout_s=timeout_s)

    import noetrium_platform.composition.environment_capabilities.minecraft_local as runtime
    monkeypatch.setattr(runtime, "MinecraftRconConsole", Console)

    server = _ConsoleServer(tmp_path, {})
    receipt = server.prepare_scientific_player_join()

    assert commands == ["gamerule spawnRadius 0", "gamerule spawnRadius"]
    assert receipt["schema"] == "noetrium.minecraft-scientific-player-join.v1"
    evidence = list((tmp_path / "scientific-session-evidence").glob("*.json"))
    assert len(evidence) == 1
    persisted = json.loads(evidence[0].read_text(encoding="utf-8"))
    assert persisted["scenario_digest"] == receipt["scenario_digest"]
    assert persisted["receipt"]["steps"][0]["step_id"] == "deterministic-spawn-radius"


def test_scientific_player_join_fails_closed_when_zero_radius_is_not_proven(monkeypatch, tmp_path):
    def execute(endpoint, *, password, command, timeout_s):
        del endpoint, password, timeout_s
        response = (
            "Gamerule updated" if command == "gamerule spawnRadius 0"
            else "spawnRadius = 10"
        )
        return MinecraftConsoleCommandResult(command, response, "evidence:bad")

    class Console:
        def __init__(self, endpoint, *, secret_provider):
            del endpoint, secret_provider

        def execute(self, command, *, timeout_s):
            return execute(None, password="test-secret", command=command, timeout_s=timeout_s)

    import noetrium_platform.composition.environment_capabilities.minecraft_local as runtime
    monkeypatch.setattr(runtime, "MinecraftRconConsole", Console)

    server = _ConsoleServer(tmp_path, {})
    with pytest.raises(Exception, match="spawnRadius"):
        server.prepare_scientific_player_join()
    assert not (tmp_path / "scientific-session-evidence").exists()
