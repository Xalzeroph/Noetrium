"""A transport-backed Runtime keeps topology checks under Machine authority."""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestration.multi_agent import (
    CommunicationEdge, CommunicationTopology, MultiAgentMessage,
    TransportBackedMultiAgentRuntime,
)

class Transport:
    def send(self, message):
        if message.recipient == "worker":
            return (MultiAgentMessage(
                "worker", "manager", "done", message.turn + 1,
                causal_parent_ids=(message.message_id,),
            ),)
        return ()

class Members:
    def members(self):
        return ("manager", "worker")

topology = CommunicationTopology((
    "manager", "worker",
), (
    CommunicationEdge("manager", "worker"),
    CommunicationEdge("worker", "manager"),
))
result = TransportBackedMultiAgentRuntime(
    topology, Transport(), membership=Members(),
).run(MultiAgentMessage("manager", "worker", "task", 0))
print(result.status.value, len(result.receipts))
