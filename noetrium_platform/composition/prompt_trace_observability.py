from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.api import ContextMetricSink, ContextRawObservationSink
from noetrium_platform.capabilities.model.request.prompt.api import PromptTraceDescriptor, PromptTracePoint, PromptTraceStage, PromptTraceSummary


class PromptTelemetryObserver:
    """Prompt trace projection into raw evidence and metric ports."""

    def __init__(
        self,
        context: ExecutionContext,
        *,
        raw_sink: ContextRawObservationSink | None = None,
        metric_sink: ContextMetricSink | None = None,
    ) -> None:
        self._context = context
        self._raw_sink = raw_sink
        self._metric_sink = metric_sink

    def point_recorded(self, descriptor: PromptTraceDescriptor, point: PromptTracePoint) -> None:
        if self._raw_sink is None:
            return
        self._raw_sink.append(
            self._context,
            "prompt.trace.raw",
            {
                "request_id": descriptor.request_id,
                "role": descriptor.role,
                "model": descriptor.model,
                "request_digest": descriptor.request_digest,
                "stage": point.stage.value,
                "details": dict(point.details),
            },
            timestamp=point.timestamp,
        )

    @staticmethod
    def _point(summary: PromptTraceSummary, stage: PromptTraceStage) -> PromptTracePoint | None:
        return next((point for point in summary.points if point.stage == stage), None)

    def summary_recorded(
        self,
        descriptor: PromptTraceDescriptor,
        summary: PromptTraceSummary,
        *,
        status: str,
    ) -> None:
        if self._metric_sink is None:
            return
        store = self._metric_sink
        context = self._context
        role = descriptor.role
        model = descriptor.model
        store.observe(
            context,
            "llm.request.latency",
            summary.total_seconds,
            role=role,
            model=model,
            endpoint="runtime",
            status=status,
        )
        if summary.compile_seconds is not None:
            store.observe(context, "prompt.compile.latency", summary.compile_seconds, role=role, result=status)
        compile_point = self._point(summary, PromptTraceStage.COMPILE_COMPLETED)
        if compile_point is not None:
            details = dict(compile_point.details)
            bundle = str(details.get("bundle") or descriptor.bundle)
            if "compiled_bytes" in details:
                store.observe(context, "prompt.compile.bytes", float(details["compiled_bytes"]), role=role, bundle=bundle)
            if "block_count" in details:
                store.observe(context, "prompt.block.count", float(details["block_count"]), role=role, bundle=bundle)
            for kind, size in details.get("block_bytes", ()):
                store.observe(context, "prompt.block.bytes", float(size), role=role, block=str(kind))
        if summary.queue_seconds is not None:
            store.observe(context, "llm.queue_wait", summary.queue_seconds, role=role, model=model, endpoint="runtime")
        if summary.headers_seconds is not None:
            store.observe(context, "llm.time_to_headers", summary.headers_seconds, role=role, model=model, endpoint="runtime")
        if summary.first_byte_seconds is not None:
            store.observe(context, "llm.stream.first_byte", summary.first_byte_seconds, role=role, model=model, endpoint="runtime")
        if summary.ttft_seconds is not None:
            store.observe(context, "model.ttft", summary.ttft_seconds, model=model, engine="runtime", replica="bound")
        if summary.parse_seconds is not None:
            store.observe(context, "llm.response_parse", summary.parse_seconds, role=role, model=model, result=status)
        if summary.schema_seconds is not None:
            store.observe(context, "prompt.schema.validation", summary.schema_seconds, role=role, schema="bound", result=status)


__all__ = ["PromptTelemetryObserver"]
