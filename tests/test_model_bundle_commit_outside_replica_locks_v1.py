"""One atomic model continuity bundle must not monopolize all replica pools."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as WorkerTimeout
from threading import Event
from unittest.mock import patch

import pytest

from tests.test_model_atomic_lifetime_bundle_v1 import _setup, _live_flows


def test_slow_atomic_resource_commit_does_not_block_replica_locks():
    registry, pools, controllers = _setup(
        replicas=2, per_replica=2, pool_count=2,
    )
    entered, release = Event(), Event()
    flow = "model-bundle-slow-physical-commit"
    controller_type = type(next(iter(controllers.values())))
    original = controller_type.commit_continuity_bundle

    def delayed_commit(self, claims):
        entered.set()
        assert release.wait(4), "controlled physical commit gate did not release"
        return original(self, claims)

    try:
        with patch.object(controller_type, "commit_continuity_bundle", delayed_commit):
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(
                    pools[0].reserve_flow_bundle,
                    pools, "tenant", flow,
                    deadline=None, cancellation=None,
                )
                assert entered.wait(3), "physical commit not reached"
                try:
                    assert not _live_flows(controllers)
                    for pool in pools:
                        assert pool._cv.acquire(timeout=.15), (
                            "cross-process Resource Authority blocked model dispatch"
                        )
                        try:
                            assert flow in pool._claiming_flows
                            assert flow not in pool._reserved_flows
                        finally:
                            pool._cv.release()
                        with pytest.raises(RuntimeError, match="during physical Claim"):
                            pool.close()
                    with pytest.raises(WorkerTimeout):
                        future.result(timeout=.025)
                finally:
                    release.set()
                future.result(timeout=4)
        assert sum(row.startswith(flow + ':role:') for row in _live_flows(controllers)) == 2
        assert all(flow not in pool._claiming_flows for pool in pools)
    finally:
        release.set()
        for pool in reversed(pools):
            if flow in pool._physical_flow_claims:
                pool.release_flow(flow)
            pool.close()
        registry.close()


def test_expired_deadline_after_authority_commit_rolls_back_all_roles():
    import time
    from noetrium_platform.foundation.kernel.concurrency.api import Deadline
    registry, pools, controllers = _setup(
        replicas=2, per_replica=2, pool_count=2,
    )
    entered, release = Event(), Event()
    flow = 'bundle-expires-after-real-atomic-claim'
    controller_type = type(next(iter(controllers.values())))
    original = controller_type.commit_continuity_bundle

    def controlled_commit(self, claims):
        entered.set()
        assert release.wait(4)
        return original(self, claims)

    try:
        with patch.object(controller_type, 'commit_continuity_bundle', controlled_commit):
            with ThreadPoolExecutor(max_workers=1) as workers:
                pending = workers.submit(
                    pools[0].reserve_flow_bundle, pools, 'tenant', flow,
                    deadline=Deadline.after(.15), cancellation=None,
                )
                assert entered.wait(2)
                try:
                    # Exercising deadline AFTER real Resource Authority commit,
                    # not just timing out before any side effect occurred.
                    time.sleep(.18)
                finally:
                    release.set()
                with pytest.raises(TimeoutError, match='committed after deadline'):
                    pending.result(timeout=3)
        assert not any(flow in pool._reserved_flows for pool in pools)
        assert not any(flow in pool._claiming_flows for pool in pools)
        assert not any(x.startswith(flow + ':role:') for x in _live_flows(controllers))
    finally:
        release.set()
        for pool in reversed(pools):
            pool.close()
        registry.close()


def test_publication_notify_failure_restores_fence_until_authority_rollback():
    registry, pools, controllers = _setup(
        replicas=2, per_replica=2, pool_count=2,
    )
    flow = 'bundle-publish-notify-failure'
    pool_cls = type(pools[0])
    original = pool_cls._notify_all_waiters_locked

    def fail_after_publication(self):
        if self is pools[1] and flow in self._reserved_flows:
            raise RuntimeError('test simulated notifier failure')
        return original(self)

    try:
        with patch.object(pool_cls, '_notify_all_waiters_locked', fail_after_publication):
            with pytest.raises(RuntimeError, match='test simulated notifier failure'):
                pools[0].reserve_flow_bundle(
                    pools, 'tenant', flow,
                    deadline=None, cancellation=None,
                )
        assert all(flow not in pool._reserved_flows for pool in pools)
        assert all(flow not in pool._claiming_flows for pool in pools)
        assert all(flow not in pool._physical_flow_claims for pool in pools)
        assert not any(x.startswith(flow + ':role:') for x in _live_flows(controllers))
    finally:
        for pool in reversed(pools):
            pool.close()
        registry.close()
