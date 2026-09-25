from __future__ import annotations

from noetrium_platform.capabilities.environment.api import ActionResult, Observation
from noetrium_platform.capabilities.environment.text_world.api import (
    TextWorldActionKind,
    TextWorldEnvironmentSpec,
)
from noetrium_platform.capabilities.participant.agent.api import AgentActionStep
from noetrium_platform.composition.text_world_agent import (
    TextWorldAgentActionExecutorPort,
    TextWorldAgentObservationPort,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class FakeTextWorld:
    def __init__(self) -> None:
        self.spec = TextWorldEnvironmentSpec(
            "text:test",
            "v1",
            action_vocabulary=(TextWorldActionKind.COMMAND,),
        )
        self.requests = []
        self.current = Observation("obs:0", "generation:0", {"text": "room"})

    def observe(self, context):
        del context
        return self.current

    def act(self, request):
        self.requests.append(request)
        self.current = Observation("obs:1", "generation:1", {"text": "door"})
        return ActionResult(request.action_id, True, self.current, None, {"provider": "fake"})

    def reconcile(self, effect, context):
        del context
        return effect

    def checkpoint(self):
        return b""

    def restore(self, payload):
        del payload

    def close(self):
        return None


_CONTEXT = ExecutionContext("run:1", "trace:1", "span:1")


def test_text_world_observation_projection_preserves_environment_payload() -> None:
    world = FakeTextWorld()
    observation = TextWorldAgentObservationPort(world).observe(_CONTEXT)

    assert observation.modality == "text_world"
    assert observation.state["environment_payload"] == {"text": "room"}
    assert observation.evidence_payload["environment_observation_id"] == "obs:0"


def test_text_world_action_projection_forwards_typed_payload_and_receipt() -> None:
    world = FakeTextWorld()
    executor = TextWorldAgentActionExecutorPort(world)
    step = AgentActionStep(
        "action:1",
        "command",
        {"command": "open door"},
        "skill:text-command",
        "sequence:1",
        0,
    )

    receipt = executor.execute(step, _CONTEXT)

    assert world.requests[0].payload == {"command": "open door"}
    assert receipt.accepted is True
    assert receipt.observation is not None
    assert receipt.observation.state["environment_payload"] == {"text": "door"}
    assert receipt.effect_certainty == "unknown"


def test_text_world_bridge_rejects_action_outside_declared_vocabulary() -> None:
    world = FakeTextWorld()
    executor = TextWorldAgentActionExecutorPort(world)
    step = AgentActionStep(
        "action:1",
        "look",
        {},
        "skill:look",
        "sequence:1",
        0,
    )

    try:
        executor.execute(step, _CONTEXT)
    except ValueError as exc:
        assert "not admitted" in str(exc)
    else:
        raise AssertionError("undeclared text-world action type must fail closed")
