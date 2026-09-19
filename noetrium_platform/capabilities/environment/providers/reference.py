from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionRequest,
    JsonValue,
    StateMachineDynamicsIdentity,
    StateMachineEnvironmentSpec,
    StateTransition,
    thaw_json_mapping,
)
from noetrium_platform.capabilities.environment.runtime.composition import (
    StateMachineEnvironmentAssembly,
    compose_state_machine_environment,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest


class ReferenceCounterDynamics:
    """Tiny deterministic dynamics used to prove the downstream provider seam."""

    identity = StateMachineDynamicsIdentity(
        dynamics_id="reference.counter.v1",
        implementation_version="1",
        artifact_digest=canonical_digest({"reference_dynamics": "counter.increment.v1"}),
    )

    def transition(
        self,
        state: Mapping[str, JsonValue],
        request: ActionRequest,
        context: ExecutionContext,
    ) -> StateTransition:
        del context
        current = thaw_json_mapping(state)
        if request.action_type == "reject":
            return StateTransition(current, False, {"code": "reference_rejected"})
        if request.action_type != "increment":
            raise ValueError(f"unsupported reference action: {request.action_type}")
        amount = request.payload.get("amount") if isinstance(request.payload, Mapping) else None
        if type(amount) is not int:
            raise TypeError("reference increment amount must be an integer")
        current_value = current.get("value")
        if type(current_value) is not int:
            raise RuntimeError("reference counter state is invalid")
        current["value"] = current_value + amount
        return StateTransition(
            current,
            True,
            {"code": "reference_incremented", "amount": amount},
        )


def reference_counter_environment() -> StateMachineEnvironmentAssembly:
    """Return a minimal non-Minecraft provider with real snapshot/recovery semantics."""

    dynamics = ReferenceCounterDynamics()
    spec = StateMachineEnvironmentSpec(
        environment_id="reference-counter",
        dynamics=dynamics.identity,
        initial_state={"value": 0},
        action_types=("increment", "reject"),
    )
    return compose_state_machine_environment(spec, dynamics=dynamics)


__all__ = ["ReferenceCounterDynamics", "reference_counter_environment"]
