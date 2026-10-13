from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import JsonDocument


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, *, field: str) -> None:
    if len(value) != 64 or any(char not in _HEX for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class VerifiedLedgerCut:
    """Verified authoritative prefix/suffix boundary without materialized payloads."""

    start_after: int
    total_rows: int
    checkpoint_hash: str
    tail_hash: str

    def __post_init__(self) -> None:
        if self.start_after < 0:
            raise ValueError("start_after must be non-negative")
        if self.total_rows < self.start_after:
            raise ValueError("total_rows cannot precede start_after")
        _require_sha256(self.checkpoint_hash, field="checkpoint_hash")
        _require_sha256(self.tail_hash, field="tail_hash")
        if self.start_after == 0 and self.checkpoint_hash != "0" * 64:
            raise ValueError("zero-row checkpoint must use the zero hash")
        if self.start_after == self.total_rows and self.checkpoint_hash != self.tail_hash:
            raise ValueError("terminal checkpoint must equal the authoritative tail hash")

    @property
    def suffix_rows(self) -> int:
        return self.total_rows - self.start_after


@dataclass(frozen=True, slots=True)
class VerifiedLedgerSlice:
    """Verified append-only suffix bound to an authoritative ledger prefix."""

    start_after: int
    total_rows: int
    checkpoint_hash: str
    tail_hash: str
    payloads: tuple[JsonDocument, ...]

    def __post_init__(self) -> None:
        if self.start_after < 0:
            raise ValueError("start_after must be non-negative")
        if self.total_rows < self.start_after:
            raise ValueError("total_rows cannot precede start_after")
        if len(self.payloads) != self.total_rows - self.start_after:
            raise ValueError("payload count must equal total_rows - start_after")
        _require_sha256(self.checkpoint_hash, field="checkpoint_hash")
        _require_sha256(self.tail_hash, field="tail_hash")
        if self.start_after == 0 and self.checkpoint_hash != "0" * 64:
            raise ValueError("zero-row checkpoint must use the zero hash")
        if self.start_after == self.total_rows and self.checkpoint_hash != self.tail_hash:
            raise ValueError("terminal checkpoint must equal the authoritative tail hash")

    @property
    def empty(self) -> bool:
        return not self.payloads


__all__ = ["VerifiedLedgerCut", "VerifiedLedgerSlice"]
