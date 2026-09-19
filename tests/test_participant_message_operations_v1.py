from __future__ import annotations

from noetrium_platform.capabilities.participant.api import (
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
    ParticipantTopology,
    ParticipantTopologyMember,
)
from noetrium_platform.capabilities.participant.agent.runtime import (
    AgentTurnFactBuffer,
    AgentTurnFactKind,
    ParticipantMessageKind,
    ParticipantMessageRouteRequest,
    RuntimeParticipantMessageRouter,
)
from noetrium_platform.composition.participant_message import (
    PARTICIPANT_MESSAGE_ROUTE_OPERATION,
    ParticipantMessageOperations,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    ExecutionContext,
    InMemoryMachineJournal,
    OperationExecutor,
    OperationStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    communication_initial_data,
    default_communication_runtime_host,
)
from noetrium_platform.research.execution.workflow.runtime.operation_dispatch import KernelOperationDispatcher


def _member(participant_id: str, role: str, token: str) -> ParticipantTopologyMember:
    digest = token * 64
    return ParticipantTopologyMember(
        participant_id=participant_id,
        role=role,
        requirement_digest=digest,
        binding_digest=digest,
        architecture_revision_digest=digest,
    )


def _broadcast_request() -> ParticipantMessageRouteRequest:
    topology = ParticipantTopology(
        topology_id="broadcast-topology",
        members=(
            _member("agent-a", "speaker", "a"),
            _member("agent-b", "listener", "b"),
            _member("agent-c", "listener", "c"),
        ),
    )
    entry = ParticipantMessageScheduleEntry(
        message_id="broadcast-1",
        sender_participant_id="agent-a",
        recipient_participant_ids=("agent-c", "agent-b"),
        sequence=0,
    )
    schedule = ParticipantMessageSchedule.for_topology(
        "round-1",
        topology,
        (entry,),
    )
    return ParticipantMessageRouteRequest.from_schedule(
        schedule,
        entry,
        "proposal",
        priority=7,
        kind=ParticipantMessageKind.TASK,
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        task_id="task-1",
        decision_cycle_id="cycle-1",
    )


def _target() -> ComponentIdentity:
    return ComponentIdentity(
        component_id="participant.message.runtime-router",
        implementation_id="runtime-program-participant-message-router",
        implementation_version="1",
        schema_version="2",
        generation_id="test-generation",
    )


def _router(*, disconnected: tuple[str, ...] = ()):
    journal = InMemoryMachineJournal()
    host = default_communication_runtime_host(journal=journal)
    initial = communication_initial_data(("agent-a", "agent-b", "agent-c"))
    for participant_id in disconnected:
        initial["peers"][participant_id]["connected"] = False
    router = RuntimeParticipantMessageRouter(
        host,
        machine_id="runtime:participant-message",
        initial_data=initial,
    )
    return router


def test_broadcast_route_crosses_kernel_operation_and_machine_fact_authority() -> None:
    router = _router()
    facts = AgentTurnFactBuffer("multi-agent-session")
    operations = ParticipantMessageOperations(
        KernelOperationDispatcher(OperationExecutor()),
        _target(),
        router,
        facts,
    )

    receipt, operation, fact_pair = operations.route(_broadcast_request(), _context())

    assert operation.status is OperationStatus.SUCCEEDED
    assert operation.operation_id == "cycle-1:participant.message.route:broadcast-1"
    assert operation.output_digest is not None
    assert len(operation.effect_receipts) == 1
    effect = operation.effect_receipts[0]
    assert effect.effect_class is EffectClass.NON_IDEMPOTENT
    assert effect.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert effect.provider_receipt == receipt.receipt_digest
    assert tuple(row.recipient_participant_id for row in receipt.recipient_receipts) == (
        "agent-b",
        "agent-c",
    )

    runtime_state = thaw_json(router.session.machine.inspect().state)["_program"]["data"]
    assert [message["text"] for message in runtime_state["inboxes"]["agent-b"]] == ["proposal"]
    assert [message["text"] for message in runtime_state["inboxes"]["agent-c"]] == ["proposal"]

    dispatch_fact, routed_fact = fact_pair
    assert dispatch_fact.kind is AgentTurnFactKind.ACTION
    assert routed_fact.kind is AgentTurnFactKind.EFFECT
    assert routed_fact.previous_fact_digest == dispatch_fact.fact_digest
    assert routed_fact.payload["stage"] == "routed"
    assert routed_fact.payload["effect_id"] == effect.effect_id
    assert routed_fact.payload["operation_invocation_id"] == operation.invocation_id
    assert facts.head_digest == routed_fact.fact_digest


def test_router_preflight_prevents_partial_broadcast_to_disconnected_peer() -> None:
    router = _router(disconnected=("agent-c",))

    try:
        router.route(_broadcast_request())
    except RuntimeError as exc:
        assert "disconnected" in str(exc)
    else:
        raise AssertionError("disconnected broadcast must fail closed")

    runtime_state = thaw_json(router.session.machine.inspect().state)["_program"]["data"]
    assert runtime_state["inboxes"]["agent-b"] == []
    assert runtime_state["inboxes"]["agent-c"] == []


def test_participant_message_route_is_globally_idempotency_protected() -> None:
    dispatcher = KernelOperationDispatcher(OperationExecutor())
    result = dispatcher.dispatch(
        root_context=_context(),
        operation_id="cycle-1:participant.message.route:unprotected",
        operation_type=PARTICIPANT_MESSAGE_ROUTE_OPERATION,
        target=_target(),
        payload={"message_id": "unprotected"},
        payload_schema="test.v1",
        idempotency_key=None,
        handler=lambda request: request.payload,
    )

    assert result.status is OperationStatus.FAILED
    assert result.diagnostics["exception_type"] == "OperationSemanticPolicyViolation"
