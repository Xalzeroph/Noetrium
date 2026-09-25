"""Reference multi-agent RuntimeProgram.

The Runtime Machine owns queue, delivery, scheduling, in-flight identity,
budgets and transcript state. Participant execution happens outside the
interpreter between a journaled select and a journaled complete/fail event.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineKind,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines import (
    MachineEvent,
    ProgramHandlerRegistry,
    ProgramNodeRequest,
    ProgramNodeResult,
    ProgramRule,
    ProgramRuleSet,
    ResearchProgram,
    RuleDispatchMode,
    RuntimeConcern,
    UnhandledEventPolicy,
    build_rule_handlers,
    compile_rule_program,
)

from .contracts import (
    CommunicationTopology,
    MultiAgentDeliveryReceipt,
    MultiAgentDeliveryStatus,
    MultiAgentMessage,
    MultiAgentRunStatus,
)


def message_payload(message: MultiAgentMessage) -> JsonObject:
    if not isinstance(message, MultiAgentMessage):
        raise TypeError("multi-agent message payload requires MultiAgentMessage")
    return {
        "sender": message.sender,
        "recipient": message.recipient,
        "content": message.content,
        "turn": message.turn,
        "conversation_id": message.conversation_id,
        "causal_parent_ids": message.causal_parent_ids,
        "delivery_attempt": message.delivery_attempt,
        "message_id": message.message_id,
    }


def message_from_payload(value: object) -> MultiAgentMessage:
    if not isinstance(value, Mapping):
        raise TypeError("multi-agent message state must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("multi-agent message state must decode to an object")
    parents = decoded.get("causal_parent_ids", ())
    if not isinstance(parents, (tuple, list)):
        raise TypeError("multi-agent causal_parent_ids must be a sequence")
    message = MultiAgentMessage(
        sender=decoded.get("sender"),
        recipient=decoded.get("recipient"),
        content=decoded.get("content"),
        turn=decoded.get("turn"),
        conversation_id=decoded.get("conversation_id", "default"),
        causal_parent_ids=tuple(parents),
        delivery_attempt=decoded.get("delivery_attempt", 0),
    )
    supplied = decoded.get("message_id")
    if supplied is not None and supplied != message.message_id:
        raise ValueError("multi-agent message digest mismatch")
    return message


def receipt_payload(receipt: MultiAgentDeliveryReceipt) -> JsonObject:
    if not isinstance(receipt, MultiAgentDeliveryReceipt):
        raise TypeError("multi-agent receipt payload requires typed receipt")
    return {
        "message_id": receipt.message_id,
        "sender": receipt.sender,
        "recipient": receipt.recipient,
        "status": receipt.status.value,
        "attempt": receipt.attempt,
        "round": receipt.round,
        "detail": receipt.detail,
        "receipt_id": receipt.receipt_id,
    }


def receipt_from_payload(value: object) -> MultiAgentDeliveryReceipt:
    if not isinstance(value, Mapping):
        raise TypeError("multi-agent receipt state must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("multi-agent receipt state must decode to an object")
    receipt = MultiAgentDeliveryReceipt(
        message_id=decoded.get("message_id"),
        sender=decoded.get("sender"),
        recipient=decoded.get("recipient"),
        status=MultiAgentDeliveryStatus(decoded.get("status")),
        attempt=decoded.get("attempt"),
        round=decoded.get("round"),
        detail=decoded.get("detail", ""),
    )
    supplied = decoded.get("receipt_id")
    if supplied is not None and supplied != receipt.receipt_id:
        raise ValueError("multi-agent receipt digest mismatch")
    return receipt


def multi_agent_rule_set() -> ProgramRuleSet:
    return ProgramRuleSet(
        (
            ProgramRule(
                "select",
                "multi_agent.select",
                "orchestration.multi-agent.select",
                priority=100,
                semantic=RuntimeConcern.LOGICAL_SCHEDULING.value,
            ),
            ProgramRule(
                "complete",
                "multi_agent.complete",
                "orchestration.multi-agent.complete",
                priority=100,
                semantic=RuntimeConcern.COMMUNICATION.value,
            ),
            ProgramRule(
                "fail",
                "multi_agent.fail",
                "orchestration.multi-agent.fail",
                priority=100,
                semantic=RuntimeConcern.RECOVERY.value,
            ),
            ProgramRule(
                "pause",
                "multi_agent.pause",
                "orchestration.multi-agent.pause",
                priority=100,
                semantic=RuntimeConcern.INTERVENTION.value,
            ),
        ),
        mode=RuleDispatchMode.FIRST,
        unhandled=UnhandledEventPolicy.ERROR,
    )


def compile_multi_agent_runtime_program() -> ResearchProgram:
    return compile_rule_program(
        program_id="orchestration.multi-agent.runtime",
        kind=MachineKind.RUNTIME,
        version="2",
        state_schema="orchestration.multi-agent.runtime-state.v2",
        rules=multi_agent_rule_set(),
    )


def multi_agent_initial_data(
    topology: CommunicationTopology,
    initials: tuple[MultiAgentMessage, ...],
) -> JsonObject:
    if not isinstance(topology, CommunicationTopology):
        raise TypeError("multi-agent initial state requires CommunicationTopology")
    if type(initials) is not tuple or not initials:
        raise ValueError("multi-agent initial messages must be a non-empty tuple")
    conversation_id = initials[0].conversation_id
    if any(
        not isinstance(message, MultiAgentMessage)
        or message.conversation_id != conversation_id
        or message.turn != 0
        or message.causal_parent_ids
        or not topology.can_send(message.sender, message.recipient)
        for message in initials
    ):
        raise ValueError(
            "multi-agent initial messages must be topology-valid turn-zero messages"
        )
    ids = tuple(message.message_id for message in initials)
    if len(ids) != len(set(ids)):
        raise ValueError("multi-agent initial messages must have unique IDs")
    return {
        "topology_digest": topology.topology_digest,
        "conversation_id": conversation_id,
        "pending": tuple(message_payload(message) for message in initials),
        "in_flight": None,
        "delivered": (),
        "delivered_message_ids": (),
        "receipts": (),
        "rounds": 0,
        "run_status": MultiAgentRunStatus.RUNNING.value,
        "error": None,
    }


def _data(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    value = thaw_json(request.data)
    if not isinstance(value, dict):
        raise TypeError("multi-agent Runtime state must be an object")
    return value


def _event_payload(request: ProgramNodeRequest) -> dict[str, JsonValue]:
    value = thaw_json(request.payload)
    if not isinstance(value, dict):
        raise TypeError("multi-agent Runtime event payload must be an object")
    return value


def _pending(data: Mapping[str, JsonValue]) -> list[MultiAgentMessage]:
    rows = data.get("pending", ())
    if not isinstance(rows, (tuple, list)):
        raise TypeError("multi-agent pending state must be a sequence")
    return [message_from_payload(row) for row in rows]


def _delivered(data: Mapping[str, JsonValue]) -> list[MultiAgentMessage]:
    rows = data.get("delivered", ())
    if not isinstance(rows, (tuple, list)):
        raise TypeError("multi-agent delivered state must be a sequence")
    return [message_from_payload(row) for row in rows]


def _receipts(data: Mapping[str, JsonValue]) -> list[MultiAgentDeliveryReceipt]:
    rows = data.get("receipts", ())
    if not isinstance(rows, (tuple, list)):
        raise TypeError("multi-agent receipt state must be a sequence")
    return [receipt_from_payload(row) for row in rows]


def _in_flight(data: Mapping[str, JsonValue]) -> MultiAgentMessage | None:
    value = data.get("in_flight")
    return None if value is None else message_from_payload(value)


def _positive_limit(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _receipt(
    message: MultiAgentMessage,
    status: MultiAgentDeliveryStatus,
    round_number: int,
    detail: str = "",
) -> MultiAgentDeliveryReceipt:
    return MultiAgentDeliveryReceipt(
        message.message_id,
        message.sender,
        message.recipient,
        status,
        message.delivery_attempt,
        round_number,
        detail,
    )


def _validate_output(
    *,
    topology: CommunicationTopology,
    parent: MultiAgentMessage,
    output: MultiAgentMessage,
    conversation_id: str,
) -> None:
    if output.sender != parent.recipient:
        raise ValueError("node emitted a message with a foreign sender")
    if output.conversation_id != conversation_id:
        raise ValueError("node emitted a cross-conversation message")
    if output.turn != parent.turn + 1:
        raise ValueError("node emitted a non-contiguous message turn")
    if parent.message_id not in output.causal_parent_ids:
        raise ValueError(
            "node output must carry its causal parent message ID"
        )
    if not topology.can_send(output.sender, output.recipient):
        raise ValueError("message violates communication topology")


def multi_agent_operation_handlers(
    topology: CommunicationTopology,
) -> ProgramHandlerRegistry:
    if not isinstance(topology, CommunicationTopology):
        raise TypeError("multi-agent handlers require CommunicationTopology")
    operations = ProgramHandlerRegistry()

    def select(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        if data.get("topology_digest") != topology.topology_digest:
            raise ValueError("multi-agent topology identity drifted")
        current = _in_flight(data)
        if current is not None:
            return ProgramNodeResult(
                value={
                    "selected": message_payload(current),
                    "replayed": True,
                },
                events=({
                    "type": "multi_agent_selection_replayed",
                    "message_id": current.message_id,
                },),
            )

        pending = _pending(data)
        delivered = _delivered(data)
        max_rounds = _positive_limit(
            payload.get("max_rounds"),
            "multi-agent max_rounds",
        )
        max_messages = _positive_limit(
            payload.get("max_messages"),
            "multi-agent max_messages",
        )
        if not pending:
            return ProgramNodeResult(
                value={"selected": None},
                state_update={
                    "run_status": MultiAgentRunStatus.COMPLETED.value,
                },
                status=MachineStatus.COMPLETED,
                events=({"type": "multi_agent_completed"},),
            )
        next_message = pending[0]
        if next_message.turn >= max_rounds:
            return ProgramNodeResult(
                value={"selected": None},
                state_update={
                    "run_status": MultiAgentRunStatus.MAX_ROUNDS.value,
                },
                status=MachineStatus.WAITING,
                wait_reason="multi-agent maximum rounds reached",
                events=({
                    "type": "multi_agent_budget_exhausted",
                    "budget": "rounds",
                    "limit": max_rounds,
                },),
            )
        if len(delivered) >= max_messages:
            return ProgramNodeResult(
                value={"selected": None},
                state_update={
                    "run_status": MultiAgentRunStatus.MAX_MESSAGES.value,
                },
                status=MachineStatus.WAITING,
                wait_reason="multi-agent maximum messages reached",
                events=({
                    "type": "multi_agent_budget_exhausted",
                    "budget": "messages",
                    "limit": max_messages,
                },),
            )
        if (
            next_message.sender not in topology.nodes
            or next_message.recipient not in topology.nodes
            or not topology.can_send(
                next_message.sender,
                next_message.recipient,
            )
        ):
            raise ValueError("pending message violates communication topology")
        conversation_id = data.get("conversation_id")
        if next_message.conversation_id != conversation_id:
            raise ValueError("pending message crosses conversation boundary")
        return ProgramNodeResult(
            value={
                "selected": message_payload(next_message),
                "replayed": False,
            },
            state_update={
                "pending": tuple(
                    message_payload(message) for message in pending[1:]
                ),
                "in_flight": message_payload(next_message),
                "run_status": MultiAgentRunStatus.RUNNING.value,
            },
            events=({
                "type": "multi_agent_message_selected",
                "message_id": next_message.message_id,
                "recipient": next_message.recipient,
                "turn": next_message.turn,
            },),
        )

    def complete(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        current = _in_flight(data)
        if current is None:
            raise RuntimeError("multi-agent completion requires in-flight message")
        message_id = payload.get("message_id")
        if message_id != current.message_id:
            raise ValueError("multi-agent completion message identity mismatch")
        outputs_value = payload.get("outputs", ())
        if not isinstance(outputs_value, (tuple, list)):
            raise TypeError("multi-agent outputs must be a sequence")
        outputs = tuple(message_from_payload(row) for row in outputs_value)
        conversation_id = data.get("conversation_id")
        if type(conversation_id) is not str:
            raise TypeError("multi-agent conversation identity is invalid")

        pending = _pending(data)
        delivered = _delivered(data)
        receipts = _receipts(data)
        delivered_ids_value = data.get("delivered_message_ids", ())
        if not isinstance(delivered_ids_value, (tuple, list)):
            raise TypeError("multi-agent delivered_message_ids must be a sequence")
        delivered_ids = [str(value) for value in delivered_ids_value]
        if current.message_id in delivered_ids:
            raise RuntimeError("in-flight message was already delivered")

        round_number = current.turn + 1
        delivered.append(current)
        delivered_ids.append(current.message_id)
        receipts.append(
            _receipt(
                current,
                MultiAgentDeliveryStatus.DELIVERED,
                round_number,
            )
        )
        scheduled = set(delivered_ids)
        scheduled.update(message.message_id for message in pending)

        for output in outputs:
            _validate_output(
                topology=topology,
                parent=current,
                output=output,
                conversation_id=conversation_id,
            )
            if output.message_id in scheduled:
                receipts.append(
                    _receipt(
                        output,
                        MultiAgentDeliveryStatus.DUPLICATE,
                        round_number,
                        "message ID already scheduled",
                    )
                )
                continue
            edge = topology.edge(output.sender, output.recipient)
            in_flight_count = sum(
                1
                for message in pending
                if message.sender == output.sender
                and message.recipient == output.recipient
            )
            if in_flight_count >= edge.max_in_flight:
                receipts.append(
                    _receipt(
                        output,
                        MultiAgentDeliveryStatus.REJECTED,
                        round_number,
                        "edge in-flight limit reached",
                    )
                )
                continue
            pending.append(output)
            scheduled.add(output.message_id)

        rounds = data.get("rounds", 0)
        if type(rounds) is not int or rounds < 0:
            raise ValueError("multi-agent round state is invalid")
        rounds = max(rounds, round_number)
        completed = not pending
        return ProgramNodeResult(
            value={
                "message_id": current.message_id,
                "output_ids": tuple(output.message_id for output in outputs),
            },
            state_update={
                "pending": tuple(
                    message_payload(message) for message in pending
                ),
                "in_flight": None,
                "delivered": tuple(
                    message_payload(message) for message in delivered
                ),
                "delivered_message_ids": tuple(delivered_ids),
                "receipts": tuple(
                    receipt_payload(receipt) for receipt in receipts
                ),
                "rounds": rounds,
                "run_status": (
                    MultiAgentRunStatus.COMPLETED.value
                    if completed
                    else MultiAgentRunStatus.RUNNING.value
                ),
                "error": None,
            },
            status=(
                MachineStatus.COMPLETED
                if completed
                else MachineStatus.RUNNABLE
            ),
            events=({
                "type": "multi_agent_message_completed",
                "message_id": current.message_id,
                "output_count": len(outputs),
                "pending_count": len(pending),
                "round": rounds,
            },),
        )

    def fail(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        payload = _event_payload(request)
        current = _in_flight(data)
        if current is None:
            raise RuntimeError("multi-agent failure requires in-flight message")
        message_id = payload.get("message_id")
        if message_id != current.message_id:
            raise ValueError("multi-agent failure message identity mismatch")
        error = payload.get("error")
        if type(error) is not str or not error.strip():
            raise ValueError("multi-agent failure error is required")
        delivered = _delivered(data)
        receipts = _receipts(data)
        delivered_ids_value = data.get("delivered_message_ids", ())
        if not isinstance(delivered_ids_value, (tuple, list)):
            raise TypeError("multi-agent delivered_message_ids must be a sequence")
        delivered_ids = [str(value) for value in delivered_ids_value]
        if current.message_id not in delivered_ids:
            delivered.append(current)
            delivered_ids.append(current.message_id)
        receipts.append(
            _receipt(
                current,
                MultiAgentDeliveryStatus.FAILED,
                current.turn + 1,
                error,
            )
        )
        return ProgramNodeResult(
            value={"message_id": current.message_id, "error": error},
            state_update={
                "in_flight": None,
                "delivered": tuple(
                    message_payload(message) for message in delivered
                ),
                "delivered_message_ids": tuple(delivered_ids),
                "receipts": tuple(
                    receipt_payload(receipt) for receipt in receipts
                ),
                "run_status": MultiAgentRunStatus.FAILED.value,
                "error": error,
            },
            status=MachineStatus.FAILED,
            events=({
                "type": "multi_agent_message_failed",
                "message_id": current.message_id,
                "error": error,
            },),
        )

    def pause(request: ProgramNodeRequest) -> ProgramNodeResult:
        data = _data(request)
        reason = _event_payload(request).get("reason", "cancelled")
        if type(reason) is not str or not reason.strip():
            raise ValueError("multi-agent pause reason is required")
        return ProgramNodeResult(
            value={"reason": reason},
            state_update={
                "run_status": MultiAgentRunStatus.CANCELLED.value,
            },
            status=MachineStatus.WAITING,
            wait_reason=f"multi-agent paused: {reason}",
            events=({
                "type": "multi_agent_paused",
                "reason": reason,
                "in_flight": data.get("in_flight") is not None,
            },),
        )

    operations.register(
        "orchestration.multi-agent.select",
        select,
        implementation_digest=canonical_digest({
            "operation": "orchestration.multi-agent.select",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "orchestration.multi-agent.complete",
        complete,
        implementation_digest=canonical_digest({
            "operation": "orchestration.multi-agent.complete",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "orchestration.multi-agent.fail",
        fail,
        implementation_digest=canonical_digest({
            "operation": "orchestration.multi-agent.fail",
            "implementation_revision": 1,
        }),
    )
    operations.register(
        "orchestration.multi-agent.pause",
        pause,
        implementation_digest=canonical_digest({
            "operation": "orchestration.multi-agent.pause",
            "implementation_revision": 1,
        }),
    )
    return operations


def multi_agent_handlers(
    topology: CommunicationTopology,
) -> ProgramHandlerRegistry:
    return build_rule_handlers(
        multi_agent_rule_set(),
        multi_agent_operation_handlers(topology),
    )


__all__ = [
    "compile_multi_agent_runtime_program",
    "message_from_payload",
    "message_payload",
    "multi_agent_handlers",
    "multi_agent_initial_data",
    "multi_agent_operation_handlers",
    "multi_agent_rule_set",
    "receipt_from_payload",
    "receipt_payload",
]
