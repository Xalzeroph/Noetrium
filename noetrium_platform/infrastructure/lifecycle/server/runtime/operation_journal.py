from __future__ import annotations

import hashlib
import os
from pathlib import Path
from contextlib import AbstractContextManager

from noetrium_platform.foundation.kernel.kernel.durability import fsync_directory
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock, InterprocessLockBusy
from noetrium_platform.foundation.kernel.concurrency.api import SerialActorPort
from .operation_journal_codec import (
    MAX_SERVER_OPERATION_RECORD_BYTES,
    SERVER_OPERATION_JOURNAL_GENESIS_CHECKSUM,
    ServerOperationJournalCodec,
    ServerOperationJournalIntegrityError,
)
from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationEffect,
    ServerOperationFinished,
    ServerOperationJournalPort,
    ServerOperationStarted,
    ServerOperationKind,
    ServerOperationRecord,
    ServerOperationResolved,
    ServerOperationResolution,
    ServerOperationState,
    ServerOperationTransitionConflict,
    ServerMutationBusy,
    ServerTransportBusy,
)


class _NonBlockingServerLock(AbstractContextManager[object]):
    """Translate a non-blocking kernel lock into a server-domain failure."""

    def __init__(self, path: Path, *, server_id: str, busy_error: type[RuntimeError]) -> None:
        self.path = path
        self._lock = InterprocessFileLock(path, blocking=False)
        self._server_id = server_id
        self._busy_error = busy_error

    def __enter__(self) -> object:
        try:
            return self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise self._busy_error(self._server_id) from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.__exit__(exc_type, exc, tb)


class _NonBlockingOperationLock(AbstractContextManager[object]):
    """Fence transitions for one operation without serializing unrelated operations."""

    def __init__(self, path: Path, *, operation_id: str) -> None:
        self.path = path
        self._operation_id = operation_id
        self._lock = InterprocessFileLock(path, blocking=False)

    def __enter__(self) -> object:
        try:
            return self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise ServerOperationTransitionConflict(
                self._operation_id, "another transition is in progress"
            ) from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.__exit__(exc_type, exc, tb)


class JsonlServerOperationJournal(ServerOperationJournalPort):
    """Append-only local operation ledger for server control-plane actions.

    The ledger is controller-local and contains no credentials or raw remote
    commands.  It stores correlation IDs, request digests, timing, result
    classes and bounded output sizes, so a failed SSH operation can be
    diagnosed without making the server profile or command text a secret
    transport.
    """

    def __init__(self, path: str | Path, *, writer_actor: SerialActorPort) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._guard_path = self.path.with_name(self.path.name + ".guard.lock")
        self._writer_actor = writer_actor
        self._codec = ServerOperationJournalCodec()

    def _operation_transition_lock(
        self, operation_id: str
    ) -> AbstractContextManager[object]:
        if not operation_id:
            raise ValueError("operation_id must be non-empty")
        identity = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:32]
        return _NonBlockingOperationLock(
            self.path.with_name(f"{self.path.name}.{identity}.transition.lock"),
            operation_id=operation_id,
        )

    def _tail_checksum_locked(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return SERVER_OPERATION_JOURNAL_GENESIS_CHECKSUM
        with self.path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            end = stream.tell()
            stream.seek(end - 1)
            if stream.read(1) != b"\n":
                raise ServerOperationJournalIntegrityError(
                    "server operation ledger has a partial durable tail"
                )
            cursor = end - 1
            chunks: list[bytes] = []
            scanned = 0
            while cursor > 0:
                block_start = max(0, cursor - 4096)
                stream.seek(block_start)
                block = stream.read(cursor - block_start)
                split = block.rfind(b"\n")
                if split >= 0:
                    chunks.insert(0, block[split + 1 :])
                    break
                chunks.insert(0, block)
                scanned += len(block)
                if scanned > MAX_SERVER_OPERATION_RECORD_BYTES:
                    raise ServerOperationJournalIntegrityError(
                        "server operation ledger tail record is oversized"
                    )
                cursor = block_start
            raw = b"".join(chunks)
            decoded = self._codec.decode(raw, expected_previous_checksum=None)
            return decoded.record_checksum

    def _append(
        self,
        event_type: str,
        event: ServerOperationStarted | ServerOperationFinished | ServerOperationResolved,
    ) -> None:
        """Append one typed hash-chained event under the short writer authority."""
        def append_owned() -> None:
            with InterprocessFileLock(self._guard_path):
                previous_checksum = self._tail_checksum_locked()
                encoded = self._codec.encode(
                    event_type,
                    event,
                    previous_checksum=previous_checksum,
                )
                created = not self.path.exists()
                with self.path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                if created:
                    fsync_directory(self.path.parent)

        self._writer_actor.call(f"append:{event_type}", append_owned)

    def _read_records(self) -> tuple[ServerOperationRecord, ...]:
        """Read one rotation-free and append-free journal snapshot.

        Replay freezes one durable byte prefix through the writer actor and
        validates that immutable prefix outside the writer authority.
        """
        if not self.path.exists():
            return ()
        records: dict[str, ServerOperationRecord] = {}
        order: list[str] = []
        # Freeze only the durable byte boundary under the writer authority.  The
        # journal never rotates, so subsequent appends can only extend this prefix.
        # Parsing the frozen prefix outside the lock removes O(file-size) lock hold.
        def freeze_owned() -> int:
            with InterprocessFileLock(self._guard_path):
                return self.path.stat().st_size

        snapshot_size = self._writer_actor.call("freeze-read-prefix", freeze_owned)
        expected_previous_checksum = SERVER_OPERATION_JOURNAL_GENESIS_CHECKSUM
        with self.path.open("rb") as stream:
            remaining = snapshot_size
            line_number = 0
            while remaining > 0:
                raw = stream.readline(remaining)
                if not raw:
                    break
                remaining -= len(raw)
                line_number += 1
                try:
                    if not raw.endswith(b"\n"):
                        raise ServerOperationJournalIntegrityError(
                            "server operation ledger has a partial durable tail"
                        )
                    decoded = self._codec.decode(
                        raw[:-1],
                        expected_previous_checksum=expected_previous_checksum,
                    )
                    expected_previous_checksum = decoded.record_checksum
                    event = decoded.event
                    if isinstance(event, ServerOperationStarted):
                        if event.operation_id in records:
                            raise ValueError("duplicate operation start")
                        records[event.operation_id] = ServerOperationRecord(event)
                        order.append(event.operation_id)
                    elif isinstance(event, ServerOperationFinished):
                        record = records.get(event.operation_id)
                        if (
                            record is None
                            or record.finished is not None
                            or record.resolution is not None
                        ):
                            raise ValueError("finish has no unique open operation")
                        if event.state is ServerOperationState.STARTED:
                            raise ValueError("finished event cannot use started state")
                        if (
                            record.started.server_id != event.server_id
                            or record.started.kind != event.kind
                            or record.started.request_digest != event.request_digest
                            or record.started.profile_digest != event.profile_digest
                            or record.started.effect != event.effect
                        ):
                            raise ValueError("finish does not match its start")
                        records[event.operation_id] = ServerOperationRecord(
                            record.started, event, record.resolution
                        )
                    elif isinstance(event, ServerOperationResolved):
                        record = records.get(event.operation_id)
                        if record is None or record.resolution is not None:
                            raise ValueError("resolution has no unique open operation")
                        if (
                            record.started.server_id != event.server_id
                            or record.started.kind != event.kind
                            or record.started.request_digest != event.request_digest
                            or record.started.profile_digest != event.profile_digest
                        ):
                            raise ValueError("resolution does not match its start")
                        if not record.effect_uncertain:
                            raise ValueError("resolution is only valid for an uncertain operation")
                        records[event.operation_id] = ServerOperationRecord(
                            record.started, record.finished, event
                        )
                    else:
                        raise TypeError("decoded server operation event type is unsupported")
                except ServerOperationJournalIntegrityError as exc:
                    raise ServerOperationJournalIntegrityError(
                        f"server operation ledger is corrupt at line {line_number}: {exc}"
                    ) from exc
                except (TypeError, ValueError, KeyError) as exc:
                    raise ServerOperationJournalIntegrityError(
                        f"server operation ledger is corrupt at line {line_number}: {exc}"
                    ) from exc
        return tuple(records[operation_id] for operation_id in order)

    def record_started(self, event: ServerOperationStarted) -> None:
        with self._operation_transition_lock(event.operation_id):
            if self.read_operation(event.operation_id) is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation is already recorded"
                )
            self._append("started", event)

    def record_finished(self, event: ServerOperationFinished) -> None:
        with self._operation_transition_lock(event.operation_id):
            record = self.read_operation(event.operation_id)
            if record is None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "finish has no recorded start"
                )
            if record.finished is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation is already finished"
                )
            if record.resolution is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation was already reconciled"
                )
            if event.state is ServerOperationState.STARTED:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "finished event cannot use started state"
                )
            started = record.started
            if (
                started.server_id != event.server_id
                or started.kind != event.kind
                or started.request_digest != event.request_digest
                or started.profile_digest != event.profile_digest
                or started.effect != event.effect
            ):
                raise ServerOperationTransitionConflict(
                    event.operation_id, "finish identity does not match its start"
                )
            self._append("finished", event)

    def record_resolved(self, event: ServerOperationResolved) -> None:
        with self._operation_transition_lock(event.operation_id):
            record = self.read_operation(event.operation_id)
            if record is None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "resolution has no recorded operation"
                )
            if record.resolution is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation is already reconciled"
                )
            if (
                record.server_id != event.server_id
                or record.kind != event.kind
                or record.started.request_digest != event.request_digest
                or record.started.profile_digest != event.profile_digest
            ):
                raise ServerOperationTransitionConflict(
                    event.operation_id, "resolution identity does not match its start"
                )
            if not record.effect_uncertain:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation does not require reconciliation"
                )
            self._append("resolved", event)

    def mutation_lock(self, *, server_id: str) -> AbstractContextManager[object]:
        """Serialize mutating remote operations for one logical server.

        The lock is deliberately separate from the short ledger append lock:
        it remains held across the remote operation, so two controllers cannot
        concurrently prepare/upload/terminate the same server state while both
        still observe an empty pending set. Process exit releases the kernel
        lock; the durable ledger then records the interrupted operation as
        effect-uncertain for the next controller.
        """

        if not server_id:
            raise ValueError("server_id must be non-empty")
        identity = hashlib.sha256(server_id.encode("utf-8")).hexdigest()[:32]
        return _NonBlockingServerLock(
            self.path.with_name(f"{self.path.name}.{identity}.mutation.lock"),
            server_id=server_id,
            busy_error=ServerMutationBusy,
        )

    def transport_lock(self, *, server_id: str) -> AbstractContextManager[object]:
        """Serialize every SSH/SCP attempt for one logical server.

        This is deliberately separate from the mutation lock.  A read-only
        health/status probe must not race an in-flight mutation into a shared
        SSH authentication or ControlMaster channel, but it also must not
        participate in mutation-effect reconciliation.
        """

        if not server_id:
            raise ValueError("server_id must be non-empty")
        identity = hashlib.sha256(server_id.encode("utf-8")).hexdigest()[:32]
        return _NonBlockingServerLock(
            self.path.with_name(f"{self.path.name}.{identity}.transport.lock"),
            server_id=server_id,
            busy_error=ServerTransportBusy,
        )

    def read_operation(self, operation_id: str) -> ServerOperationRecord | None:
        if not operation_id:
            raise ValueError("operation_id must be non-empty")
        return next(
            (record for record in self._read_records() if record.operation_id == operation_id),
            None,
        )

    def pending_operations(
        self,
        *,
        server_id: str | None = None,
    ) -> tuple[ServerOperationRecord, ...]:
        """Return operations whose remote effect is not durably known.

        This is a reconciliation signal, not a retry queue.  A caller must
        inspect the remote effect and record a resolution before submitting a
        mutating operation again.
        """

        return tuple(
            record
            for record in self._read_records()
            if record.effect_uncertain
            and (server_id is None or record.server_id == server_id)
        )

    def recent_operations(
        self,
        limit: int = 20,
        *,
        server_id: str | None = None,
    ) -> tuple[ServerOperationRecord, ...]:
        if limit <= 0:
            raise ValueError("operation history limit must be positive")
        records = tuple(
            record
            for record in self._read_records()
            if server_id is None or record.server_id == server_id
        )
        return tuple(reversed(records[-limit:]))


__all__ = ["JsonlServerOperationJournal", "ServerOperationJournalIntegrityError"]
