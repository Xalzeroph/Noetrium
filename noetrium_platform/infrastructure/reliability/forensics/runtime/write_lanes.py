from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from threading import Lock
from typing import Callable, Generic, TypeVar, cast

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.record_plane import event_document
from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicWriteActorPort
from noetrium_platform.infrastructure.reliability.forensics.runtime.event_projection_buffer import EventProjectionBuffer

T = TypeVar("T")


class ForensicProjectionError(RuntimeError):
    def __init__(
        self,
        ledger: str,
        rows: int,
        tail_hash: str,
        cause: BaseException,
        *,
        new_record: bool | None = None,
    ) -> None:
        super().__init__(
            f"authoritative {ledger} append committed but disposable projection failed "
            f"at rows={rows} tail={tail_hash}: {type(cause).__name__}: {cause}"
        )
        self.ledger = ledger
        self.rows = rows
        self.tail_hash = tail_hash
        self.cause = cause
        self.new_record = new_record


class EventWriteLane:
    """Actor-owned event lane with FIFO flat-combining across concurrent callers.

    Every public operation is still synchronous and linearized by the same
    forensic write actor.  Contending callers first join a process-local FIFO;
    one actor task drains that FIFO.  This preserves append/barrier ordering
    while avoiding one scheduler round-trip per event under high fan-in.
    """

    def __init__(self, ledger, index, *, batch_size: int, actor: ForensicWriteActorPort) -> None:
        self.ledger = ledger
        self._actor = actor
        self.buffer = EventProjectionBuffer(index, batch_size=batch_size)
        self._pending: deque[tuple[str, object, Future[object]]] = deque()
        self._pending_lock = Lock()
        self._drain_generation = 0
        self._active_drain: int | None = None

    def _flush_owned(self) -> None:
        if not self.buffer.backlog():
            return
        cursor = self.buffer.current_cursor()
        assert cursor is not None
        try:
            self.buffer.flush()
        except Exception as exc:
            raise ForensicProjectionError("events", cursor.position, cursor.source_digest, exc) from exc

    def _append_owned(self, event: NoetriumUnit) -> str:
        document = event_document(event)
        row_hash = self.ledger.append(document)
        rows, tail = self.ledger.cached_tail
        if self.buffer.add(event, document, rows, tail):
            self._flush_owned()
        return row_hash

    def _execute_owned(self, operation: str, payload: object) -> object:
        if operation == "event-append":
            return self._append_owned(cast(NoetriumUnit, payload))
        if operation == "event-flush":
            self._flush_owned()
            return None
        if operation == "critical-barrier":
            self._flush_owned()
            return cast(Callable[[], object], payload)()
        if operation == "event-backlog":
            return self.buffer.backlog()
        raise RuntimeError(f"unknown forensic event-lane operation: {operation}")

    def _drain_owned(self, generation: int) -> None:
        while True:
            with self._pending_lock:
                if not self._pending:
                    if self._active_drain != generation:
                        raise RuntimeError("forensic event-lane drain generation mismatch")
                    self._active_drain = None
                    return
                operation, payload, future = self._pending.popleft()
            try:
                result = self._execute_owned(operation, payload)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)

    def _abort_pending(self, exc: BaseException, generation: int) -> None:
        with self._pending_lock:
            if self._active_drain != generation:
                return
            pending = tuple(self._pending)
            self._pending.clear()
            self._active_drain = None
        for _operation, _payload, future in pending:
            if not future.done():
                future.set_exception(exc)

    def _call(self, operation: str, payload: object = None) -> object:
        future: Future[object] = Future()
        lead_generation: int | None = None
        with self._pending_lock:
            self._pending.append((operation, payload, future))
            if self._active_drain is None:
                self._drain_generation += 1
                lead_generation = self._drain_generation
                self._active_drain = lead_generation
        if lead_generation is not None:
            try:
                self._actor.call(operation, self._drain_owned, lead_generation)
            except BaseException as exc:
                self._abort_pending(exc, lead_generation)
                if not future.done():
                    future.set_exception(exc)
        return future.result()

    def append(self, event: NoetriumUnit) -> str:
        return cast(str, self._call("event-append", event))

    def flush(self) -> None:
        self._call("event-flush")

    def critical_call(self, fn: Callable[[], T]) -> T:
        """Flush prior events and run one critical mutation without event interleave."""
        return cast(T, self._call("critical-barrier", fn))

    def backlog(self) -> int:
        return cast(int, self._call("event-backlog"))


class CriticalWriteLane(Generic[T]):
    """Critical authoritative append executed by the forensic coordinator actor."""

    def __init__(
        self,
        ledger_name: str,
        ledger,
        projector: Callable[..., None],
        document: Callable[[T], dict[str, object]],
    ) -> None:
        self.ledger_name = ledger_name
        self.ledger = ledger
        self.projector = projector
        self.document = document

    def append_owned(self, obj: T) -> str:
        row_hash = self.ledger.append(self.document(obj))
        rows, tail = self.ledger.cached_tail
        try:
            self.projector(obj, rows=rows, tail_hash=tail)
        except Exception as exc:
            raise ForensicProjectionError(
                self.ledger_name,
                rows,
                tail,
                exc,
                new_record=True,
            ) from exc
        return row_hash
