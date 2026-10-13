"""The current Unit-backed MC scenario must fail closed with useful evidence."""
from __future__ import annotations

import unittest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftConsoleCommandResult,
    minecraft_scenario_from_mapping,
)
from noetrium_platform.capabilities.environment.minecraft.providers import (
    MinecraftScenarioProvisioningError,
    RconMinecraftScenarioProvisioner,
)


class ScenarioFeedbackTests(unittest.TestCase):
    def test_empty_verification_never_replays_physical_mutation(self):
        class Console:
            def __init__(self):
                self.commands = []

            def execute(self, command: str, *, timeout_s: float):
                self.commands.append(command)
                return MinecraftConsoleCommandResult(
                    command,
                    "" if command == "verify" else "mutation accepted",
                    "evidence:physical:" + str(len(self.commands)),
                )

        scenario = minecraft_scenario_from_mapping({
            "scenario_id": "test.scenario.join-race",
            "generation": "v1",
            "steps": [{
                "step_id": "grove",
                "command": "non-idempotent-physical-mutation",
                "verification_command": "verify",
                "expected_response_contains": "has the following entity data",
                "timeout_s": 1.0,
            }],
        })
        console = Console()
        with self.assertRaises(MinecraftScenarioProvisioningError) as caught:
            RconMinecraftScenarioProvisioner(console, scenario).apply()
        self.assertEqual(caught.exception.code, "SCENARIO_ASSERTION_FAILED")
        self.assertEqual(console.commands, ["non-idempotent-physical-mutation", "verify"])

    def test_permanently_empty_verification_fails_closed_without_polling(self):
        class Console:
            def execute(self, command: str, *, timeout_s: float):
                return MinecraftConsoleCommandResult(command, "", "evidence:empty")
        scenario = minecraft_scenario_from_mapping({
            "scenario_id": "test.scenario.absent",
            "generation": "v1",
            "steps": [{
                "step_id": "wood",
                "command": "fill",
                "verification_command": "verify",
                "expected_response_contains": "physical-confirmed",
                "timeout_s": 0.1,
            }],
        })
        with self.assertRaisesRegex(
            MinecraftScenarioProvisioningError,
            "expected response fragment",
        ):
            RconMinecraftScenarioProvisioner(Console(), scenario).apply()

    def test_mismatched_verification_reports_actual_response_without_accepting_it(self):
        class Console:
            def execute(self, command: str, *, timeout_s: float):
                return MinecraftConsoleCommandResult(
                    command, "spawnRadius = 10", "evidence:verification",
                )

        scenario = minecraft_scenario_from_mapping({
            "scenario_id": "test.scenario.feedback",
            "generation": "v1",
            "steps": [{
                "step_id": "spawn-radius",
                "command": "gamerule spawnRadius 0",
                "expected_response_contains": "spawnRadius = 0",
                "verification_command": "gamerule spawnRadius",
            }],
        })
        with self.assertRaises(MinecraftScenarioProvisioningError) as error:
            RconMinecraftScenarioProvisioner(Console(), scenario).apply()
        self.assertEqual(error.exception.code, "SCENARIO_ASSERTION_FAILED")
        self.assertIn("actual_response='spawnRadius = 10'", str(error.exception))
        self.assertIn("actual_response_sha256=", str(error.exception))
        self.assertIn("verification_evidence_ref=evidence:verification", str(error.exception))


if __name__ == "__main__":
    unittest.main()
