from __future__ import annotations

from runtime_manager_test_support import make_runtime_control_store, runtime_history_path
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control import RuntimeControlStore, RuntimeTxnPhase
from noetrium_platform.infrastructure.lifecycle.launch_control.history import RuntimeHistoryIntegrityError


class RuntimeHistoryReconcileV143Tests(unittest.TestCase):
    def test_missing_latest_projection_is_explicitly_reconciled_from_authoritative_state(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "runtime.json"
            store = make_runtime_control_store(path)
            initial = store.create("ctl", "manifest")
            current = replace(initial, phase=RuntimeTxnPhase.RUNNING, current_action="verify_release")
            store.write(current)

            history_path = runtime_history_path(path)
            lines = history_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            history_path.write_text(lines[0] + "\n", encoding="utf-8")

            self.assertTrue(store.history.reconcile_authoritative(store.read()))
            repaired = json.loads(history_path.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(repaired["projection_kind"], "authoritative_reconcile")
            self.assertEqual(repaired["state"]["current_action"], "verify_release")
            store.history.assert_tail_matches(current)

    def test_reconcile_refuses_different_control_or_manifest_identity(self) -> None:
        with TemporaryDirectory() as td:
            path = Path(td) / "runtime.json"
            store = make_runtime_control_store(path)
            state = store.create("ctl", "manifest-a")
            alien = replace(state, manifest_digest="manifest-b")
            with self.assertRaisesRegex(RuntimeHistoryIntegrityError, "different control/manifest"):
                store.history.reconcile_authoritative(alien)

    def test_control_store_refuses_authoritative_mutation_when_history_is_already_corrupt(self) -> None:
        with TemporaryDirectory() as td:
            state_path = Path(td) / "runtime.json"
            history_path = runtime_history_path(state_path)
            store = make_runtime_control_store(state_path)
            initial = store.create("ctl", "manifest")
            row = json.loads(history_path.read_text(encoding="utf-8"))
            row["row_sha256"] = "f" * 64
            history_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            authoritative_before = state_path.read_bytes()
            mutated = replace(initial, phase=RuntimeTxnPhase.RUNNING)
            with self.assertRaisesRegex(RuntimeHistoryIntegrityError, "integrity failure"):
                store.write(mutated)
            self.assertEqual(state_path.read_bytes(), authoritative_before)

    def test_append_fails_closed_when_existing_history_is_corrupt(self) -> None:
        with TemporaryDirectory() as td:
            state_path = Path(td) / "runtime.json"
            history_path = runtime_history_path(state_path)
            store = make_runtime_control_store(state_path)
            state = store.create("ctl", "manifest")
            row = json.loads(history_path.read_text(encoding="utf-8"))
            row["row_sha256"] = "0" * 64
            history_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            before = history_path.read_bytes()
            with self.assertRaisesRegex(RuntimeHistoryIntegrityError, "integrity failure"):
                store.history.append(state)
            self.assertEqual(history_path.read_bytes(), before)

    def test_v2_history_detects_state_digest_tampering(self) -> None:
        with TemporaryDirectory() as td:
            state_path = Path(td) / "runtime.json"
            history_path = runtime_history_path(state_path)
            store = make_runtime_control_store(state_path)
            store.create("ctl", "manifest")
            row = json.loads(history_path.read_text(encoding="utf-8"))
            row["state"]["phase"] = "succeeded"
            history_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            errors = store.history.verify()
            self.assertTrue(any("state digest mismatch" in x for x in errors))
            self.assertTrue(any("digest mismatch" in x for x in errors))


if __name__ == "__main__":
    unittest.main()
