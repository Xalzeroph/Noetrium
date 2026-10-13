from collections import deque
from types import SimpleNamespace

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftBridgeCommandResult,
    MinecraftObservationEvent,
)
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import (
    JsonlMinecraftBridge,
    MinecraftBridgeError,
)


def _bridge(monkeypatch):
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._closing = False
    bridge._recycle_pending = False
    bridge._request_counter = 0
    bridge._diagnostics = None
    bridge._diagnostic_errors = deque()
    bridge._event_stream_id = "stream-a"
    bridge._deferred_observation_events = deque()
    bridge._unacknowledged_actions = set()
    bridge._action_proofs = {}
    bridge._action_proof_digests = {}
    bridge._action_request_digests = {}
    bridge._action_unit_lineage = {}
    bridge._action_recovery_root = None
    bridge._action_recovery_dir = None
    bridge.spec = SimpleNamespace(command_timeout_s=1.0)
    bridge._transport = SimpleNamespace(
        send=lambda *args, **kwargs: None,
        process_id=17,
        stderr_tail=(),
    )
    monkeypatch.setattr(bridge, "_restart_dead_transport_owned", lambda **kwargs: False)
    monkeypatch.setattr(bridge, "_metric", lambda **kwargs: None)
    return bridge


def _event(kind, sequence):
    return MinecraftObservationEvent(
        kind=kind,
        payload={},
        sequence=sequence,
        timestamp_ms=sequence,
        stream_id="stream-a",
    )


def test_prepare_action_defers_world_events_into_next_environment_command(monkeypatch):
    bridge = _bridge(monkeypatch)
    death = _event("death", 37)
    respawn = _event("spawn_snapshot", 38)
    action = _event("action_result", 40)
    snapshot = _event("self_snapshot", 41)

    def observe(*, command, request_id, timeout_s, control=None):
        del request_id, timeout_s, control
        if command == "prepare_action":
            return MinecraftBridgeCommandResult(
                command,
                True,
                (death, respawn),
                {"ack": {
                    "state": "prepared",
                    "disposition": "not_applied",
                    "durability": "process_local",
                }},
            )
        assert command == "snapshot"
        return MinecraftBridgeCommandResult(
            command,
            True,
            (action, snapshot),
            {"ack": {"cmd": command}},
        )

    monkeypatch.setattr(bridge, "_observe_until_ack", observe)
    bridge._prepare_action_owned(
        "action-1", "a" * 64, "wait", "b" * 64, "c" * 64
    )
    assert tuple(bridge._deferred_observation_events) == (death, respawn)

    result = bridge._command_owned("snapshot", {}, timeout_s=1.0)
    assert result.events == (death, respawn, action, snapshot)
    assert result.diagnostics["deferred_event_count"] == 2
    assert not bridge._deferred_observation_events


def test_failed_environment_command_does_not_drop_deferred_world_events(monkeypatch):
    bridge = _bridge(monkeypatch)
    death = _event("death", 37)
    bridge._defer_observation_events((death,))

    def fail(**kwargs):
        raise MinecraftBridgeError("read", "BRIDGE_READ_TIMEOUT", "timeout")

    monkeypatch.setattr(bridge, "_observe_until_ack", fail)
    with pytest.raises(MinecraftBridgeError, match="BRIDGE_READ_TIMEOUT"):
        bridge._command_owned("snapshot", {}, timeout_s=1.0)
    assert tuple(bridge._deferred_observation_events) == (death,)
