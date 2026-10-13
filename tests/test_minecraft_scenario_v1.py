from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_SCENARIO_ASSERTION_MAX_LENGTH,
    MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH,
    MinecraftConsoleCommandResult,
    minecraft_scenario_from_mapping,
    minecraft_scenario_step_id,
    minecraft_scenario_step_unit,
    minecraft_scenario_steps,
    minecraft_scenario_unit,
)
from noetrium_platform.capabilities.environment.minecraft.composition import LocalMinecraftExperimentHostFactory
from noetrium_platform.capabilities.environment.minecraft.providers import (
    MinecraftScenarioProvisioningError,
    RconMinecraftScenarioProvisioner,
)

from test_minecraft_experiment_host_v1 import _inputs


class RecordingConsole:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.commands: list[tuple[str, float]] = []

    def execute(self, command: str, *, timeout_s: float) -> MinecraftConsoleCommandResult:
        self.commands.append((command, timeout_s))
        return MinecraftConsoleCommandResult(
            command,
            self.responses[command],
            f"evidence:{len(self.commands)}",
        )


def _scenario():
    return minecraft_scenario_unit(
        "minecraft.test.fixture",
        "v1",
        (
            minecraft_scenario_step_unit(
                "spawn-radius",
                "gamerule spawnRadius 0",
                "spawnRadius = 0",
                verification_command="gamerule spawnRadius",
            ),
            minecraft_scenario_step_unit(
                "platform",
                "fill -1 79 -1 1 79 1 stone",
                "test passed",
                verification_command="execute if block 0 79 0 stone",
            ),
        ),
    )


def test_scenario_command_limits_are_public_environment_contract() -> None:
    assert MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH == 4096
    assert MINECRAFT_SCENARIO_ASSERTION_MAX_LENGTH == 1024
    minecraft_scenario_step_unit(
        "boundary",
        "x" * MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH,
        "y" * MINECRAFT_SCENARIO_ASSERTION_MAX_LENGTH,
        verification_command="z" * MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH,
    )
    with pytest.raises(ValueError, match="command or assertion is too long"):
        minecraft_scenario_step_unit(
            "command-too-long",
            "x" * (MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH + 1),
            "ok",
        )
    with pytest.raises(ValueError, match="verification_command is too long"):
        minecraft_scenario_step_unit(
            "verification-too-long",
            "ok",
            "ok",
            verification_command="z" * (MINECRAFT_SCENARIO_COMMAND_MAX_LENGTH + 1),
        )


def test_scenario_manifest_builds_typed_immutable_spec() -> None:
    scenario = minecraft_scenario_from_mapping(
        {
            "scenario_id": "minecraft.test.fixture",
            "generation": "v1",
            "steps": [
                {
                    "step_id": "daylight",
                    "command": "gamerule doDaylightCycle false",
                    "verification_command": "gamerule doDaylightCycle",
                    "expected_response_contains": "false",
                }
            ],
        }
    )

    assert minecraft_scenario_step_id(minecraft_scenario_steps(scenario)[0]) == "daylight"
    assert len(scenario.unit_digest) == 64


def test_rcon_scenario_provisioner_records_exact_mutation_and_assertion_evidence() -> None:
    console = RecordingConsole(
        {
            "gamerule spawnRadius 0": "Gamerule spawnRadius is now set to: 0",
            "gamerule spawnRadius": "spawnRadius = 0",
            "fill -1 79 -1 1 79 1 stone": "Successfully filled 9 block(s)",
            "execute if block 0 79 0 stone": "Test passed",
        }
    )

    receipt = RconMinecraftScenarioProvisioner(console, _scenario()).apply()

    assert receipt.scenario_digest == _scenario().unit_digest
    assert [step.step_id for step in receipt.steps] == ["spawn-radius", "platform"]
    assert [command for command, _ in console.commands] == [
        "gamerule spawnRadius 0",
        "gamerule spawnRadius",
        "fill -1 79 -1 1 79 1 stone",
        "execute if block 0 79 0 stone",
    ]
    assert all(len(step.verification_response_sha256) == 64 for step in receipt.steps)


def test_rcon_scenario_provisioner_fails_closed_on_unproven_assertion() -> None:
    console = RecordingConsole(
        {
            "gamerule spawnRadius 0": "Gamerule updated",
            "gamerule spawnRadius": "spawnRadius = 10",
        }
    )
    scenario = minecraft_scenario_unit(
        "minecraft.test.bad",
        "v1",
        (
            minecraft_scenario_step_unit(
                "spawn-radius",
                "gamerule spawnRadius 0",
                "spawnRadius = 0",
                verification_command="gamerule spawnRadius",
            ),
        ),
    )

    with pytest.raises(MinecraftScenarioProvisioningError) as caught:
        RconMinecraftScenarioProvisioner(console, scenario).apply()

    assert caught.value.code == "SCENARIO_ASSERTION_FAILED"


def test_experiment_host_applies_source_scenario_after_readiness(tmp_path) -> None:
    server, inputs = _inputs(tmp_path)
    receipt = SimpleNamespace(scenario_digest="d" * 64)

    class Scenario:
        def __init__(self) -> None:
            self.applied = False

        def apply(self):
            assert server.started is True
            self.applied = True
            return receipt

    scenario = Scenario()
    host = LocalMinecraftExperimentHostFactory(
        replace(inputs, source_scenario=scenario)
    ).open()

    host.start_source()

    assert scenario.applied is True
    assert host.source_scenario_receipt is receipt
    host.stop_source()


def test_experiment_host_stops_source_when_scenario_provisioning_fails(tmp_path) -> None:
    server, inputs = _inputs(tmp_path)

    class Scenario:
        def apply(self):
            raise RuntimeError("scenario failed")

    host = LocalMinecraftExperimentHostFactory(
        replace(inputs, source_scenario=Scenario())
    ).open()

    with pytest.raises(RuntimeError, match="scenario failed"):
        host.start_source()

    assert server.stopped is True
    assert host.stop_source() is None
