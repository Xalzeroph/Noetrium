from pathlib import Path
import json
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import DEFAULT_FAILURE_CATALOG, RecoveryAction
from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.runtime import CrashBundleBuilder, FailureRecorder
from noetrium_platform.infrastructure.reliability.forensics.api import MutationRecord
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception, redact_text, redact_value
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.governance.quality import scan_silent_failures


class ForensicsAdvancedTests(unittest.TestCase):
    def _ctx(self):
        return ExecutionContext(run_id="r", trace_id="t", span_id="s", task_id="task", decision_cycle_id="dc", operation_id="op")

    def test_redaction_removes_high_confidence_credentials(self):
        text="authorization: Bearer abcdefghijklmnopqrstuvwxyz token=supersecretvalue sk-abcdefghijklmnop"
        red=redact_text(text)
        self.assertNotIn("supersecretvalue",red); self.assertNotIn("sk-abcdefghijklmnop",red)
        payload=redact_value({"api_key":"secret123","nested":{"password":"p"},"normal":"x"})
        self.assertEqual(payload["api_key"],"<REDACTED>"); self.assertEqual(payload["nested"]["password"],"<REDACTED>")


    def test_safe_exception_descriptor_normalizes_secret_bearing_errors(self):
        descriptor=describe_exception(RuntimeError("https://user:password@example.test token=supersecretvalue"))
        self.assertNotIn("password",descriptor.safe_message)
        self.assertNotIn("supersecretvalue",descriptor.safe_message)
        self.assertEqual(len(descriptor.error_digest),64)

    def test_build_failure_redacts_persisted_exception_and_cause_chain(self):
        try:
            try: raise OSError("token=supersecretvalue")
            except OSError as inner: raise RuntimeError("Bearer abcdefghijklmnop") from inner
        except RuntimeError as exc:
            f=build_failure(component_id="c",failure_domain="D",failure_code="C",stage="S",context=self._ctx(),exc=exc)
        self.assertNotIn("supersecretvalue",f.cause_message)
        self.assertNotIn("abcdefghijklmnop",f.cause_message)
        self.assertEqual(len(f.cause_chain_digest),64)

    def test_failure_catalog_is_strict(self):
        spec=DEFAULT_FAILURE_CATALOG.require("EVIDENCE","CHAIN_CORRUPTION","verify")
        self.assertEqual(spec.default_recovery,RecoveryAction.BLOCK_SCIENTIFIC_USE)
        with self.assertRaises(KeyError): DEFAULT_FAILURE_CATALOG.require("X","Y","Z")

    def test_failure_recorder_persists_terminal_failure_event(self):
        with tempfile.TemporaryDirectory() as td:
            store=ForensicStore(Path(td)); spec=DEFAULT_FAILURE_CATALOG.require("LLM_CONTRACT","OUTPUT_CONTRACT","decode")
            outcome=FailureRecorder(store).record(spec=spec,component_id="llm.planner",context=self._ctx(),exc=ValueError("bad"),operation_id="op")
            failure=outcome.failure
            self.assertEqual(store.verify_all()["failures"][0],1)
            self.assertEqual(store.verify_all()["events"][0],1)
            self.assertEqual(store.index.locate(failure.failure_id).to_payload()["failure_code"],"OUTPUT_CONTRACT")

    def test_crash_bundle_contains_verified_tails_and_writers(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); store=ForensicStore(root); ctx=self._ctx()
            store.append_event(EventEnvelope("e", "X", ctx, "c"))
            store.append_mutation(MutationRecord("m","state.x","agg",1,2,"a","b","owner","op",ctx))
            spec=DEFAULT_FAILURE_CATALOG.require("LLM_CONTRACT","OUTPUT_CONTRACT","decode")
            outcome=FailureRecorder(store).record(spec=spec,component_id="c",context=ctx,exc=ValueError("bad"))
            f=outcome.failure
            out=root/"crash"/"bundle.json"; manifest=CrashBundleBuilder(store).publish(f.failure_id,out)
            self.assertTrue(out.exists()); self.assertEqual(len(manifest.bundle_digest),64)
            self.assertEqual(manifest.recent_state_writers[0]["mutation_id"],"m")
            self.assertGreaterEqual(manifest.authoritative_chain_tails["events"]["rows"],2)
            stored=json.loads(out.read_text()); self.assertEqual(stored["bundle_digest"],manifest.bundle_digest)

    def test_silent_failure_scanner_detects_broad_swallow(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.py"; p.write_text("try:\n  x=1\nexcept Exception:\n  pass\n")
            findings=scan_silent_failures(Path(td))
            self.assertEqual(findings[0].kind,"silent_broad_except")

if __name__ == "__main__": unittest.main()


def test_failure_recorder_replay_is_one_authoritative_failure_and_one_materialization_event():
    ctx = ExecutionContext("run", "trace", "span", operation_id="op")
    spec = DEFAULT_FAILURE_CATALOG.require("LLM_CONTRACT", "OUTPUT_CONTRACT", "decode")
    with tempfile.TemporaryDirectory() as td:
        store = ForensicStore(Path(td))
        first = FailureRecorder(store).record(
            spec=spec,
            component_id="llm.planner",
            context=ctx,
            exc=ValueError("same failure"),
            operation_id="op",
            operation_invocation_id="op@invocation-1",
            operation_type="llm.decode",
            operation_payload_digest="a" * 64,
        )
        second = FailureRecorder(store).record(
            spec=spec,
            component_id="llm.planner",
            context=ctx,
            exc=ValueError("same failure"),
            operation_id="op",
            operation_invocation_id="op@invocation-1",
            operation_type="llm.decode",
            operation_payload_digest="a" * 64,
        )
        assert first.failure.failure_id == second.failure.failure_id
        assert store.verify_all()["failures"][0] == 1
        events = store.events.verified_payloads_after(0).payloads
        materialized = [row for row in events if row["event_type"] == "FAILURE_RECORDED"]
        assert len(materialized) == 1
        store.close()


def test_failure_identity_separates_component_and_operation_invocation():
    from noetrium_platform.infrastructure.reliability.failure.api import build_failure

    ctx = ExecutionContext("run", "trace", "span")
    common = dict(
        failure_domain="PLATFORM",
        failure_code="OPERATION_FAILURE",
        stage="component_boundary",
        context=ctx,
        exc=RuntimeError("same cause"),
        operation_id="op",
        operation_type="work",
        operation_payload_digest="b" * 64,
    )
    a = build_failure(component_id="component.a", operation_invocation_id="op@1", **common)
    b = build_failure(component_id="component.b", operation_invocation_id="op@1", **common)
    c = build_failure(component_id="component.a", operation_invocation_id="op@2", **common)
    assert a.failure_id != b.failure_id
    assert a.failure_id != c.failure_id
