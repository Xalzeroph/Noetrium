from __future__ import annotations

import pytest

from noetrium_platform.infrastructure.resources.container.api import (
    DockerContainerLeasePolicy,
    DockerContainerObservation,
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
)
from noetrium_platform.infrastructure.resources.container.runtime import (
    DockerContainerLeaseAuthority,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    InMemoryResourceLeaseRegistry,
)


class FakeDockerRuntime:
    docker_executable = "docker"

    def __init__(self) -> None:
        self.rows: dict[str, DockerContainerObservation] = {}
        self.events: list[str] = []

    def start(self, handle) -> DockerContainerObservation:
        row = DockerContainerObservation(
            container_id=f"cid-{handle.lease.fencing_token}",
            name=handle.container_name,
            image=handle.image,
            running=True,
            labels=dict(handle.labels),
        )
        self.rows[row.container_id] = row
        return row

    def inspect(self, reference: str):
        for row in self.rows.values():
            if reference in {row.container_id, row.name}:
                return row
        return None

    def list_managed(self):
        return tuple(
            sorted(
                (
                    row
                    for row in self.rows.values()
                    if row.labels.get(MANAGED_CONTAINER_LABEL)
                    == MANAGED_CONTAINER_LABEL_VALUE
                ),
                key=lambda row: row.container_id,
            )
        )

    def wait_running(self, reference: str, *, timeout_seconds: float = 10.0):
        del timeout_seconds
        row = self.inspect(reference)
        if row is None or not row.running:
            raise RuntimeError("container is not running")
        return row

    def remove(self, reference: str, *, force: bool = True) -> None:
        assert force
        row = self.inspect(reference)
        if row is None:
            return
        self.events.append(f"remove:{row.container_id}")
        self.rows.pop(row.container_id, None)


def _authority(resources, runtime):
    return DockerContainerLeaseAuthority(
        ownership=resources,
        leases=resources,
        runtime=runtime,
        policy=DockerContainerLeasePolicy(
            ttl_seconds=0.2,
            renewal_interval_seconds=0.05,
        ),
        reconcile_on_start=False,
    )


def _reserve(authority, allocation_id: str = "worker-a"):
    return authority.reserve(
        allocation_id=allocation_id,
        holder_scope=PLATFORM_SCOPE,
        image="noetrium-env-text:sha256",
        runtime_identity_digest="a" * 64,
    )


def test_managed_docker_release_removes_physical_container_before_logical_lease() -> None:
    resources = InMemoryResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    prefix = authority.docker_run_prefix(handle)
    assert prefix[:3] == ("docker", "run", "--rm")
    assert "--name" in prefix
    assert "--label" in prefix
    runtime.start(handle)
    observed = authority.confirm_running(handle)
    assert observed.name == handle.container_name
    resource = ResourceIdentity(ResourceKind.CONTAINER, handle.allocation_id)
    assert resources.active_for(resource) == (handle.lease,)

    released = authority.release(handle)

    assert runtime.rows == {}
    assert runtime.events == [f"remove:{observed.container_id}"]
    assert released.state is LeaseState.RELEASED
    assert resources.active_for(resource) == ()


def test_managed_docker_crash_expiry_removes_orphan_on_reconcile() -> None:
    resources = InMemoryResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    observed = runtime.start(handle)
    assert handle.lease.expires_at_epoch_s is not None

    report = authority.reconcile(now=handle.lease.expires_at_epoch_s + 1.0)

    assert report.removed_container_ids == (observed.container_id,)
    assert runtime.rows == {}
    assert resources.get(
        handle.lease.lease_id,
        now=handle.lease.expires_at_epoch_s + 1.0,
    ).state is LeaseState.EXPIRED


def test_managed_docker_restart_before_ttl_adopts_exact_generation_without_split_brain() -> None:
    resources = InMemoryResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    first = _authority(resources, runtime)
    handle = _reserve(first)
    observed = runtime.start(handle)

    restarted = _authority(resources, runtime)
    adopted = _reserve(restarted)

    assert adopted == handle
    assert runtime.inspect(observed.container_id) == observed
    assert len(runtime.rows) == 1
    assert resources.active_for(
        ResourceIdentity(ResourceKind.CONTAINER, handle.allocation_id)
    ) == (handle.lease,)


def test_managed_docker_expired_generation_can_be_replaced_with_higher_fence() -> None:
    resources = InMemoryResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    first = _reserve(authority)
    old = runtime.start(first)
    assert first.lease.expires_at_epoch_s is not None
    authority.reconcile(now=first.lease.expires_at_epoch_s + 1.0)
    assert runtime.inspect(old.container_id) is None

    second = _reserve(authority)
    assert second.lease.fencing_token > first.lease.fencing_token
    assert second.container_name != first.container_name


def test_managed_docker_reconcile_removes_malformed_noetrium_container() -> None:
    resources = InMemoryResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    runtime.rows["malformed"] = DockerContainerObservation(
        "malformed",
        "noetrium-malformed",
        "noetrium-env-text:sha256",
        True,
        {MANAGED_CONTAINER_LABEL: MANAGED_CONTAINER_LABEL_VALUE},
    )
    authority = _authority(resources, runtime)

    report = authority.reconcile()

    assert report.removed_container_ids == ("malformed",)
    assert runtime.rows == {}


def test_managed_docker_stopped_live_generation_is_reaped_and_fence_advances() -> None:
    resources = InMemoryResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    first = _reserve(authority)
    observed = runtime.start(first)
    runtime.rows[observed.container_id] = DockerContainerObservation(
        observed.container_id,
        observed.name,
        observed.image,
        False,
        observed.labels,
    )

    report = authority.reconcile()
    assert report.removed_container_ids == (observed.container_id,)
    assert report.released_lease_ids == (first.lease.lease_id,)
    assert runtime.rows == {}

    second = _reserve(authority)
    assert second.lease.fencing_token > first.lease.fencing_token
    assert second.container_name != first.container_name
