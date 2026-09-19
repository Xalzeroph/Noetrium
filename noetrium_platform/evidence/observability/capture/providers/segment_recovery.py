from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from ..api.contracts import RawObservationCorruptionError, RawObservationReceipt
from .segment_codec import RawSegmentCodecError, canonical_record_bytes, decode_record_json


@dataclass(frozen=True, slots=True)
class RecoveredRawSegment:
    sequence: int
    idempotency: dict[str, RawObservationReceipt]
    valid_bytes: int
    discarded_tail_bytes: int = 0


def _fail(target: Path, line_no: int, message: str) -> RawObservationCorruptionError:
    return RawObservationCorruptionError(f"{target}: line {line_no}: {message}")


def _decode_record(
    target: Path,
    line_no: int,
    raw: bytes,
    *,
    family: str,
    schema_version: str,
    run_id: str,
    expected_sequence: int,
) -> tuple[int, str | None, str]:
    try:
        document = decode_record_json(raw)
    except RawSegmentCodecError as exc:
        raise _fail(target, line_no, "invalid canonical json") from exc
    sequence = document.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence != expected_sequence:
        raise _fail(target, line_no, f"expected sequence {expected_sequence}, got {sequence!r}")
    if document.get("family") != family:
        raise _fail(target, line_no, f"family mismatch {document.get('family')!r} != {family!r}")
    if document.get("schema_version") != schema_version:
        raise _fail(
            target,
            line_no,
            f"schema drift {document.get('schema_version')!r} != {schema_version!r}",
        )
    context = document.get("context")
    if not isinstance(context, dict) or context.get("run_id") != run_id:
        raise _fail(target, line_no, "record context run_id does not match segment identity")
    stored_digest = document.get("record_sha256")
    if not isinstance(stored_digest, str) or len(stored_digest) != 64 or any(
        char not in "0123456789abcdef" for char in stored_digest
    ):
        raise _fail(target, line_no, "record_sha256 is not lowercase SHA-256")
    unsigned = dict(document)
    del unsigned["record_sha256"]
    try:
        canonical = canonical_record_bytes(unsigned)
    except RawSegmentCodecError as exc:
        raise _fail(target, line_no, "record cannot be canonicalized") from exc
    actual_digest = hashlib.sha256(canonical).hexdigest()
    if stored_digest != actual_digest:
        raise _fail(target, line_no, "record digest mismatch")
    idempotency_key = document.get("idempotency_key")
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key
    ):
        raise _fail(target, line_no, "idempotency_key must be a non-empty string")
    return sequence, idempotency_key, stored_digest


def scan_raw_segment(
    target: Path,
    *,
    family: str,
    schema_version: str,
    run_id: str,
    limit_bytes: int | None = None,
    repair_partial_tail: bool = False,
) -> RecoveredRawSegment:
    if not target.exists():
        return RecoveredRawSegment(0, {}, 0, 0)
    file_size = target.stat().st_size
    if limit_bytes is None:
        limit_bytes = file_size
    if limit_bytes < 0 or limit_bytes > file_size:
        raise ValueError("raw segment scan boundary is outside the current file")

    sequence = 0
    idempotency: dict[str, RawObservationReceipt] = {}
    valid_bytes = 0
    discarded_tail_bytes = 0
    with target.open("rb") as handle:
        remaining = limit_bytes
        line_no = 0
        while remaining > 0:
            raw = handle.readline(remaining)
            if not raw:
                break
            remaining -= len(raw)
            line_no += 1
            if not raw.endswith(b"\n"):
                discarded_tail_bytes = len(raw)
                if not repair_partial_tail:
                    raise _fail(target, line_no, "incomplete trailing record")
                break
            sequence_value, idempotency_key, digest = _decode_record(
                target,
                line_no,
                raw,
                family=family,
                schema_version=schema_version,
                run_id=run_id,
                expected_sequence=sequence + 1,
            )
            sequence = sequence_value
            valid_bytes += len(raw)
            if idempotency_key is not None:
                if idempotency_key in idempotency:
                    raise _fail(target, line_no, f"duplicate idempotency key {idempotency_key}")
                idempotency[idempotency_key] = RawObservationReceipt(
                    family,
                    schema_version,
                    run_id,
                    str(target),
                    sequence,
                    digest,
                    len(raw),
                )

    if discarded_tail_bytes:
        with target.open("r+b") as handle:
            handle.truncate(valid_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    return RecoveredRawSegment(sequence, idempotency, valid_bytes, discarded_tail_bytes)


def recover_raw_segment(
    target: Path,
    *,
    family: str,
    schema_version: str,
    run_id: str,
) -> RecoveredRawSegment:
    return scan_raw_segment(
        target,
        family=family,
        schema_version=schema_version,
        run_id=run_id,
        repair_partial_tail=True,
    )
