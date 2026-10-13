from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import unittest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftConsoleCommandResult,
    minecraft_scenario_from_mapping,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftServer,
)


def _scene() -> dict[str, object]:
    return {
        "scenario_id": "complex.minecraft.research",
        "generation": "experiment-01",
        "steps": [
            {
                "step_id": "place-evidence-block",
                "command": "setblock 12 68 4 minecraft:emerald_block",
                "expected_response_contains": "changed",
                "verification_command": "execute if block 12 68 4 minecraft:emerald_block",
            },
            {
                "step_id": "schedule-custom-datapack-event",
                "command": "schedule function custom:phase2 100t",
                "expected_response_contains": "scheduled",
            },
        ],
    }


class _Recorder:
    def __init__(self, root: Path):
        self.spec = SimpleNamespace(workdir=str(root), rcon_endpoint=object())
        self._rcon_password = "supplied-by-authority"
        self.commands = []

    def _rcon(self, command: str):
        self.commands.append(command)
        return "ok"


class _Console:
    commands = []

    def __init__(self, endpoint, *, secret_provider):
        assert endpoint is not None
        assert secret_provider() == "supplied-by-authority"

    def execute(self, command: str, *, timeout_s: float):
        assert timeout_s > 0
        self.commands.append(command)
        response = (
            "changed" if "execute if block" in command else
            "scheduled" if command.startswith("schedule") else "ok"
        )
        return MinecraftConsoleCommandResult(command, response, "rcon-proof:" + str(len(self.commands)))


def test_scenario_is_complete_unit_and_reaches_real_setup_executor(tmp_path):
    scenario = _scene()
    unit = minecraft_scenario_from_mapping(scenario)
    assert len(unit.members) == 2
    recorder = _Recorder(tmp_path)
    _Console.commands = []
    with patch(
        "noetrium_platform.composition.environment_capabilities.minecraft_local.MinecraftRconConsole",
        _Console,
    ):
        receipt = _DockerMinecraftServer.apply_task_setup(
            recorder, {"schema": "noetrium.minecraft-task-setup.v1", "scenario": scenario}
        )
    assert _Console.commands == [
        "setblock 12 68 4 minecraft:emerald_block",
        "execute if block 12 68 4 minecraft:emerald_block",
        "schedule function custom:phase2 100t",
    ]
    assert any(
        value.startswith("minecraft:scenario:")
        for value in receipt["evidence_refs"]
    )
    path = tmp_path / "scenario-evidence" / (unit.unit_digest + ".json")
    assert path.is_file()
    evidence = json.loads(path.read_text())
    assert evidence["receipt"]["scenario_digest"] == unit.unit_digest
    assert len(evidence["receipt"]["steps"]) == 2
    assert evidence["receipt"]["steps"][0]["verification_evidence_ref"] == "rcon-proof:2"


def test_failed_scenario_verification_fail_closes_instead_of_forging_receipt(tmp_path):
    class _RejectingConsole(_Console):
        def execute(self, command: str, *, timeout_s: float):
            return MinecraftConsoleCommandResult(command, "not found", "rcon-proof:error")
    recorder = _Recorder(tmp_path)
    with patch(
        "noetrium_platform.composition.environment_capabilities.minecraft_local.MinecraftRconConsole",
        _RejectingConsole,
    ):
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "SCENARIO_ASSERTION_FAILED"):
            _DockerMinecraftServer.apply_task_setup(
                recorder, {"schema": "noetrium.minecraft-task-setup.v1", "scenario": _scene()}
            )
    assert not (tmp_path / "scenario-evidence").exists()


def test_scenario_never_requires_agent_privilege(tmp_path):
    class _ConsoleWithoutPlayer(_Console):
        pass
    recorder = _Recorder(tmp_path)
    with patch(
        "noetrium_platform.composition.environment_capabilities.minecraft_local.MinecraftRconConsole",
        _ConsoleWithoutPlayer,
    ):
        _DockerMinecraftServer.apply_task_setup(recorder, {
            "schema": "noetrium.minecraft-task-setup.v1", "scenario": _scene()
        })
    assert all("op ResearchBot" not in cmd for cmd in recorder.commands)


def test_agent_actions_are_unit_declared_and_rejected_before_physical_prepare():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_environment_unit, minecraft_environment_allowed_action_types,
    )
    from noetrium_platform.capabilities.environment.minecraft.runtime.action_coordinator import (
        MinecraftActionCoordinator, MinecraftActionCoordinatorBindings,
    )
    from noetrium_platform.capabilities.environment.api import ActionRequest
    from noetrium_platform.foundation.kernel.kernel import ExecutionContext, EffectCertainty
    from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL

    unit = minecraft_environment_unit(
        "minecraft", "1.21.1",
        allowed_action_types=("observe_blocks", "recipe_lookup"),
    )
    allowed = minecraft_environment_allowed_action_types(unit)
    assert allowed == {"observe_blocks", "recipe_lookup"}
    with unittest.TestCase().assertRaisesRegex(ValueError, "subset"):
        minecraft_environment_unit("minecraft", "1.21.1",
            allowed_action_types=("observe_blocks", "invent_op_command"))

    class NoEffectBridge:
        prepared = False
        command_count = 0
        def prepare_action(self, *args, **kwargs):
            self.prepared = True
        def command(self, *args, **kwargs):
            self.command_count += 1
            raise AssertionError("forbidden physical effect reached provider")

    bridge = NoEffectBridge()
    coordinator = MinecraftActionCoordinator(
        session_id="scene-a", generation="a" * 64,
        provider_instance_id="minecraft:scene-a",
        command_timeout_s=45, bridge=bridge, allowed_action_types=allowed,
        bindings=MinecraftActionCoordinatorBindings(
            event_log=lambda *a, **k: None,
            failure_log=lambda *a, **k: None,
            ingest_events=lambda *a, **k: None,
            observation=lambda **k: None,
            state_payload=lambda: {},
            last_observation=lambda: None,
        ),
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")
    action = ActionRequest("forbidden-craft", "craft_item", {"item": "stick"}, context)
    handle = coordinator.prepare_action_recovery(action, context, UNBOUNDED_EXECUTION_CONTROL)
    result = coordinator.execute_prepared_action(action, handle, UNBOUNDED_EXECUTION_CONTROL)
    assert result.accepted is False
    assert result.effect.certainty is EffectCertainty.EFFECT_REJECTED
    assert result.diagnostics["contract_rejection_code"] == "ACTION_NOT_AUTHORIZED"
    assert bridge.prepared is False
    assert bridge.command_count == 0


def test_long_experiment_scene_is_not_artificially_capped_at_256_steps():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_scenario_step_unit, minecraft_scenario_unit,
    )
    steps = tuple(
        minecraft_scenario_step_unit(
            f"stage-{i}", "time query daytime", "daytime", timeout_s=180.0
        )
        for i in range(300)
    )
    scene = minecraft_scenario_unit("long-term-fieldwork", "v1", steps)
    assert len(scene.members) == 300
    assert scene.unit_digest


def test_dynamic_recipe_action_accepts_explicit_grid_and_never_trusts_vanilla_recipe():
    from noetrium_platform.capabilities.environment.minecraft.api import (
        minecraft_action_catalog, validate_minecraft_action,
    )
    names = {row.action_type: row for row in minecraft_action_catalog()}
    assert "craft_grid" in names
    assert names["craft_grid"].mutates_world is True
    grid = validate_minecraft_action("craft_grid", {
        "grid": "oak_planks,oak_planks,_,_,_,_,_,_,_",
        "station": "table",
    })
    assert grid["grid"] == "oak_planks,oak_planks,_,_,_,_,_,_,_"
    assert grid["station"] == "table"
    for invalid in ("oak_log", "_,_,_,_", "oak_log,_,_,_,_"):
        with unittest.TestCase().assertRaises(ValueError):
            validate_minecraft_action("craft_grid", {
                "grid": invalid, "station": "inventory",
            })
