from __future__ import annotations

import hashlib
import time
import unittest

from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat
from noetrium_platform.infrastructure.lifecycle.launch_control.heartbeat import assert_exact_heartbeat
from noetrium_platform.infrastructure.lifecycle.launch_control.status_readers import ServiceHeartbeatStatusReader


class MemoryHeartbeatStore:
    """Heartbeat source deliberately exposing no path/root/backend details."""

    def __init__(self) -> None:
        self.rows: dict[str, ServiceHeartbeat] = {}

    def exists(self, deployment_id: str) -> bool:
        return deployment_id in self.rows

    def read(self, deployment_id: str) -> ServiceHeartbeat:
        return self.rows[deployment_id]

    def write(self, heartbeat: ServiceHeartbeat) -> None:
        self.rows[heartbeat.deployment_id] = heartbeat

    def reference(self, deployment_id: str) -> str:
        return f"memory://heartbeat/{deployment_id}"


class HeartbeatBackendDecouplingV179Tests(unittest.TestCase):
    def test_status_and_exact_validation_need_no_file_backend(self) -> None:
        store = MemoryHeartbeatStore()
        heartbeat = ServiceHeartbeat(
            "deployment-1",
            "stack-digest",
            123,
            "pid:123:start:1",
            "argv-digest",
            True,
            "qualification-digest",
            time.time(),
        )
        store.write(heartbeat)
        observation = ServiceHeartbeatStatusReader(store).observe("deployment-1")
        self.assertEqual(observation.heartbeat, heartbeat)
        self.assertEqual(observation.evidence_refs, ("heartbeat:memory://heartbeat/deployment-1",))
        self.assertIs(
            assert_exact_heartbeat(
                heartbeat,
                deployment_id="deployment-1",
                stack_digest="stack-digest",
                max_age_seconds=30,
            ),
            heartbeat,
        )


if __name__ == "__main__":
    unittest.main()
