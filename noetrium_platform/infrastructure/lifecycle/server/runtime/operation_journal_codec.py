from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re

from noetrium_platform.foundation.kernel.kernel import CanonicalEncodingError, canonical_bytes
from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationEffect,
    ServerOperationFinished,
    ServerOperationKind,
    ServerOperationResolved,
    ServerOperationResolution,
    ServerOperationStarted,
    ServerOperationState,
)


SERVER_OPERATION_JOURNAL_SCHEMA = "server-operation-journal.v2"
SERVER_OPERATION_JOURNAL_GENESIS_CHECKSUM = "0" * 64
MAX_SERVER_OPERATION_RECORD_BYTES = 256 * 1024
_CHECKSUM_RE = re.compile(r"[0-9a-f]{64}")
_OPERATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SERVER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


def _require_sha256(value: str, label: str, *, allow_empty: bool = False) -> None:
    if allow_empty and value == "":
        return
    if _CHECKSUM_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical SHA-256 digest")


def _require_durable_identity(operation_id: str, server_id: str) -> None:
    if _OPERATION_ID_RE.fullmatch(operation_id) is None:
        raise ValueError("operation_id must be a safe non-empty durable identifier")
    if _SERVER_ID_RE.fullmatch(server_id) is None:
        raise ValueError("server_id must be a safe non-empty durable identifier")


class ServerOperationJournalIntegrityError(RuntimeError):
    """The durable server-operation ledger cannot be safely replayed."""


ServerOperationEvent = ServerOperationStarted | ServerOperationFinished | ServerOperationResolved


@dataclass(frozen=True, slots=True)
class DecodedServerOperationEnvelope:
    event_type: str
    event: ServerOperationEvent
    record_checksum: str


def _record_checksum(body: dict[str, object]) -> str:
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def _require_exact_fields(payload: dict[str, object], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        raise ValueError(f"{label} field set is not exact")


def _require_strings(payload: dict[str, object], keys: tuple[str, ...], label: str) -> None:
    if any(type(payload[key]) is not str for key in keys):
        raise TypeError(f"{label} string field has wrong type")


def _finite_nonnegative(value: object, label: str) -> float:
    if (
        type(value) not in {int, float}
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ValueError(f"{label} must be finite and non-negative")
    return float(value)


def _decode_started(payload: dict[str, object]) -> ServerOperationStarted:
    expected = {
        "operation_id", "server_id", "kind", "request_digest", "started_at",
        "interactive", "profile_digest", "effect",
    }
    _require_exact_fields(payload, expected, "started")
    _require_strings(
        payload,
        ("operation_id", "server_id", "kind", "request_digest", "profile_digest", "effect"),
        "started",
    )
    if type(payload["interactive"]) is not bool:
        raise TypeError("started interactive must be a boolean")
    _require_durable_identity(payload["operation_id"], payload["server_id"])
    _require_sha256(payload["request_digest"], "request_digest")
    _require_sha256(payload["profile_digest"], "profile_digest", allow_empty=True)
    started_at = _finite_nonnegative(payload["started_at"], "started_at")
    return ServerOperationStarted(
        payload["operation_id"],
        payload["server_id"],
        ServerOperationKind(payload["kind"]),
        payload["request_digest"],
        started_at,
        payload["interactive"],
        payload["profile_digest"],
        ServerOperationEffect(payload["effect"]),
    )


def _decode_finished(payload: dict[str, object]) -> ServerOperationFinished:
    expected = {
        "operation_id", "server_id", "kind", "request_digest", "state",
        "finished_at", "duration_seconds", "return_code", "failure_kind",
        "stdout_bytes", "stderr_bytes", "error_type", "error_digest",
        "profile_digest", "stdout_digest", "stderr_digest", "effect",
        "stdout_preview", "stderr_preview",
    }
    _require_exact_fields(payload, expected, "finished")
    _require_strings(
        payload,
        (
            "operation_id", "server_id", "kind", "request_digest", "state",
            "failure_kind", "profile_digest", "stdout_digest", "stderr_digest",
            "effect", "stdout_preview", "stderr_preview",
        ),
        "finished",
    )
    for key in ("error_type", "error_digest"):
        if payload[key] is not None and type(payload[key]) is not str:
            raise TypeError(f"finished {key} must be null or string")
    _require_durable_identity(payload["operation_id"], payload["server_id"])
    _require_sha256(payload["request_digest"], "request_digest")
    _require_sha256(payload["profile_digest"], "profile_digest", allow_empty=True)
    for key in ("stdout_digest", "stderr_digest"):
        _require_sha256(payload[key], key, allow_empty=True)
    if (payload["error_type"] is None) != (payload["error_digest"] is None):
        raise ValueError("finished error_type and error_digest must be present together")
    if payload["error_digest"] is not None:
        _require_sha256(payload["error_digest"], "error_digest")
    finished_at = _finite_nonnegative(payload["finished_at"], "finished_at")
    duration = _finite_nonnegative(payload["duration_seconds"], "duration_seconds")
    for key in ("stdout_bytes", "stderr_bytes"):
        if type(payload[key]) is not int or payload[key] < 0:
            raise ValueError(f"finished {key} must be a non-negative integer")
    if payload["return_code"] is not None and type(payload["return_code"]) is not int:
        raise TypeError("finished return_code must be null or integer")
    state = ServerOperationState(payload["state"])
    failure_kind = payload["failure_kind"]
    if state is ServerOperationState.STARTED:
        raise ValueError("finished event cannot use started state")
    if state is ServerOperationState.SUCCEEDED:
        if payload["return_code"] != 0 or failure_kind != "none":
            raise ValueError("succeeded operation must have return_code=0 and failure_kind=none")
        if payload["error_type"] is not None:
            raise ValueError("succeeded operation cannot carry error evidence")
    elif state is ServerOperationState.TIMED_OUT:
        if failure_kind != "timeout":
            raise ValueError("timed-out operation must have failure_kind=timeout")
        if payload["error_type"] is not None:
            raise ValueError("timed-out result cannot carry exception evidence")
    elif not failure_kind or failure_kind == "none":
        raise ValueError("failed operation must carry a non-success failure kind")
    return ServerOperationFinished(
        payload["operation_id"],
        payload["server_id"],
        ServerOperationKind(payload["kind"]),
        payload["request_digest"],
        state,
        finished_at,
        duration,
        payload["return_code"],
        payload["failure_kind"],
        payload["stdout_bytes"],
        payload["stderr_bytes"],
        payload["error_type"],
        payload["error_digest"],
        payload["profile_digest"],
        payload["stdout_digest"],
        payload["stderr_digest"],
        ServerOperationEffect(payload["effect"]),
        payload["stdout_preview"],
        payload["stderr_preview"],
    )


def _decode_resolved(payload: dict[str, object]) -> ServerOperationResolved:
    expected = {
        "operation_id", "server_id", "kind", "request_digest", "disposition",
        "resolved_at", "evidence_ref", "evidence_digest", "profile_digest",
    }
    _require_exact_fields(payload, expected, "resolution")
    _require_strings(
        payload,
        (
            "operation_id", "server_id", "kind", "request_digest", "disposition",
            "evidence_ref", "evidence_digest", "profile_digest",
        ),
        "resolution",
    )
    _require_durable_identity(payload["operation_id"], payload["server_id"])
    _require_sha256(payload["request_digest"], "request_digest")
    _require_sha256(payload["profile_digest"], "profile_digest", allow_empty=True)
    resolved_at = _finite_nonnegative(payload["resolved_at"], "resolved_at")
    evidence_ref = payload["evidence_ref"]
    evidence_digest = payload["evidence_digest"]
    if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,256}", evidence_ref) is None:
        raise ValueError("resolution evidence reference is unsafe")
    if re.fullmatch(r"[0-9a-f]{64}", evidence_digest) is None:
        raise ValueError("resolution evidence digest is not canonical SHA-256")
    return ServerOperationResolved(
        payload["operation_id"],
        payload["server_id"],
        ServerOperationKind(payload["kind"]),
        payload["request_digest"],
        ServerOperationResolution(payload["disposition"]),
        resolved_at,
        evidence_ref,
        evidence_digest,
        payload["profile_digest"],
    )


def _decode_event(event_type: str, payload: dict[str, object]) -> ServerOperationEvent:
    try:
        if event_type == "started":
            return _decode_started(payload)
        if event_type == "finished":
            return _decode_finished(payload)
        if event_type == "resolved":
            return _decode_resolved(payload)
        raise ValueError(f"unsupported server operation event type: {event_type!r}")
    except ServerOperationJournalIntegrityError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ServerOperationJournalIntegrityError(
            f"server operation {event_type} record is malformed"
        ) from exc


def _event_payload(event: ServerOperationEvent) -> dict[str, object]:
    payload = asdict(event)
    for key, value in tuple(payload.items()):
        if hasattr(value, "value"):
            payload[key] = value.value
    return payload


class ServerOperationJournalCodec:
    """Canonical hash-chain codec for server-operation WAL records."""

    def encode(
        self,
        event_type: str,
        event: ServerOperationEvent,
        *,
        previous_checksum: str,
    ) -> bytes:
        if _CHECKSUM_RE.fullmatch(previous_checksum) is None:
            raise ValueError("server operation previous checksum must be canonical SHA-256")
        payload = _event_payload(event)
        decoded = _decode_event(event_type, dict(payload))
        if decoded != event:
            raise ServerOperationJournalIntegrityError(
                "server operation event does not round-trip through the typed journal schema"
            )
        body: dict[str, object] = {
            "journal_schema": SERVER_OPERATION_JOURNAL_SCHEMA,
            "previous_checksum": previous_checksum,
            "event": event_type,
            **payload,
        }
        record = {**body, "record_checksum": _record_checksum(body)}
        encoded = canonical_bytes(record) + b"\n"
        if len(encoded) > MAX_SERVER_OPERATION_RECORD_BYTES:
            raise ValueError("server operation journal record exceeds size limit")
        return encoded

    def decode(
        self,
        raw: bytes,
        *,
        expected_previous_checksum: str | None,
    ) -> DecodedServerOperationEnvelope:
        if not raw or len(raw) > MAX_SERVER_OPERATION_RECORD_BYTES:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger record size is invalid"
            )
        try:
            document = json.loads(raw.decode("utf-8"))
            if not isinstance(document, dict):
                raise TypeError("record is not an object")
            canonical = canonical_bytes(document)
        except (UnicodeDecodeError, json.JSONDecodeError, CanonicalEncodingError, TypeError, ValueError) as exc:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger record is not canonical JSON"
            ) from exc
        if canonical != raw:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger record bytes are not canonical"
            )
        record_checksum = document.get("record_checksum")
        previous_checksum = document.get("previous_checksum")
        event_type = document.get("event")
        if document.get("journal_schema") != SERVER_OPERATION_JOURNAL_SCHEMA:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger schema is unsupported"
            )
        if not isinstance(record_checksum, str) or _CHECKSUM_RE.fullmatch(record_checksum) is None:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger record checksum is invalid"
            )
        if not isinstance(previous_checksum, str) or _CHECKSUM_RE.fullmatch(previous_checksum) is None:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger previous checksum is invalid"
            )
        if type(event_type) is not str:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger event type is invalid"
            )
        if (
            expected_previous_checksum is not None
            and previous_checksum != expected_previous_checksum
        ):
            raise ServerOperationJournalIntegrityError(
                "server operation ledger hash chain is discontinuous"
            )
        body = dict(document)
        body.pop("record_checksum", None)
        if _record_checksum(body) != record_checksum:
            raise ServerOperationJournalIntegrityError(
                "server operation ledger record checksum mismatch"
            )
        payload = dict(body)
        payload.pop("journal_schema", None)
        payload.pop("previous_checksum", None)
        payload.pop("event", None)
        event = _decode_event(event_type, payload)
        return DecodedServerOperationEnvelope(event_type, event, record_checksum)


__all__ = [
    "DecodedServerOperationEnvelope",
    "MAX_SERVER_OPERATION_RECORD_BYTES",
    "SERVER_OPERATION_JOURNAL_GENESIS_CHECKSUM",
    "SERVER_OPERATION_JOURNAL_SCHEMA",
    "ServerOperationJournalCodec",
    "ServerOperationJournalIntegrityError",
]
