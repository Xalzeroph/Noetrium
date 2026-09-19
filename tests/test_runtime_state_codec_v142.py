from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store
from dataclasses import asdict, replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeControlStore, RuntimeTxnPhase
from noetrium_platform.foundation.kernel.kernel.durability import ChecksummedDocumentFailureCode
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_state_codec import RuntimeControlStateIntegrityError


class RuntimeStateCodecV142Tests(unittest.TestCase):
    def test_runtime_state_is_versioned_checksummed_and_round_trips(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "runtime.json"
            store = make_runtime_control_store(path)
            state = store.create("control-1", "a" * 64)
            state = replace(
                state,
                phase=RuntimeTxnPhase.RUNNING,
                completed_actions=("verify_release",),
                evidence_refs=("evidence:1",),
            )
            store.write(state)
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema"], "runtime-control-state.v3")
            self.assertEqual(len(document["payload_sha256"]), 64)
            self.assertEqual(store.read(), state)

    def test_runtime_state_tamper_fails_closed(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "runtime.json"
            store = make_runtime_control_store(path)
            store.create("control-1", "a" * 64)
            document = json.loads(path.read_text(encoding="utf-8"))
            document["payload"]["current_mutating"] = True
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(RuntimeControlStateIntegrityError) as caught:
                store.read()
            self.assertIs(caught.exception.document_failure_code, ChecksummedDocumentFailureCode.CHECKSUM_MISMATCH)

    def test_unenveloped_runtime_state_is_rejected(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "runtime.json"
            store = make_runtime_control_store(path)
            state = store.create("control-1", "a" * 64)
            payload = asdict(state)
            payload["phase"] = state.phase.value
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RuntimeControlStateIntegrityError) as caught:
                store.read()
            self.assertIs(caught.exception.document_failure_code, ChecksummedDocumentFailureCode.SCHEMA_MISSING)


if __name__ == "__main__":
    unittest.main()
