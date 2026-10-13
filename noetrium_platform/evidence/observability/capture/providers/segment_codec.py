from __future__ import annotations

import hashlib
import json

class RawSegmentCodecError(ValueError):
    pass


def _reject_constant(token: str) -> object:
    raise RawSegmentCodecError(
        f"raw segment JSON forbids non-finite constant: {token}"
    )


def _object_from_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RawSegmentCodecError(
                f"raw segment JSON contains duplicate object key: {key!r}"
            )
        result[key] = value
    return result


def decode_record_json(raw: bytes) -> dict[str, object]:
    try:
        document = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_object_from_pairs,
        )
    except RawSegmentCodecError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RawSegmentCodecError("raw segment record is not valid JSON") from exc
    if not isinstance(document, dict):
        raise RawSegmentCodecError("raw segment record must be an object")
    return document


def canonical_record_bytes(record: dict[str, object]) -> bytes:
    try:
        return json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RawSegmentCodecError("raw segment record is not canonical JSON") from exc


def encode_record(record: dict[str, object]) -> tuple[bytes, str]:
    canonical = canonical_record_bytes(record)
    digest = hashlib.sha256(canonical).hexdigest()
    encoded = canonical_record_bytes({**record, "record_sha256": digest}) + b"\n"
    return encoded, digest


__all__ = [
    "RawSegmentCodecError",
    "canonical_record_bytes",
    "decode_record_json",
    "encode_record",
]
