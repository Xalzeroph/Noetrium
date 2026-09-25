from __future__ import annotations

from noetrium_platform.composition.operation_forensics import (
    CoreOperationFailureClassifier,
    OperationFailureClassifierChain,
)
from noetrium_platform.composition.participants.environment import (
    environment_participant_adapter,
)
from noetrium_platform.composition.participants.method import (
    method_participant_adapter,
)
from noetrium_platform.capabilities.participant.core.api import (
    ParticipantLifecycleAdapter,
    ParticipantResolverPort,
)
from noetrium_platform.composition.workflows.context_action.failure_classifier import (
    ContextActionFailureClassifier,
)


def context_action_participant_adapters(
    resolver: ParticipantResolverPort,
    *,
    extra: tuple[ParticipantLifecycleAdapter, ...] = (),
) -> tuple[ParticipantLifecycleAdapter, ...]:
    return (
        method_participant_adapter(resolver),
        environment_participant_adapter(resolver),
        *extra,
    )


def context_action_failure_classifier_chain() -> OperationFailureClassifierChain:
    return OperationFailureClassifierChain(
        (
            ContextActionFailureClassifier(),
            CoreOperationFailureClassifier(),
        )
    )


__all__ = [
    "context_action_failure_classifier_chain",
    "context_action_participant_adapters",
]
