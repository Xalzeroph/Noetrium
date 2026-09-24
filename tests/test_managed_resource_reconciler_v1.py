from __future__ import annotations

from dataclasses import dataclass

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
