"""Causal Event-Unit store for server control-plane operations.

Each operation is its own authority domain.  Independent server operations are
not forced through a synthetic global journal order; only started -> finished ->
resolved transitions for the same operation carry causal-parent edges.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import asdict
from enum import Enum
import hashlib
import math
from pathlib import Path
import re

from noetrium_platform.foundation.kernel.event import (
    causal_event,
    causal_topological_order,
    event_field,
    event_ref,
    is_event_unit,
)
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.foundation.kernel.kernel.durability import (
    InterprocessFileLock,
    InterprocessLockBusy,
)
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)
from noetrium_platform.infrastructure.lifecycle.server.api import (
    ServerOperationEffect,
    ServerOperationEventStorePort,
    ServerOperationFinished,
    ServerOperationKind,
    ServerOperationRecord,
    ServerOperationResolved,
    ServerOperationResolution,
    ServerOperationStarted,
    ServerOperationState,
    ServerOperationTransitionConflict,
    ServerMutationBusy,
    ServerTransportBusy,
)


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_OPERATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SERVER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_EVIDENCE_REF_RE = re.compile(r"[A-Za-z0-9_.:/-]{1,256}")


class ServerOperationEventIntegrityError(RuntimeError):
    """A server-operation causal Event trace cannot be safely projected."""


def _require_sha256(value: str, label: str, *, allow_empty: bool = False) -> None:
    if allow_empty and value == "":
        return
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ServerOperationEventIntegrityError(
            f"{label} must be a canonical SHA-256 digest"
        )


def _finite_nonnegative(value: object, label: str) -> float:
    if (
        type(value) not in {int, float}
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ServerOperationEventIntegrityError(
            f"{label} must be finite and non-negative"
        )
    return float(value)


def _validate_common(operation_id: str, server_id: str, request_digest: str, profile_digest: str) -> None:
    if _OPERATION_ID_RE.fullmatch(operation_id) is None:
        raise ServerOperationEventIntegrityError(
            "operation_id must be a safe non-empty durable identifier"
        )
    if _SERVER_ID_RE.fullmatch(server_id) is None:
        raise ServerOperationEventIntegrityError(
            "server_id must be a safe non-empty durable identifier"
        )
    _require_sha256(request_digest, "request_digest")
    _require_sha256(profile_digest, "profile_digest", allow_empty=True)


def _validate_projection(value: object) -> None:
    if isinstance(value, ServerOperationStarted):
        _validate_common(
            value.operation_id,
            value.server_id,
            value.request_digest,
            value.profile_digest,
        )
        _finite_nonnegative(value.started_at, "started_at")
        if type(value.interactive) is not bool:
            raise ServerOperationEventIntegrityError(
                "started interactive must be boolean"
            )
        return
    if isinstance(value, ServerOperationFinished):
        _validate_common(
            value.operation_id,
            value.server_id,
            value.request_digest,
            value.profile_digest,
        )
        _finite_nonnegative(value.finished_at, "finished_at")
        _finite_nonnegative(value.duration_seconds, "duration_seconds")
        if value.state is ServerOperationState.STARTED:
            raise ServerOperationEventIntegrityError(
                "finished event cannot use started state"
            )
        if type(value.stdout_bytes) is not int or value.stdout_bytes < 0:
            raise ServerOperationEventIntegrityError(
                "stdout_bytes must be a non-negative integer"
            )
        if type(value.stderr_bytes) is not int or value.stderr_bytes < 0:
            raise ServerOperationEventIntegrityError(
                "stderr_bytes must be a non-negative integer"
            )
        if value.return_code is not None and type(value.return_code) is not int:
            raise ServerOperationEventIntegrityError(
                "return_code must be null or integer"
            )
        if (value.error_type is None) != (value.error_digest is None):
            raise ServerOperationEventIntegrityError(
                "error_type and error_digest must be present together"
            )
        if value.error_digest is not None:
            _require_sha256(value.error_digest, "error_digest")
        _require_sha256(value.stdout_digest, "stdout_digest", allow_empty=True)
        _require_sha256(value.stderr_digest, "stderr_digest", allow_empty=True)
        if value.state is ServerOperationState.SUCCEEDED:
            if value.return_code != 0 or value.failure_kind != "none":
                raise ServerOperationEventIntegrityError(
                    "succeeded operation requires return_code=0 and failure_kind=none"
                )
            if value.error_type is not None:
                raise ServerOperationEventIntegrityError(
                    "succeeded operation cannot carry error evidence"
                )
        elif value.state is ServerOperationState.TIMED_OUT:
            if value.failure_kind != "timeout":
                raise ServerOperationEventIntegrityError(
                    "timed-out operation requires failure_kind=timeout"
                )
        elif not value.failure_kind or value.failure_kind == "none":
            raise ServerOperationEventIntegrityError(
                "failed operation requires a non-success failure kind"
            )
        return
    if isinstance(value, ServerOperationResolved):
        _validate_common(
            value.operation_id,
            value.server_id,
            value.request_digest,
            value.profile_digest,
        )
        _finite_nonnegative(value.resolved_at, "resolved_at")
        if _EVIDENCE_REF_RE.fullmatch(value.evidence_ref) is None:
            raise ServerOperationEventIntegrityError(
                "resolution evidence reference is unsafe"
            )
        _require_sha256(value.evidence_digest, "evidence_digest")
        return
    raise TypeError("unsupported server operation projection")


def _primitive_payload(value: object) -> dict[str, object]:
    _validate_projection(value)
    payload = asdict(value)
    for key, item in tuple(payload.items()):
        if isinstance(item, Enum):
            payload[key] = item.value
    return payload


def _subject(event_type: str, value: object) -> NoetriumUnit:
    payload = _primitive_payload(value)
    digest = hashlib.sha256(
        repr(tuple(sorted(payload.items()))).encode("utf-8")
    ).hexdigest()
    return NoetriumUnit(
        f"server.operation.{event_type}:{digest}",
        schemas=("server.operation", f"server.operation.{event_type}"),
        attributes={
            "kind": f"server.operation.{event_type}",
            "event_type": event_type,
            **payload,
        },
    )


def _projection(subject: NoetriumUnit) -> ServerOperationStarted | ServerOperationFinished | ServerOperationResolved:
    if type(subject) is not NoetriumUnit or not subject.has_schema("server.operation"):
        raise ServerOperationEventIntegrityError(
            "server operation Event subject is invalid"
        )
    event_type = subject.attribute("event_type")
    try:
        if event_type == "started":
            value = ServerOperationStarted(
                str(subject.attribute("operation_id")),
                str(subject.attribute("server_id")),
                ServerOperationKind(str(subject.attribute("kind_value", subject.attribute("kind")))),
                str(subject.attribute("request_digest")),
                float(subject.attribute("started_at")),
                bool(subject.attribute("interactive")),
                str(subject.attribute("profile_digest")),
                ServerOperationEffect(str(subject.attribute("effect"))),
            )
        elif event_type == "finished":
            value = ServerOperationFinished(
                str(subject.attribute("operation_id")),
                str(subject.attribute("server_id")),
                ServerOperationKind(str(subject.attribute("kind_value", subject.attribute("kind")))),
                str(subject.attribute("request_digest")),
                ServerOperationState(str(subject.attribute("state"))),
                float(subject.attribute("finished_at")),
                float(subject.attribute("duration_seconds")),
                subject.attribute("return_code"),
                str(subject.attribute("failure_kind")),
                int(subject.attribute("stdout_bytes")),
                int(subject.attribute("stderr_bytes")),
                subject.attribute("error_type"),
                subject.attribute("error_digest"),
                str(subject.attribute("profile_digest")),
                str(subject.attribute("stdout_digest")),
                str(subject.attribute("stderr_digest")),
                ServerOperationEffect(str(subject.attribute("effect"))),
                str(subject.attribute("stdout_preview")),
                str(subject.attribute("stderr_preview")),
            )
        elif event_type == "resolved":
            value = ServerOperationResolved(
                str(subject.attribute("operation_id")),
                str(subject.attribute("server_id")),
                ServerOperationKind(str(subject.attribute("kind_value", subject.attribute("kind")))),
                str(subject.attribute("request_digest")),
                ServerOperationResolution(str(subject.attribute("disposition"))),
                float(subject.attribute("resolved_at")),
                str(subject.attribute("evidence_ref")),
                str(subject.attribute("evidence_digest")),
                str(subject.attribute("profile_digest")),
            )
        else:
            raise ValueError("unknown server operation event_type")
    except (TypeError, ValueError) as exc:
        raise ServerOperationEventIntegrityError(
            "server operation Event subject cannot be projected"
        ) from exc
    _validate_projection(value)
    return value


def _subject_with_kind_value(event_type: str, value: object) -> NoetriumUnit:
    # `kind` is reserved for the Unit schema discriminator. Preserve the domain
    # enum in an explicit field rather than overloading it.
    payload = _primitive_payload(value)
    payload["kind_value"] = payload.pop("kind")
    digest = hashlib.sha256(
        repr(tuple(sorted(payload.items()))).encode("utf-8")
    ).hexdigest()
    return NoetriumUnit(
        f"server.operation.{event_type}:{digest}",
        schemas=("server.operation", f"server.operation.{event_type}"),
        attributes={
            "kind": f"server.operation.{event_type}",
            "event_type": event_type,
            **payload,
        },
    )


class _NonBlockingServerLock(AbstractContextManager[object]):
    def __init__(self, path: Path, *, server_id: str, busy_error: type[RuntimeError]) -> None:
        self.path = path
        self._lock = InterprocessFileLock(path, blocking=False)
        self._server_id = server_id
        self._busy_error = busy_error

    def __enter__(self) -> object:
        try:
            return self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise self._busy_error(self._server_id) from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.__exit__(exc_type, exc, tb)


class _NonBlockingOperationLock(AbstractContextManager[object]):
    def __init__(self, path: Path, *, operation_id: str) -> None:
        self.path = path
        self._operation_id = operation_id
        self._lock = InterprocessFileLock(path, blocking=False)

    def __enter__(self) -> object:
        try:
            return self._lock.__enter__()
        except InterprocessLockBusy as exc:
            raise ServerOperationTransitionConflict(
                self._operation_id, "another transition is in progress"
            ) from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.__exit__(exc_type, exc, tb)


class ServerOperationEventStore(ServerOperationEventStorePort):
    """Authority-partitioned causal Event store for managed server effects."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root

    def _operation_identity(self, operation_id: str) -> str:
        if _OPERATION_ID_RE.fullmatch(operation_id) is None:
            raise ServerOperationEventIntegrityError(
                "operation_id must be a safe non-empty durable identifier"
            )
        return hashlib.sha256(operation_id.encode("utf-8")).hexdigest()

    def _operation_root(self, operation_id: str) -> Path:
        return self.root / self._operation_identity(operation_id)

    def _operation_transition_lock(self, operation_id: str) -> AbstractContextManager[object]:
        identity = self._operation_identity(operation_id)[:32]
        return _NonBlockingOperationLock(
            self.root / f"operation-{identity}.lock",
            operation_id=operation_id,
        )

    def _authority_domain(self, operation_id: str) -> str:
        return "server.operation." + self._operation_identity(operation_id)

    def _event_paths(self, operation_id: str) -> tuple[Path, ...]:
        root = self._operation_root(operation_id)
        return () if not root.exists() else tuple(sorted(root.glob("*.unit")))

    def _events(self, operation_id: str) -> tuple[NoetriumUnit, ...]:
        events = []
        for path in self._event_paths(operation_id):
            try:
                event = decode_unit(path.read_bytes())
            except Exception as exc:
                raise ServerOperationEventIntegrityError(
                    f"server operation Event is corrupt: {path.name}"
                ) from exc
            if not is_event_unit(event):
                raise ServerOperationEventIntegrityError(
                    "server operation store contains non-Event Unit"
                )
            events.append(event)
        if not events:
            return ()
        try:
            ordered = causal_topological_order(tuple(events))
        except Exception as exc:
            raise ServerOperationEventIntegrityError(
                "server operation causal graph is invalid"
            ) from exc
        previous = None
        for generation, event in enumerate(ordered, start=1):
            if event_field(event, "authority_domain") != self._authority_domain(operation_id):
                raise ServerOperationEventIntegrityError(
                    "server operation Event crossed authority domain"
                )
            if int(event_field(event, "generation")) != generation:
                raise ServerOperationEventIntegrityError(
                    "server operation Event generation is not contiguous"
                )
            parents = tuple(event.refs("causal-parent"))
            if previous is None:
                if parents:
                    raise ServerOperationEventIntegrityError(
                        "server operation genesis Event has a causal parent"
                    )
            elif parents != (event_ref(previous),):
                raise ServerOperationEventIntegrityError(
                    "server operation Event chain has invalid causal parent"
                )
            previous = event
        return ordered

    def _append(
        self,
        event_type: str,
        value: ServerOperationStarted | ServerOperationFinished | ServerOperationResolved,
    ) -> None:
        operation_id = value.operation_id
        events = self._events(operation_id)
        generation = len(events) + 1
        previous = None if not events else events[-1]
        modality = {
            "started": TruthModality.DECLARED,
            "finished": TruthModality.OBSERVED,
            "resolved": TruthModality.EVIDENCED,
        }[event_type]
        subject = _subject_with_kind_value(event_type, value)
        physical_effect = (
            event_type == "finished"
            and value.effect is not ServerOperationEffect.OBSERVATION
        )
        event = causal_event(
            authority_domain=self._authority_domain(operation_id),
            generation=generation,
            subject=subject,
            operation="server-operation",
            phase=event_type,
            modality=modality,
            causal_parents=(
                () if previous is None else (event_ref(previous),)
            ),
            reads=(f"server-operation:{operation_id}",),
            writes=(f"server-operation:{operation_id}",),
            event_kind="server.operation-transition",
            physical_effect=physical_effect,
        )
        operation_root = self._operation_root(operation_id)
        operation_root.mkdir(parents=True, exist_ok=True)
        path = operation_root / f"{generation:04d}-{event.unit_digest}.unit"
        if path.exists():
            raise ServerOperationTransitionConflict(
                operation_id, "duplicate causal Event generation"
            )
        atomic_replace_bytes(path, encode_unit(event))

    @staticmethod
    def _fold(events: tuple[NoetriumUnit, ...]) -> ServerOperationRecord | None:
        if not events:
            return None
        record: ServerOperationRecord | None = None
        for event in events:
            value = _projection(event_field(event, "subject"))
            if isinstance(value, ServerOperationStarted):
                if record is not None:
                    raise ServerOperationEventIntegrityError(
                        "duplicate server operation start Event"
                    )
                record = ServerOperationRecord(value)
            elif isinstance(value, ServerOperationFinished):
                if record is None or record.finished is not None or record.resolution is not None:
                    raise ServerOperationEventIntegrityError(
                        "server operation finish has no unique open start"
                    )
                started = record.started
                if (
                    started.server_id != value.server_id
                    or started.kind != value.kind
                    or started.request_digest != value.request_digest
                    or started.profile_digest != value.profile_digest
                    or started.effect != value.effect
                ):
                    raise ServerOperationEventIntegrityError(
                        "server operation finish identity drifted"
                    )
                record = ServerOperationRecord(started, value, None)
            elif isinstance(value, ServerOperationResolved):
                if record is None or record.resolution is not None:
                    raise ServerOperationEventIntegrityError(
                        "server operation resolution has no unique operation"
                    )
                if (
                    record.server_id != value.server_id
                    or record.kind != value.kind
                    or record.started.request_digest != value.request_digest
                    or record.started.profile_digest != value.profile_digest
                    or not record.effect_uncertain
                ):
                    raise ServerOperationEventIntegrityError(
                        "server operation resolution identity/effect drifted"
                    )
                record = ServerOperationRecord(record.started, record.finished, value)
        return record

    def _read_records(self) -> tuple[ServerOperationRecord, ...]:
        records = []
        for root in sorted(path for path in self.root.iterdir() if path.is_dir()):
            paths = tuple(sorted(root.glob("*.unit")))
            if not paths:
                continue
            try:
                first = decode_unit(paths[0].read_bytes())
                subject = event_field(first, "subject")
                operation_id = str(subject.attribute("operation_id"))
            except Exception as exc:
                raise ServerOperationEventIntegrityError(
                    f"server operation Event partition is corrupt: {root.name}"
                ) from exc
            if self._operation_root(operation_id) != root:
                raise ServerOperationEventIntegrityError(
                    "server operation partition identity drifted"
                )
            record = self._fold(self._events(operation_id))
            if record is not None:
                records.append(record)
        return tuple(
            sorted(
                records,
                key=lambda row: (row.started.started_at, row.operation_id),
            )
        )

    def event_trace(self, operation_id: str) -> tuple[NoetriumUnit, ...]:
        return self._events(operation_id)

    def record_started(self, event: ServerOperationStarted) -> None:
        _validate_projection(event)
        with self._operation_transition_lock(event.operation_id):
            if self.read_operation(event.operation_id) is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation is already recorded"
                )
            self._append("started", event)

    def record_finished(self, event: ServerOperationFinished) -> None:
        _validate_projection(event)
        with self._operation_transition_lock(event.operation_id):
            record = self.read_operation(event.operation_id)
            if record is None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "finish has no recorded start"
                )
            if record.finished is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation is already finished"
                )
            if record.resolution is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation was already reconciled"
                )
            started = record.started
            if (
                started.server_id != event.server_id
                or started.kind != event.kind
                or started.request_digest != event.request_digest
                or started.profile_digest != event.profile_digest
                or started.effect != event.effect
            ):
                raise ServerOperationTransitionConflict(
                    event.operation_id, "finish identity does not match its start"
                )
            self._append("finished", event)

    def record_resolved(self, event: ServerOperationResolved) -> None:
        _validate_projection(event)
        with self._operation_transition_lock(event.operation_id):
            record = self.read_operation(event.operation_id)
            if record is None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "resolution has no recorded operation"
                )
            if record.resolution is not None:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation is already reconciled"
                )
            if (
                record.server_id != event.server_id
                or record.kind != event.kind
                or record.started.request_digest != event.request_digest
                or record.started.profile_digest != event.profile_digest
            ):
                raise ServerOperationTransitionConflict(
                    event.operation_id, "resolution identity does not match its start"
                )
            if not record.effect_uncertain:
                raise ServerOperationTransitionConflict(
                    event.operation_id, "operation does not require reconciliation"
                )
            self._append("resolved", event)

    def mutation_lock(self, *, server_id: str) -> AbstractContextManager[object]:
        if not server_id:
            raise ValueError("server_id must be non-empty")
        identity = hashlib.sha256(server_id.encode("utf-8")).hexdigest()[:32]
        return _NonBlockingServerLock(
            self.root / f"server-{identity}.mutation.lock",
            server_id=server_id,
            busy_error=ServerMutationBusy,
        )

    def transport_lock(self, *, server_id: str) -> AbstractContextManager[object]:
        if not server_id:
            raise ValueError("server_id must be non-empty")
        identity = hashlib.sha256(server_id.encode("utf-8")).hexdigest()[:32]
        return _NonBlockingServerLock(
            self.root / f"server-{identity}.transport.lock",
            server_id=server_id,
            busy_error=ServerTransportBusy,
        )

    def read_operation(self, operation_id: str) -> ServerOperationRecord | None:
        return self._fold(self._events(operation_id))

    def pending_operations(
        self,
        *,
        server_id: str | None = None,
    ) -> tuple[ServerOperationRecord, ...]:
        return tuple(
            record
            for record in self._read_records()
            if record.effect_uncertain
            and (server_id is None or record.server_id == server_id)
        )

    def recent_operations(
        self,
        limit: int = 20,
        *,
        server_id: str | None = None,
    ) -> tuple[ServerOperationRecord, ...]:
        if limit <= 0:
            raise ValueError("operation history limit must be positive")
        records = tuple(
            record
            for record in self._read_records()
            if server_id is None or record.server_id == server_id
        )
        return tuple(reversed(records[-limit:]))


__all__ = ["ServerOperationEventIntegrityError", "ServerOperationEventStore"]
