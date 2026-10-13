from __future__ import annotations

import unittest
from contextlib import nullcontext
from threading import RLock
from unittest.mock import patch

from noetrium_platform.capabilities.model.deployment.composition import replica_pool


class _Request:
    runtime_identity_digest = "fixed-replica-identity"


class _Owner:
    def __init__(self) -> None:
        self.health_checks = 0

    def assert_healthy(self) -> None:
        self.health_checks += 1


class _Pool:
    def __init__(self) -> None:
        self._lock = RLock()
        self._closed = False
        self._closing = False
        self.owner = _Owner()
        self._owners = {_Request.runtime_identity_digest: self.owner}
        self.consumer_calls = 0

    def _identity_lock(self, identity):
        assert identity == _Request.runtime_identity_digest
        return nullcontext()

    def _consumer(self, owner, identity):
        self.consumer_calls += 1
        assert owner is self.owner
        return "fenced-active-lease"


class AdmissionContractTests(unittest.TestCase):
    def test_warm_pool_ensure_proves_owner_health_before_creating_consumer(self):
        pool = _Pool()
        with patch.object(replica_pool, "ModelReplicaPoolRequest", _Request):
            result = replica_pool.LocalModelReplicaPoolRuntime.ensure(pool, _Request())
        self.assertEqual(result, "fenced-active-lease")
        self.assertEqual(pool.owner.health_checks, 1)
        self.assertEqual(pool.consumer_calls, 1)


if __name__ == "__main__":
    unittest.main()
