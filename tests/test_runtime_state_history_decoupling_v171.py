from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.lifecycle.launch_control.history import RuntimeHistory
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_history_storage import FileRuntimeHistoryStorage
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_state_contracts import RuntimeTxnPhase
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_state_storage import FileRuntimeControlStateStore
from noetrium_platform.infrastructure.lifecycle.launch_control.state import RuntimeControlStore
from noetrium_platform.infrastructure.lifecycle.launch_control.status_readers import RuntimeControlStatusReader


class RuntimeStateHistoryDecouplingV171Tests(unittest.TestCase):
    def test_authoritative_state_and_history_can_use_independent_roots(self) -> None:
        with TemporaryDirectory() as state_td, TemporaryDirectory() as history_td:
            state_path = Path(state_td) / "authority" / "runtime.json"
            history_path = Path(history_td) / "black-box" / "runtime-history.jsonl"
            state_store = FileRuntimeControlStateStore(state_path)
            history = RuntimeHistory(FileRuntimeHistoryStorage(history_path))
            control = RuntimeControlStore(state_store, history)

            initial = control.create("ctl", "manifest")
            current = replace(initial, phase=RuntimeTxnPhase.RUNNING, current_action="verify_release")
            control.write(current)

            self.assertEqual(control.read(), current)
            self.assertEqual(history.verify(), ())
            history.assert_tail_matches(current)
            observation = RuntimeControlStatusReader(state_store, history).observe()
            self.assertEqual(observation.state, current)
            self.assertEqual(observation.history_errors, ())
            self.assertIn(str(state_path), observation.evidence_refs)
            self.assertIn(str(history_path), observation.evidence_refs)


if __name__ == "__main__":
    unittest.main()
