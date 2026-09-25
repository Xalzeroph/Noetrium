from __future__ import annotations

from noetrium_platform.composition.operation_forensics import (
    CoreOperationFailureClassifier,
    OperationFailureClassifierChain,
)
from noetrium_platform.composition.participants.agent import (
    agent_participant_adapter,
)
from noetrium_platform.composition.participants.capability import (
    capability_participant_adapter,
)
from noetrium_platform.composition.participants.generic import (
    generic_participant_adapter,
)
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantLifecycleAdapter,
    ParticipantResolverPort,
)
from noetrium_platform.composition.workflows.agent_turn.failure_classifier import (
    AgentTurnFailureClassifier,
)


def agent_turn_participant_adapters(
    resolver: ParticipantResolverPort,
    *,
    runtime_kinds: tuple[str, ...] = (),
    include_capability_provider: bool = True,
    extra: tuple[ParticipantLifecycleAdapter, ...] = (),
) -> tuple[ParticipantLifecycleAdapter, ...]:
    rows: list[ParticipantLifecycleAdapter] = [
        agent_participant_adapter(resolver)
    ]
    if include_capability_provider:
        rows.append(capability_participant_adapter(resolver))
    rows.extend(
        generic_participant_adapter(kind, resolver)
        for kind in runtime_kinds
    )
    rows.extend(extra)
    return tuple(rows)


def agent_turn_failure_classifier_chain() -> OperationFailureClassifierChain:
    return OperationFailureClassifierChain(
        (
            AgentTurnFailureClassifier(),
            CoreOperationFailureClassifier(),
        )
    )


__all__ = [
    "agent_turn_failure_classifier_chain",
    "agent_turn_participant_adapters",
]
