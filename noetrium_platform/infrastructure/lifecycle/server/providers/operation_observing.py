from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
import time
from uuid import uuid4

from noetrium_platform.foundation.kernel.kernel.errors import redact_text
from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationEffect,
    ServerOperationFinished,
    ServerOperationJournalPort,
    ServerOperationKind,
    ServerOperationReconciliationRequired,
    ServerOperationStarted,
    ServerOperationState,
)
from noetrium_platform.infrastructure.lifecycle.server.identity.api import (
    ServerCommandResult,
    ServerConnectionPort,
    ServerFileTransferPort,
    ServerFileTransferResult,
    ServerTransportFailureKind,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _error_fields(exc: BaseException) -> tuple[str, str]:
    return type(exc).__name__, _digest(str(exc))


def _operation_id() -> str:
    return f"srv-op-{uuid4().hex}"


def _failure_kind(result) -> str:
    """Normalize provider results before they become durable evidence."""

    if result.failure_kind != ServerTransportFailureKind.NONE:
        return result.failure_kind.value
    return "none" if result.return_code == 0 else ServerTransportFailureKind.REMOTE_EXIT.value


def _require_reconciled(journal: ServerOperationJournalPort, *, server_id: str) -> None:
    pending = journal.pending_operations(server_id=server_id)
    if pending:
        raise ServerOperationReconciliationRequired(
            tuple(record.operation_id for record in pending)
        )


class ObservedServerConnection(ServerConnectionPort):
    """Connection decorator that journals every remote command boundary."""

    def __init__(
        self,
        connection: ServerConnectionPort,
        journal: ServerOperationJournalPort,
        *,
        profile_digest: str = "",
    ) -> None:
        self._connection = connection
        self._journal = journal
        self._profile_digest = profile_digest

    @property
    def profile(self):
        return self._connection.profile

    def execute(
        self,
        command: str,
        *,
        interactive: bool = False,
        effect: ServerOperationEffect = ServerOperationEffect.UNKNOWN,
        timeout_seconds: float | None = None,
    ) -> ServerCommandResult:
        # All automated operations share a non-blocking transport lease.  A
        # read-only probe must fail fast while a sync owns the SSH boundary;
        # otherwise it can enter the same hidden authentication/multiplexing
        # path and appear to hang independently.
        with self._journal.transport_lock(server_id=self.profile.server_id):
            if effect == ServerOperationEffect.OBSERVATION:
                return self._execute_observed(
                    command,
                    interactive=interactive,
                    effect=effect,
                    timeout_seconds=timeout_seconds,
                )
            with self._journal.mutation_lock(server_id=self.profile.server_id):
                _require_reconciled(self._journal, server_id=self.profile.server_id)
                return self._execute_observed(
                    command,
                    interactive=interactive,
                    effect=effect,
                    timeout_seconds=timeout_seconds,
                )

    def _execute_observed(
        self,
        command: str,
        *,
        interactive: bool,
        effect: ServerOperationEffect,
        timeout_seconds: float | None,
    ) -> ServerCommandResult:
        operation_id = _operation_id()
        request_digest = _digest(command)
        started_at = time.time()
        started_clock = time.perf_counter()
        self._journal.record_started(
            ServerOperationStarted(
                operation_id,
                self.profile.server_id,
                ServerOperationKind.COMMAND,
                request_digest,
                started_at,
                interactive,
                self._profile_digest,
                effect,
            )
        )
        try:
            kwargs = {"interactive": interactive}
            if timeout_seconds is not None:
                kwargs["timeout_seconds"] = timeout_seconds
            result = self._connection.execute(command, **kwargs)
        except BaseException as exc:
            error_type, error_digest = _error_fields(exc)
            self._journal.record_finished(
                ServerOperationFinished(
                    operation_id,
                    self.profile.server_id,
                    ServerOperationKind.COMMAND,
                    request_digest,
                    ServerOperationState.FAILED,
                    time.time(),
                    time.perf_counter() - started_clock,
                    None,
                    type(exc).__name__,
                    0,
                    0,
                    error_type,
                    error_digest,
                    profile_digest=self._profile_digest,
                    effect=effect,
                )
            )
            raise
        state = (
            ServerOperationState.SUCCEEDED
            if result.succeeded
            else ServerOperationState.TIMED_OUT
            if result.failure_kind == ServerTransportFailureKind.TIMEOUT
            else ServerOperationState.FAILED
        )
        self._journal.record_finished(
            ServerOperationFinished(
                operation_id,
                self.profile.server_id,
                ServerOperationKind.COMMAND,
                request_digest,
                state,
                time.time(),
                result.duration_seconds or (time.perf_counter() - started_clock),
                result.return_code,
                    _failure_kind(result),
                result.stdout_bytes or len(result.stdout.encode("utf-8", errors="replace")),
                result.stderr_bytes or len(result.stderr.encode("utf-8", errors="replace")),
                profile_digest=self._profile_digest,
                stdout_digest=_digest(result.stdout),
                stderr_digest=_digest(result.stderr),
                effect=effect,
                stdout_preview=redact_text(result.stdout),
                stderr_preview=redact_text(result.stderr),
            )
        )
        return result

    def interactive_argv(
        self,
        command: str,
        *,
        allocate_tty: bool = False,
    ) -> tuple[str, ...]:
        return self._connection.interactive_argv(command, allocate_tty=allocate_tty)

    def run_interactive(self, argv: tuple[str, ...]) -> int:
        operation_id = _operation_id()
        request_digest = _digest("interactive-attach\0" + "\0".join(argv))
        started_clock = time.perf_counter()
        self._journal.record_started(
            ServerOperationStarted(
                operation_id,
                self.profile.server_id,
                ServerOperationKind.INTERACTIVE_ATTACH,
                request_digest,
                time.time(),
                True,
                self._profile_digest,
                ServerOperationEffect.OBSERVATION,
            )
        )
        try:
            return_code = self._connection.run_interactive(argv)
        except BaseException as exc:
            error_type, error_digest = _error_fields(exc)
            self._journal.record_finished(
                ServerOperationFinished(
                    operation_id,
                    self.profile.server_id,
                    ServerOperationKind.INTERACTIVE_ATTACH,
                    request_digest,
                    ServerOperationState.FAILED,
                    time.time(),
                    time.perf_counter() - started_clock,
                    None,
                    error_type,
                    0,
                    0,
                    error_type,
                    error_digest,
                    profile_digest=self._profile_digest,
                    effect=ServerOperationEffect.OBSERVATION,
                    stdout_preview="",
                    stderr_preview="",
                )
            )
            raise
        self._journal.record_finished(
            ServerOperationFinished(
                operation_id,
                self.profile.server_id,
                ServerOperationKind.INTERACTIVE_ATTACH,
                request_digest,
                ServerOperationState.SUCCEEDED if return_code == 0 else ServerOperationState.FAILED,
                time.time(),
                time.perf_counter() - started_clock,
                return_code,
                "none" if return_code == 0 else "remote_exit",
                0,
                0,
                profile_digest=self._profile_digest,
                effect=ServerOperationEffect.OBSERVATION,
                stdout_preview="",
                stderr_preview="",
            )
        )
        return return_code


class ObservedServerFileTransfer(ServerFileTransferPort):
    """File-transfer decorator sharing the same operation ledger."""

    def __init__(
        self,
        transfer: ServerFileTransferPort,
        journal: ServerOperationJournalPort,
        *,
        profile_digest: str = "",
    ) -> None:
        self._transfer = transfer
        self._journal = journal
        self._profile_digest = profile_digest

    @property
    def profile(self):
        return self._transfer.profile

    @property
    def executable(self) -> str:
        return self._transfer.executable

    def upload(
        self,
        local_path: str,
        remote_path: str,
        *,
        interactive: bool = False,
    ) -> ServerFileTransferResult:
        with self._journal.transport_lock(server_id=self.profile.server_id):
            with self._journal.mutation_lock(server_id=self.profile.server_id):
                _require_reconciled(self._journal, server_id=self.profile.server_id)
                local = Path(local_path).expanduser().resolve()
                try:
                    size = local.stat().st_size
                except OSError:
                    size = -1
                request_digest = _digest(f"upload\0{local}\0{remote_path}\0{size}")
                return self._observe_transfer(
                    ServerOperationKind.FILE_UPLOAD,
                    request_digest,
                    interactive,
                    lambda: self._transfer.upload(local_path, remote_path, interactive=interactive),
                )

    def download(
        self,
        remote_path: str,
        local_path: str,
        *,
        interactive: bool = False,
    ) -> ServerFileTransferResult:
        with self._journal.transport_lock(server_id=self.profile.server_id):
            with self._journal.mutation_lock(server_id=self.profile.server_id):
                _require_reconciled(self._journal, server_id=self.profile.server_id)
                local = Path(local_path).expanduser()
                request_digest = _digest(f"download\0{remote_path}\0{local}")
                return self._observe_transfer(
                    ServerOperationKind.FILE_DOWNLOAD,
                    request_digest,
                    interactive,
                    lambda: self._transfer.download(remote_path, local_path, interactive=interactive),
                )

    def _observe_transfer(
        self,
        kind: ServerOperationKind,
        request_digest: str,
        interactive: bool,
        operation: Callable[[], ServerFileTransferResult],
    ) -> ServerFileTransferResult:
        operation_id = _operation_id()
        started_clock = time.perf_counter()
        self._journal.record_started(
            ServerOperationStarted(
                operation_id,
                self.profile.server_id,
                kind,
                request_digest,
                time.time(),
                interactive,
                self._profile_digest,
                ServerOperationEffect.MUTATION,
            )
        )
        try:
            result = operation()
        except BaseException as exc:
            error_type, error_digest = _error_fields(exc)
            self._journal.record_finished(
                ServerOperationFinished(
                    operation_id,
                    self.profile.server_id,
                    kind,
                    request_digest,
                    ServerOperationState.FAILED,
                    time.time(),
                    time.perf_counter() - started_clock,
                    None,
                    type(exc).__name__,
                    0,
                    0,
                    error_type,
                    error_digest,
                    profile_digest=self._profile_digest,
                    effect=ServerOperationEffect.MUTATION,
                )
            )
            raise
        state = (
            ServerOperationState.SUCCEEDED
            if result.succeeded
            else ServerOperationState.TIMED_OUT
            if result.failure_kind == ServerTransportFailureKind.TIMEOUT
            else ServerOperationState.FAILED
        )
        self._journal.record_finished(
            ServerOperationFinished(
                operation_id,
                self.profile.server_id,
                kind,
                request_digest,
                state,
                time.time(),
                result.duration_seconds or (time.perf_counter() - started_clock),
                result.return_code,
                _failure_kind(result),
                result.stdout_bytes or len(result.stdout.encode("utf-8", errors="replace")),
                result.stderr_bytes or len(result.stderr.encode("utf-8", errors="replace")),
                profile_digest=self._profile_digest,
                stdout_digest=_digest(result.stdout),
                stderr_digest=_digest(result.stderr),
                effect=ServerOperationEffect.MUTATION,
                stdout_preview=redact_text(result.stdout),
                stderr_preview=redact_text(result.stderr),
            )
        )
        return result


__all__ = [
    "ObservedServerConnection",
    "ObservedServerFileTransfer",
]
