from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import MetricEmitterCoverageAudit


REQUIRED=(
    "llm.request.latency",
    "llm.queue_wait",
    "llm.time_to_headers",
    "llm.stream.first_byte",
    "model.ttft",
    "llm.response_parse",
    "prompt.compile.latency",
    "prompt.compile.bytes",
    "prompt.block.count",
    "prompt.block.bytes",
    "prompt.schema.validation",
    "runtime.control.action.count",
    "runtime.control.action.latency",
    "runtime.control.reconcile",
    "runtime.control.exact_service_start",
    "runtime.control.qualification",
    "runtime.recovery.lease.conflicts",
    "resource.lease.wait",
    "recovery.attempts",
    "recovery.duration",
    "recovery.step.duration",
)


class MetricEmitterCoverageV80Tests(unittest.TestCase):
    def test_required_metrics_have_real_source_emitters_and_are_registered(self):
        root=Path(__file__).resolve().parents[1]/"noetrium_platform"
        coverage=MetricEmitterCoverageAudit(root,build_default_registry(),required_metrics=REQUIRED).run()
        self.assertEqual(coverage.errors,())
        self.assertTrue(set(REQUIRED)<=set(coverage.emitted_metrics))

    def test_source_emitter_for_unregistered_metric_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"x.py").write_text('def f(store,ctx): store.observe(ctx,"not.registered.metric",1)\n',encoding="utf-8")
            coverage=MetricEmitterCoverageAudit(root,build_default_registry()).run()
            self.assertTrue(any("not.registered.metric" in x for x in coverage.errors))


if __name__=="__main__": unittest.main()
