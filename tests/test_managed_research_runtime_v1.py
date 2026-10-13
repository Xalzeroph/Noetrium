from __future__ import annotations

from types import SimpleNamespace
from threading import Event, Thread

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.scope.api.contracts import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
from noetrium_platform.infrastructure.resources.authority.api import lease_field
from noetrium_platform.composition.managed_research_runtime import ManagedResearchRuntime


class Handle:
    def __init__(self, target):
        self.error = None
        self.value = None
        self.thread = Thread(target=self._run, args=(target,), daemon=True)
        self.thread.start()

    def _run(self, target):
        try:
            self.value = target(
                ExecutionContext("managed-test", "managed-test-trace", "managed-test-span")
            )
        except BaseException as exc:
            self.error = exc

    def done(self):
        return not self.thread.is_alive()

    def result(self, timeout=None):
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise TimeoutError("controller did not stop")
        if self.error is not None:
            raise self.error
        return self.value

    def cancel(self):
        return False


class Group:
    def __init__(self):
        self.submissions = []
        self.closed = False

    def submit(self, spec, fn, /, *args, **kwargs):
        self.submissions.append(spec.task_id)
        return Handle(lambda context: fn(context, *args, **kwargs))

    def assert_healthy(self):
        return None


class Pool:
    owner_generation_id = "managed-test-generation"

    def __init__(self):
        self.workloads_quiesced = False
        self.closed = False
        self.control_closed = False
        self.orchestration_closed = False

    def quiesce_workloads(self, *, deadline=None):
        self.workloads_quiesced = True

    def close_control_group(self, group, *, cancel_pending=False, deadline=None):
        group.closed = True
        self.control_closed = True

    def close_orchestration_group(self, group, *, cancel_pending=False, deadline=None):
        group.closed = True
        self.orchestration_closed = True

    def close(self, *, deadline=None):
        self.closed = True


class ModelController:
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
        self.shutdowns = 0

    def remove_selected(self, selector):
        assert selector.tags == ("auto-managed",)
        self.removals += 1
        return ()

    def shutdown_all(self):
        self.shutdowns += 1
        return ()


class Closeable:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class RuntimeLock:
    def __init__(self):
        self.released = False

    def __exit__(self, exc_type, exc, tb):
        self.released = True


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


def runtime(tmp_path):
    pool = Pool()
    group = Group()
    docker_group = Group()
    controller = ModelController()
    fleet = Fleet()
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    management = SimpleNamespace(
        platform_meta=SimpleNamespace(resource_authority=authority),
        models=SimpleNamespace(controller=controller, fleet=fleet),
    )
    observability = Closeable()
    operation_runtime = Closeable()
    lock = RuntimeLock()
    managed = ManagedResearchRuntime(
        execution_pool=pool,
        management=management,
        observability=observability,
        operation_runtime=operation_runtime,
        recovery_execution=object(),
        services=object(),
        _orchestration_group=group,
        _docker_group=docker_group,
        _runtime_lock=lock,
    )
    return managed, authority, pool, group, controller, fleet, observability, operation_runtime, lock


def attach_consumer(managed, authority, tmp_path, *, foreign=False):
    resource = "runtime-fabric:host-runtime-fabric"
    own = authority.acquire_ttl_lease(
        lease_id="runtime-fabric-consumer:self",
        resource_key=resource,
        holder_key="platform:self",
        owner_scope=PLATFORM_SCOPE,
        ttl_seconds=120.0,
        metadata={"kind": "runtime-fabric-consumer"},
    )
    other = None
    if foreign:
        other = authority.acquire_ttl_lease(
            lease_id="runtime-fabric-consumer:foreign",
            resource_key=resource,
            holder_key="platform:foreign",
            owner_scope=PLATFORM_SCOPE,
            ttl_seconds=120.0,
            metadata={"kind": "runtime-fabric-consumer"},
        )
    guard = Guard(own)
    managed._fabric_consumer_resource = resource
    managed._fabric_consumer_lease = own
    managed._fabric_consumer_guard = guard
    managed._fabric_coordination_lock_path = tmp_path / "runtime-fabric.lock"
    managed._fabric_consumer_released = False
    return resource, own, other, guard


def test_close_is_idempotent_and_never_retires_durable_fabric(tmp_path):
    managed, authority, pool, _group, _controller, fleet, observability, operation_runtime, lock = runtime(tmp_path)
    resource, own, foreign, guard = attach_consumer(
        managed, authority, tmp_path, foreign=True
    )
    managed.close()
    managed.close()
    active = authority.active_leases(resource)
    assert tuple(str(lease_field(row, "lease_id")) for row in active) == (str(lease_field(foreign, "lease_id")),)
    assert guard.closed is True
    assert pool.workloads_quiesced is True
    assert pool.closed is True
    assert fleet.removals == 0
    assert fleet.shutdowns == 0
    assert observability.closed and operation_runtime.closed
    assert lock.released is True
    authority.release_lease(foreign)


def test_terminal_retirement_refuses_foreign_runtime_fabric_consumer(tmp_path):
    managed, authority, pool, *_ = runtime(tmp_path)
    resource, own, foreign, guard = attach_consumer(
        managed, authority, tmp_path, foreign=True
    )
    try:
        managed.retire_runtime_fabric()
    except RuntimeError as exc:
        assert "live consumers" in str(exc) or "active consumers" in str(exc)
    else:
        raise AssertionError("terminal retirement accepted a foreign consumer")
    assert pool.workloads_quiesced is False
    assert guard.closed is False
    assert {str(lease_field(row, "lease_id")) for row in authority.active_leases(resource)} == {
        str(lease_field(own, "lease_id")),
        str(lease_field(foreign, "lease_id")),
    }
    authority.release_lease(foreign)
    managed.close()


def test_terminal_retirement_converges_after_zero_foreign_consumers(tmp_path):
    managed, authority, pool, _group, _controller, fleet, *_ = runtime(tmp_path)
    resource, own, _foreign, guard = attach_consumer(managed, authority, tmp_path)
    managed.retire_runtime_fabric()
    assert authority.active_leases(resource) == ()
    assert guard.closed is True
    assert pool.workloads_quiesced is True
    assert fleet.removals == 1
    assert fleet.shutdowns == 1
    assert managed._closed is True
