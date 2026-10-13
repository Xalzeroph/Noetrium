from __future__ import annotations

from noetrium_platform.foundation.scope.api import scope_unit
from noetrium_platform.infrastructure.reliability.effect.runtime import sqlite_effect_intent_journal


from tests._concurrency_support import make_task_group

import json
import queue
import subprocess
from typing import Any

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_ACTION_TYPES,
    MinecraftActionOutcomeStatus,
    minecraft_action_result_record,
    MinecraftBridgeCommandResult,
    MinecraftBridgeEnvelope,
    MinecraftBridgeSpec,
    MinecraftAgentSpec,
    MinecraftEndpointSpec,
    MinecraftEnvironmentRuntimeBinding,
    minecraft_environment_provider_id,
    minecraft_environment_unit,
    MinecraftObservationEvent,
    MinecraftServerSpec,
    minecraft_action_catalog,
    minecraft_action_timeout,
    minecraft_action_invocation_unit,
    minecraft_action_authorization_unit,
    validate_minecraft_action,
)
from noetrium_platform.capabilities.environment.minecraft.providers.readiness import (
    parse_java_major,
    parse_node_major,
    probe_node,
    probe_node_package,
    probe_minecraft_protocol_version,
)
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import (
    JsonlMinecraftBridge,
    MinecraftBridgeError,
)
from noetrium_platform.capabilities.environment.minecraft.providers.server_files import (
    MinecraftServerPreparationError,
    prepare_server_files,
)
from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
    MinecraftServerServiceController,
    build_server_service_contract,
    compose_minecraft_server_service_runtime,
)
from noetrium_platform.composition.environment_observability.minecraft_diagnostics import (
    StructuredMinecraftDiagnostics,
)
from noetrium_platform.capabilities.environment.minecraft.composition.environment import compose_minecraft_environment
from noetrium_platform.composition.minecraft_agent.participant_runtime import (
    compose_minecraft_participant_endpoint,
)
from noetrium_platform.capabilities.environment.minecraft.runtime import (
    MinecraftEnvironmentFailure,
    MinecraftEnvironmentImplementation,
    MinecraftEnvironmentSession,
    MinecraftStateProjection,
)
from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    action_request_digest,
)
from noetrium_platform.evidence.observability.logging.context.api import DiagnosticAddress
from noetrium_platform.evidence.observability.logging.record.api import LogRecord
from noetrium_platform.evidence.observability.logging.record.runtime import StructuredLogger
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, ExecutionContext, thaw_json
from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL
from noetrium_platform.foundation.kernel.record import record_payload
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_supervisor
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceProcessIdentity,
    ServiceReadyObservation,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.infrastructure.lifecycle.service.api.environment import MaterializedServiceEnvironment
from noetrium_platform.infrastructure.reliability.effect.api import prepared_handle_field
from noetrium_platform.infrastructure.lifecycle.service.composition import LocalServiceRuntimeComposer
from noetrium_platform.infrastructure.lifecycle.service.runtime.process_contracts import ProcessReconcileResult, ProcessReconcileStatus
from noetrium_platform.foundation.scope.api import NoetriumUnit, ScopeKind


TEST_OPERATING_SYSTEM = LocalOperatingSystemRoute()


def _test_action_wire_identity(request: ActionRequest) -> dict[str, object]:
    invocation = minecraft_action_invocation_unit(request)
    authorization = minecraft_action_authorization_unit(
        invocation,
        allowed_action_types=MINECRAFT_ACTION_TYPES,
        contract_validation="passed",
    )
    return {
        "action_id": request.action_id,
        "_request_digest": action_request_digest(request),
        "_action_invocation_unit_digest": invocation.unit_digest,
        "_action_authorization_unit_digest": authorization.unit_digest,
    }


def _test_reconcile_unit_kwargs(request: ActionRequest) -> dict[str, str]:
    wire = _test_action_wire_identity(request)
    return {
        "invocation_unit_digest": str(wire["_action_invocation_unit_digest"]),
        "authorization_unit_digest": str(wire["_action_authorization_unit_digest"]),
    }


def _test_environment(
    *,
    endpoint: MinecraftEndpointSpec | None = None,
    bridge_spec: MinecraftBridgeSpec | None = None,
    agent: MinecraftAgentSpec | None = None,
    max_entities: int = 256,
    entity_observation_distance: int = 32,
):
    agent = agent or MinecraftAgentSpec()
    environment = minecraft_environment_unit(
        "minecraft",
        "test",
        agent_username=agent.username,
        agent_auth=agent.auth,
        agent_version=agent.version,
        max_entities=max_entities,
        entity_observation_distance=entity_observation_distance,
    )
    binding = MinecraftEnvironmentRuntimeBinding(
        endpoint=endpoint or MinecraftEndpointSpec(),
        bridge=bridge_spec or MinecraftBridgeSpec(command=("fake-node",), cwd="."),
    )
    return environment, binding


def _test_implementation(
    bridge,
    *,
    endpoint: MinecraftEndpointSpec | None = None,
    bridge_spec: MinecraftBridgeSpec | None = None,
    agent: MinecraftAgentSpec | None = None,
    max_entities: int = 256,
    entity_observation_distance: int = 32,
    checkpoint=None,
):
    environment, binding = _test_environment(
        endpoint=endpoint,
        bridge_spec=bridge_spec,
        agent=agent,
        max_entities=max_entities,
        entity_observation_distance=entity_observation_distance,
    )
    return MinecraftEnvironmentImplementation(
        environment=environment,
        runtime_binding=binding,
        bridge_factory=lambda _environment, _binding: bridge,
        checkpoint=checkpoint,
    )

def _act(session, request):
    return session.act(request, UNBOUNDED_EXECUTION_CONTROL)

def _prepare_action_recovery(session, request, context):
    return session.prepare_action_recovery(
        request,
        context,
        UNBOUNDED_EXECUTION_CONTROL,
    )

def _execute_prepared_action(session, request, handle):
    return session.execute_prepared_action(
        request,
        handle,
        UNBOUNDED_EXECUTION_CONTROL,
    )

def _reconcile_prepared_action(session, handle, context):
    return session.reconcile_prepared_action(
        handle,
        context,
        UNBOUNDED_EXECUTION_CONTROL,
    )

def test_bridge_envelope_is_strict_and_preserves_wire_identity() -> None:
    envelope = MinecraftBridgeEnvelope.from_mapping(
        {
            "type": "event",
            "kind": "self_snapshot",
            "ts_ms": 123,
            "seq": 9,
            "source": "mineflayer",
            "request_id": "request-1",
            "payload": {"username": "bot"},
        }
    )
    event = envelope.as_observation()
    assert event.kind == "self_snapshot"
    assert event.timestamp_ms == 123
    assert event.sequence == 9
    assert event.request_id == "request-1"
    with pytest.raises(ValueError, match="type=event"):
        MinecraftBridgeEnvelope.from_mapping({"type": "ack"})


def test_state_projection_reuses_v034_reduction_invariant_and_is_bounded() -> None:
    state = MinecraftStateProjection(max_entities=1)
    state.ingest(
        MinecraftObservationEvent(
            "self_snapshot",
            {
                "username": "bot",
                "position": {"x": 1, "y": 2, "z": 3},
                "health": 20,
                "food": 18,
                "inventory": [{"name": "oak_log", "count": 3}],
                "dimension": "overworld",
            },
            sequence=1,
        )
    )
    state.ingest(
        MinecraftObservationEvent(
            "entity_snapshot", {"entities": [{"uuid": "a", "name": "cow"}]}, sequence=2
        )
    )
    state.ingest(
        MinecraftObservationEvent(
            "entity_snapshot", {"entities": [{"uuid": "b", "name": "pig"}]}, sequence=3
        )
    )
    state.ingest(
        MinecraftObservationEvent(
            "action_result",
            {
                "action_id": "action-1",
                "verified": True,
                "effect_disposition": "applied",
                "action": {"tool": "wait"},
                "outcome": {"status": "applied", "waited_ms": 1},
            },
            sequence=4,
        )
    )
    assert state.username == "bot"
    assert state.anchor("spawn") == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert tuple(state.entities) == ("b",)
    assert state.last_effect_disposition == "applied"
    assert state.snapshot_digest() == state.snapshot_digest()

    state.ingest(
        MinecraftObservationEvent(
            "action_result",
            {
                "action_id": None,
                "verified": False,
                "effect_disposition": "unknown",
                "action": {"tool": "observe_entities"},
                "outcome": {"status": "partial"},
            },
            sequence=5,
        )
    )
    assert state.last_effect_disposition == "applied"

    with pytest.raises(ValueError, match="not strictly increasing"):
        state.ingest(MinecraftObservationEvent("health", {"health": 1}, sequence=2))


def test_state_projection_sequence_is_fenced_per_bridge_stream() -> None:
    state = MinecraftStateProjection(max_entities=4)
    state.ingest(
        MinecraftObservationEvent(
            "self_snapshot",
            {
                "username": "bot",
                "position": {"x": 1, "y": 2, "z": 3},
                "health": 20,
                "food": 20,
                "inventory": [],
                "dimension": "overworld",
            },
            sequence=5,
            stream_id="bridge-stream-a",
        )
    )
    with pytest.raises(ValueError, match="not strictly increasing"):
        state.ingest(
            MinecraftObservationEvent(
                "health", {"health": 19}, sequence=4, stream_id="bridge-stream-a"
            )
        )

    # Restarting only the short-lived bridge process starts a fresh sequence
    # domain; durable projected world state must remain intact.
    state.ingest(
        MinecraftObservationEvent(
            "health", {"health": 18}, sequence=1, stream_id="bridge-stream-b"
        )
    )
    assert state.health == 18
    assert state.position == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert state.last_event_sequence == 1
    assert state.last_event_stream_id == "bridge-stream-b"


def test_readiness_parsers_and_probe_codes_are_actionable() -> None:
    assert parse_node_major("v22.1.0") == 22
    assert parse_java_major('openjdk version "21.0.8" 2025-07-15') == 21

    def runner(command, **_kwargs):
        if command[0] == "node" and command[1] == "--version":
            return subprocess.CompletedProcess(command, 0, "v22.1.0\n", "")
        return subprocess.CompletedProcess(command, 1, "", "MODULE_NOT_FOUND")

    assert probe_node(runner=runner).ok is True
    missing = probe_node_package("/bridge", package_name="mineflayer", runner=runner)
    assert missing.ok is False
    assert missing.cause_code == "PACKAGE_NOT_RESOLVABLE"


def test_protocol_version_preflight_fails_before_live_bridge_start() -> None:
    def supported(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"requested": "1.21.8", "versions": ["1.21.6", "1.21.8"]}),
            "",
        )

    def unsupported(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"requested": "9.9.9", "versions": ["1.21.8"]}),
            "",
        )

    assert probe_minecraft_protocol_version(
        "/bridge", minecraft_version="1.21.8", runner=supported
    ).ok is True
    failed = probe_minecraft_protocol_version(
        "/bridge", minecraft_version="9.9.9", runner=unsupported
    )
    assert failed.ok is False
    assert failed.cause_code == "MINECRAFT_VERSION_UNSUPPORTED"


def test_mc_spec_is_independent_of_old_runtime_package() -> None:
    environment, binding = _test_environment(
        bridge_spec=MinecraftBridgeSpec(command=("node", "bridge.js"), cwd="/bridge"),
    )
    assert minecraft_environment_provider_id(environment) == "minecraft.mineflayer.jsonl.v1"
    assert binding.endpoint.port is None


def test_scientific_environment_generation_excludes_operational_endpoint_but_binds_agent_conditions() -> None:
    bridge_spec = MinecraftBridgeSpec(command=("node", "bridge.js"), cwd="/bridge")
    first, first_binding = _test_environment(
        endpoint=MinecraftEndpointSpec(host="127.0.0.1", port=25565),
        bridge_spec=bridge_spec,
        agent=MinecraftAgentSpec(username="ResearchBot", auth="offline", version="1.21.6"),
    )
    relocated, relocated_binding = _test_environment(
        endpoint=MinecraftEndpointSpec(host="127.0.0.1", port=26565),
        bridge_spec=bridge_spec,
        agent=MinecraftAgentSpec(username="ResearchBot", auth="offline", version="1.21.6"),
    )
    changed_agent, _ = _test_environment(
        endpoint=MinecraftEndpointSpec(host="127.0.0.1", port=25565),
        bridge_spec=bridge_spec,
        agent=MinecraftAgentSpec(username="ResearchBot", auth="offline", version="1.21.7"),
    )
    assert first.unit_digest == relocated.unit_digest
    assert first_binding.operational_binding_digest != relocated_binding.operational_binding_digest
    assert first.unit_digest != changed_agent.unit_digest


def test_minecraft_agent_username_matches_protocol_contract() -> None:
    assert MinecraftAgentSpec(username="ResearchBot").username == "ResearchBot"
    with pytest.raises(ValueError, match=r"\[A-Za-z0-9_\]\{3,16\}"):
        MinecraftAgentSpec(username="NoetriumResearchBot")
    with pytest.raises(ValueError, match=r"\[A-Za-z0-9_\]\{3,16\}"):
        MinecraftAgentSpec(username="research bot")


def test_minecraft_action_contract_normalizes_and_rejects_before_provider() -> None:
    assert validate_minecraft_action("wait", {}) == {"ms": 500}
    assert validate_minecraft_action(
        "goto", {"position": {"x": 1, "y": 2, "z": 3}, "radius": 2}
    ) == {"position": {"x": 1.0, "y": 2.0, "z": 3.0}, "radius": 2.0}
    with pytest.raises(ValueError, match="UNKNOWN_FIELD"):
        validate_minecraft_action("wait", {"ms": 1, "unsafe": True})
    with pytest.raises(ValueError, match="POSITION_SHAPE"):
        validate_minecraft_action("goto", {"position": {"x": 1, "y": 2}})


def test_minecraft_action_catalog_covers_mc_domain_capabilities() -> None:
    assert MINECRAFT_ACTION_TYPES == {
        "goto",
        "goto_block",
        "goto_entity",
        "move_away",
        "follow_player",
        "stay",
        "collect_block",
        "excavate_region",
        "craft_item",
        "craft_grid",
        "smelt_item",
        "enchant_item",
        "clear_furnace",
        "place_block",
        "pickup_items",
        "auto_light",
        "equip_item",
        "consume_item",
        "discard_item",
        "give_item",
        "chest_inspect",
        "chest_deposit",
        "chest_withdraw",
        "till_and_sow",
        "attack_nearest",
        "attack_entity",
        "attack_player",
        "ranged_attack",
        "fire_projectile",
        "defend_self",
        "use_shield",
        "fish",
        "mount",
        "dismount",
        "use_door",
        "go_to_bed",
        "activate_nearest_block",
        "show_villager_trades",
        "trade_villager",
        "use_tool_on",
        "wait",
        "chat",
        "observe_blocks",
        "observe_entities",
        "registry_search",
        "recipe_lookup",
        "recipe_dependencies",
        "describe_action",
    }
    assert validate_minecraft_action(
        "smelt_item", {"item": "raw_iron", "count": 2, "fuel": "coal"}
    )["max_wait_s"] == 90
    assert validate_minecraft_action(
        "enchant_item", {"item": "diamond_pickaxe", "choice": 2}
    ) == {"item": "diamond_pickaxe", "choice": 2, "max_distance": 16.0}
    assert validate_minecraft_action(
        "attack_player", {"player": "ResearchBot", "max_hits": 40}
    )["max_hits"] == 40
    assert validate_minecraft_action(
        "chest_deposit", {"item": "oak_log", "count": 3}
    )["max_distance"] == 32
    assert minecraft_action_timeout("collect_block", 10) == 40
    planner_catalog = minecraft_action_catalog()
    assert {row.action_type for row in planner_catalog} == MINECRAFT_ACTION_TYPES
    assert all(row.arguments and row.description for row in planner_catalog)
    with pytest.raises(ValueError, match="FIELD_RANGE"):
        validate_minecraft_action("ranged_attack", {"entity": "zombie", "shots": 9})


def test_minecraft_action_evidence_is_bound_to_request_identity_and_status() -> None:
    request_digest = "a" * 64
    invocation_digest = "b" * 64
    authorization_digest = "c" * 64
    lineage = {
        "request_digest": request_digest,
        "action_invocation_unit_digest": invocation_digest,
        "action_authorization_unit_digest": authorization_digest,
    }
    expected = {
        "expected_request_digest": request_digest,
        "expected_invocation_unit_digest": invocation_digest,
        "expected_authorization_unit_digest": authorization_digest,
    }
    event = MinecraftObservationEvent(
        "action_result",
        {
            "action_id": "action-1",
            **lineage,
            "action": {"tool": "craft_item", "item": "stick"},
            "outcome": {"status": "applied", "code": "ITEM_CRAFTED", "crafted": 4},
            "verified": True,
            "effect_disposition": "applied",
        },
    )
    evidence = minecraft_action_result_record(
        event,
        expected_action_id="action-1",
        expected_action_type="craft_item",
        **expected,
    )
    payload = record_payload(evidence)
    assert payload["status"] == MinecraftActionOutcomeStatus.APPLIED.value
    assert payload["outcome"]["crafted"] == 4
    assert payload["request_digest"] == request_digest
    assert payload["action_invocation_unit_digest"] == invocation_digest
    assert payload["action_authorization_unit_digest"] == authorization_digest
    with pytest.raises(ValueError, match="action_id"):
        minecraft_action_result_record(
            event,
            expected_action_id="action-2",
            expected_action_type="craft_item",
            **expected,
        )
    with pytest.raises(ValueError, match="tool"):
        minecraft_action_result_record(
            event,
            expected_action_id="action-1",
            expected_action_type="smelt_item",
            **expected,
        )
    with pytest.raises(ValueError, match="cannot be verified"):
        minecraft_action_result_record(
            MinecraftObservationEvent(
                "action_result",
                {
                    "action_id": "action-1",
                    **lineage,
                    "action": {"tool": "craft_item"},
                    "outcome": {"status": "rejected", "code": "NO_RECIPE"},
                    "verified": True,
                    "effect_disposition": "rejected",
                },
            ),
            expected_action_id="action-1",
            expected_action_type="craft_item",
            **expected,
        )

    with pytest.raises(ValueError, match="outcome.status is required"):
        minecraft_action_result_record(
            MinecraftObservationEvent(
                "action_result",
                {
                    "action_id": "action-1",
                    **lineage,
                    "action": {"tool": "craft_item"},
                    "outcome": {"code": "ITEM_CRAFTED"},
                    "verified": True,
                    "effect_disposition": "applied",
                },
            ),
            expected_action_id="action-1",
            expected_action_type="craft_item",
            **expected,
        )


class _SessionBridge:
    action_recovery_durability = "crash_durable"
    include_entity_snapshot = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.started = False
        self.closed = False
        self.start_calls = 0
        self.close_calls = 0
        self._sequence = 0

    def _event(self, kind: str, payload: dict[str, object]) -> MinecraftObservationEvent:
        self._sequence += 1
        return MinecraftObservationEvent(kind, payload, sequence=self._sequence)

    def _snapshot_entities(self) -> list[dict[str, object]]:
        return []

    def configure_action_recovery(self, namespace: str) -> None:
        assert namespace.startswith("minecraft:")

    def start(self) -> None:
        self.started = True
        self.closed = False
        self.start_calls += 1

    def supports_command(self, command: str) -> bool:
        return command in {"snapshot", "wait"}

    def command(self, command, payload, *, timeout_s, control=None):
        del timeout_s, control
        self.calls.append((command, dict(payload)))
        if command == "snapshot":
            events = [
                self._event(
                    "self_snapshot",
                    {
                        "username": "bot",
                        "position": {"x": 1, "y": 2, "z": 3},
                        "health": 20,
                        "food": 20,
                        "inventory": [{"name": "oak_log", "count": 2}],
                        "dimension": "overworld",
                    },
                )
            ]
            if self.include_entity_snapshot:
                events.append(self._event(
                    "entity_snapshot",
                    {"entities": self._snapshot_entities()},
                ))
            return MinecraftBridgeCommandResult(command, True, tuple(events), {})
        if command == "wait":
            events = (
                self._event(
                    "action_result",
                    {
                        "action_id": payload["action_id"],
                        "request_digest": payload["_request_digest"],
                        "action_invocation_unit_digest": payload["_action_invocation_unit_digest"],
                        "action_authorization_unit_digest": payload["_action_authorization_unit_digest"],
                        "verified": True,
                        "effect_disposition": "applied",
                        "action": {"tool": "wait"},
                        "outcome": {"status": "applied", "waited_ms": payload["ms"]},
                    },
                ),
            )
            return MinecraftBridgeCommandResult(command, True, events, {})
        raise AssertionError(f"unexpected command: {command}")

    def prepare_action(
        self, action_id, *, request_digest, action_type,
        invocation_unit_digest, authorization_unit_digest,
    ):
        self.calls.append((
            "prepare_action",
            {
                "action_id": action_id,
                "request_digest": request_digest,
                "action_type": action_type,
                "invocation_unit_digest": invocation_unit_digest,
                "authorization_unit_digest": authorization_unit_digest,
            },
        ))

    def reconcile_action(
        self, action_id, *, request, context, request_digest=None,
        invocation_unit_digest, authorization_unit_digest,
    ):
        del request, context, request_digest, invocation_unit_digest, authorization_unit_digest
        raise AssertionError(f"unexpected reconciliation: {action_id}")

    def close(self) -> None:
        self.closed = True
        self.started = False
        self.close_calls += 1


class _EntityProjectionBridge(_SessionBridge):
    def _snapshot_entities(self) -> list[dict[str, object]]:
        return [
            {
                "id": 11, "uuid": "rabbit-a", "name": "rabbit",
                "mob_type": "Rabbit", "type": "animal",
                "position": {"x": 2, "y": 64, "z": 0}, "distance": 2.0,
            },
            {
                "id": 12, "uuid": "rabbit-b", "name": "rabbit",
                "mob_type": "Rabbit", "type": "animal",
                "position": {"x": 5, "y": 64, "z": 0}, "distance": 5.0,
            },
            {
                "id": 21, "uuid": "player-alice", "username": "Alice",
                "name": "player", "type": "player",
                "position": {"x": 3, "y": 64, "z": 1}, "distance": 3.2,
            },
        ]


class _NoEntityObservationBridge(_SessionBridge):
    include_entity_snapshot = False


class _AcceptedUnverifiedBridge(_SessionBridge):
    def __init__(self) -> None:
        super().__init__()
        self.reconciled: list[str] = []

    def command(self, command, payload, *, timeout_s, control=None):
        if command != "wait":
            return super().command(command, payload, timeout_s=timeout_s)
        del timeout_s, control
        self.calls.append((command, dict(payload)))
        events = (
            MinecraftObservationEvent(
                "action_result",
                {
                    "action_id": payload["action_id"],
                    "request_digest": payload["_request_digest"],
                    "action_invocation_unit_digest": payload["_action_invocation_unit_digest"],
                    "action_authorization_unit_digest": payload["_action_authorization_unit_digest"],
                    "verified": False,
                    "effect_disposition": "unknown",
                    "action": {"tool": command},
                    "outcome": {"status": "partial", "code": "WAIT_UNCONFIRMED"},
                },
                sequence=1,
            ),
        )
        return MinecraftBridgeCommandResult(command, True, events, {})

    def reconcile_action(
        self, action_id, *, request, context, request_digest=None,
        invocation_unit_digest, authorization_unit_digest,
    ):
        del request, context, request_digest, invocation_unit_digest, authorization_unit_digest
        self.reconciled.append(action_id)
        return ActionReconciliationResult(
            action_id,
            ActionReconciliationDisposition.APPLIED,
            None,
            {"source": "test-ledger"},
        )


class _UnknownRecoveryBridge(_SessionBridge):
    def __init__(self) -> None:
        super().__init__()
        self.reconciled: list[tuple[str, str | None]] = []

    def reconcile_action(
        self, action_id, *, request, context, request_digest=None,
        invocation_unit_digest, authorization_unit_digest,
    ):
        del request, context, invocation_unit_digest, authorization_unit_digest
        self.reconciled.append((action_id, request_digest))
        return ActionReconciliationResult(
            action_id,
            ActionReconciliationDisposition.UNKNOWN,
            None,
            {"source": "test-crash-window"},
        )


class _EvidenceBridge(_SessionBridge):
    def __init__(self, *, action_id: str, tool: str, status: str, verified: bool) -> None:
        super().__init__()
        self.action_id = action_id
        self.tool = tool
        self.status = status
        self.verified = verified

    def command(self, command, payload, *, timeout_s, control=None):
        if command != "wait":
            return super().command(command, payload, timeout_s=timeout_s)
        del timeout_s, control
        self.calls.append((command, dict(payload)))
        events = (
            MinecraftObservationEvent(
                "action_result",
                {
                    "action_id": self.action_id,
                    "request_digest": payload["_request_digest"],
                    "action_invocation_unit_digest": payload["_action_invocation_unit_digest"],
                    "action_authorization_unit_digest": payload["_action_authorization_unit_digest"],
                    "verified": self.verified,
                    "effect_disposition": (
                        "applied"
                        if self.status == "applied"
                        else "rejected"
                        if self.status == "rejected"
                        else "unknown"
                    ),
                    "action": {"tool": self.tool},
                    "outcome": {"status": self.status, "code": "TEST_OUTCOME"},
                },
                sequence=1,
            ),
        )
        return MinecraftBridgeCommandResult(
            command, True, events, {}
        )


def test_minecraft_session_persists_state_projection_and_validates_before_bridge() -> None:
    bridge = _SessionBridge()
    implementation = _test_implementation(
        bridge, max_entities=2, entity_observation_distance=64
    )
    session = MinecraftEnvironmentSession(
        session_id="mc-session",
        implementation=implementation,
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")

    descriptor = session.capability_descriptors()[0]
    assert descriptor.action_types == tuple(
        contract.action_type for contract in minecraft_action_catalog()
    )
    assert thaw_json(descriptor.metadata["action_contracts"]) == thaw_json(
        tuple(contract.as_payload() for contract in minecraft_action_catalog())
    )

    observed = session.observe(context)
    assert observed.payload["state"]["position"] == {"x": 1.0, "y": 2.0, "z": 3.0}
    assert observed.payload["state"]["inventory"] == {"oak_log": 2}
    assert bridge.calls[0][0] == "snapshot"
    assert bridge.calls[0][1]["entity_distance"] == 64
    assert bridge.calls[0][1]["entity_limit"] == 2

    acted = _act(session, ActionRequest("action-1", "wait", {}, context))
    assert acted.observation is not None
    assert acted.observation.payload["state"]["last_effect_disposition"] == "applied"
    assert bridge.calls[-1][1]["ms"] == 500

    call_count = len(bridge.calls)
    with pytest.raises(MinecraftEnvironmentFailure, match="MISSING_FIELD"):
        _act(session, ActionRequest("action-2", "goto", {}, context))
    assert len(bridge.calls) == call_count
    session.close()
    assert bridge.closed is True


def test_minecraft_decision_view_aggregates_by_default_and_can_expand_entities() -> None:
    bridge = _EntityProjectionBridge()
    session = MinecraftEnvironmentSession(
        session_id="mc-context-session",
        implementation=_test_implementation(bridge, max_entities=8),
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")

    observed = session.observe(context)
    raw_entities = observed.payload["state"]["nearby_entities"]
    assert len(raw_entities) == 3
    assert raw_entities[0]["runtime_id"] in {11, 12, 21}

    summary = observed.payload["decision_view"]
    assert summary["kind"] == "minecraft_decision_view.v1"
    nearby = summary["state"]["nearby_entities"]
    assert nearby["mode"] == "summary"
    assert nearby["counts"] == {"player": 1, "rabbit": 2}
    assert len(nearby["rows"]) == 2
    assert any(row[1] == "Alice" for row in nearby["rows"])
    assert any(row[0] == 11 for row in nearby["rows"])
    assert all("rabbit-" not in str(row) for row in nearby["rows"])

    detailed = session._decision_view(detailed_entities=True)
    detailed_nearby = detailed["state"]["nearby_entities"]
    assert detailed_nearby["mode"] == "detailed"
    assert len(detailed_nearby["rows"]) == 3
    assert {row[0] for row in detailed_nearby["rows"]} == {11, 12, 21}
    assert "state_digest" not in detailed
    assert "last_event_sequence" not in detailed["state"]
    session.close()


def test_minecraft_session_prepared_action_binds_exact_identity_before_effect() -> None:
    bridge = _SessionBridge()
    session = MinecraftEnvironmentSession(
        session_id="mc-prepared-session",
        implementation=_test_implementation(bridge),
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("action-prepared-1", "wait", {"ms": 25}, context)

    handle = _prepare_action_recovery(session, request, context)
    assert session.action_recovery_durability == "crash_durable"
    assert prepared_handle_field(handle, "request_id") == request.action_id
    assert prepared_handle_field(handle, "provider_instance_id") == "minecraft:mc-prepared-session"
    assert prepared_handle_field(handle, "provider_schema") == "minecraft.action-recovery.v3"

    result = _execute_prepared_action(session, request, handle)
    assert result.accepted is True
    assert result.effect is not None
    assert result.effect.request_digest == prepared_handle_field(handle, "request_digest")
    assert bridge.calls[-1][1]["_request_digest"] == prepared_handle_field(handle, "request_digest")

    with pytest.raises(ActionIdentityViolation, match="request identity mismatch"):
        _execute_prepared_action(session,
            ActionRequest("action-prepared-2", "wait", {"ms": 25}, context), handle
        )
    session.close()


def test_minecraft_prepared_reconciliation_preserves_unknown_without_reexecution() -> None:
    bridge = _UnknownRecoveryBridge()
    session = MinecraftEnvironmentSession(
        session_id="mc-crash-window-session",
        implementation=_test_implementation(bridge),
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("action-uncertain-1", "wait", {}, context)
    handle = _prepare_action_recovery(session, request, context)
    calls_before = len(bridge.calls)

    reconciliation = _reconcile_prepared_action(session, handle, context)

    assert reconciliation.disposition is ActionReconciliationDisposition.UNKNOWN
    assert reconciliation.result is not None
    assert reconciliation.result.effect is not None
    assert reconciliation.result.effect.certainty is EffectCertainty.INDETERMINATE
    assert bridge.reconciled == [(request.action_id, prepared_handle_field(handle, "request_digest"))]
    assert len(bridge.calls) == calls_before + 1
    assert bridge.calls[-1][0] == "snapshot"
    session.close()


def test_minecraft_session_rejects_duplicate_action_identity_without_reexecution() -> None:
    bridge = _SessionBridge()
    session = MinecraftEnvironmentSession(
        session_id="mc-session",
        implementation=_test_implementation(bridge),
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("action-1", "wait", {}, context)
    _act(session, request)
    call_count = len(bridge.calls)

    with pytest.raises(ActionIdentityViolation, match="already executed"):
        _act(session, request)
    with pytest.raises(ActionIdentityViolation, match="reused with drift"):
        _act(session, ActionRequest("action-1", "wait", {"ms": 1}, context))
    assert len(bridge.calls) == call_count
    session.close()


def test_minecraft_reconcile_does_not_treat_accepted_unverified_as_not_applied() -> None:
    bridge = _AcceptedUnverifiedBridge()
    session = MinecraftEnvironmentSession(
        session_id="mc-session",
        implementation=_test_implementation(bridge),
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")
    result = _act(session, ActionRequest("action-1", "wait", {}, context))

    reconciled = session.reconcile(result.effect, context)

    assert bridge.reconciled == ["action-1"]
    assert reconciled.certainty.value == "effect_confirmed"
    session.close()


@pytest.mark.parametrize(
    ("action_id", "tool", "match"),
    (("wrong-action", "wait", "action_id"), ("action-1", "chat", "tool")),
)
def test_minecraft_session_fails_closed_on_action_evidence_identity_drift(
    action_id: str, tool: str, match: str
) -> None:
    bridge = _EvidenceBridge(
        action_id=action_id, tool=tool, status="applied", verified=True
    )
    session = MinecraftEnvironmentSession(
        session_id="mc-evidence-session",
        implementation=_test_implementation(bridge),
        bridge=bridge,
    )
    with pytest.raises(MinecraftEnvironmentFailure, match=match):
        _act(session,
            ActionRequest(
                "action-1",
                "wait",
                {},
                ExecutionContext("run", "trace", "span", task_id="task"),
            )
        )
    session.close()


def test_minecraft_session_maps_rejected_domain_outcome_to_rejected_effect() -> None:
    bridge = _EvidenceBridge(
        action_id="action-1", tool="wait", status="rejected", verified=False
    )
    session = MinecraftEnvironmentSession(
        session_id="mc-rejected-session",
        implementation=_test_implementation(bridge),
        bridge=bridge,
    )
    result = _act(session,
        ActionRequest(
            "action-1",
            "wait",
            {},
            ExecutionContext("run", "trace", "span", task_id="task"),
        )
    )
    assert result.accepted is False
    assert result.effect.certainty.value == "effect_rejected"
    session.close()


class _CheckpointProvider:
    def __init__(self) -> None:
        self.captures = 0
        self.restores: list[bytes] = []

    def capture(self, *, session_id, context):
        assert session_id == "mc-checkpoint-session"
        assert context is None
        self.captures += 1
        return b"authoritative-world-cut"

    def restore(self, payload, *, session_id, context):
        assert session_id == "mc-checkpoint-session"
        assert context is None
        self.restores.append(payload)


class _FailingCheckpointProvider(_CheckpointProvider):
    def restore(self, payload, *, session_id, context):
        super().restore(payload, session_id=session_id, context=context)
        raise OSError("simulated world restore failure")


def test_minecraft_checkpoint_restores_world_projection_and_bridge_lifecycle() -> None:
    bridge = _SessionBridge()
    checkpoint = _CheckpointProvider()
    implementation = _test_implementation(bridge, max_entities=2, checkpoint=checkpoint)
    session = MinecraftEnvironmentSession(
        session_id="mc-checkpoint-session",
        implementation=implementation,
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")
    session.observe(context)
    action = _act(session, ActionRequest("action-1", "wait", {}, context))
    expected_state_digest = session.diagnostics()["state_digest"]
    payload = session.checkpoint()

    _act(session, ActionRequest("action-2", "wait", {}, context))
    session.restore(payload)

    assert checkpoint.captures == 1
    assert checkpoint.restores == [b"authoritative-world-cut"]
    assert bridge.close_calls == 1
    assert bridge.start_calls == 2
    assert session.diagnostics()["state_digest"] == expected_state_digest
    assert session.diagnostics()["known_action_ids"] == 1
    assert session.reconcile(action.effect, context).certainty.value == "effect_confirmed"


def test_minecraft_checkpoint_validates_before_touching_world_or_bridge() -> None:
    bridge = _SessionBridge()
    checkpoint = _CheckpointProvider()
    implementation = _test_implementation(bridge, checkpoint=checkpoint)
    session = MinecraftEnvironmentSession(
        session_id="mc-checkpoint-session",
        implementation=implementation,
        bridge=bridge,
    )
    session.observe(ExecutionContext("run", "trace", "span", task_id="task"))
    valid_document = json.loads(session.checkpoint())

    with pytest.raises(MinecraftEnvironmentFailure, match="restore.decode"):
        session.restore(b'{"schema_version":"wrong"}')

    uppercase_digest = json.loads(json.dumps(valid_document))
    uppercase_digest["world_payload_sha256"] = uppercase_digest[
        "world_payload_sha256"
    ].upper()
    with pytest.raises(MinecraftEnvironmentFailure, match="restore.decode"):
        session.restore(json.dumps(uppercase_digest).encode("utf-8"))

    coerced_observation = json.loads(json.dumps(valid_document))
    coerced_observation["last_observation"]["observation_id"] = 1
    with pytest.raises(MinecraftEnvironmentFailure, match="restore.decode"):
        session.restore(json.dumps(coerced_observation).encode("utf-8"))

    assert checkpoint.restores == []
    assert bridge.close_calls == 0


def test_minecraft_checkpoint_provider_failure_faults_session_but_allows_close() -> None:
    bridge = _SessionBridge()
    checkpoint = _FailingCheckpointProvider()
    session = MinecraftEnvironmentSession(
        session_id="mc-checkpoint-session",
        implementation=_test_implementation(bridge, checkpoint=checkpoint),
        bridge=bridge,
    )
    payload = session.checkpoint()

    with pytest.raises(MinecraftEnvironmentFailure, match="restore failed"):
        session.restore(payload)

    assert session.diagnostics()["restore_faulted"] is True
    with pytest.raises(RuntimeError, match="unusable after restore failure"):
        session.observe(ExecutionContext("run", "trace", "span"))
    session.close()
    assert bridge.closed is True


def test_minecraft_session_fails_closed_when_entity_observation_is_undeclared() -> None:
    bridge = _NoEntityObservationBridge()
    implementation = _test_implementation(bridge)
    session = MinecraftEnvironmentSession(
        session_id="mc-session-no-entities",
        implementation=implementation,
        bridge=bridge,
    )
    with pytest.raises(MinecraftEnvironmentFailure, match="snapshot returned no entity_snapshot"):
        session.observe(ExecutionContext("run", "trace", "span", task_id="task"))
    session.close()


class _QueueReader:
    def __init__(self) -> None:
        self._queue: queue.Queue[str] = queue.Queue()
        self._closed = False

    def put(self, value: str) -> None:
        self._queue.put(value)

    def readline(self) -> str:
        if self._closed and self._queue.empty():
            return ""
        return self._queue.get()

    def close(self) -> None:
        self._closed = True
        self._queue.put("")


class _FakeProcess:
    _next_pid = 1000

    def __init__(self, action_types: list[str] | None = None) -> None:
        self.pid = _FakeProcess._next_pid
        _FakeProcess._next_pid += 1
        self.stdout = _QueueReader()
        self.stderr = _QueueReader()
        self.stdin = self
        self.returncode: int | None = None
        self.action_types = (
            sorted(MINECRAFT_ACTION_TYPES) if action_types is None else action_types
        )

    def write(self, line: str) -> int:
        message = json.loads(line)
        command = str(message["cmd"])
        request_id = message.get("request_id")
        if command == "connect":
            self._event(
                "bridge_status",
                {
                    "status": "spawned",
                    "version": "1.21.6",
                    "action_types": self.action_types,
                    "terminal_settlement_ms": 6000,
                },
                request_id,
            )
            self._ack(command, request_id)
        elif command == "wait":
            self._event(
                "action_result",
                {
                    "action_id": message.get("action_id"),
                    "request_digest": message.get("_request_digest"),
                    "action_invocation_unit_digest": message.get("_action_invocation_unit_digest"),
                    "action_authorization_unit_digest": message.get("_action_authorization_unit_digest"),
                    "verified": True,
                    "effect_disposition": "applied",
                    "action": {"tool": "wait"},
                    "outcome": {
                        "status": "applied",
                        "code": "WAIT_COMPLETED",
                        "waited_ms": 1,
                    },
                },
                request_id,
            )
            self._ack(command, request_id, verified=True)
        elif command == "reconcile_action":
            self._ack(
                command,
                request_id,
                disposition="not_applied",
                state="terminal",
                durability="crash_durable",
                outcome={
                    "status": "rejected",
                    "code": "COLLECTION_FAILED",
                    "errors": [
                        {
                            "phase": "collectblock",
                            "name": "NoPath",
                            "code": "NoPath",
                            "message": "No path to the goal!",
                        }
                    ],
                },
            )
        elif command == "quit":
            self._ack(command, request_id)
            self.returncode = 0
            self.stdout.close()
            self.stderr.close()
        return len(line)

    def flush(self) -> None:
        return None

    def _event(self, kind: str, payload: dict[str, Any], request_id: str | None) -> None:
        value = {"type": "event", "kind": kind, "seq": 1, "ts_ms": 1, "payload": payload}
        if request_id:
            value["request_id"] = request_id
        self.stdout.put(json.dumps(value) + "\n")

    def _ack(self, command: str, request_id: str | None, **payload: Any) -> None:
        value = {"type": "ack", "cmd": command, **payload}
        if request_id:
            value["request_id"] = request_id
        self.stdout.put(json.dumps(value) + "\n")

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15
        self.stdout.close()
        self.stderr.close()

    def kill(self) -> None:
        self.returncode = -9
        self.stdout.close()
        self.stderr.close()


class _Diagnostics:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.failures: list[str] = []
        self.metrics: list[str] = []

    def event(self, *, phase, event, attributes=None, level="DEBUG", correlation_refs=()):
        del attributes, level, correlation_refs
        self.events.append((phase, event))

    def failure(self, *, phase, code, message, exception=None, attributes=None, correlation_refs=()):
        del phase, message, exception, attributes, correlation_refs
        self.failures.append(code)

    def metric(self, *, name, value, labels=None):
        del value, labels
        self.metrics.append(name)


class _LogSink:
    def __init__(self) -> None:
        self.records: list[LogRecord] = []

    def append(self, record: LogRecord) -> None:
        self.records.append(record)


class _MetricSink:
    def __init__(self) -> None:
        self.rows: list[tuple[ExecutionContext, str, float, dict[str, str]]] = []

    def observe(self, context, name, value, **dimensions):
        self.rows.append((context, name, value, dimensions))


class _FailureLedger:
    def __init__(self) -> None:
        self.failures: list[object] = []

    def append_failure_once(self, failure):
        self.failures.append(failure)
        return True, "failure-ref"



def test_minecraft_bridge_spec_requires_bounded_stdout_queue_capacity() -> None:
    with pytest.raises(ValueError, match="stdout_queue_capacity"):
        MinecraftBridgeSpec(command=("node",), cwd=".", stdout_queue_capacity=0)
    spec = MinecraftBridgeSpec(command=("node",), cwd=".", stdout_queue_capacity=17)
    assert spec.stdout_queue_capacity == 17


def test_jsonl_bridge_preserves_action_identity_and_reconciliation_proof() -> None:
    endpoint = MinecraftEndpointSpec(port=25565)
    agent = MinecraftAgentSpec(version="1.21.6")
    spec = MinecraftBridgeSpec(command=("fake-node",), cwd=".", command_timeout_s=1, connect_timeout_s=1)
    diagnostics = _Diagnostics()
    task_group = make_task_group("minecraft-bridge")
    bridge = JsonlMinecraftBridge(
        endpoint=endpoint,
        spec=spec,
        agent=agent,
        operating_system=TEST_OPERATING_SYSTEM,
        process_factory=lambda _command, **_kwargs: _FakeProcess(),
        diagnostics=diagnostics,
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    bridge.start()
    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("action-1", "wait", {"ms": 1}, context)
    result = bridge.command(
        "wait",
        {**_test_action_wire_identity(request), "ms": 1},
        timeout_s=1,
    )
    assert result.acknowledged is True
    assert result.events[0].request_id == "action-1"
    assert ("start", "BRIDGE_PROCESS_READY") in diagnostics.events
    assert ("command", "BRIDGE_COMMAND_START") in diagnostics.events
    assert "minecraft.bridge.command_latency_s" in diagnostics.metrics

    proof = bridge.reconcile_action(
        "action-1", request=request, context=context,
        **_test_reconcile_unit_kwargs(request),
    )
    assert proof.disposition is ActionReconciliationDisposition.APPLIED

    durable_request = ActionRequest("durable-action", "wait", {"ms": 1}, context)
    durable = bridge.reconcile_action(
        "durable-action", request=durable_request, context=context,
        **_test_reconcile_unit_kwargs(durable_request),
    )
    assert durable.disposition is ActionReconciliationDisposition.NOT_APPLIED
    assert durable.diagnostics["proof_source"] == "process_action_journal"
    assert durable.diagnostics["provider_outcome"]["code"] == "COLLECTION_FAILED"
    assert durable.diagnostics["provider_outcome"]["errors"][0]["name"] == "NoPath"
    bridge.close()


class _LateActionResultProcess(_FakeProcess):
    def __init__(self) -> None:
        super().__init__()
        self._wait_count = 0
        self._wire_by_action: dict[str, dict[str, object]] = {}

    def write(self, line: str) -> int:
        message = json.loads(line)
        if str(message["cmd"]) != "wait":
            return super().write(line)
        self._wait_count += 1
        request_id = str(message.get("request_id") or "")
        action_id = str(message.get("action_id") or "")
        self._wire_by_action[action_id] = dict(message)
        if self._wait_count == 2:
            original = self._wire_by_action["action-1"]
            self._event(
                "action_result",
                {
                    "action_id": "action-1",
                    "request_digest": original.get("_request_digest"),
                    "action_invocation_unit_digest": original.get("_action_invocation_unit_digest"),
                    "action_authorization_unit_digest": original.get("_action_authorization_unit_digest"),
                    "verified": True,
                    "effect_disposition": "applied",
                    "action": {"tool": "wait"},
                    "outcome": {
                        "status": "applied",
                        "code": "WAIT_COMPLETED_LATE",
                        "waited_ms": 1,
                    },
                },
                "action-1",
            )
        self._event(
            "action_result",
            {
                "action_id": action_id,
                "request_digest": message.get("_request_digest"),
                "action_invocation_unit_digest": message.get("_action_invocation_unit_digest"),
                "action_authorization_unit_digest": message.get("_action_authorization_unit_digest"),
                "verified": True,
                "effect_disposition": "applied",
                "action": {"tool": "wait"},
                "outcome": {
                    "status": "applied",
                    "code": "WAIT_COMPLETED",
                    "waited_ms": 1,
                },
            },
            request_id,
        )
        self._ack("wait", request_id, verified=True)
        return len(line)


def test_jsonl_bridge_routes_late_action_result_to_its_original_proof() -> None:
    task_group = make_task_group("minecraft-bridge-late-action-result")
    diagnostics = _Diagnostics()
    process = _LateActionResultProcess()
    bridge = JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25565),
        spec=MinecraftBridgeSpec(
            command=("fake-node",),
            cwd=".",
            command_timeout_s=1,
            connect_timeout_s=1,
        ),
        agent=MinecraftAgentSpec(version="1.21.6"),
        operating_system=TEST_OPERATING_SYSTEM,
        process_factory=lambda _command, **_kwargs: process,
        diagnostics=diagnostics,
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    bridge.start()
    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("action-1", "wait", {"ms": 1}, context)
    request2 = ActionRequest("action-2", "wait", {"ms": 1}, context)

    first = bridge.command(
        "wait",
        {**_test_action_wire_identity(request), "ms": 1},
        timeout_s=1,
    )
    second = bridge.command(
        "wait",
        {**_test_action_wire_identity(request2), "ms": 1},
        timeout_s=1,
    )

    assert first.acknowledged is True
    assert second.acknowledged is True
    assert [
        event.payload["action_id"]
        for event in second.events
        if event.kind == "action_result"
    ] == ["action-2"]
    assert (
        "command",
        "BRIDGE_STALE_ACTION_RESULT_ROUTED",
    ) in diagnostics.events

    proof = bridge.reconcile_action(
        "action-1", request=request, context=context,
        **_test_reconcile_unit_kwargs(request),
    )
    assert proof.disposition is ActionReconciliationDisposition.APPLIED

    bridge.close()
    task_group.close()


class _ContradictoryActionResultProcess(_FakeProcess):
    def write(self, line: str) -> int:
        message = json.loads(line)
        if str(message["cmd"]) != "wait":
            return super().write(line)
        request_id = str(message.get("request_id") or "")
        action_id = str(message.get("action_id") or "")
        self._event(
            "action_result",
            {
                "action_id": action_id,
                "request_digest": message.get("_request_digest"),
                "action_invocation_unit_digest": message.get("_action_invocation_unit_digest"),
                "action_authorization_unit_digest": message.get("_action_authorization_unit_digest"),
                "verified": True,
                "effect_disposition": "applied",
                "action": {"tool": "wait"},
                "outcome": {
                    "status": "applied",
                    "code": "WAIT_COMPLETED",
                    "waited_ms": 1,
                },
            },
            request_id + "-contradiction",
        )
        self._ack("wait", request_id, verified=True)
        return len(line)


def test_jsonl_bridge_fails_closed_on_contradictory_action_result_correlation() -> None:
    task_group = make_task_group("minecraft-bridge-contradictory-action-result")
    bridge = JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25565),
        spec=MinecraftBridgeSpec(
            command=("fake-node",),
            cwd=".",
            command_timeout_s=1,
            connect_timeout_s=1,
        ),
        agent=MinecraftAgentSpec(version="1.21.6"),
        operating_system=TEST_OPERATING_SYSTEM,
        process_factory=lambda _command, **_kwargs: _ContradictoryActionResultProcess(),
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    bridge.start()
    with pytest.raises(MinecraftBridgeError) as caught:
        bridge.command(
            "wait",
            {
                "action_id": "action-1",
                "ms": 1,
                "_request_digest": "a" * 64,
                "_action_invocation_unit_digest": "b" * 64,
                "_action_authorization_unit_digest": "c" * 64,
            },
            timeout_s=1,
        )
    assert caught.value.cause_code == "BRIDGE_INVALID_ACTION_RESULT"
    bridge.close()
    task_group.close()


def test_jsonl_bridge_cached_unknown_reprobes_provider_without_physical_reexecution() -> None:
    class RecordingProcess(_FakeProcess):
        def __init__(self) -> None:
            super().__init__()
            self.commands: list[str] = []

        def write(self, line: str) -> int:
            self.commands.append(str(json.loads(line)["cmd"]))
            return super().write(line)

    task_group = make_task_group("minecraft-bridge-local-unknown")
    process = RecordingProcess()
    bridge = JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25565),
        spec=MinecraftBridgeSpec(command=("fake-node",), cwd=".", command_timeout_s=1, connect_timeout_s=1),
        agent=MinecraftAgentSpec(version="1.21.6"),
        operating_system=TEST_OPERATING_SYSTEM,
        process_factory=lambda _command, **_kwargs: process,
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    try:
        bridge.start()
        context = ExecutionContext("run", "trace", "span", task_id="task")
        request = ActionRequest("action-1", "wait", {"ms": 1}, context)
        digest = action_request_digest(request)
        bridge._action_proofs[request.action_id] = ActionReconciliationDisposition.UNKNOWN
        bridge._action_proof_digests[request.action_id] = digest
        bridge._action_request_digests[request.action_id] = digest
        before = bridge._request_counter

        proof = bridge.reconcile_action(
            request.action_id, request=request, context=context,
            **_test_reconcile_unit_kwargs(request),
        )

        assert proof.disposition is ActionReconciliationDisposition.NOT_APPLIED
        assert proof.diagnostics["proof_source"] == "process_action_journal"
        assert bridge._request_counter == before + 1
        assert process.commands.count("reconcile_action") == 1
        assert "wait" not in process.commands
    finally:
        bridge.close()
        task_group.close()


def test_jsonl_bridge_fails_handshake_on_provider_capability_drift() -> None:
    task_group = make_task_group("minecraft-bridge-drift")
    bridge = JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25566),
        spec=MinecraftBridgeSpec(
            command=("fake-node",), cwd=".", command_timeout_s=1, connect_timeout_s=1
        ),
        agent=MinecraftAgentSpec(version="1.21.6"),
        operating_system=TEST_OPERATING_SYSTEM,
        process_factory=lambda _command, **_kwargs: _FakeProcess(["wait"]),
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    with pytest.raises(MinecraftBridgeError) as caught:
        bridge.start()
    assert caught.value.cause_code == "MINECRAFT_CAPABILITY_DRIFT"
    assert bridge.process_id is None


def test_minecraft_diagnostics_composition_unifies_log_metric_and_failure_ports() -> None:
    log_sink = _LogSink()
    logger = StructuredLogger(
        log_sink,
        logger="environment.minecraft",
        address=DiagnosticAddress((scope_unit(ScopeKind.PROJECT, "paper"),)),
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")
    metric_sink = _MetricSink()
    failure_ledger = _FailureLedger()
    materialized: list[dict[str, object]] = []

    def materializer(**kwargs):
        materialized.append(kwargs)
        return {"failure_code": kwargs["code"], "phase": kwargs["phase"]}

    diagnostics = StructuredMinecraftDiagnostics(
        logger=logger,
        context=lambda: context,
        metrics=metric_sink,
        failure_ledger=failure_ledger,
        failure_materializer=materializer,
    )
    diagnostics.event(
        phase="command",
        event="MC_COMMAND_END",
        level="INFO",
        attributes={"action_id": "action-1"},
        correlation_refs=("action-1",),
    )
    diagnostics.metric(name="minecraft.command_latency_s", value=0.25, labels={"command": "wait"})
    diagnostics.failure(
        phase="read",
        code="BRIDGE_STDOUT_EOF",
        message="bridge ended",
        exception=RuntimeError("bridge ended"),
        correlation_refs=("action-1",),
    )

    assert [record.event for record in log_sink.records] == ["MC_COMMAND_END", "MC_FAILURE"]
    assert metric_sink.rows[0][1:] == ("minecraft.command_latency_s", 0.25, {"command": "wait"})
    assert len(failure_ledger.failures) == 1
    assert materialized[0]["code"] == "BRIDGE_STDOUT_EOF"
    assert diagnostics.diagnostic_errors == ()


def test_server_files_require_explicit_eula_policy(tmp_path) -> None:
    jar = tmp_path / "server.jar"
    jar.write_bytes(b"server-artifact")
    spec = MinecraftServerSpec(
        jar_path=str(jar),
        workdir=str(tmp_path / "world"),
        java_executable="/usr/bin/java",
        port=25565,
    )
    with pytest.raises(MinecraftServerPreparationError, match="EULA_ACCEPTANCE_REQUIRED"):
        prepare_server_files(spec, accept_eula=False)
    prepared = prepare_server_files(spec, accept_eula=True)
    assert prepared.eula_accepted is True
    assert "eula=true" in (tmp_path / "world" / "eula.txt").read_text()
    properties = (tmp_path / "world" / "server.properties").read_text()
    assert "level-name=research-world" in properties
    assert "server-port=25565" in properties


class _FakeServiceRuntime:
    def __init__(self) -> None:
        self.process = ServiceProcessIdentity(42, "start-42", 42)
        self.calls: list[str] = []

    def reconcile_exact(self, contract):
        self.calls.append("reconcile")
        return ServiceReconcileObservation(True, self.process, (contract.digest(),))

    def start_exact(self, contract):
        self.calls.append("start")
        return ServiceStartOutcome(contract.digest(), self.process, "ready-ref", 1234.5, ("start-ref",))

    def verify_ready_exact(self, contract):
        self.calls.append("verify")
        return ServiceReadyObservation(contract.digest(), self.process, "ready-ref", 1234.5, ("ready-ref",))

    def stop_exact(self, contract, expected_process):
        if expected_process != self.process:
            raise RuntimeError("test Minecraft process generation drifted")
        self.calls.append("stop")
        return ServiceStopOutcome(contract.digest(), True, ("stop-ref",))


def test_server_controller_uses_generic_service_port_only() -> None:
    spec = MinecraftServerSpec(
        jar_path="/srv/minecraft/server.jar",
        workdir="/srv/minecraft/world",
        java_executable="/usr/bin/java",
        port=25565,
    )
    contract = build_server_service_contract(
        spec,
        environment_digest="a" * 64,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
    )
    runtime = _FakeServiceRuntime()
    controller = MinecraftServerServiceController(spec, contract, runtime)
    assert controller.reconcile().process is not None
    assert controller.start().ready_evidence_ref == "ready-ref"
    assert controller.verify_ready().process.pid == 42
    assert controller.stop().stopped is True
    assert runtime.calls == ["reconcile", "start", "verify", "stop"]


class _ComposedServiceBackend:
    def reconcile(self, process, contract, environment):
        del process, contract, environment
        return ProcessReconcileResult(ProcessReconcileStatus.MISSING, ())

    def start(self, contract, environment, captures):
        del contract, environment, captures
        return ServiceProcessIdentity(77, "start-77", 77), ("process-start",)

    def alive(self, process):
        return process.pid == 77

    def stop(self, process, contract):
        del process, contract
        return ("process-stop",)


def test_minecraft_server_runtime_uses_generic_service_composer(tmp_path) -> None:
    spec = MinecraftServerSpec(
        jar_path="/srv/minecraft/server.jar",
        workdir="/srv/minecraft/world",
        java_executable="/usr/bin/java",
        port=25565,
    )
    environment = MaterializedServiceEnvironment.from_mapping({"JAVA_HOME": "/usr/lib/jvm"}, "env-ref")
    contract = build_server_service_contract(
        spec,
        environment_digest=environment.digest,
        artifact_digest="b" * 64,
        runtime_identity_digest="c" * 64,
    )
    task_group = make_task_group("minecraft-server-service")
    runtime_factory = LocalServiceRuntimeComposer(
        state_root=tmp_path / "state",
        intent_root=tmp_path / "intents",
        capture_root=tmp_path / "captures",
        operating_system=TEST_OPERATING_SYSTEM,
        process_backend=_ComposedServiceBackend(),
        process_supervisor=build_process_supervisor(task_group),
        effect_journal_factory=sqlite_effect_intent_journal,
    )
    runtime = compose_minecraft_server_service_runtime(
        spec,
        contract,
        environment=environment,
        runtime_factory=runtime_factory,
    )
    # Construction proves the MC composition contributes only TCP readiness;
    # the injected backend keeps this test independent of a live Java server.
    assert runtime is not None


def test_minecraft_composition_binds_provider_once() -> None:
    environment, runtime_binding = _test_environment(
        bridge_spec=MinecraftBridgeSpec(command=("node", "bridge.js"), cwd="/srv/minecraft/bridge"),
    )
    task_group = make_task_group("minecraft-environment")
    assembly = compose_minecraft_environment(
        environment,
        runtime_binding,
        operating_system=TEST_OPERATING_SYSTEM,
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    assert assembly.implementation.identity.environment_id == "minecraft"
    assert assembly.runtime.runtime_identity.runtime_id == "minecraft.environment.session"


def test_minecraft_composition_joins_generic_participant_endpoint_without_second_lifecycle() -> None:
    environment, runtime_binding = _test_environment(
        bridge_spec=MinecraftBridgeSpec(command=("node", "bridge.js"), cwd="/srv/minecraft/bridge"),
    )
    task_group = make_task_group("minecraft-environment")
    assembly = compose_minecraft_environment(
        environment,
        runtime_binding,
        operating_system=TEST_OPERATING_SYSTEM,
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    from noetrium_platform.capabilities.participant.core.api import (
        participant_implementation_id,
        participant_implementation_kind,
    )

    endpoint = compose_minecraft_participant_endpoint(assembly.implementation, assembly.runtime)
    assert participant_implementation_kind(endpoint.implementation_identity) == "environment"
    assert participant_implementation_id(endpoint.implementation_identity) == "minecraft"
    assert endpoint.runtime_identity.runtime_id == "minecraft.environment.session"
    assert endpoint.implementation is assembly.implementation




def test_minecraft_agent_observation_uses_canonical_decision_view_not_raw_state() -> None:
    from noetrium_platform.composition.minecraft_agent import MinecraftAgentObservationPort

    bridge = _EntityProjectionBridge()
    session = MinecraftEnvironmentSession(
        session_id="mc-agent-context",
        implementation=_test_implementation(bridge, max_entities=8),
        bridge=bridge,
    )
    context = ExecutionContext("run", "trace", "span", task_id="task")

    observation = MinecraftAgentObservationPort(session).observe(context)
    entities = observation.state["nearby_entities"]
    assert entities["mode"] == "summary"
    assert entities["counts"] == {"player": 1, "rabbit": 2}
    assert len(entities["rows"]) == 2
    assert "events" not in observation.state
    assert observation.evidence_payload["events"]
    session.close()


def test_minecraft_agent_executor_preserves_effect_identity_and_possible_certainty() -> None:
    from noetrium_platform.capabilities.environment.api import ActionResult
    from noetrium_platform.composition.minecraft_agent import MinecraftAgentActionExecutor
    from noetrium_platform.capabilities.participant.agent.api import AgentActionStep
    from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt

    context = ExecutionContext("run", "trace", "span", task_id="task")
    step = AgentActionStep(
        "action:possible",
        "wait",
        {"ms": 1},
        "minecraft.wait",
        "sequence:1",
        0,
    )
    effect = EffectReceipt(
        "minecraft-action:action:possible",
        "d" * 64,
        EffectClass.RECONCILABLE,
        EffectCertainty.INDETERMINATE,
        provider_instance_id="minecraft:test",
        provider_receipt=step.action_id,
    )

    class Session:
        def act(self, request, control):
            control.checkpoint()
            assert request.action_id == step.action_id
            return ActionResult(request.action_id, True, None, effect, {"verified": False})

    receipt = MinecraftAgentActionExecutor(Session()).execute(step, context)
    assert receipt.accepted is True
    assert receipt.effect_id == effect.effect_id
    assert receipt.effect_certainty == "indeterminate"


def test_jsonl_bridge_restarts_dead_transport_before_durable_reconciliation() -> None:
    task_group = make_task_group("minecraft-bridge-restart-reconcile")
    processes: list[_FakeProcess] = []

    def process_factory(_command, **_kwargs):
        process = _FakeProcess()
        processes.append(process)
        return process

    bridge = JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25567),
        spec=MinecraftBridgeSpec(
            command=("fake-node",), cwd=".", command_timeout_s=1, connect_timeout_s=1
        ),
        agent=MinecraftAgentSpec(version="1.21.6"),
        operating_system=TEST_OPERATING_SYSTEM,
        process_factory=process_factory,
        process_supervisor=build_process_supervisor(task_group),
        task_group=task_group,
    )
    bridge.start()
    assert len(processes) == 1
    processes[0].returncode = 134
    processes[0].stdout.close()
    processes[0].stderr.close()

    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("durable-action", "wait", {"ms": 1}, context)
    proof = bridge.reconcile_action(
        "durable-action", request=request, context=context,
        **_test_reconcile_unit_kwargs(request),
    )

    assert len(processes) == 2
    assert proof.disposition is ActionReconciliationDisposition.NOT_APPLIED
    assert proof.diagnostics["bridge_restarted"] is True
    bridge.close()
