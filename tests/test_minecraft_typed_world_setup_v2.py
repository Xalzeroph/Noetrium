from __future__ import annotations

import json
import pytest

from types import SimpleNamespace
from unittest.mock import patch

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftConsoleCommandResult,
    minecraft_effect_world_op,
    minecraft_fill_world_op,
    minecraft_set_block_world_op,
    minecraft_summon_world_op,
    normalize_minecraft_world_ops,
)
from noetrium_platform.capabilities.environment.minecraft.providers.task_setup import (
    RconMinecraftWorldSetupProvisioner,
    minecraft_world_op_command,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    _DockerMinecraftServer,
    _minecraft_inventory_slot_destination,
)


class _Console:
    commands: list[str] = []
    def __init__(self, endpoint=None, *, secret_provider=None):
        if secret_provider is not None:
            assert secret_provider()
    def execute(self, command: str, *, timeout_s: float):
        assert timeout_s > 0
        self.commands.append(command)
        return MinecraftConsoleCommandResult(
            command, "accepted", f"proof:{len(self.commands)}"
        )


class _Recorder:
    def __init__(self, root):
        self.spec = SimpleNamespace(workdir=str(root), rcon_endpoint=object())
        self._rcon_password = "authority-secret"
        self.commands: list[str] = []
    def _rcon(self, command: str):
        self.commands.append(command)
        return "ok"
    def _materialize_datapack(self, raw):
        raise AssertionError("not used")


def _ops():
    return (
        minecraft_fill_world_op("logs", (1, 0, 1), (5, 10, 5), "oak_log"),
        minecraft_set_block_world_op("table", (2, 0, 0), "crafting_table"),
        minecraft_summon_world_op("zombie", "zombie", (3, 0, 0)),
        minecraft_effect_world_op(
            "blind", "blindness", duration_seconds=300, amplifier=1
        ),
    )


def test_typed_world_ops_compile_to_bounded_provider_commands_without_verifier_programs():
    ops = normalize_minecraft_world_ops(_ops())
    commands = tuple(minecraft_world_op_command(row) for row in ops)
    assert commands[0] == (
        "execute at ResearchBot run fill ~1 ~ ~1 ~5 ~10 ~5 minecraft:oak_log"
    )
    assert commands[1].startswith("execute at ResearchBot run setblock")
    assert commands[2].startswith("execute at ResearchBot run summon minecraft:zombie")
    assert commands[3] == "effect give ResearchBot minecraft:blindness 300 1 true"
    assert all(" if block " not in command for command in commands)
    assert max(map(len, commands)) < 256


def test_typed_world_ops_produce_one_authoritative_receipt_per_semantic_operation():
    _Console.commands = []
    receipt = RconMinecraftWorldSetupProvisioner(_Console(), _ops()).apply()
    assert len(receipt.operations) == 4
    assert len({row.operation_id for row in receipt.operations}) == 4
    assert tuple(_Console.commands) == tuple(
        minecraft_world_op_command(row) for row in normalize_minecraft_world_ops(_ops())
    )


def test_typed_world_ops_do_not_replay_mutation_on_empty_rcon_response():
    class EmptyResponseConsole:
        def __init__(self):
            self.commands = []
        def execute(self, command: str, *, timeout_s: float):
            assert timeout_s > 0
            self.commands.append(command)
            return MinecraftConsoleCommandResult(command, "", f"proof:{len(self.commands)}")

    console = EmptyResponseConsole()
    operation = (minecraft_summon_world_op("zombie", "zombie", (3, 0, 0)),)
    receipt = RconMinecraftWorldSetupProvisioner(console, operation).apply()
    assert len(receipt.operations) == 1
    assert console.commands == [minecraft_world_op_command(normalize_minecraft_world_ops(operation)[0])]


def test_minecraft_player_inventory_slot_abi_matches_vanilla_indices():
    assert _minecraft_inventory_slot_destination("0") == "hotbar.0"
    assert _minecraft_inventory_slot_destination("8") == "hotbar.8"
    assert _minecraft_inventory_slot_destination("9") == "inventory.0"
    assert _minecraft_inventory_slot_destination("35") == "inventory.26"
    assert _minecraft_inventory_slot_destination("36") == "armor.feet"
    assert _minecraft_inventory_slot_destination("39") == "armor.head"
    assert _minecraft_inventory_slot_destination("40") == "weapon.offhand"
    assert _minecraft_inventory_slot_destination("mainhand") == "weapon.mainhand"
    with pytest.raises(ValueError, match=r"\[0, 40\]"):
        _minecraft_inventory_slot_destination("41")
    with pytest.raises(ValueError, match="unsupported"):
        _minecraft_inventory_slot_destination("mystery")


def test_minedojo_numeric_inventory_slots_preserve_official_physical_slots(tmp_path):
    recorder = _Recorder(tmp_path)
    setup = {
        "schema": "noetrium.minecraft-task-setup.v2",
        "initial_inventory": (
            {"item": "diamond_axe", "count": 1, "slot": "1"},
            {"item": "diamond_hoe", "count": 1, "slot": "2"},
            {"item": "diamond_sword", "count": 1, "slot": "3"},
            {"item": "diamond_shovel", "count": 1, "slot": "4"},
            {"item": "diamond_pickaxe", "count": 1, "slot": "mainhand"},
        ),
        "initial_mobs": (),
        "world_ops": (),
    }
    receipt = _DockerMinecraftServer.apply_task_setup(recorder, setup)
    commands = [row["command"] for row in receipt["rcon_commands"]]
    expected = [
        "item replace entity ResearchBot hotbar.1 with minecraft:diamond_axe 1",
        "item replace entity ResearchBot hotbar.2 with minecraft:diamond_hoe 1",
        "item replace entity ResearchBot hotbar.3 with minecraft:diamond_sword 1",
        "item replace entity ResearchBot hotbar.4 with minecraft:diamond_shovel 1",
        "item replace entity ResearchBot weapon.mainhand with minecraft:diamond_pickaxe 1",
    ]
    for command in expected:
        assert commands.count(command) == 1
    assert not any(
        command.startswith("give ResearchBot minecraft:diamond_")
        for command in commands
    )
    # Base setup commands plus five inventory mutations: slot fidelity changes
    # command targets, never setup round-trip count.
    assert len(commands) == 9


def test_task_setup_receipt_binds_initial_inventory_command_to_server_response(tmp_path):
    class ReceiptRecorder(_Recorder):
        def _rcon(self, command: str):
            self.commands.append(command)
            if command.startswith("give ResearchBot minecraft:diamond_axe"):
                return "Gave 1 [Diamond Axe] to ResearchBot"
            return "ok"

    recorder = ReceiptRecorder(tmp_path)
    receipt = _DockerMinecraftServer.apply_task_setup(
        recorder,
        {
            "schema": "noetrium.minecraft-task-setup.v2",
            "initial_inventory": ({"item": "diamond_axe", "count": 1},),
            "initial_mobs": (),
            "world_ops": (),
        },
    )
    rows = list(receipt["rcon_commands"])
    give = [row for row in rows if row["command"] == "give ResearchBot minecraft:diamond_axe 1"]
    assert len(give) == 1
    assert give[0]["response"] == "Gave 1 [Diamond Axe] to ResearchBot"
    assert give[0]["elapsed_ns"] >= 0


def test_task_setup_physical_rejection_persists_mutation_and_control_evidence(tmp_path):
    class EvidenceRecorder(_Recorder):
        apply_task_setup = _DockerMinecraftServer.apply_task_setup
        verify_task_setup_control_state = _DockerMinecraftServer.verify_task_setup_control_state
        _persist_task_setup_verification = _DockerMinecraftServer._persist_task_setup_verification
        apply_and_verify_task_setup = _DockerMinecraftServer.apply_and_verify_task_setup

        def _rcon(self, command: str):
            self.commands.append(command)
            if command == "gamerule doDaylightCycle":
                return "Gamerule doDaylightCycle is currently set to: true"
            if command == "gamerule doMobSpawning":
                return "Gamerule doMobSpawning is currently set to: true"
            if command.startswith("give ResearchBot minecraft:diamond_axe"):
                return "Gave 1 [Diamond Axe] to ResearchBot"
            return "ok"

    class RejectingSession:
        def wait_for_task_setup_anchor(self):
            return {"verified": True, "checks": (), "failures": ()}
        def verify_task_setup(self, setup, *, control_proof=None):
            del setup, control_proof
            raise RuntimeError("initial_inventory diamond_axe expected=1 observed=0")

    setup = {
        "schema": "noetrium.minecraft-task-setup.v2",
        "initial_inventory": ({"item": "diamond_axe", "count": 1},),
        "initial_mobs": (),
        "world_ops": (),
    }
    recorder = EvidenceRecorder(tmp_path)
    with pytest.raises(RuntimeError, match="diamond_axe"):
        recorder.apply_and_verify_task_setup(RejectingSession(), setup)

    files = tuple((tmp_path / "task-setup-verification").glob("*.json"))
    assert len(files) == 1
    evidence = json.loads(files[0].read_text())
    assert evidence["schema"] == "noetrium.minecraft-task-setup-verification.v2"
    assert evidence["status"] == "rejected"
    assert evidence["physical_proof"] is None
    assert evidence["control_proof"]["verified"] is True
    commands = evidence["mutation_receipt"]["rcon_commands"]
    give = [row for row in commands if row["command"] == "give ResearchBot minecraft:diamond_axe 1"]
    assert len(give) == 1
    assert "Gave 1" in give[0]["response"]
    assert "client_convergence_proof" not in evidence
    assert evidence["authority_rebase"] is False
    assert evidence["failure"] == {
        "phase": "physical.verify",
        "type": "RuntimeError",
        "message": "initial_inventory diamond_axe expected=1 observed=0",
    }
    # Mutation commands are issued once; control-state reads are queries only.
    assert recorder.commands.count("give ResearchBot minecraft:diamond_axe 1") == 1



def test_survival_anchor_precedes_agent_relative_mob_provisioning(tmp_path):
    class AnchorRecorder(_Recorder):
        apply_task_setup = _DockerMinecraftServer.apply_task_setup
        verify_task_setup_control_state = _DockerMinecraftServer.verify_task_setup_control_state
        _persist_task_setup_verification = _DockerMinecraftServer._persist_task_setup_verification
        apply_and_verify_task_setup = _DockerMinecraftServer.apply_and_verify_task_setup

        def _rcon(self, command: str):
            self.commands.append(command)
            if command.startswith("gamerule "):
                return "Gamerule is currently set to: true"
            return "ok"

    recorder = AnchorRecorder(tmp_path)

    class Session:
        def wait_for_task_setup_anchor(self):
            assert "gamemode survival ResearchBot" in recorder.commands
            assert not any("summon minecraft:wolf" in command for command in recorder.commands)
            return {
                "schema": "noetrium.minecraft-task-setup-physical-proof.v1",
                "verified": True,
                "checks": ({"kind": "physical_anchor", "ok": True},),
                "failures": (),
            }

        def verify_task_setup(self, setup, *, control_proof=None):
            assert control_proof is not None and control_proof["verified"] is True
            assert any("summon minecraft:wolf" in command for command in recorder.commands)
            return {"verified": True, "checks": (), "failures": ()}

    record = recorder.apply_and_verify_task_setup(Session(), {
        "schema": "noetrium.minecraft-task-setup.v2",
        "dimension": "overworld",
        "initial_inventory": (),
        "initial_mobs": ({"entity": "wolf", "count": 1},),
        "world_ops": (),
        "allow_mob_spawn": True,
        "always_night": False,
    })
    commands = recorder.commands
    survival = commands.index("gamemode survival ResearchBot")
    summon = next(i for i, command in enumerate(commands) if "summon minecraft:wolf" in command)
    assert survival < summon
    assert record["mutation_receipt"]["survival_anchor_proof"]["verified"] is True


def test_biome_setup_gates_client_biome_on_server_authority_cut(tmp_path):
    class HandshakeRecorder(_Recorder):
        apply_task_setup = _DockerMinecraftServer.apply_task_setup
        verify_task_setup_control_state = _DockerMinecraftServer.verify_task_setup_control_state
        _persist_task_setup_verification = _DockerMinecraftServer._persist_task_setup_verification
        apply_and_verify_task_setup = _DockerMinecraftServer.apply_and_verify_task_setup

        def _rcon(self, command: str):
            self.commands.append(command)
            if "locate biome minecraft:plains" in command:
                return "The nearest minecraft:plains is at [12, 64, -32]"
            if "run data get entity ResearchBot Pos" in command:
                return "ResearchBot has the following entity data: [12.25d, 65.0d, -31.75d]"
            if "if biome ~ ~ ~ minecraft:plains" in command:
                return "Test passed"
            if command.startswith("gamerule "):
                return "Gamerule is currently set to: true"
            return "ok"

    recorder = HandshakeRecorder(tmp_path)

    class PhysicalSession:
        def __init__(self):
            self.calls = []
        def wait_for_task_setup_anchor(self):
            return {"verified": True, "checks": (), "failures": ()}

        def verify_task_setup(self, setup, *, control_proof=None):
            del setup
            self.calls.append(control_proof)
            # Final survival activation is part of the state being proved, and
            # biome observation is never accepted without a server position cut.
            assert "gamemode survival ResearchBot" in recorder.commands
            assert control_proof is not None
            assert control_proof["verified"] is True
            return {
                "schema": "noetrium.minecraft-task-setup-physical-proof.v1",
                "verified": True, "checks": (), "failures": (),
            }

    session = PhysicalSession()
    record = recorder.apply_and_verify_task_setup(session, {
        "schema": "noetrium.minecraft-task-setup.v2",
        "dimension": "overworld",
        "biome": "plains",
        "initial_inventory": (),
        "initial_mobs": (),
        "world_ops": (),
        "allow_mob_spawn": True,
        "always_night": False,
    })
    assert record["status"] == "verified"
    assert record["mutation_receipt"]["survival_anchor_proof"]["verified"] is True
    assert len(session.calls) == 1
    assert session.calls[0]["verified"] is True
    assert len(record["control_proof_history"]) == 1
    assert record["authority_rebase"] is False
    assert recorder.commands.count("gamemode survival ResearchBot") == 1


def test_biome_setup_rebases_only_to_fresh_server_proven_client_voxel(tmp_path):
    from noetrium_platform.capabilities.environment.minecraft.runtime.errors import (
        MinecraftEnvironmentFailure,
    )

    class MovingRecorder(_Recorder):
        apply_task_setup = _DockerMinecraftServer.apply_task_setup
        verify_task_setup_control_state = _DockerMinecraftServer.verify_task_setup_control_state
        _persist_task_setup_verification = _DockerMinecraftServer._persist_task_setup_verification
        apply_and_verify_task_setup = _DockerMinecraftServer.apply_and_verify_task_setup

        def __init__(self, path):
            super().__init__(path)
            self.position_reads = 0

        def _rcon(self, command: str):
            self.commands.append(command)
            if "locate biome minecraft:plains" in command:
                return "The nearest minecraft:plains is at [12, 64, -32]"
            if "run data get entity ResearchBot Pos" in command:
                self.position_reads += 1
                y = 65.0 if self.position_reads == 1 else 64.0
                return f"ResearchBot has the following entity data: [12.25d, {y}d, -31.75d]"
            if "if biome ~ ~ ~ minecraft:plains" in command:
                return "Test passed"
            if command.startswith("gamerule "):
                return "Gamerule is currently set to: true"
            return "ok"

    recorder = MovingRecorder(tmp_path)

    class PhysicalSession:
        def __init__(self):
            self.calls = []
        def wait_for_task_setup_anchor(self):
            return {"verified": True, "checks": (), "failures": ()}

        def verify_task_setup(self, setup, *, control_proof=None):
            del setup
            self.calls.append(control_proof)
            assert control_proof is not None
            authority = next(
                row for row in control_proof["checks"]
                if row["kind"] == "biome_authority"
            )["position"]
            if int(authority["y"]) == 65:
                raise MinecraftEnvironmentFailure(
                    "setup.verify", "authority position advanced after server cut",
                    cause_code="MINECRAFT_SETUP_POSTCONDITION_FAILED",
                    diagnostics={
                        "failures": ({
                            "kind": "authority_position",
                            "expected_voxel": {"x": 12, "y": 65, "z": -32},
                            "observed_voxel": {"x": 12, "y": 64, "z": -32},
                        },),
                    },
                )
            return {"verified": True, "checks": (), "failures": ()}

    session = PhysicalSession()
    record = recorder.apply_and_verify_task_setup(session, {
        "schema": "noetrium.minecraft-task-setup.v2",
        "dimension": "overworld", "biome": "plains",
        "initial_inventory": (), "initial_mobs": (), "world_ops": (),
        "allow_mob_spawn": True, "always_night": False,
    })
    assert record["status"] == "verified"
    assert record["authority_rebase"] is True
    assert len(record["control_proof_history"]) == 2
    assert len(session.calls) == 2
    final_position = next(
        row for row in record["control_proof"]["checks"]
        if row["kind"] == "biome_authority"
    )["position"]
    assert final_position["y"] == 64.0


def test_biome_setup_rebase_fails_closed_when_server_does_not_confirm_client_voxel(tmp_path):
    from noetrium_platform.capabilities.environment.minecraft.runtime.errors import (
        MinecraftEnvironmentFailure,
    )

    class DivergedRecorder(_Recorder):
        apply_task_setup = _DockerMinecraftServer.apply_task_setup
        verify_task_setup_control_state = _DockerMinecraftServer.verify_task_setup_control_state
        _persist_task_setup_verification = _DockerMinecraftServer._persist_task_setup_verification
        apply_and_verify_task_setup = _DockerMinecraftServer.apply_and_verify_task_setup

        def _rcon(self, command: str):
            self.commands.append(command)
            if "locate biome minecraft:plains" in command:
                return "The nearest minecraft:plains is at [12, 64, -32]"
            if "run data get entity ResearchBot Pos" in command:
                return "ResearchBot has the following entity data: [12.25d, 65.0d, -31.75d]"
            if "if biome ~ ~ ~ minecraft:plains" in command:
                return "Test passed"
            if command.startswith("gamerule "):
                return "Gamerule is currently set to: true"
            return "ok"

    recorder = DivergedRecorder(tmp_path)

    class PhysicalSession:
        def __init__(self):
            self.calls = 0
        def wait_for_task_setup_anchor(self):
            return {"verified": True, "checks": (), "failures": ()}

        def verify_task_setup(self, setup, *, control_proof=None):
            del setup
            self.calls += 1
            assert control_proof is not None
            raise MinecraftEnvironmentFailure(
                "setup.verify", "client and server remain on distinct voxels",
                cause_code="MINECRAFT_SETUP_POSTCONDITION_FAILED",
                diagnostics={
                    "failures": ({
                        "kind": "authority_position",
                        "expected_voxel": {"x": 12, "y": 65, "z": -32},
                        "observed_voxel": {"x": 12, "y": 64, "z": -32},
                    },),
                },
            )

    session = PhysicalSession()
    with pytest.raises(MinecraftEnvironmentFailure, match="distinct voxels"):
        recorder.apply_and_verify_task_setup(session, {
            "schema": "noetrium.minecraft-task-setup.v2",
            "dimension": "overworld", "biome": "plains",
            "initial_inventory": (), "initial_mobs": (), "world_ops": (),
            "allow_mob_spawn": True, "always_night": False,
        })
    # One strict proof rejects the stale cut. The server disagrees with the
    # rejected client voxel, so no self-authorizing second client proof occurs.
    assert session.calls == 1
    files = tuple((tmp_path / "task-setup-verification").glob("*.json"))
    assert len(files) == 1
    evidence = json.loads(files[0].read_text())
    assert evidence["status"] == "rejected"
    assert evidence["authority_rebase"] is False
    assert len(evidence["control_proof_history"]) == 1


def test_task_setup_v2_reaches_typed_world_executor_and_persists_receipt(tmp_path):
    recorder = _Recorder(tmp_path)
    _Console.commands = []
    with patch(
        "noetrium_platform.composition.environment_capabilities.minecraft_local.MinecraftRconConsole",
        _Console,
    ):
        receipt = _DockerMinecraftServer.apply_task_setup(
            recorder,
            {
                "schema": "noetrium.minecraft-task-setup.v2",
                "initial_inventory": (),
                "initial_mobs": (),
                "world_ops": _ops(),
            },
        )
    assert len(_Console.commands) == 4
    assert receipt["schema"] == "noetrium.minecraft-task-setup-mutation-receipt.v1"
    assert any(
        row.startswith("minecraft:typed-world-setup:")
        for row in receipt["evidence_refs"]
    )
    files = tuple((tmp_path / "world-setup-evidence").glob("*.json"))
    assert len(files) == 1


def _bare_session(acks):
    from noetrium_platform.capabilities.environment.minecraft.runtime.session import (
        MinecraftEnvironmentSession,
    )

    class _Bridge:
        def __init__(self, values):
            self.values = list(values)
            self.calls = []
        def command(self, command, payload, *, timeout_s, control=None):
            assert command == "setup_verify_wait"
            assert timeout_s > 0
            self.calls.append((command, payload))
            value = self.values.pop(0) if self.values else {"verified": False, "failures": ()}
            return SimpleNamespace(diagnostics={"ack": {
                "type": "ack", "protocol_version": "minecraft-jsonl-v1",
                "cmd": "setup_verify_wait", "request_id": "proof", **value,
            }})

    session = object.__new__(MinecraftEnvironmentSession)
    session._closed = False
    session._restore_faulted = False
    session._projection_faulted = False
    session._bridge = _Bridge(acks)
    session._event_log = lambda *args, **kwargs: None
    return session


def test_session_survival_anchor_wait_uses_provider_private_event_projection():
    session = _bare_session([{
        "schema": "noetrium.minecraft-task-setup-physical-proof.v1",
        "verified": True, "check_count": 1,
        "checks": ({"kind": "physical_anchor", "ok": True},), "failures": (),
    }])
    proof = session.wait_for_task_setup_anchor()
    assert proof["verified"] is True
    command, payload = session._bridge.calls[0]
    assert command == "setup_verify_wait"
    assert payload["setup"] == {"require_physical_anchor": True}
    assert payload["timeout_ms"] == 8000


def test_session_setup_verifier_is_provider_private_and_sends_only_semantic_projection():
    session = _bare_session([{
        "schema": "noetrium.minecraft-task-setup-physical-proof.v1",
        "verified": True, "check_count": 4, "checks": (), "failures": (),
    }])
    proof = session.verify_task_setup({
        "schema": "noetrium.minecraft-task-setup.v2",
        "dimension": "overworld",
        "weather": "clear",
        "initial_inventory": (),
        "initial_mobs": (),
        "world_ops": _ops(),
        "agent_access": {"allowed_actions": ("observe_blocks",)},
        "datapack": {"pack_id": "secret-large-authority", "files": {"data/x": {}}},
    })
    assert proof["verified"] is True
    assert len(session._bridge.calls) == 1
    command, payload = session._bridge.calls[0]
    assert command == "setup_verify_wait"
    projected = payload["setup"]
    assert payload["timeout_ms"] == 8000
    assert "datapack" not in projected
    assert "agent_access" not in projected
    assert len(projected["world_ops"]) == 4


def test_session_setup_verifier_projects_server_owned_authority_position():
    session = _bare_session([{
        "schema": "noetrium.minecraft-task-setup-physical-proof.v1",
        "verified": True, "check_count": 2, "checks": (), "failures": (),
    }])
    proof = session.verify_task_setup(
        {
            "schema": "noetrium.minecraft-task-setup.v2",
            "biome": "swamp",
            "initial_inventory": (), "initial_mobs": (), "world_ops": (),
            "authority_position": {"x": 999, "y": 999, "z": 999},
        },
        control_proof={
            "checks": ({
                "kind": "biome_authority", "ok": True,
                "position": {"x": 12.25, "y": 65.0, "z": -31.75},
            },),
        },
    )
    assert proof["verified"] is True
    projected = session._bridge.calls[0][1]["setup"]
    assert projected["authority_position"] == {"x": 12.25, "y": 65.0, "z": -31.75}


def test_session_setup_verifier_fails_closed_when_physical_readback_never_matches():
    from noetrium_platform.capabilities.environment.minecraft.runtime.errors import (
        MinecraftEnvironmentFailure,
    )
    session = _bare_session([{
        "schema": "noetrium.minecraft-task-setup-physical-proof.v1",
        "verified": False, "check_count": 1,
        "checks": ({"kind": "fill", "ok": False},),
        "failures": ({"kind": "fill", "mismatch_count": 1},),
    }])
    import pytest
    with pytest.raises(MinecraftEnvironmentFailure, match="postconditions did not converge") as caught:
        session.verify_task_setup({
            "schema": "noetrium.minecraft-task-setup.v2",
            "initial_inventory": (), "initial_mobs": (), "world_ops": (),
        }, timeout_s=0.01)
    assert caught.value.cause_code == "MINECRAFT_SETUP_POSTCONDITION_FAILED"
    assert caught.value.diagnostics["failures"] == ({"kind": "fill", "mismatch_count": 1},)
    assert caught.value.diagnostics["proof"]["verified"] is False


def test_server_control_state_readback_verifies_gamerules_and_datapack():
    class _ControlRecorder:
        def _rcon(self, command):
            return {
                "gamerule doDaylightCycle": "Gamerule doDaylightCycle is currently set to: false",
                "gamerule doMobSpawning": "Gamerule doMobSpawning is currently set to: true",
                "datapack list enabled": "There are 2 data pack(s) enabled: vanilla, file/test_fixture_pack",
            }[command]
    proof = _DockerMinecraftServer.verify_task_setup_control_state(
        _ControlRecorder(),
        {
            "always_night": True,
            "allow_mob_spawn": True,
            "datapack": {"pack_id": "test_fixture_pack"},
        },
    )
    assert proof["verified"] is True
    assert len(proof["checks"]) == 3


def test_server_biome_control_proof_binds_match_to_authoritative_position():
    class _BiomeControlRecorder:
        def _rcon(self, command):
            if command == "gamerule doDaylightCycle":
                return "Gamerule doDaylightCycle is currently set to: true"
            if command == "gamerule doMobSpawning":
                return "Gamerule doMobSpawning is currently set to: true"
            assert command == (
                "execute at ResearchBot if biome ~ ~ ~ minecraft:swamp "
                "run data get entity ResearchBot Pos"
            )
            return "ResearchBot has the following entity data: [12.25d, 65.0d, -31.75d]"

    proof = _DockerMinecraftServer.verify_task_setup_control_state(
        _BiomeControlRecorder(),
        {"biome": "swamp"},
    )
    row = next(row for row in proof["checks"] if row["kind"] == "biome_authority")
    assert proof["verified"] is True
    assert row["observed"] == "matched"
    assert row["position"] == {"x": 12.25, "y": 65.0, "z": -31.75}
