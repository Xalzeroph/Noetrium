from __future__ import annotations

import multiprocessing as mp
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLeaseBusy
from tests_support import recovery_lease_state


def _lease_worker(path: str, owner: str, start, results) -> None:
    store = recovery_lease_state(Path(path))
    start.wait()
    try:
        store.acquire(owner, "manifest", ttl_seconds=100.0, now=1.0)
    except RecoveryLeaseBusy:
        results.put("busy")
    else:
        results.put("acquired")


class RecoveryLeaseConcurrencyV143Tests(unittest.TestCase):
    def test_concurrent_operator_processes_have_exactly_one_winner(self) -> None:
        if "spawn" not in mp.get_all_start_methods():
            self.skipTest("multiprocessing spawn unavailable")
        ctx = mp.get_context("spawn")
        with TemporaryDirectory() as td:
            path = str(Path(td) / "lease.json")
            start = ctx.Event()
            results = ctx.Queue()
            workers = [
                ctx.Process(target=_lease_worker, args=(path, f"op-{i}", start, results))
                for i in range(8)
            ]
            for worker in workers:
                worker.start()
            start.set()
            outcomes = [results.get(timeout=5) for _ in workers]
            for worker in workers:
                worker.join(timeout=5)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(outcomes.count("acquired"), 1)
            self.assertEqual(outcomes.count("busy"), 7)

    def test_same_owner_cannot_rebind_live_lease_to_another_manifest(self) -> None:
        with TemporaryDirectory() as td:
            store = recovery_lease_state(Path(td) / "lease.json")
            store.acquire("operator", "manifest-a", ttl_seconds=100.0, now=1.0)
            with self.assertRaises(RecoveryLeaseBusy):
                store.acquire("operator", "manifest-b", ttl_seconds=100.0, now=2.0)
            self.assertEqual(store.read().manifest_digest, "manifest-a")

    def test_same_owner_same_manifest_can_renew(self) -> None:
        with TemporaryDirectory() as td:
            store = recovery_lease_state(Path(td) / "lease.json")
            first = store.acquire("operator", "manifest-a", ttl_seconds=10.0, now=1.0)
            renewed = store.acquire("operator", "manifest-a", ttl_seconds=20.0, now=2.0)
            self.assertGreater(renewed.expires_at, first.expires_at)


if __name__ == "__main__":
    unittest.main()
