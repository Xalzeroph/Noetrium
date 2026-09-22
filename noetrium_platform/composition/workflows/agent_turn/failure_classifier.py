from __future__ import annotations

from noetrium_platform.infrastructure.reliability.failure.api import ClassifiedOperationFailure
from noetrium_platform.foundation.kernel.kernel import OperationRequest


class AgentTurnFailureClassifier:
    """Extension point for Agent/Capability taxonomy; currently delegates unknowns to core fallback."""

    def classify(self, request: OperationRequest[object], exc: BaseException) -> ClassifiedOperationFailure | None:
        del request, exc
        return None


__all__ = ["AgentTurnFailureClassifier"]
