from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import JsonDocument
from noetrium_platform.infrastructure.reliability.forensics.api import VerifiedLedgerCut, VerifiedLedgerSlice
from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import ZERO_HASH, hash_payload


class HashChainError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _HashChainScan:
    total_rows: int
    tail_hash: str
    checkpoint_hash: str
    payloads: tuple[JsonDocument, ...]


def _scan_hash_chain(
    path: Path, *, start_after: int | None, collect_payloads: bool = True
) -> _HashChainScan:
    if start_after is not None and start_after < 0:
        raise ValueError("start_after must be non-negative")
    prev = ZERO_HASH
    checkpoint = ZERO_HASH
    count = 0
    payloads: list[JsonDocument] = []
    if not path.exists():
        if start_after:
            raise HashChainError("projection checkpoint exceeds missing ledger")
        return _HashChainScan(0, prev, checkpoint, ())

    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HashChainError(f"line {lineno}: invalid/truncated JSON") from exc
            payload = row.get("payload")
            if not isinstance(payload, dict):
                raise HashChainError(f"line {lineno}: invalid payload")
            if row.get("prev_hash") != prev:
                raise HashChainError(f"line {lineno}: previous hash mismatch")
            expected = hash_payload(prev, payload)
            if row.get("row_hash") != expected:
                raise HashChainError(f"line {lineno}: row hash mismatch")
            prev = expected
            count += 1
            if start_after is not None and count == start_after:
                checkpoint = expected
            if collect_payloads and start_after is not None and count > start_after:
                payloads.append(payload)
    if start_after is not None and start_after > count:
        raise HashChainError(
            f"projection checkpoint rows={start_after} exceeds authoritative rows={count}"
        )
    if start_after is not None and start_after == count:
        checkpoint = prev
    return _HashChainScan(count, prev, checkpoint, tuple(payloads))


def scan_hash_chain(path: Path) -> tuple[int, str]:
    result = _scan_hash_chain(path, start_after=None)
    return result.total_rows, result.tail_hash


def scan_hash_chain_payloads(path: Path, *, start_after: int = 0) -> VerifiedLedgerSlice:
    result = _scan_hash_chain(path, start_after=start_after)
    return VerifiedLedgerSlice(
        start_after=start_after,
        total_rows=result.total_rows,
        checkpoint_hash=result.checkpoint_hash,
        tail_hash=result.tail_hash,
        payloads=result.payloads,
    )


def scan_hash_chain_cut(path: Path, *, start_after: int = 0) -> VerifiedLedgerCut:
    result = _scan_hash_chain(path, start_after=start_after, collect_payloads=False)
    return VerifiedLedgerCut(
        start_after=start_after,
        total_rows=result.total_rows,
        checkpoint_hash=result.checkpoint_hash,
        tail_hash=result.tail_hash,
    )


def iter_hash_chain_payload_batches(
    path: Path, *, cut: VerifiedLedgerCut, batch_size: int = 512
):
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if cut.total_rows == 0:
        return
    prev = ZERO_HASH
    checkpoint = ZERO_HASH
    count = 0
    batch: list[JsonDocument] = []
    if not path.exists():
        raise HashChainError("verified ledger cut disappeared before streaming")
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HashChainError(f"line {lineno}: invalid/truncated JSON") from exc
            payload = row.get("payload")
            if not isinstance(payload, dict):
                raise HashChainError(f"line {lineno}: invalid payload")
            if row.get("prev_hash") != prev:
                raise HashChainError(f"line {lineno}: previous hash mismatch")
            expected = hash_payload(prev, payload)
            if row.get("row_hash") != expected:
                raise HashChainError(f"line {lineno}: row hash mismatch")
            prev = expected
            count += 1
            if count == cut.start_after:
                checkpoint = expected
            if cut.start_after < count <= cut.total_rows:
                batch.append(payload)
                if len(batch) >= batch_size:
                    yield tuple(batch)
                    batch.clear()
            if count == cut.total_rows:
                if checkpoint != cut.checkpoint_hash or prev != cut.tail_hash:
                    raise HashChainError("ledger changed after verified cut")
                if batch:
                    yield tuple(batch)
                return
    raise HashChainError(
        f"verified ledger cut rows={cut.total_rows} exceeds streamed rows={count}"
    )


__all__ = [
    "HashChainError",
    "iter_hash_chain_payload_batches",
    "scan_hash_chain",
    "scan_hash_chain_cut",
    "scan_hash_chain_payloads",
]
