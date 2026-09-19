from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.providers import HashChainError
from noetrium_platform.infrastructure.reliability.forensics.api import MutationRecord
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


class ForensicsOSTests(unittest.TestCase):
    def test_hash_chain_and_index(self):
        with tempfile.TemporaryDirectory() as td:
            store = ForensicStore(Path(td))
            ctx = ExecutionContext(run_id="r", trace_id="t", span_id="s", task_id="task", decision_cycle_id="dc", operation_id="op")
            store.append_event(EventEnvelope("e1", "X", ctx, "c"))
            store.append_mutation(MutationRecord("m1", "state.x", "agg", None, 1, None, "abc", "owner", "op", ctx))
            self.assertEqual(store.verify_all()["events"][0], 1)
            self.assertEqual(store.index.locate("e1").to_payload()["event_id"], "e1")
            self.assertEqual(store.index.last_writer("r", "state.x").mutation_id, "m1")

    def test_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            store = ForensicStore(Path(td))
            ctx = ExecutionContext(run_id="r", trace_id="t", span_id="s")
            store.append_event(EventEnvelope("e1", "X", ctx, "c"))
            p = Path(td) / "events.chain" / "00000000.jsonl"
            text = p.read_text(encoding="utf-8").replace('"event_type":"X"', '"event_type":"Y"')
            p.write_text(text, encoding="utf-8")
            with self.assertRaises(HashChainError):
                store.events.verify()

if __name__ == "__main__":
    unittest.main()
