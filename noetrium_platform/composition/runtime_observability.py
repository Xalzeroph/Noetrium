from __future__ import annotations

import time
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.api import ContextMetricSink
from noetrium_platform.infrastructure.lifecycle.launch_control.contracts import RuntimeAction


class MetricRuntimeObserver:
    """Telemetry adapter for runtime-control and one-click recovery lifecycle callbacks."""

    def __init__(
        self,
        sink: ContextMetricSink,
        context: ExecutionContext,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._sink = sink
        self._context = context
        self._clock = clock
        self._action_started_at: dict[RuntimeAction, float] = {}
        self._lease_wait_started_at: float | None = None

    def action_started(self, action: RuntimeAction, *, mutating: bool) -> None:
        del mutating
        self._action_started_at[action] = self._clock()

    def action_finished(self, action: RuntimeAction, *, result: str, mutating: bool) -> None:
        now = self._clock()
        started = self._action_started_at.pop(action, now)
        dimensions = {
            "action": action.value,
            "result": result,
            "mutating": str(mutating).lower(),
        }
        self._sink.observe(
            self._context,
            "runtime.control.action.count",
            1,
            **dimensions,
        )
        self._sink.observe(
            self._context,
            "runtime.control.action.latency",
            max(0.0, now - started),
            **dimensions,
        )

    def reconcile_finished(self, *, scope: str) -> None:
        self._sink.observe(
            self._context,
            "runtime.control.reconcile",
            1,
            scope=scope,
        )

    def exact_service_started(self) -> None:
        self._sink.observe(
            self._context,
            "runtime.control.exact_service_start",
            1,
            result="success",
        )

    def qualification_verified(self) -> None:
        self._sink.observe(
            self._context,
            "runtime.control.qualification",
            1,
            result="success",
        )

    def lease_wait_started(self) -> None:
        self._lease_wait_started_at = self._clock()

    def _finish_lease_wait(self) -> None:
        now = self._clock()
        started = self._lease_wait_started_at if self._lease_wait_started_at is not None else now
        self._sink.observe(
            self._context,
            "resource.lease.wait",
            max(0.0, now - started),
            resource_class="runtime_recovery",
        )
        self._lease_wait_started_at = None

    def lease_acquired(self) -> None:
        self._finish_lease_wait()

    def lease_conflict(self) -> None:
        self._sink.observe(
            self._context,
            "runtime.recovery.lease.conflicts",
            1,
            resource_class="runtime_recovery",
        )
        self._finish_lease_wait()

    def recovery_round(self, action: RuntimeAction, *, round_number: int) -> None:
        self._sink.observe(
            self._context,
            "runtime.control.recovery_round",
            1,
            action=action.value,
            round=str(round_number),
        )


__all__ = ["MetricRuntimeObserver"]
