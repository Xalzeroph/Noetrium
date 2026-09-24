from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.composition.resource_lifecycle import ManagedResourceReconciler
from noetrium_platform.infrastructure.resources.container.api import (
    DockerContainerReconciliation,
)
from noetrium_platform.composition.environment_instance_leases import (
    EnvironmentInstanceReconciliation,
)


class Recorder:
    def __init__(self, name: str, events: list[str], result) -> None:
        self.name = name
        self.events = events
        self.result = result

    def reconcile(self, *, now=None):
        self.events.append(self.name)
        return self.result


class ComputeRecorder:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def reconcile_expired(self, *, now=None):
        self.events.append("compute")
        return ()


class Stop:
    def __init__(self) -> None:
        self.calls = 0

    def wait(self, timeout=None):
        self.calls += 1
        return True


def test_managed_resource_reconciler_orders_physical_before_logical_resources() -> None:
    events: list[str] = []
    reconciler = ManagedResourceReconciler(
        containers=Recorder(
            "containers",
            events,
            DockerContainerReconciliation((), ()),
        ),
        environments=Recorder(
            "environments",
            events,
            EnvironmentInstanceReconciliation((), ()),
        ),
        endpoints=Recorder("endpoints", events, ()),
        compute=ComputeRecorder(events),
    )

    report = reconciler.reconcile(now=1000.0)

    assert events == ["containers", "environments", "endpoints", "compute"]
    assert report.changed is False


def test_managed_resource_reconciler_runs_one_final_cycle_before_stop() -> None:
    events: list[str] = []
    reconciler = ManagedResourceReconciler(
        containers=Recorder(
            "containers",
            events,
            DockerContainerReconciliation((), ()),
        ),
        environments=Recorder(
            "environments",
            events,
            EnvironmentInstanceReconciliation((), ()),
        ),
        endpoints=Recorder("endpoints", events, ()),
        compute=ComputeRecorder(events),
    )

    report = reconciler.run(interval_seconds=0.01, stop=Stop())

    assert report.observed_at_epoch_s > 0
    assert events == ["containers", "environments", "endpoints", "compute"]


@dataclass(frozen=True)
class Allocation:
    allocation_id: str


class ShutdownAuthority:
    def __init__(self, result):
        self.result = result

    def reconcile(self, *, now=None):
        return self.result

    def shutdown_cleanup(self, *, now=None):
        return self.result


class EndpointShutdownAuthority:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.live = {"endpoint-live"}

    def reconcile(self, *, now=None):
        self.events.append("endpoint-reconcile")
        return ()

    def active(self):
        return tuple(Allocation(value) for value in sorted(self.live))

    def release(self, allocation_id):
        self.events.append(f"endpoint-release:{allocation_id}")
        self.live.remove(allocation_id)
        return Allocation(allocation_id)


class ComputeShutdownAuthority:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.live = {"compute-live"}

    def reconcile_expired(self, *, now=None):
        self.events.append("compute-reconcile")
        return ()

    def allocations(self, *, scope=None):
        return tuple(Allocation(value) for value in sorted(self.live))

    def release(self, allocation_id):
        self.events.append(f"compute-release:{allocation_id}")
        self.live.remove(allocation_id)
        return Allocation(allocation_id)


def test_managed_resource_shutdown_actively_reclaims_endpoint_and_compute() -> None:
    events: list[str] = []
    endpoints = EndpointShutdownAuthority(events)
    compute = ComputeShutdownAuthority(events)
    reconciler = ManagedResourceReconciler(
        containers=ShutdownAuthority(
            DockerContainerReconciliation((), ()),
        ),
        environments=ShutdownAuthority(
            EnvironmentInstanceReconciliation((), ()),
        ),
        endpoints=endpoints,
        compute=compute,
    )

    report = reconciler.shutdown_cleanup(now=1000.0)

    assert report.endpoints == (Allocation("endpoint-live"),)
    assert endpoints.active() == ()
    assert compute.allocations() == ()
    assert events == [
        "endpoint-reconcile",
        "endpoint-release:endpoint-live",
        "compute-reconcile",
        "compute-release:compute-live",
    ]


class FailingContainerShutdownAuthority(ShutdownAuthority):
    def shutdown_cleanup(self, *, now=None):
        raise RuntimeError("container physical removal failed")


class NeverCalledShutdownAuthority:
    def __init__(self) -> None:
        self.called = False

    def shutdown_cleanup(self, *, now=None):
        self.called = True
        raise AssertionError("later cleanup stage must remain fenced")

    def reconcile(self, *, now=None):
        self.called = True
        raise AssertionError("later reconcile stage must remain fenced")


def test_managed_resource_shutdown_stops_at_first_unproven_dependency_stage() -> None:
    environment = NeverCalledShutdownAuthority()
    endpoints = NeverCalledShutdownAuthority()
    compute = NeverCalledShutdownAuthority()
    reconciler = ManagedResourceReconciler(
        containers=FailingContainerShutdownAuthority(
            DockerContainerReconciliation((), ()),
        ),
        environments=environment,
        endpoints=endpoints,
        compute=compute,
    )

    with pytest.raises(ExceptionGroup, match="container cleanup"):
        reconciler.shutdown_cleanup(now=1000.0)

    assert environment.called is False
    assert endpoints.called is False
    assert compute.called is False
