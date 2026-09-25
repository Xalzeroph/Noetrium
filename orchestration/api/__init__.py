"""Internal aggregation boundary for reusable multi-agent orchestration.

Downstream projects use noetrium.api. This module exists only so the unified
facade does not import orchestration implementation modules directly.
"""

from ..multi_agent import (
    CommunicationEdge,
    CommunicationTopology,
    MultiAgentCancellationPort,
    MultiAgentDeliveryReceipt,
    MultiAgentDeliveryStatus,
    MultiAgentMessage,
    MultiAgentNodePort,
    MultiAgentRunResult,
    MultiAgentRunStatus,
    MultiAgentRuntime,
    MultiAgentMembershipPort,
    MultiAgentTransportPort,
    TransportBackedMultiAgentRuntime,
    compile_multi_agent_runtime_program,
    debate_initial_message,
    group_chat_initial_messages,
    hierarchical_initial_message,
    multi_agent_initial_data,
    multi_agent_rule_set,
)

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
    "MultiAgentRuntime",
    "MultiAgentMembershipPort",
    "MultiAgentTransportPort",
    "TransportBackedMultiAgentRuntime",
    "compile_multi_agent_runtime_program",
    "debate_initial_message",
    "group_chat_initial_messages",
    "hierarchical_initial_message",
    "multi_agent_initial_data",
    "multi_agent_rule_set",
]
