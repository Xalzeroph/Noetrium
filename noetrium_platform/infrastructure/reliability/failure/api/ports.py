from __future__ import annotations

from typing import Protocol

from .contracts import FailureEnvelope


class FailureLedgerPort(Protocol):
    """Minimal durable append-once authority used by non-forensic coordinators."""

    def append_failure_once(self, failure: FailureEnvelope) -> tuple[bool, str | None]: ...


__all__ = ["FailureLedgerPort"]
