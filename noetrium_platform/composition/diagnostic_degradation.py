from __future__ import annotations

import warnings

from noetrium_platform.evidence.observability.api import (
    DiagnosticDegradationPort,
    EventSink,
    event_record,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest
from noetrium_platform.foundation.kernel.kernel.errors import (
    attempt_secondary_delivery,
    describe_exception,
)


class ForensicDiagnosticDegradationSink(DiagnosticDegradationPort):
    """Project non-authoritative diagnostic failures into the durable forensic event plane."""

    def __init__(self, sink: EventSink) -> None:
        if not isinstance(sink, EventSink):
            raise TypeError("diagnostic degradation sink requires EventSink")
        self._sink = sink

    def record(
        self,
        context: ExecutionContext,
        *,
        subsystem: str,
        stage: str,
        exc: BaseException,
        correlation_refs: tuple[str, ...] = (),
    ) -> str:
        if not isinstance(context, ExecutionContext):
            raise TypeError("diagnostic degradation requires ExecutionContext")
        if not subsystem.strip() or not stage.strip():
            raise ValueError("diagnostic degradation subsystem/stage must be non-empty")
        descriptor = describe_exception(exc)
        coordinate = context.graph_coordinate
        degradation_id = "diagnostic_degradation_" + canonical_digest(
            {
                "coordinate": None if coordinate is None else coordinate.coordinate_digest,
                "run_id": context.run_id,
                "subsystem": subsystem,
                "stage": stage,
                "error_digest": descriptor.error_digest,
                "correlation_refs": tuple(sorted(set(correlation_refs))),
            }
        )[:24]
        event_id = f"event_{degradation_id}"
        self._sink.append_event(
            event_record(
                event_id=event_id,
                event_type="OBSERVABILITY_DEGRADED",
                context=context,
                component_id=subsystem,
                payload={
                    "degradation_id": degradation_id,
                    "subsystem": subsystem,
                    "stage": stage,
                    "error_type": descriptor.qualified_type,
                    "error_digest": descriptor.error_digest,
                    "safe_message": descriptor.safe_message,
                    "correlation_refs": tuple(dict.fromkeys(correlation_refs)),
                },
                request_refs=tuple(dict.fromkeys(correlation_refs)),
            )
        )
        return degradation_id


def record_diagnostic_degradation(
    sink: DiagnosticDegradationPort | None,
    context: ExecutionContext,
    *,
    subsystem: str,
    stage: str,
    exc: BaseException,
    correlation_refs: tuple[str, ...] = (),
) -> None:
    """Never change primary truth; never silently discard a diagnostic delivery failure."""

    if sink is None:
        warnings.warn(
            f"diagnostic coverage gap: no degradation sink for {subsystem}:{stage}",
            RuntimeWarning,
            stacklevel=2,
        )
        return
    delivery = attempt_secondary_delivery(
        lambda: sink.record(
            context,
            subsystem=subsystem,
            stage=stage,
            exc=exc,
            correlation_refs=correlation_refs,
        )
    )
    if delivery is not None:
        warnings.warn(
            "diagnostic coverage gap: degradation recording failed "
            f"({delivery.error_type}:{delivery.error_digest})",
            RuntimeWarning,
            stacklevel=2,
        )


__all__ = [
    "ForensicDiagnosticDegradationSink",
    "record_diagnostic_degradation",
]
