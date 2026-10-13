from __future__ import annotations

import unittest

from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftServer,
)


class _ServerRecorder:
    def __init__(
        self,
        locate: str | list[str],
        *,
        exact_passes: bool = True,
        surface_passes: bool | list[bool] = True,
        post_surface_passes: bool = True,
    ):
        self.locates = [locate] if isinstance(locate, str) else list(locate)
        self.surface_passes = (
            [surface_passes]
            if isinstance(surface_passes, bool)
            else list(surface_passes)
        )
        self.exact_passes = exact_passes
        self.post_surface_passes = post_surface_passes
        self.commands: list[str] = []
        self._surface_index = 0
        self._locate_index = 0
        self._surface_teleported = False

    def _rcon(self, command: str) -> str:
        self.commands.append(command)
        if "locate biome" in command:
            index = min(self._locate_index, len(self.locates) - 1)
            self._locate_index += 1
            return self.locates[index]
        if "positioned over ocean_floor if biome" in command:
            index = min(self._surface_index, len(self.surface_passes) - 1)
            self._surface_index += 1
            return "Test passed" if self.surface_passes[index] else "Test failed"
        if "positioned over ocean_floor run tp ResearchBot" in command:
            self._surface_teleported = True
            return "Teleported ResearchBot"
        if "if biome ~ ~ ~" in command:
            if self._surface_teleported:
                return "Test passed" if self.post_surface_passes else "Test failed"
            return "Test passed" if self.exact_passes else "Test failed"
        return "ok"


class MinecraftBiomeSpawnTests(unittest.TestCase):
    def test_overworld_stages_remote_locate_position_before_surface_heightmap(self) -> None:
        recorder = _ServerRecorder(
            "The nearest minecraft:plains is at [608, 63, -639]"
        )
        receipt = _DockerMinecraftServer.apply_task_setup(recorder, {
            "schema": "noetrium.minecraft-task-setup.v1",
            "dimension": "overworld",
            "biome": "plains",
        })
        self.assertEqual(
            receipt["schema"], "noetrium.minecraft-task-setup-mutation-receipt.v1"
        )
        stage = "execute in minecraft:overworld run tp ResearchBot 608 63 -639"
        surface = (
            "execute at ResearchBot positioned over ocean_floor "
            "if biome ~ ~ ~ minecraft:plains"
        )
        final = (
            "execute at ResearchBot positioned over ocean_floor "
            "run tp ResearchBot ~ ~1 ~"
        )
        self.assertLess(recorder.commands.index(stage), recorder.commands.index(surface))
        self.assertLess(recorder.commands.index(surface), recorder.commands.index(final))
        self.assertIn("gamemode spectator ResearchBot", recorder.commands)
        self.assertIn("gamemode survival ResearchBot", recorder.commands)

    def test_overworld_relocates_from_surface_when_locate_cell_is_not_surface_biome(self) -> None:
        recorder = _ServerRecorder(
            [
                "The nearest minecraft:taiga is at [608, 63, -639]",
                "The nearest minecraft:taiga is at [640, 72, -672]",
            ],
            surface_passes=[False, True],
        )
        _DockerMinecraftServer.apply_task_setup(recorder, {
            "schema": "noetrium.minecraft-task-setup.v1",
            "dimension": "overworld",
            "biome": "taiga",
        })
        stages = [
            command for command in recorder.commands
            if command.startswith("execute in minecraft:overworld run tp ResearchBot")
        ]
        self.assertEqual(stages[:2], [
            "execute in minecraft:overworld run tp ResearchBot 608 63 -639",
            "execute in minecraft:overworld run tp ResearchBot 640 72 -672",
        ])
        self.assertIn(
            "execute at ResearchBot positioned ~ 319 ~ run locate biome minecraft:taiga",
            recorder.commands,
        )

    def test_overworld_exact_mismatch_repeated_locate_uses_surface_frontier(self) -> None:
        recorder = _ServerRecorder(
            "The nearest minecraft:swamp is at [608, 63, -639]",
            exact_passes=False,
            surface_passes=[False, True],
        )
        _DockerMinecraftServer.apply_task_setup(recorder, {
            "schema": "noetrium.minecraft-task-setup.v1",
            "dimension": "overworld",
            "biome": "swamp",
        })
        self.assertGreaterEqual(sum(
            "locate biome minecraft:swamp" in command
            for command in recorder.commands
        ), 2)
        self.assertIn(
            "execute in minecraft:overworld run tp ResearchBot 624 319 -639",
            recorder.commands,
        )
        self.assertIn("gamemode survival ResearchBot", recorder.commands)

    def test_overworld_searches_surface_columns_when_3d_locate_repeats(self) -> None:
        recorder = _ServerRecorder(
            "The nearest minecraft:swamp is at [608, 63, -639]",
            surface_passes=[False, False, True],
        )
        _DockerMinecraftServer.apply_task_setup(recorder, {
            "schema": "noetrium.minecraft-task-setup.v1",
            "dimension": "overworld",
            "biome": "swamp",
        })
        self.assertIn(
            "execute at ResearchBot positioned ~ 319 ~ run locate biome minecraft:swamp",
            recorder.commands,
        )
        self.assertIn(
            "execute in minecraft:overworld run tp ResearchBot 592 319 -639",
            recorder.commands,
        )
        self.assertIn("gamemode survival ResearchBot", recorder.commands)


    def test_overworld_fails_closed_when_surface_projection_cycles(self) -> None:
        recorder = _ServerRecorder(
            "The nearest minecraft:swamp is at [608, 63, -639]",
            surface_passes=False,
        )
        with self.assertRaisesRegex(RuntimeError, "surface projection did not converge"):
            _DockerMinecraftServer.apply_task_setup(recorder, {
                "schema": "noetrium.minecraft-task-setup.v1",
                "dimension": "overworld",
                "biome": "swamp",
            })

    def test_control_proof_rejects_server_side_biome_mismatch_before_physical_wait(self) -> None:
        class ControlRecorder:
            def _rcon(self, command: str) -> str:
                if command.startswith("gamerule "):
                    return "Gamerule is currently set to: true"
                if "if biome ~ ~ ~ minecraft:taiga" in command:
                    return "Test failed"
                return "ok"

        with self.assertRaisesRegex(RuntimeError, "server control postconditions failed"):
            _DockerMinecraftServer.verify_task_setup_control_state(ControlRecorder(), {
                "schema": "noetrium.minecraft-task-setup.v1",
                "dimension": "overworld",
                "biome": "taiga",
                "always_night": False,
                "allow_mob_spawn": True,
            })

    def test_non_overworld_preserves_located_vertical_coordinate(self) -> None:
        recorder = _ServerRecorder(
            "The nearest minecraft:crimson_forest is at [5, 40, -300]"
        )
        _DockerMinecraftServer.apply_task_setup(recorder, {
            "schema": "noetrium.minecraft-task-setup.v1",
            "dimension": "the_nether",
            "biome": "crimson_forest",
        })
        self.assertIn(
            "execute in minecraft:the_nether run tp ResearchBot 5 40 -300",
            recorder.commands,
        )
        self.assertIn(
            "execute in minecraft:the_nether run tp ResearchBot 5 41 -300",
            recorder.commands,
        )
        self.assertFalse(any(
            "positioned over ocean_floor" in command
            for command in recorder.commands
        ))


if __name__ == "__main__":
    unittest.main()
