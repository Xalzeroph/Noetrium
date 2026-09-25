from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLeaseBusy
from tests_support import recovery_lease_state


class RecoveryLeaseExactIdentityV160Tests(unittest.TestCase):
    def test_renew_preserves_original_acquired_at_and_extends_expiry(self):
        with TemporaryDirectory() as td:
            store=recovery_lease_state(Path(td)/'lease.json')
            first=store.acquire('owner','manifest-a',ttl_seconds=10,now=1)
            renewed=store.renew('owner','manifest-a',ttl_seconds=20,now=5)
            self.assertEqual(renewed.acquired_at,first.acquired_at)
            self.assertEqual(renewed.expires_at,25)

    def test_expired_lease_cannot_be_renewed(self):
        with TemporaryDirectory() as td:
            store=recovery_lease_state(Path(td)/'lease.json')
            store.acquire('owner','manifest-a',ttl_seconds=2,now=1)
            with self.assertRaises(RecoveryLeaseBusy):
                store.renew('owner','manifest-a',ttl_seconds=10,now=3)

    def test_old_process_cannot_release_same_owner_new_manifest_lease(self):
        with TemporaryDirectory() as td:
            store=recovery_lease_state(Path(td)/'lease.json')
            store.acquire('owner','manifest-a',ttl_seconds=1,now=1)
            # Old lease has expired; a new controller intentionally reuses the human owner label.
            store.acquire('owner','manifest-b',ttl_seconds=10,now=3)
            with self.assertRaises(RecoveryLeaseBusy):
                store.release('owner','manifest-a')
            current=store.read()
            self.assertIsNotNone(current)
            self.assertEqual(current.manifest_digest,'manifest-b')

    def test_release_requires_exact_owner_and_manifest(self):
        with TemporaryDirectory() as td:
            store=recovery_lease_state(Path(td)/'lease.json')
            store.acquire('owner','manifest-a',ttl_seconds=10,now=1)
            with self.assertRaises(RecoveryLeaseBusy):
                store.release('other','manifest-a')
            with self.assertRaises(RecoveryLeaseBusy):
                store.release('owner','manifest-b')
            store.release('owner','manifest-a')
            self.assertIsNone(store.read())

if __name__ == '__main__':
    unittest.main()
