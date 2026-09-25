from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Iterator

from .runtime_history_codec import (
    build_runtime_history_row,
    encode_runtime_history_row,
    runtime_state_digest,
)
from .runtime_history_contracts import (
    RUNTIME_HISTORY_ROW_SCHEMA_VERSION,
    RuntimeHistoryEntry,
    RuntimeHistoryIntegrityError,
    RuntimeHistoryProjectionKind,
)
from .runtime_history_integrity import runtime_history_tail, verify_runtime_history_lines
from .runtime_history_ports import RuntimeHistoryAppendSession, RuntimeHistoryStoragePort
from .runtime_state_contracts import RuntimeControlState


@dataclass
class _VerifiedAppendSession:
    storage: RuntimeHistoryStoragePort
    sequence: int
    previous_sha256: str | None
    _tail: RuntimeHistoryEntry | None
    _used: bool = False

    @property
    def tail(self) -> RuntimeHistoryEntry | None:
        return self._tail

    def append(
        self,
        state: RuntimeControlState,
        *,
        projection_kind: RuntimeHistoryProjectionKind = RuntimeHistoryProjectionKind.STATE_WRITE,
    ) -> RuntimeHistoryEntry:
        if self._used:
            raise RuntimeError("verified runtime history append session already consumed")
        if not isinstance(projection_kind, RuntimeHistoryProjectionKind):
            raise TypeError("projection_kind must be RuntimeHistoryProjectionKind")
        row, entry = build_runtime_history_row(
            sequence=self.sequence + 1,
            state=state,
            projection_kind=projection_kind,
            previous_sha256=self.previous_sha256,
        )
        self.storage.append(encode_runtime_history_row(row))
        self._used = True
        return entry


class RuntimeHistory:
    """Hash-chain and reconciliation authority over an opaque durable row store."""

    def __init__(self, storage: RuntimeHistoryStoragePort) -> None:
        self._storage = storage
        self._lock = RLock()

    def reference(self) -> str:
        return self._storage.reference()

    @staticmethod
    def _verified_tail_from_lines(lines: tuple[str, ...]) -> RuntimeHistoryEntry | None:
        errors = verify_runtime_history_lines(lines)
        if errors:
            raise RuntimeHistoryIntegrityError("runtime history integrity failure: " + "; ".join(errors))
        try:
            return runtime_history_tail(lines)
        except ValueError as exc:
            raise RuntimeHistoryIntegrityError("runtime history tail contract failure") from exc

    def verify(self) -> tuple[str, ...]:
        with self._lock, self._storage.exclusive():
            return verify_runtime_history_lines(self._storage.lines())

    def assert_integrity(self) -> None:
        with self._lock, self._storage.exclusive():
            self._verified_tail_from_lines(self._storage.lines())

    @contextmanager
    def verified_append_session(self) -> Iterator[RuntimeHistoryAppendSession]:
        """Hold one process/thread-wide history write fence from verification through append.

        RuntimeControlStore deliberately keeps this context open while publishing the
        authoritative state.  Therefore two processes cannot verify the same tail and then
        append competing rows.  A crash after state publication but before append remains
        the explicit reconciliation window.
        """

        with self._lock, self._storage.exclusive():
            tail = self._verified_tail_from_lines(self._storage.lines())
            sequence = 0 if tail is None else tail.sequence
            previous_sha256 = None if tail is None else tail.row_sha256
            yield _VerifiedAppendSession(self._storage, sequence, previous_sha256, tail)

    def append(
        self,
        state: RuntimeControlState,
        *,
        projection_kind: RuntimeHistoryProjectionKind = RuntimeHistoryProjectionKind.STATE_WRITE,
    ) -> RuntimeHistoryEntry:
        with self.verified_append_session() as session:
            return session.append(state, projection_kind=projection_kind)

    def reconcile_authoritative(self, state: RuntimeControlState) -> bool:
        """Append an explicit reconciliation only when projection lags authoritative state."""

        expected_digest = runtime_state_digest(state)
        with self.verified_append_session() as session:
            tail = session.tail
            if tail is not None:
                if (
                    tail.state.control_id != state.control_id
                    or tail.state.manifest_digest != state.manifest_digest
                ):
                    raise RuntimeHistoryIntegrityError(
                        "runtime history tail belongs to a different control/manifest identity"
                    )
                if tail.state_sha256 == expected_digest:
                    return False
            session.append(
                state,
                projection_kind=RuntimeHistoryProjectionKind.AUTHORITATIVE_RECONCILE,
            )
            return True

    def assert_tail_matches(self, state: RuntimeControlState) -> None:
        expected_digest = runtime_state_digest(state)
        with self._lock, self._storage.exclusive():
            tail = self._verified_tail_from_lines(self._storage.lines())
        if tail is None:
            raise RuntimeHistoryIntegrityError("runtime history missing authoritative state projection")
        if tail.state_sha256 != expected_digest:
            raise RuntimeHistoryIntegrityError("runtime history tail does not match authoritative current state")


__all__ = [
    "RUNTIME_HISTORY_ROW_SCHEMA_VERSION",
    "RuntimeHistory",
    "RuntimeHistoryEntry",
    "RuntimeHistoryIntegrityError",
    "RuntimeHistoryProjectionKind",
]
