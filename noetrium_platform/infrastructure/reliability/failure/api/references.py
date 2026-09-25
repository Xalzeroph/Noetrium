from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import OperationRequest


@dataclass(frozen=True, slots=True)
class OperationFailureReferenceProjection:
    request_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    state_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()


class OperationFailureReferenceProjector(Protocol):
    def project(
        self,
        request: OperationRequest[object],
        exc: BaseException,
    ) -> OperationFailureReferenceProjection: ...


__all__ = ["OperationFailureReferenceProjection", "OperationFailureReferenceProjector"]
