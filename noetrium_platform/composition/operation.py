from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    OperationAuxiliaryFailureSink,
    OperationExecutor,
    OperationFailureSink,
    OperationObserver,
)
from noetrium_platform.evidence.observability.api import (
    EventSink,
    OperationAuxiliaryFailureEventSink,
    OperationLifecycleObserver,
)


def build_operation_executor(
    *,
    failure_sink: OperationFailureSink | None = None,
    event_sink: EventSink | None = None,
    observers: tuple[OperationObserver, ...] = (),
    auxiliary_failure_sink: OperationAuxiliaryFailureSink | None = None,
) -> OperationExecutor:
    """Compose the cross-system operation boundary from explicit ports.

    The execution kernel remains mechanical.  This composition binds its
    observability and failure projections without making the kernel know either
    concrete system.  It is intentionally a platform composition seam rather
    than a runtime-control owner.
    """

    lifecycle_observers: tuple[OperationObserver, ...] = (
        (OperationLifecycleObserver(event_sink),) if event_sink is not None else ()
    )
    auxiliary = auxiliary_failure_sink
    if auxiliary is None and event_sink is not None:
        auxiliary = OperationAuxiliaryFailureEventSink(event_sink)
    return OperationExecutor(
        failure_sink,
        observers=lifecycle_observers + tuple(observers),
        auxiliary_failure_sink=auxiliary,
    )


__all__ = ["build_operation_executor"]
