from __future__ import annotations

from unittest.mock import patch

from noetrium_platform.capabilities.environment.minecraft.runtime.state import (
    MinecraftStateProjection,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.state_views import (
    MinecraftEntityState,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.session import (
    MinecraftEnvironmentSession,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


def _world() -> MinecraftStateProjection:
    state = MinecraftStateProjection(max_entities=256)
    state.username = "ResearchBot"
    state.position = {"x": 1.0, "y": 65.0, "z": 2.0}
    state.inventory = {f"item_{i}": i + 1 for i in range(30)}
    for i in range(20):
        state.entities[f"entity:{i}"] = MinecraftEntityState(
            entity_id=f"entity:{i}",
            runtime_id=i,
            username=None,
            name=f"zombie_{i % 4}",
            mob_type="zombie",
            entity_type="mob",
            position={"x": float(i), "y": 65.0, "z": 0.0},
            distance=float(i),
        )
    return state


def test_single_snapshot_produces_exact_world_digest_and_agent_view():
    world = _world()
    raw = world.compact()
    summary = world.decision_view()
    detailed = world.decision_view(detailed_entities=True)
    with patch.object(MinecraftStateProjection, "compact", wraps=world.compact) as physical:
        snapshot, digest = world.snapshot_with_digest()
        decision = world.decision_view(snapshot_state=snapshot)
        rich = world.decision_view(detailed_entities=True, snapshot_state=snapshot)
    assert physical.call_count == 1
    assert snapshot == raw
    assert digest == canonical_digest(snapshot)
    assert decision == summary
    assert rich == detailed
    assert "last_event_sequence" in snapshot
    assert "last_event_sequence" not in decision
    assert snapshot["nearby_entities"][0]["id"] in repr(snapshot)
    assert snapshot["nearby_entities"][0]["id"] not in repr(decision["nearby_entities"]["rows"])


def test_session_reuses_exact_materialized_snapshot():
    world = _world()
    proxy = type("Session", (), {"_state": world})()
    with patch.object(MinecraftStateProjection, "compact", wraps=world.compact) as physical:
        payload = MinecraftEnvironmentSession._state_payload(proxy)
        view = MinecraftEnvironmentSession._decision_view(
            proxy, snapshot_state=payload["state"]
        )
    assert physical.call_count == 1
    assert payload["state_digest"] == canonical_digest(payload["state"])
    assert view["state"] == world.decision_view()
