"""A cold scheduling replay may not monopolize the global SQLite writer."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)


class SchedulingCatchupTests(unittest.TestCase):
    def test_cold_mutation_replays_readonly_before_acquiring_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.sqlite"
            cold = DurableUnifiedSchedulingAuthority(path)
            writer = DurableUnifiedSchedulingAuthority(path)
            for index in range(12):
                writer.record_grant(
                    tenant_id="first-paper", flow_id=f"warm-{index}",
                    reserved_service_quanta=1,
                )
                writer.record_completion(
                    tenant_id="first-paper", flow_id=f"warm-{index}",
                    service_quanta=1, reserved_service_quanta=1,
                )

            original = cold._catch_up
            snapshots = []

            def assert_writer_not_held_by_replay(conn):
                if not snapshots:
                    # A new connection can acquire the sole write permit
                    # while the cold process replays its historical cut.
                    with sqlite3.connect(path, timeout=0.15, isolation_level=None) as peer:
                        peer.execute("BEGIN IMMEDIATE")
                        peer.execute("ROLLBACK")
                    snapshots.append(conn.execute("PRAGMA query_only").fetchone()[0])
                return original(conn)

            cold._catch_up = assert_writer_not_held_by_replay
            seq = cold.record_grant(tenant_id="second-paper", flow_id="new")
            self.assertEqual(seq, 25)
            self.assertEqual(snapshots, [1])
            self.assertEqual(cold._applied, 25)
            with sqlite3.connect(path) as reader:
                self.assertEqual(
                    reader.execute("SELECT COUNT(*) FROM unified_scheduling_events").fetchone()[0],
                    25,
                )

    def test_failed_mutation_is_not_persisted_after_read_catchup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shared.sqlite"
            cold = DurableUnifiedSchedulingAuthority(path)
            writer = DurableUnifiedSchedulingAuthority(path)
            writer.record_grant(tenant_id="paper", flow_id="existing")
            with self.assertRaisesRegex(RuntimeError, "no active flow"):
                cold.record_completion(
                    tenant_id="paper", flow_id="unknown", service_quanta=2,
                )
            self.assertEqual(writer.record_grant(tenant_id="paper", flow_id="next"), 2)
            self.assertEqual(
                DurableUnifiedSchedulingAuthority(path).service_revision(), 2
            )


if __name__ == "__main__":
    unittest.main()
