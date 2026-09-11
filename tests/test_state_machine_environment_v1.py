from __future__ import annotations

from dataclasses import replace
import json

import pytest

from noetrium_platform.capabilities.environment.runtime.api import (
    ActionIdentityViolation,
    ActionRequest,
    StateMachineDynamicsIdentity,
    StateMachineEnvironmentSpec,
    StateTransition,
    thaw_json_mapping,
)
from noetrium_platform.capabilities.environment.api import state_machine as canonical_state_machine
from noetrium_platform.capabilities.environment.runtime.composition import (
    compose_state_machine_environment,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest


class _CounterDynamics:
    identity = StateMachineDynamicsIdentity(
        "test.counter.v1",
        "1",
        canonical_digest({"transition": "increment.v1"}),
    )

    def transition(self, state, request, context):
        del context
        current = thaw_json_mapping(state)
        if request.action_type == "increment":
            current["value"] = int(current["value"]) + int(request.payload["amount"])
            return StateTransition(current, True, {"code": "incremented"})
        return StateTransition(current, False, {"code": "rejected"})


def _assembly():
    dynamics = _CounterDynamics()
    return compose_state_machine_environment(
        StateMachineEnvironmentSpec(
            environment_id="counter-world",
            dynamics=dynamics.identity,
            initial_state={"value": 0, "history": []},
            action_types=("increment", "reject"),
        ),
        dynamics=dynamics,
    )


def _session():
    assembly = _assembly()
    return assembly.runtime.open_session(
        assembly.implementation,
        session_id="counter-session",
        services=object(),
    )


def test_state_machine_action_is_idempotent_and_rejects_identity_drift() -> None:
    session = _session()
    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("action-1", "increment", {"amount": 2}, context)

    first = session.act(request)
    replay = session.act(request)

    assert replay == first
    assert session.observe(context).payload["state"]["value"] == 2
    with pytest.raises(ActionIdentityViolation, match="reused with drift"):
        session.act(replace(request, payload={"amount": 3}))
    assert session.reconcile(first.effect, context) == first.effect


def test_state_machine_checkpoint_roundtrip_preserves_state_and_action_ledger() -> None:
    source = _session()
    context = ExecutionContext("run", "trace", "span", task_id="task")
    request = ActionRequest("action-1", "increment", {"amount": 2}, context)
    result = source.act(request)
    payload = source.checkpoint()

    restored = _session()
    restored.restore(payload)

    assert restored.act(request) == result
    assert restored.observe(context).payload["state"]["value"] == 2
    assert restored.diagnostics()["known_action_ids"] == 1


def test_state_machine_restore_is_validate_before_mutate() -> None:
    session = _session()
    context = ExecutionContext("run", "trace", "span", task_id="task")
    before = session.diagnostics()
    with pytest.raises(ValueError, match="checkpoint"):
        session.restore(b'{"schema_version":"wrong"}')
    assert session.diagnostics()["state_digest"] == before["state_digest"]


def test_state_machine_restore_rejects_result_coercion_and_ledger_state_drift() -> None:
    source = _session()
    context = ExecutionContext("run", "trace", "span", task_id="task")
    source.act(ActionRequest("action-1", "increment", {"amount": 2}, context))
    document = json.loads(source.checkpoint())

    coerced = json.loads(json.dumps(document))
    coerced["actions"][0]["result"]["accepted"] = 1
    target = _session()
    before = target.diagnostics()["state_digest"]
    with pytest.raises(ValueError, match="checkpoint"):
        target.restore(json.dumps(coerced).encode("utf-8"))
    assert target.diagnostics()["state_digest"] == before

    drifted = json.loads(json.dumps(document))
    drifted["state"]["value"] = 99
    drifted["state_digest"] = canonical_digest(drifted["state"])
    with pytest.raises(ValueError, match="invalid or incompatible"):
        target.restore(json.dumps(drifted).encode("utf-8"))
    assert target.diagnostics()["state_digest"] == before

    uppercase_digest = json.loads(json.dumps(document))
    uppercase_digest["actions"][0]["request_digest"] = uppercase_digest["actions"][0][
        "request_digest"
    ].upper()
    uppercase_digest["actions"][0]["result"]["effect"][
        "request_digest"
    ] = uppercase_digest["actions"][0]["request_digest"]
    with pytest.raises(ValueError, match="checkpoint"):
        target.restore(json.dumps(uppercase_digest).encode("utf-8"))
    assert target.diagnostics()["state_digest"] == before


def test_state_machine_action_payload_must_be_portable_json() -> None:
    session = _session()
    context = ExecutionContext("run", "trace", "span", task_id="task")
    before = session.diagnostics()["state_digest"]

    with pytest.raises(TypeError, match="unsupported bytes"):
        session.act(ActionRequest("action-1", "increment", {"amount": b"2"}, context))

    assert session.diagnostics()["state_digest"] == before
    assert session.diagnostics()["known_action_ids"] == 0


def test_rejected_transition_cannot_mutate_authoritative_state() -> None:
    class _InvalidDynamics(_CounterDynamics):
        def transition(self, state, request, context):
            del state, request, context
            return StateTransition({"value": 99, "history": []}, False, {})

    dynamics = _InvalidDynamics()
    assembly = compose_state_machine_environment(
        StateMachineEnvironmentSpec(
            environment_id="counter-world",
            dynamics=dynamics.identity,
            initial_state={"value": 0, "history": []},
            action_types=("increment",),
        ),
        dynamics=dynamics,
    )
    session = assembly.runtime.open_session(
        assembly.implementation,
        session_id="counter-session",
        services=object(),
    )
    request = ActionRequest(
        "action-1",
        "increment",
        {"amount": 1},
        ExecutionContext("run", "trace", "span"),
    )
    with pytest.raises(ValueError, match="rejected.*cannot mutate"):
        session.act(request)


def test_runtime_state_machine_surface_forwards_canonical_contracts() -> None:
    from noetrium_platform.capabilities.environment.runtime.api import state_machine as runtime_state_machine

    for name in (
        "StateMachineDynamicsIdentity",
        "StateMachineEnvironmentSpec",
        "StateTransition",
        "StateMachineDynamicsPort",
        "freeze_json_mapping",
        "thaw_json",
        "thaw_json_mapping",
    ):
        assert getattr(runtime_state_machine, name) is getattr(canonical_state_machine, name)
