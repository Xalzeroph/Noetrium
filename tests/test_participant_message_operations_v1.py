from __future__ import annotations

from noetrium_platform.capabilities.participant.api import (
    ParticipantMessageSchedule,
    ParticipantMessageScheduleEntry,
    ParticipantTopology,
    ParticipantTopologyMember,
)
from noetrium_platform.capabilities.participant.agent.runtime import (
    AgentCoordinationHub,
    AgentTurnFactBuffer,
    AgentTurnFactKind,
    ConversationKind,
    InProcessParticipantMessageRouter,
    ParticipantMessageRouteRequest,
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
    OperationExecutor,
    OperationStatus,
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
        kind=ConversationKind.TASK,
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
        component_id="participant.message.local-router",
        implementation_id="in-process-participant-message-router",
        implementation_version="1",
        schema_version="1",
        generation_id="test-generation",
    )


def test_broadcast_route_crosses_kernel_operation_and_fact_authority() -> None:
    hub = AgentCoordinationHub(max_agents=3, max_messages=8)
    for participant_id in ("agent-a", "agent-b", "agent-c"):
        hub.register(participant_id)
    facts = AgentTurnFactBuffer("multi-agent-session")
    operations = ParticipantMessageOperations(
        KernelOperationDispatcher(OperationExecutor()),
        _target(),
        InProcessParticipantMessageRouter(hub),
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
    assert [message.text for message in hub.pending("agent-b", "agent-a")] == ["proposal"]
    assert [message.text for message in hub.pending("agent-c", "agent-a")] == ["proposal"]

    dispatch_fact, routed_fact = fact_pair
    assert dispatch_fact.kind is AgentTurnFactKind.ACTION
    assert routed_fact.kind is AgentTurnFactKind.EFFECT
    assert routed_fact.previous_fact_digest == dispatch_fact.fact_digest
    assert routed_fact.payload["stage"] == "routed"
    assert routed_fact.payload["effect_id"] == effect.effect_id
    assert routed_fact.payload["operation_invocation_id"] == operation.invocation_id
    assert facts.head_digest == routed_fact.fact_digest


def test_router_preflight_prevents_partial_broadcast_to_disconnected_peer() -> None:
    hub = AgentCoordinationHub(max_agents=3, max_messages=8)
    for participant_id in ("agent-a", "agent-b", "agent-c"):
        hub.register(participant_id)
    hub.disconnect("agent-c")
    router = InProcessParticipantMessageRouter(hub)

    try:
        router.route(_broadcast_request())
    except RuntimeError as exc:
        assert "disconnected" in str(exc)
    else:
        raise AssertionError("disconnected broadcast must fail closed")

    assert hub.pending("agent-b", "agent-a") == ()


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
