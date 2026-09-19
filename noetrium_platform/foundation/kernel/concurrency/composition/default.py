from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget, ExecutionPermitPort
from noetrium_platform.foundation.kernel.concurrency.providers import (
    AsyncIoExecutor,
    BoundedProcessExecutor,
    BoundedThreadExecutor,
    HeapTimerScheduler,
    SharedSerialExecutionLaneFactory,
)
from noetrium_platform.foundation.kernel.concurrency.runtime import StructuredConcurrencyRuntime


def _build_blocking_io_provider(
    budget: ConcurrencyBudget,
    *,
    thread_name_prefix: str,
) -> BoundedThreadExecutor:
    return BoundedThreadExecutor(
        max_workers=budget.max_blocking_io_workers,
        max_in_flight=int(budget.max_blocking_io_in_flight),
        thread_name_prefix=thread_name_prefix,
    )


def _build_async_io_provider(budget: ConcurrencyBudget) -> AsyncIoExecutor:
    return AsyncIoExecutor(
        max_in_flight=int(budget.max_async_io_in_flight),
        shutdown_timeout_seconds=budget.shutdown_timeout_seconds,
    )


def _build_cpu_provider(budget: ConcurrencyBudget) -> BoundedProcessExecutor:
    return BoundedProcessExecutor(
        max_workers=budget.max_cpu_workers,
        max_in_flight=int(budget.max_cpu_in_flight),
    )


def build_concurrency_runtime(
    *,
    budget: ConcurrencyBudget | None = None,
    blocking_io_thread_name_prefix: str = "platform-blocking-io",
    timer_name: str = "platform-timer",
    permits: ExecutionPermitPort | None = None,
) -> StructuredConcurrencyRuntime:
    """Build the process-level structured-concurrency authority.

    Raw executors, serial-lane factories, and timers are provider details and are
    intentionally not exposed by composition. Production callers must open an
    owned task group so task identity, cancellation, deadlines, and topology are
    always observable at the same authority boundary.
    """

    resolved = budget or ConcurrencyBudget()
    return StructuredConcurrencyRuntime(
        budget=resolved,
        _blocking_io=_build_blocking_io_provider(
            resolved,
            thread_name_prefix=blocking_io_thread_name_prefix,
        ),
        _async_io=_build_async_io_provider(resolved),
        _cpu=_build_cpu_provider(resolved),
        _timers=HeapTimerScheduler(
            name=timer_name,
            shutdown_timeout_seconds=resolved.shutdown_timeout_seconds,
        ),
        _permits=permits,
        _serial_lane_factory=SharedSerialExecutionLaneFactory(
            max_workers=resolved.max_serial_workers,
            shutdown_timeout_seconds=resolved.shutdown_timeout_seconds,
        ),
    )
