from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLeaseBusy
from noetrium_platform.foundation.kernel.kernel.lease_clock import ManualLeaseClock
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
from noetrium_platform.composition.reliability_resources import RecoveryLeaseProjection


class RecoveryLeaseExactIdentityV160Tests(unittest.TestCase):
    def _store(self, root):
        clock = ManualLeaseClock(elapsed_seconds=1.0, wall_epoch_seconds=1_000_000.0)
        authority = UniversalResourceAuthority(
            Path(root) / "authority.sqlite",
            clock=clock,
        )
        return RecoveryLeaseProjection(authority), clock

    def test_renew_preserves_original_acquired_at_and_extends_expiry(self):
        with TemporaryDirectory() as td:
            store, clock = self._store(td)
            first = store.acquire("owner", "manifest-a", ttl_seconds=10)
            clock.advance(4)
            renewed = store.renew("owner", "manifest-a", ttl_seconds=20)
            self.assertEqual(renewed.acquired_at, first.acquired_at)
            self.assertEqual(renewed.expires_at, first.acquired_at + 24)

    def test_expired_lease_cannot_be_renewed(self):
        with TemporaryDirectory() as td:
            store, clock = self._store(td)
            store.acquire("owner", "manifest-a", ttl_seconds=2)
            clock.advance(2)
            with self.assertRaises(RecoveryLeaseBusy):
                store.renew("owner", "manifest-a", ttl_seconds=10)

    def test_old_process_cannot_release_same_owner_new_manifest_lease(self):
        with TemporaryDirectory() as td:
            store, clock = self._store(td)
            store.acquire("owner", "manifest-a", ttl_seconds=1)
            clock.advance(2)
            store.acquire("owner", "manifest-b", ttl_seconds=10)
            with self.assertRaises(RecoveryLeaseBusy):
                store.release("owner", "manifest-a")
            self.assertEqual(store.read().manifest_digest, "manifest-b")

    def test_release_requires_exact_owner_and_manifest(self):
        with TemporaryDirectory() as td:
            store, _clock = self._store(td)
            store.acquire("owner", "manifest-a", ttl_seconds=10)
            with self.assertRaises(RecoveryLeaseBusy):
                store.release("other", "manifest-a")
            with self.assertRaises(RecoveryLeaseBusy):
                store.release("owner", "manifest-b")
            store.release("owner", "manifest-a")
            self.assertIsNone(store.read())


if __name__ == "__main__":
    unittest.main()
