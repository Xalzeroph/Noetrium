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
from noetrium_platform.foundation.kernel.kernel import MachineCut


@dataclass(frozen=True, slots=True, order=True)
class CommunicationEdge:
    sender: str
    recipient: str
    max_in_flight: int = 64
    ordered: bool = True

    def __post_init__(self) -> None:
        if any(
            type(value) is not str or not value.strip()
            for value in (self.sender, self.recipient)
        ):
            raise ValueError("communication edge endpoints must be non-empty")
        if self.sender == self.recipient:
            raise ValueError("communication edge cannot self-reference")
        if type(self.max_in_flight) is not int or self.max_in_flight <= 0:
            raise ValueError("communication edge max_in_flight must be positive")
        if type(self.ordered) is not bool:
            raise TypeError("communication edge ordered must be bool")


@dataclass(frozen=True, slots=True)
class CommunicationTopology:
    nodes: tuple[str, ...]
    edges: tuple[CommunicationEdge, ...]
    topology_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.nodes) is not tuple or not self.nodes:
            raise ValueError("multi-agent topology nodes must be non-empty")
        if any(type(node) is not str or not node.strip() for node in self.nodes):
            raise TypeError(
                "multi-agent topology nodes must contain non-empty strings"
            )
        if len(self.nodes) != len(set(self.nodes)):
            raise ValueError("multi-agent topology nodes must be unique")
        known = set(self.nodes)
        if type(self.edges) is not tuple or any(
            type(edge) is not CommunicationEdge for edge in self.edges
        ):
            raise TypeError(
                "multi-agent topology edges must contain CommunicationEdge"
            )
        if any(
            edge.sender not in known or edge.recipient not in known
            for edge in self.edges
        ):
            raise ValueError(
                "communication edge references an unknown node"
            )
        if len(self.edges) != len(set(self.edges)):
            raise ValueError("communication edges must be unique")
        object.__setattr__(
            self,
            "topology_digest",
            canonical_digest({
                "nodes": self.nodes,
                "edges": tuple(
                    (
                        edge.sender,
                        edge.recipient,
                        edge.max_in_flight,
                        edge.ordered,
                    )
                    for edge in self.edges
                ),
            }),
        )

    def can_send(self, sender: str, recipient: str) -> bool:
        return any(
            edge.sender == sender and edge.recipient == recipient
            for edge in self.edges
        )

    def edge(self, sender: str, recipient: str) -> CommunicationEdge:
        for edge in self.edges:
            if edge.sender == sender and edge.recipient == recipient:
                return edge
        raise KeyError((sender, recipient))

    def neighbors(self, sender: str) -> tuple[str, ...]:
        return tuple(sorted(
            edge.recipient for edge in self.edges if edge.sender == sender
        ))


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
    "CommunicationEdge",
    "CommunicationTopology",
    "MultiAgentCancellationPort",
    "MultiAgentDeliveryReceipt",
    "MultiAgentDeliveryStatus",
    "MultiAgentMessage",
    "MultiAgentNodePort",
    "MultiAgentRunResult",
    "MultiAgentRunStatus",
]
