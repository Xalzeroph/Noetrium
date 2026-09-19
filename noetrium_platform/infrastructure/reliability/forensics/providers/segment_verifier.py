from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import JsonDocument
from noetrium_platform.infrastructure.reliability.forensics.api import VerifiedLedgerCut, VerifiedLedgerSlice
from noetrium_platform.infrastructure.reliability.forensics.providers.hashchain_core import ZERO_HASH, hash_payload
from noetrium_platform.infrastructure.reliability.forensics.providers.hashlog_scanner import HashChainError


@dataclass(frozen=True, slots=True)
class SegmentScanSummary:
    index: int
    rows: int
    bytes: int
    start_prev_hash: str
    end_hash: str
    filename: str


@dataclass(frozen=True, slots=True)
class SegmentScanResult:
    total_rows: int
    tail_hash: str
    summaries: tuple[SegmentScanSummary, ...]


def segment_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.glob("[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].jsonl")))

def _scan_segment_chain(
    root: Path,
    *,
    start_after: int | None,
    collect_payloads: bool = True,
) -> tuple[SegmentScanResult, str, tuple[JsonDocument, ...]]:
    if start_after is not None and start_after < 0:
        raise ValueError("start_after must be non-negative")
    prev = ZERO_HASH
    checkpoint = ZERO_HASH
    total = 0
    summaries: list[SegmentScanSummary] = []
    payloads: list[JsonDocument] = []

    for expected_index, path in enumerate(segment_files(root)):
        if path.name != f"{expected_index:08d}.jsonl":
            raise HashChainError(
                f"segment sequence gap: expected {expected_index:08d}.jsonl, found {path.name}"
            )
        start_prev = prev
        rows = 0
        with path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: invalid/truncated JSON"
                    ) from exc
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: invalid payload"
                    )
                if row.get("prev_hash") != prev:
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: previous hash mismatch"
                    )
                expected = hash_payload(prev, payload)
                if row.get("row_hash") != expected:
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: row hash mismatch"
                    )
                prev = expected
                rows += 1
                total += 1
                if start_after is not None and total == start_after:
                    checkpoint = expected
                if collect_payloads and start_after is not None and total > start_after:
                    payloads.append(payload)
        summaries.append(
            SegmentScanSummary(
                expected_index,
                rows,
                path.stat().st_size,
                start_prev,
                prev,
                path.name,
            )
        )
    if start_after is not None and start_after > total:
        raise HashChainError(
            f"projection checkpoint rows={start_after} exceeds authoritative rows={total}"
        )
    if start_after is not None and start_after == total:
        checkpoint = prev
    return SegmentScanResult(total, prev, tuple(summaries)), checkpoint, tuple(payloads)


def scan_segment_chain(root: Path) -> SegmentScanResult:
    """Verify authoritative segment bytes without writing projection state."""
    result, _, _ = _scan_segment_chain(root, start_after=None)
    return result


def scan_segment_chain_payloads(
    root: Path,
    *,
    start_after: int = 0,
) -> tuple[SegmentScanResult, VerifiedLedgerSlice]:
    """Verify one global chain and expose a typed authoritative suffix."""
    result, checkpoint, payloads = _scan_segment_chain(root, start_after=start_after)
    return result, VerifiedLedgerSlice(
        start_after=start_after,
        total_rows=result.total_rows,
        checkpoint_hash=checkpoint,
        tail_hash=result.tail_hash,
        payloads=payloads,
    )


def scan_segment_chain_cut(root: Path, *, start_after: int = 0) -> tuple[SegmentScanResult, VerifiedLedgerCut]:
    result, checkpoint, _ = _scan_segment_chain(
        root, start_after=start_after, collect_payloads=False
    )
    return result, VerifiedLedgerCut(
        start_after=start_after,
        total_rows=result.total_rows,
        checkpoint_hash=checkpoint,
        tail_hash=result.tail_hash,
    )


def iter_segment_chain_payload_batches(
    root: Path, *, cut: VerifiedLedgerCut, batch_size: int = 512
):
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if cut.total_rows == 0:
        return
    prev = ZERO_HASH
    checkpoint = ZERO_HASH
    total = 0
    batch: list[JsonDocument] = []
    for expected_index, path in enumerate(segment_files(root)):
        if path.name != f"{expected_index:08d}.jsonl":
            raise HashChainError(
                f"segment sequence gap: expected {expected_index:08d}.jsonl, found {path.name}"
            )
        with path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: invalid/truncated JSON"
                    ) from exc
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: invalid payload"
                    )
                if row.get("prev_hash") != prev:
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: previous hash mismatch"
                    )
                expected = hash_payload(prev, payload)
                if row.get("row_hash") != expected:
                    raise HashChainError(
                        f"segment {expected_index} line {lineno}: row hash mismatch"
                    )
                prev = expected
                total += 1
                if total == cut.start_after:
                    checkpoint = expected
                if cut.start_after < total <= cut.total_rows:
                    batch.append(payload)
                    if len(batch) >= batch_size:
                        yield tuple(batch)
                        batch.clear()
                if total == cut.total_rows:
                    if checkpoint != cut.checkpoint_hash or prev != cut.tail_hash:
                        raise HashChainError("segmented ledger changed after verified cut")
                    if batch:
                        yield tuple(batch)
                    return
    raise HashChainError(
        f"verified segmented cut rows={cut.total_rows} exceeds streamed rows={total}"
    )


__all__ = [
    "SegmentScanResult",
    "SegmentScanSummary",
    "iter_segment_chain_payload_batches",
    "scan_segment_chain",
    "scan_segment_chain_cut",
    "scan_segment_chain_payloads",
    "segment_files",
]
