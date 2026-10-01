from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
import time

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
    _reconcile_startup_ownership,
)


class Handle:
    def __init__(self, target, *args, **kwargs):
        self.error = None
        self.value = None
        self.thread = Thread(target=self._run, args=(target, args, kwargs), daemon=True)
        self.thread.start()

    @property
    def task_id(self): return "controller"
    @property
    def lane_kind(self): return "blocking-io"
    @property
    def state(self): return "running" if self.thread.is_alive() else "succeeded"
    def done(self): return not self.thread.is_alive()
    def cancel(self): return False

    def _run(self, target, args, kwargs):
        try: self.value = target(*args, **kwargs)
        except BaseException as exc: self.error = exc

    def result(self, timeout=None):
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise TimeoutError("controller did not stop")
        if self.error is not None:
            raise self.error
        return self.value


class Group:
    def __init__(self):
        self.submissions = []
        self.closed = False

    def submit(self, spec, fn, /, *args, **kwargs):
        self.submissions.append(spec.task_id)
        return Handle(
            fn,
            ExecutionContext("managed-test", "managed-test-trace", "managed-test-span"),
            *args,
            **kwargs,
        )

    def assert_healthy(self):
        return None


class Pool:
    def __init__(self):
        self.group_closed = False
        self.closed_groups = []
        self.orchestration_closed_groups = []
        self.control_closed_groups = []
        self.closed = False
        self.workloads_quiesced = False
        self.quiesce_error = None

    def quiesce_workloads(self, *, deadline=None):
        if self.quiesce_error is not None:
            raise self.quiesce_error
        self.workloads_quiesced = True

    def close_orchestration_group(self, group, *, cancel_pending=False, deadline=None):
        self.group_closed = True
        self.closed_groups.append(group)
        self.orchestration_closed_groups.append(group)
        group.closed = True

    def close_control_group(self, group, *, cancel_pending=False, deadline=None):
        self.group_closed = True
        self.closed_groups.append(group)
        self.control_closed_groups.append(group)
        group.closed = True

    def close(self, *, deadline=None):
        self.closed = True


class Controller:
    def __init__(self):
        self.started = Event()
        self.cycles = 0

    def run(self, *, interval_seconds, stop, max_cycles=None):
        self.started.set()
        while not stop.wait(interval_seconds):
            self.cycles += 1
        return {"cycles": self.cycles}


class Fleet:
    def __init__(self):
        self.removals = 0
        self.remove_error = None
        self.shutdowns = 0

    def remove_selected(self, selector):
        self.removals += 1
        if self.remove_error is not None:
            raise self.remove_error
        assert selector.tags == ("auto-managed",)
        return ()

    def shutdown_all(self):
        self.shutdowns += 1
        return ()

    def status_all(self):
        return ()


@dataclass
class Models:
    controller: Controller
    fleet: Fleet


@dataclass
class Management:
    models: Models


class Observability:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class ResourceController(Controller):
    def __init__(self):
        super().__init__()
        self.cleaned = 0

    def shutdown_cleanup(self):
        self.cleaned += 1
        return None


class RuntimeLock:
    def __init__(self):
        self.released = False

    def __exit__(self, exc_type, exc, tb):
        self.released = True


class OperationRuntime:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RecoveryExecution:
    def execution(self, owner_id, manifest_digest, *, ttl_seconds):
        raise AssertionError("fake recovery execution is not invoked in lifecycle tests")


def runtime():
    pool = Pool()
    group = Group()
    docker_group = Group()
    controller = Controller()
    fleet = Fleet()
    resource_controller = ResourceController()
    runtime_lock = RuntimeLock()
    observability = Observability()
    managed = ManagedResearchRuntime(
        execution_pool=pool,
        management=Management(Models(controller, fleet)),
        observability=observability,
        operation_runtime=OperationRuntime(),
        recovery_execution=RecoveryExecution(),
        services=object(),
        _orchestration_group=group,
        _docker_group=docker_group,
        _stop=Event(),
        resources=resource_controller,
        _runtime_lock=runtime_lock,
    )
    return (
        managed,
        pool,
        group,
        controller,
        resource_controller,
        fleet,
        runtime_lock,
    )


def test_managed_runtime_owns_background_controller_lifecycle() -> None:
    managed, pool, group, controller, resource_controller, fleet, runtime_lock = runtime()
    managed.start_background_controllers(
        model_reconcile_interval_seconds=0.01,
        resource_reconcile_interval_seconds=0.01,
    )
    assert controller.started.wait(1.0)
    assert resource_controller.started.wait(1.0)
    managed.start_background_controllers(
        model_reconcile_interval_seconds=0.01,
        resource_reconcile_interval_seconds=0.01,
    )
    assert group.submissions == [
        "managed-model-desired-state-controller",
        "managed-resource-reconciler",
    ]

    time.sleep(0.03)
    managed.assert_healthy()
    managed.close()

    assert pool.workloads_quiesced is True
    assert pool.group_closed is True
    assert len(pool.closed_groups) == 2
    assert len(pool.control_closed_groups) == 1
    assert len(pool.orchestration_closed_groups) == 1
    assert pool.closed is True
    assert group.closed is True
    assert managed.observability.closed is True
    assert controller.cycles >= 1
    assert resource_controller.cycles >= 1
    assert resource_controller.cleaned == 0
    assert fleet.removals == 0
    assert fleet.shutdowns == 0
    assert runtime_lock.released is True


def test_managed_runtime_close_is_idempotent() -> None:
    managed, pool, _group, _controller, _resource_controller, _fleet, _runtime_lock = runtime()
    managed.start_background_controllers(model_reconcile_interval_seconds=0.01)
    managed.close()
    managed.close()
    assert pool.closed is True


def test_managed_runtime_rejects_controller_restart_after_close() -> None:
    managed, _pool, _group, _controller, _resource_controller, _fleet, _runtime_lock = runtime()
    managed.close()
    try:
        managed.start_background_controllers()
    except RuntimeError as exc:
        assert "closed" in str(exc)
    else:
        raise AssertionError("closed managed runtime accepted controller start")


def test_public_product_entrypoint_remains_research_os_only() -> None:
    from noetrium import api

    assert callable(api.open_project)
    assert not hasattr(api, "ManagedResearchRuntime")


def test_managed_runtime_does_not_release_resources_when_workloads_fail_to_quiesce() -> None:
    (
        managed,
        pool,
        _group,
        _controller,
        resource_controller,
        fleet,
        runtime_lock,
    ) = runtime()
    pool.quiesce_error = TimeoutError("workloads still live")

    try:
        managed.close()
    except ExceptionGroup as error:
        assert any(
            isinstance(item, TimeoutError)
            for item in error.exceptions
        )
    else:
        raise AssertionError("workload quiesce failure was not surfaced")

    assert resource_controller.cleaned == 0
    assert fleet.removals == 0
    assert fleet.shutdowns == 0
    assert pool.closed is False
    assert runtime_lock.released is False

    pool.quiesce_error = None
    managed.close()
    assert resource_controller.cleaned == 0
    assert fleet.removals == 0
    assert fleet.shutdowns == 0
    assert pool.closed is True
    assert runtime_lock.released is True

def test_managed_runtime_close_never_retires_warm_model_or_resource_fabric() -> None:
    (
        managed,
        pool,
        _group,
        _controller,
        resource_controller,
        fleet,
        runtime_lock,
    ) = runtime()
    fleet.remove_error = RuntimeError("retirement must not be called by run close")

    managed.close()

    assert pool.workloads_quiesced is True
    assert fleet.removals == 0
    assert fleet.shutdowns == 0
    assert resource_controller.cleaned == 0
    assert pool.closed is True
    assert runtime_lock.released is True


def test_startup_ownership_barrier_observes_models_without_reclaiming_resources() -> None:
    events: list[str] = []

    class StartupFleet:
        def status_all(self):
            events.append("model-status")
            return ()

    class StartupResources:
        def reconcile(self):
            raise AssertionError(
                "generic resource reconciliation must wait for targeted adoption"
            )

    class StartupModels:
        fleet = StartupFleet()

    class StartupManagement:
        models = StartupModels()

    _reconcile_startup_ownership(StartupManagement(), StartupResources())

    assert events == ["model-status"]


def test_startup_ownership_barrier_never_reclaims_resources_after_model_observation_failure() -> None:
    events: list[str] = []

    class StartupFleet:
        def status_all(self):
            events.append("model-status")
            raise RuntimeError("model observation failed")

    class StartupResources:
        def reconcile(self):
            events.append("resources")
            raise AssertionError("resource takeover must remain fenced")

    class StartupModels:
        fleet = StartupFleet()

    class StartupManagement:
        models = StartupModels()

    try:
        _reconcile_startup_ownership(StartupManagement(), StartupResources())
    except RuntimeError as exc:
        assert "model observation failed" in str(exc)
    else:
        raise AssertionError("startup model observation failure was not surfaced")

    assert events == ["model-status"]



def _attach_test_fabric_consumer(managed, tmp_path, *, include_foreign=False):
    from types import SimpleNamespace

    from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
    from noetrium_platform.infrastructure.resources.lease.api import (
        ResourceIdentity,
        ResourceKind,
        ResourceLease,
        ResourceLeaseCardinality,
        ResourceOwner,
        ResourceOwnership,
    )
    from noetrium_platform.infrastructure.resources.lease.runtime import (
        ManualLeaseClock,
        ResourceLeaseRegistry,
    )

    registry = ResourceLeaseRegistry(
        tmp_path / "fabric-resource.sqlite3",
        clock=ManualLeaseClock(elapsed_seconds=1.0, wall_epoch_seconds=10.0),
    )
    resource = ResourceIdentity(ResourceKind.RUNTIME_FABRIC, "host-runtime-fabric")
    registry.register_owner(
        ResourceOwner(
            resource,
            PLATFORM_SCOPE,
            ResourceOwnership.SHARED,
            ResourceLeaseCardinality.MULTI_ACTIVE,
        )
    )
    own = registry.acquire(
        ResourceLease(
            "runtime-fabric-consumer:self",
            resource,
            PLATFORM_SCOPE,
            "runtime-fabric-consumer",
        ),
        ttl_seconds=120.0,
    )
    foreign = None
    if include_foreign:
        foreign = registry.acquire(
            ResourceLease(
                "runtime-fabric-consumer:foreign",
                resource,
                PLATFORM_SCOPE,
                "runtime-fabric-consumer",
            ),
            ttl_seconds=120.0,
        )

    class Guard:
        def __init__(self, row):
            self._row = row
            self.closed = False

        @property
        def rows(self):
            return (self._row,)

        def assert_healthy(self):
            return None

        def close(self):
            self.closed = True

    guard = Guard(own)
    managed.management.platform_meta = SimpleNamespace(
        resource_leases=registry,
        resource_ownership=registry,
    )
    managed._fabric_consumer_resource = resource
    managed._fabric_consumer_lease = own
    managed._fabric_consumer_guard = guard
    managed._fabric_coordination_lock_path = tmp_path / "runtime-fabric.lock"
    managed._fabric_consumer_released = False
    return registry, resource, own, foreign, guard


def test_normal_project_close_detaches_only_its_runtime_fabric_consumer(
    tmp_path,
) -> None:
    managed, pool, _group, _controller, resources, fleet, runtime_lock = runtime()
    registry, resource, own, foreign, guard = _attach_test_fabric_consumer(
        managed,
        tmp_path,
        include_foreign=True,
    )
    assert foreign is not None

    managed.close()

    active = registry.active_for(resource)
    assert tuple(row.lease_id for row in active) == (foreign.lease_id,)
    assert guard.closed is True
    assert pool.workloads_quiesced is True
    assert resources.cleaned == 0
    assert fleet.removals == 0
    assert fleet.shutdowns == 0
    assert runtime_lock.released is True

    registry.release(foreign.lease_id, fencing_token=foreign.fencing_token)


def test_terminal_runtime_fabric_retirement_refuses_foreign_consumer_without_side_effects(
    tmp_path,
) -> None:
    managed, pool, _group, _controller, resources, fleet, _lock = runtime()
    registry, resource, own, foreign, guard = _attach_test_fabric_consumer(
        managed,
        tmp_path,
        include_foreign=True,
    )

    try:
        managed.retire_runtime_fabric()
    except RuntimeError as exc:
        assert "active consumers" in str(exc)
    else:
        raise AssertionError("terminal retirement accepted a foreign Runtime Fabric consumer")

    assert managed._closing is False
    assert pool.workloads_quiesced is False
    assert resources.cleaned == 0
    assert fleet.removals == 0
    assert fleet.shutdowns == 0
    assert guard.closed is False
    assert set(registry.active_for(resource)) == {own, foreign}

    # Test cleanup: foreign consumer leaves, then ordinary close only detaches self.
    registry.release(foreign.lease_id, fencing_token=foreign.fencing_token)
    managed.close()
    assert registry.active_for(resource) == ()


def test_terminal_runtime_fabric_retirement_converges_after_zero_foreign_consumer(
    tmp_path,
) -> None:
    managed, pool, _group, _controller, resources, fleet, runtime_lock = runtime()
    registry, resource, own, foreign, guard = _attach_test_fabric_consumer(
        managed,
        tmp_path,
        include_foreign=False,
    )
    assert foreign is None

    managed.retire_runtime_fabric()

    assert guard.closed is True
    assert pool.workloads_quiesced is True
    assert resources.cleaned == 1
    assert fleet.removals == 1
    assert fleet.shutdowns == 1
    assert registry.active_for(resource) == ()
    assert registry.owner(resource).ownership.value == "shared"
    assert runtime_lock.released is True
    assert managed._closed is True
