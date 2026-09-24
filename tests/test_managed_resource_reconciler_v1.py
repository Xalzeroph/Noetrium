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
    def reconcile(self, *, now=None):
        return ()

    def active(self):
        return (Allocation("endpoint-live"),)


class ComputeShutdownAuthority:
    def reconcile_expired(self, *, now=None):
        return ()

    def allocations(self, *, scope=None):
        return (Allocation("compute-live"),)


def test_managed_resource_shutdown_fails_closed_on_live_endpoint_and_compute() -> None:
    reconciler = ManagedResourceReconciler(
        containers=ShutdownAuthority(
            DockerContainerReconciliation((), ()),
        ),
        environments=ShutdownAuthority(
            EnvironmentInstanceReconciliation((), ()),
        ),
        endpoints=EndpointShutdownAuthority(),
        compute=ComputeShutdownAuthority(),
    )

    with pytest.raises(ExceptionGroup) as captured:
        reconciler.shutdown_cleanup(now=1000.0)

    messages = tuple(str(exc) for exc in captured.value.exceptions)
    assert any("live endpoint allocations remain" in message for message in messages)
    assert any("live compute allocations remain" in message for message in messages)
