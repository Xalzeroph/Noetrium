from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import telemetry_backend
from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
from noetrium_platform.capabilities.model.request.runtime import DirectoryModelRequestLedger, ReconstructableModelRequestRecorder
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.capabilities.model.request.prompt.runtime import (
    PromptBlock, PromptBlockKind, PromptCompilePipeline,
    PromptRegistry, PromptRequestBuildTransaction, PromptRequestTrace, default_block_policies,
    default_output_schemas, default_prompt_specs,
)
from noetrium_platform.capabilities.model.request.prompt.api import PromptTraceStage
from noetrium_platform.composition.prompt_trace_observability import PromptTelemetryObserver
from tests._concurrency_support import raw_observation_lake
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryStore


def prompt_transaction() -> PromptRequestBuildTransaction:
    return PromptRequestBuildTransaction(PromptCompilePipeline())


class PromptMetricEmissionV80Tests(unittest.TestCase):
    def test_real_build_and_trace_emit_extended_prompt_and_transport_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            metrics=TelemetryStore(build_default_registry(), telemetry_backend(self, root/"metrics.sqlite3"))
            raw=raw_observation_lake(root/"raw")
            ctx=ExecutionContext(run_id="r80",trace_id="tr80",span_id="sp80",task_id="task",decision_cycle_id="dc")
            trace=PromptRequestTrace(
                request_id="rq80",role="planner",model="m",
                request_digest="digest",bundle="planner.v6",
                observer=PromptTelemetryObserver(ctx,raw_sink=raw,metric_sink=metrics),
            )
            trace.mark(PromptTraceStage.REQUEST_CREATED,timestamp=1.0)
            registry=PromptRegistry(); registry.publish("g80",default_prompt_specs())
            K=PromptBlockKind
            blocks=(
                PromptBlock(K.TASK,"task","d1",1),
                PromptBlock(K.VERIFIED_STATE,"state","d2",2),
                PromptBlock(K.TOOL_CATALOG,"tool","d3",3),
            )
            model=ImmutableModelIdentity("m","repo","rev","sglang","1","bfloat16",None,262144)
            prompt_transaction().build(
                registry=registry,prompt_id="planner.v6",policy=default_block_policies()["planner"],
                blocks=blocks,schemas=default_output_schemas(),
                request_id="rq80",context=ctx,model=model,trace=trace,
                model_requests=ReconstructableModelRequestRecorder(
                    DirectoryArtifactBlobStore(root/"model-request-blobs"),
                    DirectoryModelRequestLedger(root/"model-request-ledger"),
                ),
                body_builder=lambda resolution,compilation:{"messages":[{"role":"system","content":compilation.compiled.text}]},
            )
            trace.mark(PromptTraceStage.QUEUED,timestamp=2.0)
            trace.mark(PromptTraceStage.DISPATCHED,timestamp=3.0)
            trace.mark(PromptTraceStage.HEADERS_RECEIVED,timestamp=3.2)
            trace.mark(PromptTraceStage.FIRST_BYTE,timestamp=3.3)
            trace.mark(PromptTraceStage.FIRST_TOKEN,timestamp=3.5)
            trace.mark(PromptTraceStage.RESPONSE_COMPLETED,timestamp=5.0)
            trace.mark(PromptTraceStage.PARSE_COMPLETED,timestamp=5.1)
            trace.mark(PromptTraceStage.SCHEMA_VALIDATED,timestamp=5.2)
            trace.summarize()

            names={row["metric"] for row in metrics.query(run_id="r80",limit=100)}
            expected={
                "prompt.compile.latency","prompt.compile.bytes","prompt.block.count",
                "prompt.block.bytes","llm.time_to_headers",
                "llm.stream.first_byte","llm.queue_wait","model.ttft",
                "llm.response_parse","prompt.schema.validation","llm.request.latency",
            }
            self.assertTrue(expected<=names,expected-names)
            self.assertEqual(raw.verify("r80","prompt.trace.raw"),())
            raw.close()


if __name__=="__main__": unittest.main()
