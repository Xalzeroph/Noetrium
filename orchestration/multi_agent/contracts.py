"""Typed values and ports for the reference multi-agent Runtime preset.

Durable execution state is owned by the Runtime Machine Journal. This module
contains only immutable topology/message/result values and participant ports;
it defines no second checkpoint or journal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium.contracts.json import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    endpoint_child_id,
    endpoint_port_name,
    endpoint_unit,
    relation_id,
    relation_unit,
    structure_unit,
)
from noetrium_platform.foundation.kernel.kernel import MachineCut


COMMUNICATION_TOPOLOGY_TRAIT = "orchestration.multi-agent.communication-topology"
COMMUNICATION_NODE_TRAIT = "orchestration.multi-agent.node"
COMMUNICATION_EDGE_RELATION = "orchestration.multi-agent.can-send"


def communication_edge(
    sender: str,
    recipient: str,
    *,
    max_in_flight: int = 64,
    ordered: bool = True,
) -> NoetriumUnit:
    if any(
        type(value) is not str or not value.strip()
        for value in (sender, recipient)
    ):
        raise ValueError("communication edge endpoints must be non-empty")
    if sender == recipient:
        raise ValueError("communication edge cannot self-reference")
    if type(max_in_flight) is not int or max_in_flight <= 0:
        raise ValueError("communication edge max_in_flight must be positive")
    if type(ordered) is not bool:
        raise TypeError("communication edge ordered must be bool")
    return relation_unit(
        (endpoint_unit(sender, None),),
        (endpoint_unit(recipient, None),),
        COMMUNICATION_EDGE_RELATION,
        parameters={
            "max_in_flight": max_in_flight,
            "ordered": ordered,
        },
    )


def communication_topology(
    nodes: tuple[str, ...],
    edges: tuple[NoetriumUnit, ...],
) -> NoetriumUnit:
    if type(nodes) is not tuple or not nodes:
        raise ValueError("multi-agent topology nodes must be non-empty")
    if any(type(node) is not str or not node.strip() for node in nodes):
        raise TypeError("multi-agent topology nodes must contain non-empty strings")
    if len(nodes) != len(set(nodes)):
        raise ValueError("multi-agent topology nodes must be unique")
    if type(edges) is not tuple or any(type(edge) is not NoetriumUnit for edge in edges):
        raise TypeError("multi-agent topology edges must be NoetriumUnit tuple")
    if len({edge.semantic_digest for edge in edges}) != len(edges):
        raise ValueError("communication edges must be unique")
    topology = structure_unit(
        "communication-topology",
        traits=(COMMUNICATION_TOPOLOGY_TRAIT,),
        members=tuple(
            structure_unit(node, traits=(COMMUNICATION_NODE_TRAIT,))
            for node in nodes
        ),
        relations=edges,
    )
    validate_communication_topology(topology)
    return topology


def validate_communication_topology(topology: NoetriumUnit) -> None:
    if (
        type(topology) is not NoetriumUnit
        or not topology.has_trait(COMMUNICATION_TOPOLOGY_TRAIT)
        or topology.attribute("kind") != "structure"
    ):
        raise TypeError("multi-agent topology must be a communication Unit")
    if any(
        not child.has_trait(COMMUNICATION_NODE_TRAIT)
        for child in topology.units("member")
    ):
        raise TypeError("multi-agent topology members must be communication nodes")
    pairs: set[tuple[str, str]] = set()
    for edge in topology.units("relation"):
        if relation_id(edge) != COMMUNICATION_EDGE_RELATION:
            raise ValueError("multi-agent topology contains unsupported relation")
        sources = edge.units("source")
        targets = edge.units("target")
        if len(sources) != 1 or len(targets) != 1:
            raise ValueError("communication edge must be binary")
        source, target = sources[0], targets[0]
        if endpoint_port_name(source) is not None or endpoint_port_name(target) is not None:
            raise ValueError("communication edge cannot bind ports")
        source_id = endpoint_child_id(source)
        target_id = endpoint_child_id(target)
        if source_id is None or target_id is None:
            raise ValueError("communication edge requires member endpoints")
        pair = (source_id, target_id)
        if pair in pairs:
            raise ValueError("communication topology has duplicate directed edge")
        pairs.add(pair)
        max_in_flight = edge.parameters.get("max_in_flight")
        ordered = edge.parameters.get("ordered")
        if type(max_in_flight) is not int or max_in_flight <= 0:
            raise ValueError("communication edge max_in_flight must be positive")
        if type(ordered) is not bool:
            raise TypeError("communication edge ordered must be bool")


def communication_nodes(topology: NoetriumUnit) -> tuple[str, ...]:
    validate_communication_topology(topology)
    return tuple(child.unit_id for child in topology.units("member"))


def _communication_relation(
    topology: NoetriumUnit,
    sender: str,
    recipient: str,
) -> NoetriumUnit:
    validate_communication_topology(topology)
    for edge in topology.units("relation"):
        source = edge.one_unit("source")
        target = edge.one_unit("target")
        if (
            endpoint_child_id(source) == sender
            and endpoint_child_id(target) == recipient
        ):
            return edge
    raise KeyError((sender, recipient))


def communication_can_send(
    topology: NoetriumUnit,
    sender: str,
    recipient: str,
) -> bool:
    try:
        _communication_relation(topology, sender, recipient)
    except KeyError:
        return False
    return True


def communication_edge_max_in_flight(
    topology: NoetriumUnit,
    sender: str,
    recipient: str,
) -> int:
    edge = _communication_relation(topology, sender, recipient)
    return int(edge.parameters["max_in_flight"])


def communication_neighbors(
    topology: NoetriumUnit,
    sender: str,
) -> tuple[str, ...]:
    validate_communication_topology(topology)
    return tuple(
        sorted(
            target_id
            for edge in topology.units("relation")
            if endpoint_child_id(edge.one_unit("source")) == sender
            for target_id in (endpoint_child_id(edge.one_unit("target")),)
            if target_id is not None
        )
    )




class MultiAgentDeliveryStatus(StrEnum):
    DELIVERED = "delivered"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    FAILED = "failed"


class MultiAgentRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    MAX_ROUNDS = "max_rounds"
    MAX_MESSAGES = "max_messages"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MultiAgentMessage:
    sender: str
    recipient: str
    content: str
    turn: int
    conversation_id: str = "default"
    causal_parent_ids: tuple[str, ...] = ()
    delivery_attempt: int = 0
    message_id: str = field(init=False)

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or not value.strip()
            for value in (
                self.sender,
                self.recipient,
                self.conversation_id,
            )
        ):
            raise ValueError("multi-agent message identities must be non-empty")
        if type(self.content) is not str or not self.content:
            raise ValueError("multi-agent message content must be non-empty")
        if (
            type(self.turn) is not int
            or isinstance(self.turn, bool)
            or self.turn < 0
        ):
            raise ValueError("multi-agent message turn must be non-negative")
        if type(self.causal_parent_ids) is not tuple:
            raise TypeError("multi-agent causal_parent_ids must be a tuple")
        if any(
            type(parent) is not str
            or len(parent) != 64
            or any(char not in "0123456789abcdef" for char in parent)
            for parent in self.causal_parent_ids
        ):
            raise ValueError(
                "multi-agent causal parents must be lowercase SHA-256 IDs"
            )
        if len(self.causal_parent_ids) != len(set(self.causal_parent_ids)):
            raise ValueError("multi-agent causal parents must be unique")
        if (
            type(self.delivery_attempt) is not int
            or isinstance(self.delivery_attempt, bool)
            or self.delivery_attempt < 0
        ):
            raise ValueError(
                "multi-agent delivery_attempt must be non-negative"
            )
        object.__setattr__(
            self,
            "message_id",
            canonical_digest({
                "sender": self.sender,
                "recipient": self.recipient,
                "content": self.content,
                "turn": self.turn,
                "conversation_id": self.conversation_id,
                "causal_parent_ids": self.causal_parent_ids,
            }),
        )


@dataclass(frozen=True, slots=True)
class MultiAgentDeliveryReceipt:
    message_id: str
    sender: str
    recipient: str
    status: MultiAgentDeliveryStatus
    attempt: int
    round: int
    detail: str = ""
    receipt_id: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.message_id, "multi-agent receipt message_id")
        if any(
            type(value) is not str or not value.strip()
            for value in (self.sender, self.recipient)
        ):
            raise ValueError("multi-agent receipt endpoints must be non-empty")
        if not isinstance(self.status, MultiAgentDeliveryStatus):
            raise TypeError("multi-agent receipt status is invalid")
        if any(
            type(value) is not int
            or isinstance(value, bool)
            or value < 0
            for value in (self.attempt, self.round)
        ):
            raise ValueError(
                "multi-agent receipt counters must be non-negative"
            )
        if type(self.detail) is not str:
            raise TypeError("multi-agent receipt detail must be string")
        object.__setattr__(
            self,
            "receipt_id",
            canonical_digest({
                "message_id": self.message_id,
                "sender": self.sender,
                "recipient": self.recipient,
                "status": self.status.value,
                "attempt": self.attempt,
                "round": self.round,
                "detail": self.detail,
            }),
        )


class MultiAgentNodePort(Protocol):
    """Participant execution seam.

    Implementations must be deterministic or idempotent for a stable message
    identity. External effects belong behind the platform effect/capability
    substrate rather than hidden in this method.
    """

    def handle(
        self,
        message: MultiAgentMessage,
    ) -> tuple[MultiAgentMessage, ...]: ...


class MultiAgentCancellationPort(Protocol):
    def cancelled(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class MultiAgentRunResult:
    topology_digest: str
    conversation_id: str
    messages: tuple[MultiAgentMessage, ...]
    pending_messages: tuple[MultiAgentMessage, ...]
    rounds: int
    terminated: bool
    status: MultiAgentRunStatus
    receipts: tuple[MultiAgentDeliveryReceipt, ...]
    machine_cut: MachineCut
    error: str | None = None

    def __post_init__(self) -> None:
        require_sha256(
            self.topology_digest,
            "multi-agent result topology_digest",
        )
        if (
            type(self.conversation_id) is not str
            or not self.conversation_id.strip()
        ):
            raise ValueError("multi-agent result conversation_id is required")
        for name in ("messages", "pending_messages"):
            rows = getattr(self, name)
            if type(rows) is not tuple or any(
                type(row) is not MultiAgentMessage for row in rows
            ):
                raise TypeError(
                    f"multi-agent result {name} must contain MultiAgentMessage"
                )
        if type(self.rounds) is not int or self.rounds < 0:
            raise ValueError("multi-agent result rounds must be non-negative")
        if type(self.terminated) is not bool:
            raise TypeError("multi-agent result terminated must be bool")
        if not isinstance(self.status, MultiAgentRunStatus):
            raise TypeError("multi-agent result status is invalid")
        if type(self.receipts) is not tuple or any(
            type(row) is not MultiAgentDeliveryReceipt
            for row in self.receipts
        ):
            raise TypeError(
                "multi-agent result receipts must be typed"
            )
        if not isinstance(self.machine_cut, MachineCut):
            raise TypeError("multi-agent result requires MachineCut")
        if self.error is not None and type(self.error) is not str:
            raise TypeError("multi-agent result error must be string or None")
        if (
            self.status is MultiAgentRunStatus.COMPLETED
            and not self.terminated
        ):
            raise ValueError(
                "completed multi-agent result must be terminated"
            )
        if (
            self.status is MultiAgentRunStatus.FAILED
            and not self.error
        ):
            raise ValueError("failed multi-agent result requires an error")


__all__ = [
    "COMMUNICATION_EDGE_RELATION",
    "COMMUNICATION_NODE_TRAIT",
    "COMMUNICATION_TOPOLOGY_TRAIT",
    "communication_can_send",
    "communication_edge",
    "communication_edge_max_in_flight",
    "communication_neighbors",
    "communication_nodes",
    "communication_topology",
    "validate_communication_topology",
    "MultiAgentCancellationPort",
    "MultiAgentDeliveryReceipt",
    "MultiAgentDeliveryStatus",
    "MultiAgentMessage",
    "MultiAgentNodePort",
    "MultiAgentRunResult",
    "MultiAgentRunStatus",
]
