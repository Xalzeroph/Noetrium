from __future__ import annotations

import time
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.model.serving.runtime.recovery import RecoveryStep
from noetrium_platform.evidence.observability.api import ContextMetricSink


class MetricDurableRecoveryObserver:
    """Telemetry adapter for recovery lifecycle events; state-machine code stays metric-agnostic."""

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
        self._attempt_started_at: float | None = None
        self._step_started_at: dict[RecoveryStep, float] = {}
        self._cause: str | None = None

    def attempt_started(self, *, cause: str) -> None:
        self._cause = cause
        self._attempt_started_at = self._clock()

    def step_started(self, step: RecoveryStep) -> None:
        self._step_started_at[step] = self._clock()

    def step_finished(self, step: RecoveryStep, *, result: str) -> None:
        started = self._step_started_at.pop(step, self._clock())
        self._sink.observe(
            self._context,
            "recovery.step.duration",
            max(0.0, self._clock() - started),
            scope="model_runtime",
            step=step.value,
            result=result,
        )

    def attempt_finished(self, *, result: str) -> None:
        now = self._clock()
        started = self._attempt_started_at if self._attempt_started_at is not None else now
        self._sink.observe(
            self._context,
            "recovery.attempts",
            1,
            scope="model_runtime",
            result=result,
            cause=self._cause or "unknown",
        )
        self._sink.observe(
            self._context,
            "recovery.duration",
            max(0.0, now - started),
            scope="model_runtime",
            result=result,
        )
        self._attempt_started_at = None
        self._cause = None
        self._step_started_at.clear()


__all__ = ["MetricDurableRecoveryObserver"]
