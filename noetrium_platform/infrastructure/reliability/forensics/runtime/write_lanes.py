from __future__ import annotations

from typing import Callable, Generic, TypeVar

from noetrium_platform.evidence.observability.api import EventEnvelope
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
    """Actor-owned authoritative event append + projection barrier coordination."""

    def __init__(self, ledger, index, *, batch_size: int, actor: ForensicWriteActorPort) -> None:
        self.ledger = ledger
        self._actor = actor
        self.buffer = EventProjectionBuffer(index, batch_size=batch_size)

    def _flush_owned(self) -> None:
        if not self.buffer.backlog():
            return
        cursor = self.buffer.current_cursor()
        assert cursor is not None
        try:
            self.buffer.flush()
        except Exception as exc:
            raise ForensicProjectionError("events", cursor.position, cursor.source_digest, exc) from exc

    def _append_owned(self, event: EventEnvelope) -> str:
        row_hash = self.ledger.append(event.to_dict())
        rows, tail = self.ledger.cached_tail
        if self.buffer.add(event, rows, tail):
            self._flush_owned()
        return row_hash

    def append(self, event: EventEnvelope) -> str:
        return self._actor.call("event-append", self._append_owned, event)

    def flush(self) -> None:
        self._actor.call("event-flush", self._flush_owned)

    def critical_call(self, fn: Callable[[], T]) -> T:
        """Flush prior events and run one critical mutation without event interleave."""

        def invoke() -> T:
            self._flush_owned()
            return fn()

        return self._actor.call("critical-barrier", invoke)

    def backlog(self) -> int:
        return self._actor.call("event-backlog", self.buffer.backlog)


class CriticalWriteLane(Generic[T]):
    """Critical authoritative append executed by the forensic coordinator actor."""

    def __init__(self, ledger_name: str, ledger, projector: Callable[..., None]) -> None:
        self.ledger_name = ledger_name
        self.ledger = ledger
        self.projector = projector

    def append_owned(self, obj: T) -> str:
        row_hash = self.ledger.append(obj.to_dict())
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
