from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread
import time

from noetrium_platform.composition.managed_research_runtime import ManagedResearchRuntime


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
        return Handle(fn, *args, **kwargs)

    def assert_healthy(self):
        return None


class Pool:
    def __init__(self):
        self.group_closed = False
        self.closed = False

    def close_orchestration_group(self, group, *, cancel_pending=False, deadline=None):
        self.group_closed = True
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


@dataclass
class Models:
    controller: Controller


@dataclass
class Management:
    models: Models


def runtime():
    pool = Pool()
    group = Group()
    controller = Controller()
    managed = ManagedResearchRuntime(
        execution_pool=pool,
        management=Management(Models(controller)),
        _orchestration_group=group,
        _stop=Event(),
    )
    return managed, pool, group, controller


def test_managed_runtime_owns_background_controller_lifecycle() -> None:
    managed, pool, group, controller = runtime()
    managed.start_background_controllers(model_reconcile_interval_seconds=0.01)
    assert controller.started.wait(1.0)
    managed.start_background_controllers(model_reconcile_interval_seconds=0.01)
    assert group.submissions == ["managed-model-desired-state-controller"]

    time.sleep(0.03)
    managed.assert_healthy()
    managed.close()

    assert pool.group_closed is True
    assert pool.closed is True
    assert group.closed is True
    assert controller.cycles >= 1


def test_managed_runtime_close_is_idempotent() -> None:
    managed, pool, _group, _controller = runtime()
    managed.start_background_controllers(model_reconcile_interval_seconds=0.01)
    managed.close()
    managed.close()
    assert pool.closed is True


def test_managed_runtime_rejects_controller_restart_after_close() -> None:
    managed, _pool, _group, _controller = runtime()
    managed.close()
    try:
        managed.start_background_controllers()
    except RuntimeError as exc:
        assert "closed" in str(exc)
    else:
        raise AssertionError("closed managed runtime accepted controller start")


def test_managed_research_runtime_is_available_from_public_platform_facade() -> None:
    from noetrium_platform import platform

    assert platform.ManagedResearchRuntime is ManagedResearchRuntime
    assert callable(platform.bind_local_managed_research_runtime)
