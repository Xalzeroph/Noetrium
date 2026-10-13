"""Method lifetime capacity belongs to endpoint Authorities, not Method wrappers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Condition, Lock
import time

import pytest

from noetrium_platform.research.execution.workflow.api import (
    method_lifetime_resources,
)
from noetrium_platform.research.execution.workflow.composition import (
    MethodAgentLoopRouter,
)


class _CapacityDomain:
    def __init__(self) -> None:
        self.condition = Condition(Lock())
        self.owner: str | None = None

    def reserve(self, lifetime_id: str) -> None:
        with self.condition:
            assert self.condition.wait_for(
                lambda: self.owner is None, timeout=2.0
            ), "cyclic Method lifetime reservation"
            self.owner = lifetime_id

    def release(self, lifetime_id: str) -> None:
        with self.condition:
            assert self.owner == lifetime_id
            self.owner = None
            self.condition.notify_all()


class _Leaf:
    def __init__(self, domain: _CapacityDomain, digest: str) -> None:
        self.domain = domain
        self.identity_digest = digest

    def run(self, request):
        raise AssertionError("execution is unrelated to lifetime reservation")

    def lifetime_resource_ports(self):
        return ((self.domain, self),)

    def reserve_lifetime(self, lifetime_id, context, control):
        self.domain.reserve(lifetime_id)

    def release_lifetime(self, lifetime_id):
        self.domain.release(lifetime_id)


class _PassiveLoop:
    identity_digest = "d" * 64

    def run(self, request):
        raise AssertionError("passive Method not executed in resource test")


def test_nested_router_flattens_deduplicates_and_orders_physical_domains():
    first = _CapacityDomain()
    second = _CapacityDomain()
    a = _Leaf(first, "a" * 64)
    shared = _Leaf(first, "b" * 64)
    b = _Leaf(second, "c" * 64)
    forward = MethodAgentLoopRouter({"z": a, "a": b, "passive": _PassiveLoop()})
    reverse = MethodAgentLoopRouter({"z": b, "a": shared})
    expected = tuple(
        leaf for _, leaf in sorted(((id(first), a), (id(second), b)))
    )
    assert method_lifetime_resources((forward, reverse)) == expected
    assert method_lifetime_resources((reverse, forward)) == expected
    assert len(forward.lifetime_resource_ports()) == 2


def test_oppositely_ordered_method_routers_cannot_deadlock_across_endpoints():
    a = _CapacityDomain()
    b = _CapacityDomain()
    first = MethodAgentLoopRouter({"a": _Leaf(a, "1" * 64), "b": _Leaf(b, "2" * 64)})
    second = MethodAgentLoopRouter({"a": _Leaf(b, "3" * 64), "b": _Leaf(a, "4" * 64)})

    def execute(router, lifetime):
        acquired = []
        for leaf in method_lifetime_resources((router,)):
            leaf.reserve_lifetime(lifetime, None, None)
            acquired.append(leaf)
        try:
            time.sleep(0.01)
            return len(acquired)
        finally:
            for leaf in reversed(acquired):
                leaf.release_lifetime(lifetime)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_run = executor.submit(execute, first, "life-1")
        second_run = executor.submit(execute, second, "life-2")
        assert first_run.result(timeout=2) == 2
        assert second_run.result(timeout=2) == 2
    assert a.owner is None and b.owner is None


def test_router_rejects_unflattenable_lifetime_port_instead_of_skipping_it():
    class _BrokenLoop(_PassiveLoop):
        def reserve_lifetime(self, lifetime_id, context, control):
            raise AssertionError("unreachable")

        def release_lifetime(self, lifetime_id):
            raise AssertionError("unreachable")

    with pytest.raises(TypeError, match="Authority claims"):
        MethodAgentLoopRouter({"broken": _BrokenLoop()})
