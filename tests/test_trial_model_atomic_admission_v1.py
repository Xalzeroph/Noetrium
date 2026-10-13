"""Regression: the Trial boundary must not hold a partial model role bundle."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import sleep
from types import SimpleNamespace

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.research.execution.workflow.composition import (
    MethodModelAgentLoop,
    reserve_method_lifetime_resources,
)
from tests.test_model_atomic_lifetime_bundle_v1 import _setup, _live_flows


class _Control:
    cancelled = False
    reason = None

    def __init__(self, deadline=None):
        self.deadline = deadline

    def checkpoint(self):
        return None

    def wait(self, *_args):
        return False


def _resources(pools):
    resources = []
    for pool in pools:
        loop = object.__new__(MethodModelAgentLoop)
        loop.pool = pool
        resources.append(loop)
    return tuple(resources)


def test_trial_reserves_all_shared_deployment_model_roles_atomically(monkeypatch):
    from noetrium_platform.research.execution.workflow.composition import model_agent

    monkeypatch.setattr(model_agent, "model_execution_owner_id", lambda _: "demo-tenant")
    monkeypatch.setattr(model_agent, "model_lifetime_flow_id", lambda identity: identity)
    registry, pools, controllers = _setup(
        replicas=1, per_replica=2, pool_count=2,
    )
    resources = _resources(pools)
    reserve_method_lifetime_resources(
        resources, "trial-first", SimpleNamespace(), _Control(),
    )
    assert len(tuple(flow for flow in _live_flows(controllers)
                     if flow.startswith("trial-first:role:"))) == 2

    with pytest.raises(TimeoutError, match="deadline expired"):
        reserve_method_lifetime_resources(
            resources, "trial-second", SimpleNamespace(),
            _Control(Deadline.after(0.12)),
        )
    assert not any(flow.startswith("trial-second:")
                   for flow in _live_flows(controllers))

    for resource in reversed(resources):
        resource.release_lifetime("trial-first")
    reserve_method_lifetime_resources(
        resources, "trial-second", SimpleNamespace(), _Control(),
    )
    assert len(tuple(flow for flow in _live_flows(controllers)
                     if flow.startswith("trial-second:role:"))) == 2
    for resource in reversed(resources):
        resource.release_lifetime("trial-second")
    for pool in pools:
        pool.close()
    assert not _live_flows(controllers)
    registry.close()


def test_trial_concurrent_contenders_cannot_hold_partial_bundle(monkeypatch):
    from noetrium_platform.research.execution.workflow.composition import model_agent

    monkeypatch.setattr(model_agent, "model_execution_owner_id", lambda _: "demo-tenant")
    monkeypatch.setattr(model_agent, "model_lifetime_flow_id", lambda identity: identity)
    registry, pools, controllers = _setup(
        replicas=1, per_replica=2, pool_count=2,
    )
    resources = _resources(pools)
    first_ready = Event()
    first_release = Event()

    def first():
        reserve_method_lifetime_resources(
            resources, "trial-first", SimpleNamespace(), _Control(),
        )
        first_ready.set()
        assert first_release.wait(5)
        for resource in reversed(resources):
            resource.release_lifetime("trial-first")

    def second():
        assert first_ready.wait(5)
        reserve_method_lifetime_resources(
            resources, "trial-second", SimpleNamespace(),
            _Control(Deadline.after(5)),
        )
        try:
            return tuple(flow for flow in _live_flows(controllers)
                         if flow.startswith("trial-second:role:"))
        finally:
            for resource in reversed(resources):
                resource.release_lifetime("trial-second")

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(first)
        b = executor.submit(second)
        assert first_ready.wait(5)
        sleep(0.09)
        assert not b.done()
        assert not any(flow.startswith("trial-second:")
                       for flow in _live_flows(controllers))
        first_release.set()
        assert len(b.result(timeout=5)) == 2
        a.result(timeout=5)
    assert not _live_flows(controllers)
    for pool in pools:
        pool.close()
    registry.close()
