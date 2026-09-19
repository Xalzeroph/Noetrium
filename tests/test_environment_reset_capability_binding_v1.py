from __future__ import annotations

from noetrium_platform.capabilities.environment.api import (
    EnvironmentIdentity,
    EnvironmentProviderCapabilities,
    EnvironmentProviderPort,
    EnvironmentResetPort,
    EnvironmentSession,
    Observation,
)
from noetrium_platform.capabilities.environment.composition import (
    EnvironmentResetCapabilityBinding,
    environment_reset_capability_payload,
)
from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, EffectClass


class _ResetSession:
    def __init__(self) -> None:
        self.calls = 0

    def observe(self, context):
        return Observation("obs:before", "generation:0", {"state": "before"})

    def reset(self, context):
        self.calls += 1
        return Observation(
            f"obs:reset:{self.calls}",
            f"generation:{self.calls}",
            {"state": "initial", "task_id": context.task_id},
        )

    def act(self, request):
        raise AssertionError("reset binding must not route through act")

    def reconcile(self, effect, context):
        raise AssertionError("reset binding must not reconcile")

    def close(self):
        pass


def test_environment_reset_capability_is_native_idempotent_control() -> None:
    session = _ResetSession()
    assert isinstance(session, EnvironmentSession)
    assert isinstance(session, EnvironmentResetPort)

    binding = EnvironmentResetCapabilityBinding(session)
    descriptor = binding.describe("environment.reset")
    assert descriptor.effect_class is EffectClass.IDEMPOTENT

    context = ExecutionContext("run", "trace", "span", task_id="task:1")
    request = CapabilityRequest(
        "environment.reset",
        environment_reset_capability_payload({"trial": 2}),
        context,
        "reset:task:1:trial:2",
    )
    result = binding.invoke(request)
    assert result.capability_id == "environment.reset"
    assert result.payload["reset"] is True
    assert result.payload["metadata"] == {"trial": 2}
    assert result.payload["observation"]["payload"] == {
        "state": "initial",
        "task_id": "task:1",
    }
    assert result.generation == "generation:1"
    assert result.request_digest is not None
    assert session.calls == 1
