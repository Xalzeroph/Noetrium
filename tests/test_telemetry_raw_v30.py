from pathlib import Path
import json
import tempfile
import unittest

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from tests._concurrency_support import raw_observation_lake
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry


class RawTelemetryV30Tests(unittest.TestCase):
    def _ctx(self):
        return ExecutionContext(run_id="r",trace_id="t",span_id="s",task_id="task-high-card",decision_cycle_id="dc-high-card",operation_id="op-high-card",component_id="llm.runtime")

    def test_metric_catalog_expands_without_high_cardinality_labels(self):
        registry=build_default_registry()
        self.assertGreaterEqual(len(registry.names()),170)
        self.assertNotIn("request_id", registry.definition("llm.request.latency").allowed_dimensions)
        self.assertIn("telemetry.raw.records", registry.names())

    def test_raw_lake_keeps_high_cardinality_context_and_payload(self):
        with tempfile.TemporaryDirectory() as td:
            lake=raw_observation_lake(Path(td))
            receipt=lake.append(self._ctx(),"llm.request.raw",{
                "role":"planner","model":"m","request_digest":"sha","status":"success",
                "request_id":"rq-123","provider_request_id":"provider-987","token_ids":[1,2,3],
            })
            self.assertEqual(receipt.sequence,1)
            row=json.loads(Path(receipt.segment_path).read_text().splitlines()[0])
            self.assertEqual(row["context"]["task_id"],"task-high-card")
            self.assertEqual(row["payload"]["provider_request_id"],"provider-987")
            self.assertEqual(lake.verify("r","llm.request.raw"),())

    def test_raw_lake_never_silently_accepts_unregistered_or_incomplete_family(self):
        with tempfile.TemporaryDirectory() as td:
            lake=raw_observation_lake(Path(td))
            with self.assertRaises(KeyError): lake.append(self._ctx(),"unknown.raw",{"x":1})
            with self.assertRaises(ValueError): lake.append(self._ctx(),"llm.request.raw",{"role":"planner"})

    def test_raw_digest_detects_tamper(self):
        with tempfile.TemporaryDirectory() as td:
            lake=raw_observation_lake(Path(td))
            receipt=lake.append_once(self._ctx(),"study.raw",{"kind":"task","status":"running"},idempotency_key="tamper")
            p=Path(receipt.segment_path); text=p.read_text(); p.write_text(text.replace('"running"','"done"'))
            self.assertTrue(any("digest mismatch" in e for e in lake.verify("r","study.raw")))

if __name__ == "__main__": unittest.main()
