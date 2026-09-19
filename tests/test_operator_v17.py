from __future__ import annotations

from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests._concurrency_support import telemetry_backend
from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import RecoveryAction
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import (
    CausalGraphService,
    CausalGraphSnapshot,
    CausalNodeSnapshot,
)

from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.api import MutationRecord
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.product.operator.composition.cli import main as operator_main
from noetrium_platform.composition.release_verification import verify_source_tree_release
from noetrium_platform.evidence.observability.telemetry.metric.providers import SQLiteTelemetryReader
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import TelemetryStore


class OperatorV17Tests(unittest.TestCase):
    def _ctx(self):
        return ExecutionContext(run_id="run17", trace_id="trace17", span_id="span17", task_id="task17", decision_cycle_id="dc17", operation_id="op17", component_id="planner")

    def _fixture(self, root: Path):
        store=ForensicStore(root); ctx=self._ctx()
        store.append_event(EventEnvelope("event17", "planner.started", ctx, "planner",request_refs=("rq17",),artifact_refs=("prompt17",)))
        store.append_mutation(MutationRecord("mut17","method.architecture_head","agg",1,2,"old","new","method.adoption","op17",ctx))
        failure=build_failure(component_id="planner",failure_domain="LLM",failure_code="OUTPUT_CONTRACT",stage="decode",context=ctx,exc=ValueError("bad json"),operation_id="op17",recommended_recovery=RecoveryAction.RETRY_OPERATION)
        store.append_failure(failure)
        return store,failure

    def test_causal_graph_uses_explicit_refs(self):
        with tempfile.TemporaryDirectory() as td:
            store,failure=self._fixture(Path(td))
            graph=CausalGraphService(ForensicDiagnosticEvidence(store)).build(failure.failure_id)
            edges={(x.source,x.relation,x.target) for x in graph.edges}
            self.assertIn((failure.failure_id,"caused_by","operation:op17"),edges)
            self.assertIn(("event17","references_request","request:rq17"),edges)
            self.assertIn(("mut17","writes_state","state:method.architecture_head"),edges)
            self.assertNotIn(("event17","caused_by",failure.failure_id),edges)
            operation = next(node for node in graph.nodes if node.kind == "operation")
            with self.assertRaises(TypeError):
                operation.attrs["value"] = "changed"
            attrs = operation.attrs
            with self.assertRaises(TypeError):
                attrs |= {"new": "changed"}
            self.assertNotIn("new", operation.attrs)
            self.assertIn('"nodes"', json.dumps(asdict(graph), sort_keys=True))

    def test_causal_snapshot_rejects_non_scalar_attrs_and_missing_root(self):
        with self.assertRaises(TypeError):
            CausalNodeSnapshot("n", "node", {"nested": []})
        node = CausalNodeSnapshot("n", "node", {"value": "ok"})
        with self.assertRaises(ValueError):
            CausalGraphSnapshot("missing", (node,), ())

    def test_operator_forensic_queries_are_zero_write(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); store,failure=self._fixture(root); store.verify_all()
            authoritative=("failures.chain.jsonl","mutations.chain.jsonl","index.sqlite3","events.chain/00000000.jsonl")
            before={name:((root/name).stat().st_size,(root/name).stat().st_mtime_ns) for name in authoritative}
            out=io.StringIO()
            with redirect_stdout(out): rc=operator_main(["why",str(root),failure.failure_id,"--graph"])
            self.assertEqual(rc,0); self.assertTrue(json.loads(out.getvalue())["ok"])
            after={name:((root/name).stat().st_size,(root/name).stat().st_mtime_ns) for name in authoritative}
            self.assertEqual(before,after)

    def test_read_only_store_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self._fixture(root)
            ro=ForensicStore(root,read_only=True)
            with self.assertRaises(PermissionError):
                ro.append_event(EventEnvelope("x", "x", self._ctx(), "x"))

    def test_telemetry_reader_is_read_only_and_summarizes(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"metrics.sqlite3"; store=TelemetryStore(build_default_registry(), telemetry_backend(self, path)); ctx=self._ctx()
            for value in (1.0,2.0,3.0,4.0): store.observe(ctx,"operation.latency",value,component="c",operation="op",status="ok")
            before=(path.stat().st_size,path.stat().st_mtime_ns)
            reader=SQLiteTelemetryReader(path); rows=reader.query(run_id="run17",metric="operation.latency"); summary=reader.summarize(run_id="run17",metric="operation.latency")
            self.assertEqual(len(rows),4); self.assertEqual(summary.mean,2.5); self.assertEqual(summary.p50,2.5); self.assertEqual(before,(path.stat().st_size,path.stat().st_mtime_ns))

    def test_release_verify_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"src"; root.mkdir(); (root/"a.py").write_text("x=1\n")
            manifest=build_release_manifest(root)
            path=Path(td)/"manifest.json"; path.write_text(json.dumps(asdict(manifest),default=str),encoding="utf-8")
            report=verify_source_tree_release(root,path); self.assertTrue(report.clean); self.assertEqual(report.file_count,1)
            (root/"a.py").write_text("x=2\n"); self.assertFalse(verify_source_tree_release(root,path).clean)

    def test_expected_cli_error_is_structured_and_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); self._fixture(root)
            err=io.StringIO()
            with redirect_stderr(err): rc=operator_main(["locate",str(root),"missing"])
            payload=json.loads(err.getvalue()); self.assertEqual(rc,2); self.assertFalse(payload["ok"]); self.assertEqual(payload["error_type"],"KeyError")


if __name__ == "__main__": unittest.main()
