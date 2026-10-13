from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import OperationRequest

from .catalog import FailureSpec


@dataclass(frozen=True, slots=True)
class ClassifiedOperationFailure:
    spec: FailureSpec
    effect_certainty: str | None = None


class PartialOperationFailureClassifier(Protocol):
    def classify(
        self,
        request: OperationRequest[object],
        exc: BaseException,
    ) -> ClassifiedOperationFailure | None: ...


__all__ = ["ClassifiedOperationFailure", "PartialOperationFailureClassifier"]
