from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from noetrium_platform.infrastructure.reliability.recovery.api.lease import RecoveryLease, RecoveryLeaseBusy
from tests_support import recovery_lease_state
from noetrium_platform.infrastructure.reliability.recovery.execution.runtime.file_lock import FileLockedRecoveryExecutionFactory


class RecoveryExecutionLockV163Tests(unittest.TestCase):
    def test_long_held_execution_lock_blocks_second_writer_even_if_document_ttl_is_short(self):
        with TemporaryDirectory() as td:
            path=Path(td)/'lease.json'
            first=recovery_lease_state(path)
            second=recovery_lease_state(path)
            with FileLockedRecoveryExecutionFactory(first, lock_path=path.with_name('execution.lock')).execution('owner-a','manifest-a',ttl_seconds=0.01):
                # The fencing lock is independent of the document TTL.  A second exact
                # recovery command cannot enter even if the observable document expires.
                with self.assertRaises(RecoveryLeaseBusy):
                    with FileLockedRecoveryExecutionFactory(second, lock_path=path.with_name('execution.lock')).execution('owner-b','manifest-b',ttl_seconds=10):
                        pass

    def test_execution_guard_releases_document_and_kernel_lock_together(self):
        with TemporaryDirectory() as td:
            path=Path(td)/'lease.json'
            store=recovery_lease_state(path)
            with FileLockedRecoveryExecutionFactory(store, lock_path=path.with_name('execution.lock')).execution('owner','manifest',ttl_seconds=10) as execution:
                self.assertEqual(execution.assert_owned().manifest_digest,'manifest')
            self.assertIsNone(store.read())
            with FileLockedRecoveryExecutionFactory(store, lock_path=path.with_name('execution.lock')).execution('next','manifest-2',ttl_seconds=10):
                self.assertEqual(store.read().owner_id,'next')

    def test_release_failure_keeps_kernel_fence_until_retry_converges(self):
        class FailOnceLeaseState:
            def __init__(self):
                self.lease = None
                self.fail_release = True
            def read(self):
                return self.lease
            def acquire(self, owner_id, manifest_digest, *, ttl_seconds=300.0, now=None):
                if self.lease is not None:
                    raise RecoveryLeaseBusy("already owned")
                self.lease = RecoveryLease(
                    owner_id, manifest_digest, 1.0, 1.0 + ttl_seconds
                )
                return self.lease
            def renew(self, owner_id, manifest_digest, *, ttl_seconds=300.0, now=None):
                assert self.lease is not None
                return self.lease
            def assert_owned(self, owner_id, manifest_digest, *, now=None):
                if (
                    self.lease is None
                    or self.lease.owner_id != owner_id
                    or self.lease.manifest_digest != manifest_digest
                ):
                    raise RecoveryLeaseBusy("not owned")
                return self.lease
            def release(self, owner_id, manifest_digest):
                if self.fail_release:
                    self.fail_release = False
                    raise RuntimeError("simulated durable release failure")
                assert self.lease is not None
                assert self.lease.owner_id == owner_id
                assert self.lease.manifest_digest == manifest_digest
                self.lease = None

        with TemporaryDirectory() as td:
            lock_path = Path(td) / "execution.lock"
            state = FailOnceLeaseState()
            first = FileLockedRecoveryExecutionFactory(
                state, lock_path=lock_path
            ).execution("owner", "manifest", ttl_seconds=10)
            first.__enter__()

            with self.assertRaisesRegex(
                RuntimeError, "simulated durable release failure"
            ):
                first.close()

            with self.assertRaises(RecoveryLeaseBusy):
                FileLockedRecoveryExecutionFactory(
                    state, lock_path=lock_path
                ).execution("next", "manifest-2", ttl_seconds=10).__enter__()

            first.close()
            with FileLockedRecoveryExecutionFactory(
                state, lock_path=lock_path
            ).execution("next", "manifest-2", ttl_seconds=10):
                self.assertEqual(state.read().owner_id, "next")

    def test_execution_fence_accepts_non_file_lease_state_port(self):
        class MemoryLeaseState:
            def __init__(self): self.lease=None
            def read(self): return self.lease
            def acquire(self, owner_id, manifest_digest, *, ttl_seconds=300.0, now=None):
                self.lease=RecoveryLease(owner_id, manifest_digest, 1.0, 1.0+ttl_seconds)
                return self.lease
            def renew(self, owner_id, manifest_digest, *, ttl_seconds=300.0, now=None):
                assert self.lease is not None
                self.lease=RecoveryLease(owner_id, manifest_digest, self.lease.acquired_at, self.lease.expires_at+ttl_seconds)
                return self.lease
            def assert_owned(self, owner_id, manifest_digest, *, now=None):
                if self.lease is None or self.lease.owner_id != owner_id or self.lease.manifest_digest != manifest_digest:
                    raise RecoveryLeaseBusy('not owned')
                return self.lease
            def release(self, owner_id, manifest_digest): self.lease=None

        with TemporaryDirectory() as td:
            state=MemoryLeaseState()
            factory=FileLockedRecoveryExecutionFactory(state, lock_path=Path(td)/'execution.lock')
            with factory.execution('owner','manifest',ttl_seconds=10) as execution:
                self.assertEqual(execution.assert_owned().owner_id,'owner')
            self.assertIsNone(state.read())


if __name__=='__main__': unittest.main()
