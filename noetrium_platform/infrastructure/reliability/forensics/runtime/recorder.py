from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.infrastructure.reliability.failure.api import (
    FailureEnvelope,
    FailureSpec,
    build_failure_from_spec,
)
from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.api.ports import ForensicStorePort
from noetrium_platform.infrastructure.reliability.forensics.runtime.write_lanes import ForensicProjectionError


@dataclass(frozen=True, slots=True)
class Breadcrumb:
    timestamp: float
    component_id: str
    stage: str
    message: str
    fields: dict[str, object]


class BreadcrumbBuffer:
    """Bounded in-memory pre-failure breadcrumbs. Authoritative events remain in the event ledger."""
    def __init__(self, maxlen: int = 128) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self._rows: deque[Breadcrumb] = deque(maxlen=maxlen)

    def add(self, component_id: str, stage: str, message: str, **fields: object) -> None:
        self._rows.append(Breadcrumb(time.time(), component_id, stage, message, dict(fields)))

    def snapshot(self) -> tuple[Breadcrumb, ...]:
        return tuple(self._rows)


@dataclass(frozen=True, slots=True)
class ForensicRecordDegradation:
    """A secondary failure after or around authoritative forensic materialization."""

    stage: str
    error_type: str
    error_digest: str
    message: str = field(default="", repr=False, compare=False, metadata={"transient": True})

    @classmethod
    def from_exception(cls, stage: str, exc: BaseException) -> "ForensicRecordDegradation":
        descriptor = describe_exception(exc)
        return cls(
            stage=stage,
            error_type=descriptor.error_type,
            error_digest=descriptor.error_digest,
            message=descriptor.safe_message,
        )


@dataclass(frozen=True, slots=True)
class FailureRecordOutcome:
    failure: FailureEnvelope
    degradations: tuple[ForensicRecordDegradation, ...] = ()


class FailureRecorder:
    """Authoritatively records failure truth; event/index degradation is secondary.

    A ``ForensicProjectionError`` explicitly means the authoritative ledger append has
    already committed.  Such a failure must therefore never erase the new failure_id.
    The disposable projection can be rebuilt from the hash-chained ledger later.
    """

    def __init__(self, store: ForensicStorePort) -> None:
        self.store = store

    def record(self, *, spec: FailureSpec, component_id: str, context: ExecutionContext,
               exc: BaseException, operation_id: str | None = None,
               operation_invocation_id: str | None = None,
               operation_type: str | None = None, operation_payload_digest: str | None = None,
               operation_idempotency_key: str | None = None,
               effect_certainty: str | None = None,
               request_refs: tuple[str, ...] = (), effect_refs: tuple[str, ...] = (),
               state_refs: tuple[str, ...] = (), correlation_refs: tuple[str, ...] = ()) -> FailureRecordOutcome:
        failure = build_failure_from_spec(
            spec=spec,
            component_id=component_id,
            context=context,
            exc=exc,
            operation_id=operation_id,
            operation_invocation_id=operation_invocation_id,
            operation_type=operation_type,
            operation_payload_digest=operation_payload_digest,
            operation_idempotency_key=operation_idempotency_key,
            effect_certainty=effect_certainty,
            request_refs=request_refs, effect_refs=effect_refs,
            state_refs=state_refs, correlation_refs=correlation_refs,
        )
        degradations: list[ForensicRecordDegradation] = []
        created = False
        try:
            created, _ = self.store.append_failure_once(failure)
        except ForensicProjectionError as projection_exc:
            # The failure row already exists authoritatively whether this was a new append
            # or a repair projection of an existing row.
            created = projection_exc.new_record is True
            degradations.append(ForensicRecordDegradation.from_exception(
                "failure_projection", projection_exc
            ))

        event = EventEnvelope(
            event_id=f"event_failure_{failure.failure_id}", event_type="FAILURE_RECORDED",
            context=context, component_id=component_id,
            payload={
                "failure_id": failure.failure_id,
                "operation_id": operation_id,
                "operation_invocation_id": operation_invocation_id,
                "domain": spec.domain,
                "code": spec.code,
                "stage": spec.stage,
            },
            request_refs=tuple(x for x in (operation_invocation_id, operation_id) if x),
        )
        if created:
            try:
                self.store.append_event(event)
            except ForensicProjectionError as projection_exc:
                # The event ledger committed; only its disposable projection is degraded.
                degradations.append(ForensicRecordDegradation.from_exception(
                    "failure_event_projection", projection_exc
                ))
            except Exception as event_exc:
                # Failure truth is already durable.  The convenience event is secondary.
                degradations.append(ForensicRecordDegradation.from_exception(
                    "failure_event_delivery", event_exc
                ))
        return FailureRecordOutcome(failure, tuple(degradations))


__all__ = [
    "Breadcrumb",
    "BreadcrumbBuffer",
    "FailureRecordOutcome",
    "FailureRecorder",
    "ForensicRecordDegradation",
]
