from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)


class DurableReleaseReplayTests(unittest.TestCase):
    def _owner(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "sched.sqlite"
        return path, DurableUnifiedSchedulingAuthority(path)

    def _append_historical_release(self, path, flow):
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO unified_scheduling_events(operation,payload) VALUES (?,?)",
                ("release_flow", json.dumps({"flow_id": flow})),
            )

    def test_exact_old_release_is_recovered_from_previous_bound_grant(self):
        path, owner = self._owner()
        owner.record_grant(tenant_id=None, flow_id="environment", resource_id="world", permit_count=1)
        owner.record_completion(tenant_id=None, flow_id="environment", resource_id="world", service_quanta=17)
        self._append_historical_release(path, "environment")
        recovered = DurableUnifiedSchedulingAuthority(path)
        self.assertEqual(recovered.service_revision(), 3)
        key = recovered._flow_key(None, "world", "environment")
        self.assertTrue(recovered._flow_states.get(key).retire_requested)

    def test_historical_release_with_no_prior_grant_does_not_forge_accounting(self):
        path, owner = self._owner()
        self._append_historical_release(path, "unallocated")
        self.assertEqual(DurableUnifiedSchedulingAuthority(path).service_revision(), 1)
        self.assertIsNone(owner._flow_states.get(owner._flow_key(None, None, "unallocated")))

    def test_ambiguous_historical_release_fails_closed_without_mutating_journal(self):
        path, owner = self._owner()
        for tenant in ("paper-a", "paper-b"):
            owner.record_grant(tenant_id=tenant, flow_id="same", resource_id="model")
            owner.record_completion(tenant_id=tenant, flow_id="same", resource_id="model", service_quanta=1)
        self._append_historical_release(path, "same")
        with self.assertRaisesRegex(RuntimeError, "ambiguous flow identity"):
            DurableUnifiedSchedulingAuthority(path).service_revision()
        with sqlite3.connect(path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM unified_scheduling_events").fetchone()[0], 5)


if __name__ == "__main__":
    unittest.main()
