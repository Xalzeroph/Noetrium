from __future__ import annotations

import unittest

from noetrium_platform.capabilities.model.request.prompt.api import PromptTraceStage
from noetrium_platform.capabilities.model.request.prompt.runtime import PromptRequestTrace


class ExplodingObserver:
    def point_recorded(self, descriptor, point):
        del descriptor, point
        raise RuntimeError("prompt-observer-secret")

    def summary_recorded(self, descriptor, summary, *, status):
        del descriptor, summary, status
        raise RuntimeError("prompt-observer-secret")


class ExplodingFailureSink:
    def record(self, failure):
        del failure
        raise RuntimeError("prompt-failure-sink-secret")


class PromptTraceObserverIsolationV186Tests(unittest.TestCase):
    def test_observer_failures_never_change_prompt_trace_truth(self):
        trace = PromptRequestTrace(
            request_id="rq",
            role="planner",
            model="m",
            request_digest="digest",
            observer=ExplodingObserver(),
            observer_failure_sink=ExplodingFailureSink(),
        )
        trace.mark(PromptTraceStage.REQUEST_CREATED, timestamp=1.0)
        trace.mark(PromptTraceStage.FAILED, timestamp=2.0, error="provider-secret")
        summary = trace.summarize()
        self.assertEqual(summary.failed_stage, "failed")
        self.assertEqual(summary.total_seconds, 1.0)
        self.assertTrue(trace.observer_failures)
        rendered = repr(trace.observer_failures)
        self.assertNotIn("prompt-observer-secret", rendered)
        self.assertNotIn("prompt-failure-sink-secret", rendered)
        self.assertTrue(all(row.error_type == "RuntimeError" for row in trace.observer_failures))


if __name__ == "__main__":
    unittest.main()
