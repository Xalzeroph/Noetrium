from __future__ import annotations

from tests.resource_lease_support import TestResourceLeaseRegistry

import json
from pathlib import Path
import pytest

from noetrium_platform.infrastructure.resources.container.api import (
    DockerContainerLeasePolicy,
    DockerContainerObservation,
    LABEL_AUTHORITY,
    LABEL_OWNER_GENERATION,
    MANAGED_CONTAINER_LABEL,
    MANAGED_CONTAINER_LABEL_VALUE,
)
from noetrium_platform.infrastructure.resources.container.runtime import (
    DockerContainerLeaseAuthority,
)
from noetrium_platform.infrastructure.resources.container.providers import (
    DockerCliManagedContainerProvider,
    DockerContainerRuntimeError,
    discover_docker_root,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
)
from noetrium_platform.infrastructure.resources.lease.runtime import (
    ManualLeaseClock,
)


class FakeDockerRuntime:
    docker_executable = "docker"

    def __init__(
        self,
        authority_id: str = "1" * 64,
        *,
        rows: dict[str, DockerContainerObservation] | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.authority_id = authority_id
        self.rows = {} if rows is None else rows
        self.events = [] if events is None else events

    def assert_expansion_admissible(self) -> None:
        return None

    def start(self, handle) -> DockerContainerObservation:
        row = DockerContainerObservation(
            container_id=f"cid-{handle.container_name}",
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
                    and row.labels.get(LABEL_AUTHORITY) == self.authority_id
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


def _authority(resources, runtime, *, owner_generation_id: str = "2" * 64):
    return DockerContainerLeaseAuthority(
        ownership=resources,
        leases=resources,
        runtime=runtime,
        authority_id=runtime.authority_id,
        owner_generation_id=owner_generation_id,
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
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    prefix = authority.docker_run_prefix(handle)
    assert prefix[:3] == ("docker", "run", "--rm")
    assert "--name" in prefix
    assert "--label" in prefix
    assert "--cpu-shares" not in prefix
    assert "--blkio-weight" not in prefix
    assert "--oom-score-adj" not in prefix
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


def test_managed_docker_release_follows_exact_generation_after_external_rename() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    observed = runtime.start(handle)
    renamed = DockerContainerObservation(
        observed.container_id,
        "externally-renamed-container",
        observed.image,
        observed.running,
        observed.labels,
    )
    runtime.rows[observed.container_id] = renamed

    released = authority.release(handle)

    assert released.state is LeaseState.RELEASED
    assert runtime.inspect(observed.container_id) is None
    assert runtime.events == [f"remove:{observed.container_id}"]


def test_managed_docker_release_ignores_reused_name_when_exact_generation_was_renamed() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    observed = runtime.start(handle)
    runtime.rows[observed.container_id] = DockerContainerObservation(
        observed.container_id,
        "externally-renamed-container",
        observed.image,
        observed.running,
        observed.labels,
    )
    foreign_labels = dict(handle.labels)
    foreign_labels[LABEL_OWNER_GENERATION] = "f" * 64
    foreign = DockerContainerObservation(
        "foreign-container",
        handle.container_name,
        handle.image,
        True,
        foreign_labels,
    )
    runtime.rows[foreign.container_id] = foreign

    released = authority.release(handle)

    assert released.state is LeaseState.RELEASED
    assert runtime.inspect(observed.container_id) is None
    assert runtime.inspect(foreign.container_id) == foreign
    assert runtime.events == [f"remove:{observed.container_id}"]


def test_managed_docker_crash_expiry_removes_orphan_on_reconcile() -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    resources = TestResourceLeaseRegistry(clock=clock)
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    observed = runtime.start(handle)
    assert handle.lease.expires_at_epoch_s is not None

    clock.advance(1.0)
    report = authority.reconcile()

    assert report.removed_container_ids == (observed.container_id,)
    assert runtime.rows == {}
    assert resources.get(handle.lease.lease_id).state is LeaseState.EXPIRED


def test_managed_docker_restart_quarantines_old_generation_until_exclusive_recovery() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    first = _authority(resources, runtime, owner_generation_id="2" * 64)
    first_handle = _reserve(first)
    old = runtime.start(first_handle)

    restarted = _authority(resources, runtime, owner_generation_id="3" * 64)
    report = restarted.reconcile()
    assert report.removed_container_ids == ()
    assert report.released_lease_ids == ()
    assert report.quarantined_container_ids == (old.container_id,)
    assert runtime.inspect(old.container_id) == old

    with pytest.raises(
        RuntimeError,
        match="quarantined by another owner generation",
    ):
        _reserve(restarted)

    # ManagedResearchRuntime calls this only while holding its outer
    # interprocess lock. That exclusive proof is what makes takeover safe.
    recovered = restarted.shutdown_cleanup()
    assert recovered.removed_container_ids == (old.container_id,)
    assert recovered.released_lease_ids == (first_handle.lease.lease_id,)
    assert runtime.inspect(old.container_id) is None

    replacement = _reserve(restarted)
    assert replacement.owner_generation_id == "3" * 64
    assert replacement.lease.fencing_token > first_handle.lease.fencing_token
    assert replacement.container_name != first_handle.container_name


def test_managed_docker_expired_generation_can_be_replaced_with_higher_fence() -> None:
    clock = ManualLeaseClock(
        elapsed_seconds=1.0,
        wall_epoch_seconds=100.0,
    )
    resources = TestResourceLeaseRegistry(clock=clock)
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    first = _reserve(authority)
    old = runtime.start(first)
    assert first.lease.expires_at_epoch_s is not None

    clock.advance(1.0)
    authority.reconcile()
    assert runtime.inspect(old.container_id) is None

    second = _reserve(authority)
    assert second.lease.fencing_token > first.lease.fencing_token
    assert second.container_name != first.container_name


def test_managed_docker_reconcile_removes_malformed_noetrium_container() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    runtime.rows["malformed"] = DockerContainerObservation(
        "malformed",
        "noetrium-malformed",
        "noetrium-env-text:sha256",
        True,
        {
            MANAGED_CONTAINER_LABEL: MANAGED_CONTAINER_LABEL_VALUE,
            LABEL_AUTHORITY: runtime.authority_id,
            LABEL_OWNER_GENERATION: "2" * 64,
        },
    )
    authority = _authority(resources, runtime)

    report = authority.reconcile()

    assert report.removed_container_ids == ("malformed",)
    assert runtime.rows == {}


def test_managed_docker_unknown_owner_generation_is_quarantined_until_exclusive_cleanup() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    unknown = DockerContainerObservation(
        "unknown-generation",
        "noetrium-unknown-generation",
        "noetrium-env-text:sha256",
        True,
        {
            MANAGED_CONTAINER_LABEL: MANAGED_CONTAINER_LABEL_VALUE,
            LABEL_AUTHORITY: runtime.authority_id,
        },
    )
    runtime.rows[unknown.container_id] = unknown
    authority = _authority(resources, runtime)

    report = authority.reconcile()
    assert report.removed_container_ids == ()
    assert report.quarantined_container_ids == (unknown.container_id,)
    assert runtime.inspect(unknown.container_id) == unknown

    exclusive = authority.shutdown_cleanup()
    assert exclusive.removed_container_ids == (unknown.container_id,)
    assert runtime.inspect(unknown.container_id) is None


def test_managed_docker_stopped_live_generation_is_reaped_and_fence_advances() -> None:
    resources = TestResourceLeaseRegistry()
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


def test_managed_docker_shutdown_cleanup_releases_prestart_lease() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    resource = ResourceIdentity(ResourceKind.CONTAINER, handle.allocation_id)

    report = authority.shutdown_cleanup()

    assert report.removed_container_ids == ()
    assert report.released_lease_ids == (handle.lease.lease_id,)
    assert resources.active_for(resource) == ()


def test_managed_docker_shutdown_cleanup_removes_physical_before_releasing() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    observed = runtime.start(handle)

    report = authority.shutdown_cleanup()

    assert report.removed_container_ids == (observed.container_id,)
    assert report.released_lease_ids == (handle.lease.lease_id,)
    assert runtime.events == [f"remove:{observed.container_id}"]
    assert resources.get(handle.lease.lease_id).state is LeaseState.RELEASED


def test_managed_docker_authority_namespace_isolates_shared_daemon() -> None:
    rows: dict[str, DockerContainerObservation] = {}
    events: list[str] = []
    left_resources = TestResourceLeaseRegistry()
    right_resources = TestResourceLeaseRegistry()
    left_runtime = FakeDockerRuntime("a" * 64, rows=rows, events=events)
    right_runtime = FakeDockerRuntime("b" * 64, rows=rows, events=events)
    left = _authority(left_resources, left_runtime)
    right = _authority(right_resources, right_runtime)

    left_handle = _reserve(left, "worker")
    right_handle = _reserve(right, "worker")
    left_observed = left_runtime.start(left_handle)
    right_observed = right_runtime.start(right_handle)

    assert left_handle.container_name != right_handle.container_name
    assert len(rows) == 2

    left_report = left.reconcile()
    assert left_report.removed_container_ids == ()
    assert right_runtime.inspect(right_observed.container_id) == right_observed

    left_cleanup = left.shutdown_cleanup()
    assert left_cleanup.removed_container_ids == (left_observed.container_id,)
    assert right_runtime.inspect(right_observed.container_id) == right_observed
    assert len(rows) == 1


def test_managed_docker_live_current_generation_cannot_be_double_started() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    runtime.start(handle)

    with pytest.raises(RuntimeError, match="already has a live container"):
        _reserve(authority)

    assert len(runtime.rows) == 1



def test_managed_docker_release_refuses_reused_foreign_container_name() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)

    foreign_labels = dict(handle.labels)
    foreign_labels[LABEL_OWNER_GENERATION] = "f" * 64
    foreign = DockerContainerObservation(
        "foreign-container",
        handle.container_name,
        handle.image,
        True,
        foreign_labels,
    )
    runtime.rows[foreign.container_id] = foreign

    with pytest.raises(RuntimeError, match="name was reused|label drift"):
        authority.release(handle)

    assert runtime.inspect(foreign.container_id) == foreign
    current = resources.get(handle.lease.lease_id)
    assert current.state is LeaseState.ACTIVE
    assert current.fencing_token == handle.lease.fencing_token


def test_new_docker_owner_generation_cannot_close_old_generation_handle() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    old_authority = _authority(
        resources,
        runtime,
        owner_generation_id="2" * 64,
    )
    old_handle = _reserve(old_authority)
    old_container = runtime.start(old_handle)

    new_authority = _authority(
        resources,
        runtime,
        owner_generation_id="3" * 64,
    )
    with pytest.raises(RuntimeError, match="stale owner generation"):
        new_authority.release(old_handle)

    assert runtime.inspect(old_container.container_id) == old_container
    assert resources.get(old_handle.lease.lease_id).state is LeaseState.ACTIVE



class _DockerCommandResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _AmbiguousRemoveRunner:
    def __init__(self, *, observable_after_remove: bool = True) -> None:
        self.present = True
        self.observable_after_remove = observable_after_remove
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...], *, timeout_seconds: float):
        del timeout_seconds
        self.calls.append(argv)
        action = argv[1]
        if action == "inspect":
            if not self.observable_after_remove and not self.present:
                return _DockerCommandResult(
                    1,
                    stderr="Cannot connect to the Docker daemon",
                )
            if not self.present:
                return _DockerCommandResult(
                    1,
                    stderr="Error: No such container: cid-ambiguous",
                )
            return _DockerCommandResult(
                0,
                json.dumps(
                    [
                        {
                            "Id": "cid-ambiguous",
                            "Name": "/noetrium-ambiguous",
                            "Config": {
                                "Image": "image:exact",
                                "Labels": {
                                    MANAGED_CONTAINER_LABEL:
                                        MANAGED_CONTAINER_LABEL_VALUE,
                                    LABEL_AUTHORITY: "1" * 64,
                                },
                            },
                            "State": {"Running": True},
                        }
                    ]
                ),
            )
        if action == "rm":
            self.present = False
            return _DockerCommandResult(
                125,
                stderr="daemon connection reset after request commit",
            )
        raise AssertionError(f"unexpected Docker command: {argv}")


def test_docker_provider_accepts_only_proven_absence_after_ambiguous_remove_ack() -> None:
    runner = _AmbiguousRemoveRunner()
    provider = DockerCliManagedContainerProvider(
        runner,
        runner,
        authority_id="1" * 64,
    )

    provider.remove("cid-ambiguous")

    assert runner.present is False
    assert [call[1] for call in runner.calls] == ["inspect", "rm", "inspect"]


def test_docker_provider_keeps_ambiguous_remove_fail_closed_when_daemon_unobservable() -> None:
    runner = _AmbiguousRemoveRunner(observable_after_remove=False)
    provider = DockerCliManagedContainerProvider(
        runner,
        runner,
        authority_id="1" * 64,
    )

    with pytest.raises(
        DockerContainerRuntimeError,
        match="removal outcome is unobservable",
    ):
        provider.remove("cid-ambiguous")

    assert runner.present is False
    assert [call[1] for call in runner.calls] == ["inspect", "rm", "inspect"]


class _UnavailableDockerRuntime(FakeDockerRuntime):
    def list_managed(self):
        raise RuntimeError("Docker daemon restarted during reconcile")


def test_managed_docker_daemon_restart_during_reconcile_preserves_lease_authority() -> None:
    resources = TestResourceLeaseRegistry()
    runtime = FakeDockerRuntime()
    authority = _authority(resources, runtime)
    handle = _reserve(authority)
    observed = runtime.start(handle)
    authority.runtime = _UnavailableDockerRuntime(
        runtime.authority_id,
        rows=runtime.rows,
        events=runtime.events,
    )

    with pytest.raises(RuntimeError, match="daemon restarted"):
        authority.reconcile()

    assert runtime.inspect(observed.container_id) == observed
    current = resources.get(handle.lease.lease_id)
    assert current.state is LeaseState.ACTIVE
    assert current.fencing_token == handle.lease.fencing_token


class _DockerInfoRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "/var/lib/docker\n") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def run(self, argv: tuple[str, ...], *, timeout_seconds: float):
        from types import SimpleNamespace

        self.calls.append((argv, timeout_seconds))
        return SimpleNamespace(
            returncode=self.returncode,
            stdout=self.stdout,
            stderr="",
        )


def test_docker_provider_separates_recovery_control_from_expansion_admission() -> None:
    control = _AmbiguousRemoveRunner()
    expansion = _DockerInfoRunner()
    provider = DockerCliManagedContainerProvider(
        control,
        expansion,
        authority_id="1" * 64,
    )

    provider.remove("cid-ambiguous")
    assert [call[1] for call in control.calls] == ["inspect", "rm", "inspect"]
    assert expansion.calls == []

    provider.assert_expansion_admissible()
    assert expansion.calls == [
        (("docker", "info", "--format", "{{.DockerRootDir}}"), 15.0)
    ]


def test_discover_docker_root_uses_runtime_authority_path() -> None:
    runner = _DockerInfoRunner()
    assert discover_docker_root(runner) == Path("/var/lib/docker")
    assert runner.calls == [
        (("docker", "info", "--format", "{{.DockerRootDir}}"), 15.0)
    ]


def test_discover_docker_root_is_best_effort_for_unavailable_daemon() -> None:
    assert discover_docker_root(_DockerInfoRunner(returncode=1)) is None


def test_discover_docker_root_rejects_non_absolute_daemon_path() -> None:
    assert discover_docker_root(_DockerInfoRunner(stdout="relative/docker\n")) is None
