"""Ranking may release a pool mutex only while no peer mutex is held."""
from unittest.mock import patch
from tests.test_model_atomic_lifetime_bundle_v1 import _setup, _live_flows


def test_bundle_ranking_never_releases_one_mutex_inside_multi_pool_cut():
    registry, pools, controllers = _setup(replicas=2, per_replica=2, pool_count=2)
    cls = type(pools[0])
    original = cls._selected_waiter_locked
    flow = 'ranking-lock-order-regression'

    def checked_projection(self):
        assert not any(
            peer is not self and peer._lock.locked() for peer in pools
        ), 'ranking releases coordinator while holding peer pool mutex'
        return original(self)

    try:
        with patch.object(cls, '_selected_waiter_locked', checked_projection):
            pools[0].reserve_flow_bundle(
                pools, 'tenant', flow, deadline=None, cancellation=None,
            )
        assert len(_live_flows(controllers)) == 2
    finally:
        for pool in reversed(pools):
            if flow in pool._physical_flow_claims:
                pool.release_flow(flow)
            pool.close()
        registry.close()


def test_contending_bundles_with_opposite_role_order_complete_and_release():
    from concurrent.futures import ThreadPoolExecutor
    from noetrium_platform.foundation.kernel.concurrency.api import Deadline
    registry, pools, controllers = _setup(replicas=2, per_replica=3, pool_count=2)

    def run(index):
        roles = pools if index % 2 else tuple(reversed(pools))
        flow = f'contending-bundle-{index}'
        try:
            roles[0].reserve_flow_bundle(
                roles, f'tenant-{index}', flow,
                deadline=Deadline.after(5), cancellation=None,
            )
            assert all(flow in pool._reserved_flows for pool in pools)
        finally:
            for pool in reversed(roles):
                if flow in pool._physical_flow_claims:
                    pool.release_flow(flow)

    try:
        with ThreadPoolExecutor(max_workers=8) as workers:
            futures = [workers.submit(run, index) for index in range(24)]
            for future in futures:
                future.result(timeout=8)
        assert not _live_flows(controllers)
        assert all(not pool._claiming_flows for pool in pools)
    finally:
        for pool in reversed(pools):
            pool.close()
        registry.close()
