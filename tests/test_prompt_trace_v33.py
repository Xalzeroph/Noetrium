from pathlib import Path
import tempfile, unittest

from tests._concurrency_support import telemetry_backend
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.capabilities.model.request.prompt.runtime import (
    PromptBlock, PromptBlockKind, PromptCompiler, PromptRegistry, PromptRequestTrace,
    default_block_policies, default_prompt_specs,
)
from noetrium_platform.capabilities.model.request.prompt.api import PromptTraceStage
from noetrium_platform.composition.prompt_trace_observability import PromptTelemetryObserver
from tests._concurrency_support import raw_observation_lake
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryStore

class PromptTraceV33Tests(unittest.TestCase):
    def _ctx(self): return ExecutionContext(run_id='r',trace_id='tr',span_id='sp',task_id='task',decision_cycle_id='dc',operation_id='op',component_id='llm.runtime')
    def test_compiler_exposes_exact_block_size_stats(self):
        r=PromptRegistry(); r.publish('g',default_prompt_specs()); b=r.get('planner.v6'); K=PromptBlockKind
        c=PromptCompiler().compile(b,default_block_policies()['planner'],(
            PromptBlock(K.TASK,'abc','d1',1),PromptBlock(K.VERIFIED_STATE,'state','d2',2),PromptBlock(K.TOOL_CATALOG,'tool','d3',3),
        ))
        self.assertEqual(c.block_stats[0].chars,3); self.assertEqual(c.block_stats[0].source_digest,'d1')
        self.assertGreater(c.compiled_bytes,0)
    def test_request_trace_persists_every_stage_and_derives_latency(self):
        with tempfile.TemporaryDirectory() as td:
            raw=raw_observation_lake(Path(td)/'raw')
            metrics=TelemetryStore(build_default_registry(), telemetry_backend(self, Path(td)/'m.sqlite3'))
            t=PromptRequestTrace(request_id='rq',role='planner',model='m',request_digest='sha',observer=PromptTelemetryObserver(self._ctx(),raw_sink=raw,metric_sink=metrics))
            t.mark(PromptTraceStage.REQUEST_CREATED,timestamp=1)
            t.mark(PromptTraceStage.QUEUED,timestamp=2)
            t.mark(PromptTraceStage.DISPATCHED,timestamp=3)
            t.mark(PromptTraceStage.FIRST_TOKEN,timestamp=5)
            t.mark(PromptTraceStage.RESPONSE_COMPLETED,timestamp=7)
            t.mark(PromptTraceStage.PARSE_COMPLETED,timestamp=7.5)
            t.mark(PromptTraceStage.SCHEMA_VALIDATED,timestamp=7.7)
            s=t.summarize()
            self.assertEqual(s.queue_seconds,1); self.assertEqual(s.ttft_seconds,2); self.assertAlmostEqual(s.parse_seconds,0.5)
            self.assertEqual(raw.verify('r','prompt.trace.raw'),())
            self.assertGreaterEqual(metrics.count(),4)
    def test_failure_stage_is_explicit(self):
        t=PromptRequestTrace(request_id='rq',role='meta',model='m',request_digest='sha')
        t.mark(PromptTraceStage.REQUEST_CREATED,timestamp=1); t.mark(PromptTraceStage.FAILED,timestamp=2,error='timeout')
        self.assertEqual(t.summarize().failed_stage,'failed')

if __name__=='__main__': unittest.main()
