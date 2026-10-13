"""Physical model bundle snapshots must not hold unrelated pool locks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import (
    AdaptiveModelEndpointPool,
)
from tests.test_model_atomic_lifetime_bundle_v1 import _setup


def test_bundle_authority_snapshot_does_not_hold_pool_dispatch_locks(monkeypatch):
    registry, pools, _controllers = _setup(
        replicas=2, per_replica=1, pool_count=2,
    )
    flow = "snapshot-outside-lock"
    snapshot_entered = Event()
    snapshot_release = Event()
    original = AdaptiveModelEndpointPool._atomic_flow_bundle_placement

    def observed_snapshot(pools_arg, *, flow_id):
        snapshot_entered.set()
        assert snapshot_release.wait(5), "authoritative snapshot test gate timed out"
        return original(pools_arg, flow_id=flow_id)

    monkeypatch.setattr(
        AdaptiveModelEndpointPool,
        "_atomic_flow_bundle_placement",
        staticmethod(observed_snapshot),
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                pools[0].reserve_flow_bundle,
                pools, "tenant", flow,
                deadline=None, cancellation=None,
            )
            try:
                assert snapshot_entered.wait(2)
                # Concurrent model completions must remain able to take
                # either pool's lock while SQLite reads its physical cut.
                for pool in pools:
                    acquired = pool._lock.acquire(blocking=False)
                    assert acquired, "SQLite snapshot monopolized model dispatch"
                    pool._lock.release()
            finally:
                snapshot_release.set()
            future.result(timeout=5)
        for pool in pools:
            assert flow in pool._physical_flow_claims
    finally:
        snapshot_release.set()
        for pool in reversed(pools):
            if flow in pool._physical_flow_claims:
                pool.release_flow(flow)
            pool.close()
        registry.close()
