from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ServerOperationKind(StrEnum):
    COMMAND = "command"
    FILE_UPLOAD = "file_upload"
    FILE_DOWNLOAD = "file_download"
    INTERACTIVE_ATTACH = "interactive_attach"


class ServerOperationState(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class ServerOperationEffect(StrEnum):
    """What the caller knows about an operation's possible side effect."""

    OBSERVATION = "observation"
    MUTATION = "mutation"
    UNKNOWN = "unknown"


class ServerOperationResolution(StrEnum):
    """Human/operator reconciliation decision for an uncertain operation."""

    EFFECT_CONFIRMED = "effect_confirmed"
    EFFECT_NOT_APPLIED = "effect_not_applied"


class ServerOperationReconciliationRequired(RuntimeError):
    """A new side effect is blocked until an earlier effect is reconciled."""

    def __init__(self, operation_ids: tuple[str, ...]) -> None:
        self.operation_ids = operation_ids
        super().__init__(
            "server operation is blocked by unreconciled effects: "
            + ", ".join(operation_ids)
        )


class ServerOperationTransitionConflict(RuntimeError):
    """A durable operation transition conflicts with the recorded lifecycle."""

    def __init__(self, operation_id: str, reason: str) -> None:
        self.operation_id = operation_id
        self.reason = reason
        super().__init__(f"server operation transition conflict for {operation_id}: {reason}")


class ServerMutationBusy(RuntimeError):
    """A second controller tried to mutate one server while it was busy.

    Mutation submission is fail-fast.  Waiting indefinitely behind an SSH or
    remote Git operation makes an operator unable to distinguish a valid long
    operation from a dead authentication prompt, and can create duplicate
    callers after a retry.  The caller must inspect the operation ledger and
    retry explicitly after the owning mutation has released the lock.
    """

    def __init__(self, server_id: str) -> None:
        self.server_id = server_id
        super().__init__(f"server mutation is already in progress: {server_id}")


class ServerTransportBusy(RuntimeError):
    """A second controller tried to open a transport to one server.

    Observations are intentionally fail-fast too.  A read-only probe must not
    create a second SSH authentication attempt while another controller owns
    the server transport lease: on password-only or multiplexed SSH setups
    that second attempt can otherwise wait behind the first hidden prompt.
    """

    def __init__(self, server_id: str) -> None:
        self.server_id = server_id
        super().__init__(f"server transport is already in progress: {server_id}")


@dataclass(frozen=True, slots=True)
class ServerOperationStarted:
    operation_id: str
    server_id: str
    kind: ServerOperationKind
    request_digest: str
    started_at: float
    interactive: bool
    profile_digest: str = ""
    effect: ServerOperationEffect = ServerOperationEffect.UNKNOWN


@dataclass(frozen=True, slots=True)
class ServerOperationFinished:
    operation_id: str
    server_id: str
    kind: ServerOperationKind
    request_digest: str
    state: ServerOperationState
    finished_at: float
    duration_seconds: float
    return_code: int | None
    failure_kind: str
    stdout_bytes: int
    stderr_bytes: int
    error_type: str | None = None
    error_digest: str | None = None
    profile_digest: str = ""
    stdout_digest: str = ""
    stderr_digest: str = ""
    effect: ServerOperationEffect = ServerOperationEffect.UNKNOWN
    stdout_preview: str = ""
    stderr_preview: str = ""


@dataclass(frozen=True, slots=True)
class ServerOperationResolved:
    """Durable evidence that an uncertain operation has been inspected.

    The resolution contains only a stable evidence reference and digest.  It
    deliberately cannot submit, retry, or mutate the remote host.
    """

    operation_id: str
    server_id: str
    kind: ServerOperationKind
    request_digest: str
    disposition: ServerOperationResolution
    resolved_at: float
    evidence_ref: str
    evidence_digest: str
    profile_digest: str = ""


class ServerOperationJournalPort(Protocol):
    """Durable observation boundary for every managed server side effect."""

    def record_started(self, event: ServerOperationStarted) -> None: ...

    def record_finished(self, event: ServerOperationFinished) -> None: ...

    def record_resolved(self, event: ServerOperationResolved) -> None: ...

    def mutation_lock(self, *, server_id: str) -> AbstractContextManager[object]: ...

    def transport_lock(self, *, server_id: str) -> AbstractContextManager[object]: ...

    def read_operation(self, operation_id: str) -> "ServerOperationRecord | None": ...

    def pending_operations(
        self,
        *,
        server_id: str | None = None,
    ) -> tuple["ServerOperationRecord", ...]: ...

    def recent_operations(
        self,
        limit: int = 20,
        *,
        server_id: str | None = None,
    ) -> tuple["ServerOperationRecord", ...]: ...


@dataclass(frozen=True, slots=True)
class ServerOperationRecord:
    """One replayable operation lifecycle reconstructed from the ledger.

    A record whose effect is not proven is deliberately not treated as a
    normal failure. The controller may have died after the remote side effect
    was submitted, or a timeout may have returned after the remote process
    accepted the command. Its effect remains unknown until an operator
    reconciles it.
    """

    started: ServerOperationStarted
    finished: ServerOperationFinished | None = None
    resolution: ServerOperationResolved | None = None

    @property
    def operation_id(self) -> str:
        return self.started.operation_id

    @property
    def server_id(self) -> str:
        return self.started.server_id

    @property
    def kind(self) -> ServerOperationKind:
        return self.started.kind

    @property
    def state(self) -> ServerOperationState:
        return self.finished.state if self.finished is not None else ServerOperationState.STARTED

    @property
    def effect_uncertain(self) -> bool:
        if self.resolution is not None:
            return False
        if self.started.effect == ServerOperationEffect.OBSERVATION:
            return False
        if self.finished is None:
            return True
        if self.finished.state == ServerOperationState.TIMED_OUT:
            return True
        if self.finished.failure_kind in {"timeout", "network"}:
            return True
        return self.started.effect in {
            ServerOperationEffect.MUTATION,
            ServerOperationEffect.UNKNOWN,
        } and self.finished.state == ServerOperationState.FAILED


__all__ = [
    "ServerOperationFinished",
    "ServerOperationEffect",
    "ServerOperationJournalPort",
    "ServerOperationKind",
    "ServerOperationStarted",
    "ServerOperationRecord",
    "ServerOperationReconciliationRequired",
    "ServerOperationTransitionConflict",
    "ServerMutationBusy",
    "ServerTransportBusy",
    "ServerOperationResolved",
    "ServerOperationResolution",
    "ServerOperationState",
]
