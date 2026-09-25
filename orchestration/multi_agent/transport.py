"""Transport seams for the reference multi-agent Runtime preset."""

from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    MachineSnapshotStorePort,
)

from .contracts import (
    CommunicationTopology,
    MultiAgentMessage,
    MultiAgentNodePort,
)
from .orchestration import MultiAgentRuntime


class MultiAgentTransportPort(Protocol):
    """Deployment transport.

    send() must be deterministic or idempotent for a stable message_id.
    Non-idempotent external effects belong behind Noetrium effect mediation.
    """

    def send(
        self,
        message: MultiAgentMessage,
    ) -> tuple[MultiAgentMessage, ...]: ...


class MultiAgentMembershipPort(Protocol):
    def members(self) -> tuple[str, ...]: ...


class _TransportNode(MultiAgentNodePort):
    def __init__(self, transport: MultiAgentTransportPort) -> None:
        self._transport = transport

    def handle(
        self,
        message: MultiAgentMessage,
    ) -> tuple[MultiAgentMessage, ...]:
        outputs = self._transport.send(message)
        if type(outputs) is not tuple or any(
            type(item) is not MultiAgentMessage for item in outputs
        ):
            raise TypeError(
                "multi-agent transport must return tuple[MultiAgentMessage, ...]"
            )
        return outputs


class TransportBackedMultiAgentRuntime(MultiAgentRuntime):
    """RuntimeMachine-backed multi-agent preset using injected transport."""

    def __init__(
        self,
        topology: CommunicationTopology,
        transport: MultiAgentTransportPort,
        *,
        membership: MultiAgentMembershipPort | None = None,
        journal: MachineJournalPort | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> None:
        if membership is not None:
            members = membership.members()
            if (
                type(members) is not tuple
                or set(members) != set(topology.nodes)
            ):
                raise ValueError(
                    "transport membership must exactly match topology nodes"
                )
        if not callable(getattr(transport, "send", None)):
            raise TypeError(
                "multi-agent transport must implement send()"
            )
        super().__init__(
            topology,
            {
                node: _TransportNode(transport)
                for node in topology.nodes
            },
            journal=journal,
            snapshot_store=snapshot_store,
        )


__all__ = [
    "MultiAgentMembershipPort",
    "MultiAgentTransportPort",
    "TransportBackedMultiAgentRuntime",
]
