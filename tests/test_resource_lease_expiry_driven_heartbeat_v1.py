from __future__ import annotations

from dataclasses import dataclass
import unittest
from unittest.mock import patch

from noetrium_platform.composition import research_execution_pool as pool_module
from noetrium_platform.infrastructure.resources.authority.api import AuthorityLeasePolicy
from noetrium_platform.infrastructure.resources.authority.runtime import heartbeat as heartbeat_module
from noetrium_platform.infrastructure.resources.authority.runtime.heartbeat import (
    LeaseHeartbeatError,
    LeaseHeartbeatFactory,
)


class _Group:
    group_id = "expiry-driven-heartbeat-test"


class _Scheduled:
    task_id = "expiry-driven-heartbeat"

    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def assert_healthy(self) -> None:
        return None


class _Scheduler:
    def __init__(self) -> None:
        self.spec = None
        self.fn = None
        self.handle = _Scheduled()

    def register(self, _owner_group_id, spec, fn, /, *args, **kwargs):
        self.spec = spec
        self.fn = fn
        return self.handle

    def assert_healthy(self) -> None:
        return None

    def snapshot(self):
        return ()


@dataclass(frozen=True)
class _LeaseRow:
    lease_id: str
    expiry: float


class _Authority:
    def renew_leases(self, rows, *, ttl_seconds):
        return tuple(rows)


class ResourceLeaseExpiryDrivenHeartbeatTests(unittest.TestCase):
    def test_scheduler_tick_duration_is_not_lease_truth(self) -> None:
        scheduler = _Scheduler()
        factory = LeaseHeartbeatFactory(
            renew=lambda rows: rows,
            row_identity=lambda row: row.lease_id,
            row_expiry_epoch_s=lambda row: row.expiry,
            heartbeat_namespace="resource:test",
            task_group=_Group(),
            heartbeat_scheduler=scheduler,
            lane_id="resource-lease-writer",
            interval_seconds=30.0,
            policy=object(),
        )
        guard = factory.create((_LeaseRow("lease:a", 1_100.0),))
        guard.start()
        self.assertIsNotNone(scheduler.spec)
        self.assertIsNone(scheduler.spec.max_tick_seconds)

        with patch.object(heartbeat_module.time, "time", return_value=1_050.0):
            guard.assert_healthy()
        with patch.object(heartbeat_module.time, "time", return_value=1_100.0):
            with self.assertRaisesRegex(LeaseHeartbeatError, "authority expired"):
                guard.assert_healthy()

        guard.close()
        factory.close()

    def test_contention_retry_horizon_is_earliest_actual_expiry(self) -> None:
        rows = (
            _LeaseRow("lease:a", 1_090.0),
            _LeaseRow("lease:b", 1_120.0),
        )
        captured = {}

        def fake_retry(operation, *, should_retry, timeout_seconds, interval_seconds):
            captured["timeout_seconds"] = timeout_seconds
            captured["interval_seconds"] = interval_seconds
            captured["should_retry"] = should_retry
            return ("renewed",)

        def fake_lease_field(row, name):
            self.assertEqual(name, "expires_at_epoch_s")
            return row.expiry

        with (
            patch.object(pool_module.time, "time", return_value=1_000.0),
            patch.object(pool_module, "lease_field", side_effect=fake_lease_field),
            patch.object(pool_module, "retry_until_deadline", side_effect=fake_retry),
        ):
            result = pool_module._renew_resource_authority_leases(
                _Authority(),
                rows,
                AuthorityLeasePolicy(
                    ttl_seconds=120.0,
                    renewal_interval_seconds=30.0,
                ),
            )

        self.assertEqual(result, ("renewed",))
        self.assertEqual(captured["timeout_seconds"], 90.0)
        self.assertGreater(captured["interval_seconds"], 0.0)
        self.assertLessEqual(captured["interval_seconds"], 0.3)

    def test_policy_needs_only_renewal_before_expiry(self) -> None:
        policy = AuthorityLeasePolicy(
            ttl_seconds=100.0,
            renewal_interval_seconds=40.0,
        )
        self.assertEqual(policy.ttl_seconds, 100.0)
        self.assertEqual(policy.renewal_interval_seconds, 40.0)


if __name__ == "__main__":
    unittest.main()
