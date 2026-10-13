from __future__ import annotations

from typing import Protocol

from noetrium_platform.capabilities.api import EffectReconciliationProof
from noetrium_platform.research.execution.operation.command.api import CommandId
from .contracts import (
    EffectId,
    OperationEffectCertainty,
    OperationEffectProfile,
    OperationFailure,
    OperationId,
    OperationSnapshot,
)


class OperationConflict(RuntimeError):
    pass


class OperationCorruption(RuntimeError):
    pass


class OperationStorePort(Protocol):
    @property
    def durability(self) -> str: ...

    def create_or_get(
        self,
        snapshot: OperationSnapshot,
    ) -> tuple[OperationSnapshot, bool]: ...

    def load(
        self,
        operation_id: OperationId,
    ) -> OperationSnapshot | None: ...

    def compare_and_swap(
        self,
        current: OperationSnapshot,
        snapshot: OperationSnapshot,
    ) -> OperationSnapshot: ...
    def close(self) -> None: ...


class OperationSubmissionPort(Protocol):
    def submit(
        self,
        command_id: CommandId,
        *,
        operation_id: OperationId,
        parent_operation_id: OperationId | None = None,
        effect_profile: OperationEffectProfile = OperationEffectProfile.NONE,
        effect_id: EffectId | None = None,
        effect_request_id: str | None = None,
        effect_request_digest: str | None = None,
        now_unix: float | None = None,
    ) -> tuple[OperationSnapshot, bool]: ...


class OperationAdmissionPort(Protocol):
    """Scheduling/admission transitions over an exact durable snapshot."""

    def queue(
        self,
        current: OperationSnapshot,
        *,
        now_unix: float | None = None,
    ) -> OperationSnapshot: ...

    def admit(
        self,
        current: OperationSnapshot,
        *,
        now_unix: float | None = None,
    ) -> OperationSnapshot: ...


class OperationRecoveryPort(Protocol):
    """Read/reconciliation authority for proof-driven workflow recovery."""

    def require(self, operation_id: OperationId) -> OperationSnapshot: ...

    def recover_interrupted(
        self,
        current: OperationSnapshot,
    ) -> OperationSnapshot: ...

    def reconcile_effect(
        self,
        current: OperationSnapshot,
        proof: EffectReconciliationProof,
    ) -> OperationSnapshot: ...

    def complete(
        self,
        current: OperationSnapshot,
        *,
        result_digest: str | None = None,
        effect_certainty: OperationEffectCertainty | None = None,
    ) -> OperationSnapshot: ...


class OperationLifecyclePort(Protocol):
    """Operation-state authority; mutation always consumes an exact snapshot."""

    def require(self, operation_id: OperationId) -> OperationSnapshot: ...

    def begin_execution(
        self,
        current: OperationSnapshot,
    ) -> OperationSnapshot: ...

    def request_cancel(
        self,
        current: OperationSnapshot,
        reason: str,
    ) -> OperationSnapshot: ...

    def recover_interrupted(
        self,
        current: OperationSnapshot,
    ) -> OperationSnapshot: ...

    def mark_effect_unknown(
        self,
        current: OperationSnapshot,
        *,
        failure: OperationFailure | None = None,
    ) -> OperationSnapshot: ...

    def reconcile_effect(
        self,
        current: OperationSnapshot,
        proof: EffectReconciliationProof,
    ) -> OperationSnapshot: ...

    def complete(
        self,
        current: OperationSnapshot,
        *,
        result_digest: str | None = None,
        effect_certainty: OperationEffectCertainty | None = None,
    ) -> OperationSnapshot: ...

    def fail(
        self,
        current: OperationSnapshot,
        failure: OperationFailure,
    ) -> OperationSnapshot: ...


__all__ = [
    "OperationAdmissionPort",
    "OperationConflict",
    "OperationCorruption",
    "OperationLifecyclePort",
    "OperationRecoveryPort",
    "OperationStorePort",
    "OperationSubmissionPort",
]
