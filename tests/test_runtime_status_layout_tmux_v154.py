from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.composition.runtime_status_config import load_runtime_status_layout
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.lifecycle.session.runtime import default_persistent_session_backend_registry


class RuntimeStatusPersistentSessionLayoutTests(unittest.TestCase):
    def test_backend_neutral_session_layout_resolves_tmux_through_registry(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "layout.json"
            path.write_text(
                json.dumps(
                    {
                        "runtime_state": str(root / "runtime.json"),
                        "runtime_history": str(root / "runtime.json.history.jsonl"),
                        "heartbeat_root": str(root / "heartbeats"),
                        "resource_authority": str(root / "lease"),
                        "forensic_root": str(root / "forensics"),
                        "deployments": [],
                        "services": [],
                        "server_session": {
                            "binding_root": str(root / "bindings"),
                            "session_name": "rp-prod",
                            "backend": {
                                "id": "tmux",
                                "options": {
                                    "tmux_executable": "/definitely/missing/tmux",
                                    "server_label": "rp",
                                    "tmpdir": "/tmp/rp",
                                    "binary_identity_digest": "1" * 64,
                                },
                            },
                        },
                    }
                )
            )
            layout = load_runtime_status_layout(path)
            self.assertIsNotNone(layout.server_session)
            assert layout.server_session is not None
            self.assertEqual(layout.server_session.session_name, "rp-prod")
            self.assertEqual(layout.server_session.backend.backend_id, "tmux")
            concurrency_runtime = build_concurrency_runtime()
            task_group = concurrency_runtime.open_task_group("test-runtime-status-layout")
            try:
                probe = default_persistent_session_backend_registry(task_group).build_status_probe(layout.server_session)
                self.assertEqual(probe.control.server_label, "rp")
                self.assertEqual(probe.control.socket_directory, "/tmp/rp")
            finally:
                concurrency_runtime.close()

    def test_layout_can_explicitly_disable_persistent_session_observation(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            path = root / "layout.json"
            path.write_text(
                json.dumps(
                    {
                        "runtime_state": "r",
                        "runtime_history": "rh",
                        "heartbeat_root": "h",
                        "resource_authority": "l",
                        "forensic_root": "f",
                        "deployments": [],
                        "services": [],
                    }
                )
            )
            layout = load_runtime_status_layout(path)
            self.assertIsNone(layout.server_session)


if __name__ == "__main__":
    unittest.main()
