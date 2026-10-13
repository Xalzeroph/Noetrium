from __future__ import annotations

import time

from noetrium_platform.foundation.kernel.kernel.errors import attempt_secondary_delivery

from noetrium_platform.capabilities.model.request.prompt.api import (
    PromptTraceDescriptor,
    PromptTraceObserverFailure,
    PromptTraceObserverFailureSink,
    PromptTraceObserverPort,
    PromptTracePoint,
    PromptTraceStage,
    PromptTraceSummary,
)


class PromptRequestTrace:
    """In-memory prompt request trace; persistence/metrics are fail-isolated observers."""

    def __init__(
        self,
        *,
        request_id: str,
        role: str,
        model: str,
        request_digest: str,
        bundle: str = "bound",
        observer: PromptTraceObserverPort | None = None,
        observer_failure_sink: PromptTraceObserverFailureSink | None = None,
    ) -> None:
        self.descriptor = PromptTraceDescriptor(request_id, role, model, request_digest, bundle)
        self.observer = observer
        self.observer_failure_sink = observer_failure_sink
        self._points: list[PromptTracePoint] = []
        self._observer_failures: list[PromptTraceObserverFailure] = []

    @property
    def observer_failures(self) -> tuple[PromptTraceObserverFailure, ...]:
        return tuple(self._observer_failures)

    def _notify(self, stage: str, callback) -> None:
        if self.observer is None:
            return
        try:
            callback()
        except Exception as exc:
            failure = PromptTraceObserverFailure.from_exception(stage, exc)
            self._observer_failures.append(failure)
            if self.observer_failure_sink is not None:
                attempt_secondary_delivery(lambda: self.observer_failure_sink.record(failure))

    def mark(
        self,
        stage: PromptTraceStage,
        *,
        timestamp: float | None = None,
        **details: object,
    ) -> PromptTracePoint:
        ts = time.time() if timestamp is None else float(timestamp)
        point = PromptTracePoint(stage, ts, tuple(sorted(details.items())))
        self._points.append(point)
        self._notify(
            f"point_recorded:{stage.value}",
            lambda: self.observer.point_recorded(self.descriptor, point),
        )
        return point

    def _point(self, stage: PromptTraceStage) -> PromptTracePoint | None:
        return next((point for point in self._points if point.stage == stage), None)

    def _at(self, stage: PromptTraceStage) -> float | None:
        point = self._point(stage)
        return None if point is None else point.timestamp

    @staticmethod
    def _delta(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else max(0.0, b - a)

    def summarize(self) -> PromptTraceSummary:
        if not self._points:
            raise RuntimeError("prompt request trace is empty")
        start = self._points[0].timestamp
        end = self._points[-1].timestamp
        compile_seconds = self._delta(
            self._at(PromptTraceStage.COMPILE_STARTED),
            self._at(PromptTraceStage.COMPILE_COMPLETED),
        )
        queue = self._delta(self._at(PromptTraceStage.QUEUED), self._at(PromptTraceStage.DISPATCHED))
        headers = self._delta(self._at(PromptTraceStage.DISPATCHED), self._at(PromptTraceStage.HEADERS_RECEIVED))
        first_byte = self._delta(self._at(PromptTraceStage.DISPATCHED), self._at(PromptTraceStage.FIRST_BYTE))
        ttft = self._delta(self._at(PromptTraceStage.DISPATCHED), self._at(PromptTraceStage.FIRST_TOKEN))
        parse = self._delta(
            self._at(PromptTraceStage.RESPONSE_COMPLETED),
            self._at(PromptTraceStage.PARSE_COMPLETED),
        )
        schema = self._delta(
            self._at(PromptTraceStage.PARSE_COMPLETED),
            self._at(PromptTraceStage.SCHEMA_VALIDATED),
        )
        failed = next(
            (point.stage.value for point in reversed(self._points) if point.stage == PromptTraceStage.FAILED),
            None,
        )
        descriptor = self.descriptor
        summary = PromptTraceSummary(
            descriptor.request_id,
            descriptor.role,
            descriptor.model,
            descriptor.request_digest,
            tuple(self._points),
            max(0.0, end - start),
            compile_seconds,
            queue,
            headers,
            first_byte,
            ttft,
            parse,
            schema,
            failed,
        )
        status = "failed" if failed else "success"
        self._notify(
            f"summary_recorded:{status}",
            lambda: self.observer.summary_recorded(descriptor, summary, status=status),
        )
        return summary


__all__ = ["PromptRequestTrace"]
