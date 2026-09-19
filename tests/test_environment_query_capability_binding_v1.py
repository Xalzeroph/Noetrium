from __future__ import annotations

from noetrium_platform.capabilities.environment.api import (
    EnvironmentQuery,
    EnvironmentQueryResult,
    Observation,
)
from noetrium_platform.capabilities.environment.composition import (
    EnvironmentQueryCapabilityBinding,
    environment_query_capability_payload,
)
from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class _Query:
    def __init__(self) -> None:
        self.requests: list[EnvironmentQuery] = []

    def query(self, request: EnvironmentQuery) -> EnvironmentQueryResult:
        self.requests.append(request)
        return EnvironmentQueryResult(
            query_id=request.query_id,
            supported=True,
            payload={"width": 1440, "height": 900},
            observation=Observation(
                observation_id="snapshot-1",
                generation="gui-generation-7",
                payload={"kind": "screenshot"},
                artifact_refs=("artifact:screenshot-1",),
            ),
            diagnostics={"source": "test"},
        )


def test_environment_query_capability_preserves_read_only_query_identity() -> None:
    query = _Query()
    binding = EnvironmentQueryCapabilityBinding(query)
    context = ExecutionContext(
        "run-1",
        "trace-1",
        "span-1",
        task_id="task-1",
        decision_cycle_id="cycle-1",
    )
    request = CapabilityRequest(
        "environment.query",
        environment_query_capability_payload("state", {"view": "screen"}),
        context,
    )

    result = binding.invoke(request)

    assert binding.describe("environment.query").effect_class.value == "pure"
    assert len(query.requests) == 1
    assert query.requests[0].query_type == "state"
    assert query.requests[0].payload == {"view": "screen"}
    assert result.effect is None
    assert result.generation == "gui-generation-7"
    assert result.artifacts == ("artifact:screenshot-1",)
    assert result.payload == {
        "supported": True,
        "payload": {"height": 900, "width": 1440},
        "observation": {
            "observation_id": "snapshot-1",
            "generation": "gui-generation-7",
            "payload": {"kind": "screenshot"},
            "artifact_refs": ("artifact:screenshot-1",),
        },
    }
