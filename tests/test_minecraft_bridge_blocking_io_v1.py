from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock, RLock
import time
from types import SimpleNamespace

from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import JsonlMinecraftBridge
from noetrium_platform.composition.environment_capabilities.minecraft_local import LocalMinecraftLifetimeSessionAuthority
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionLaneKind


class _Context:
    def checkpoint(self) -> None:
        return None


class _Handle:
    def __init__(self, value):
        self._value = value

    def result(self, timeout=None):
        return self._value


class _ImmediateTaskGroup:
    def __init__(self) -> None:
        self.specs = []
        self.serial_actor_opened = False

    def submit(self, spec, fn, /, *args, **kwargs):
        self.specs.append(spec)
        return _Handle(fn(_Context(), *args, **kwargs))

    def open_serial_actor(self, *args, **kwargs):
        self.serial_actor_opened = True
        raise AssertionError("Minecraft bridge blocking I/O must not use a SERIAL actor")


class _Guard:
    def assert_healthy(self) -> None:
        return None


class _Authority(LocalMinecraftLifetimeSessionAuthority):
    def __init__(self, opener):
        self.lock = RLock()
        self.runtimes = {}
        self._lifetime_locks = {}
        self._opener = opener

    def _open(self, context):
        return self._opener(context)


def _runtime(session):
    return SimpleNamespace(
        binding=SimpleNamespace(close=lambda: None),
        session=session,
        workdir=Path("/tmp/unused"),
        instance_handle=object(),
        instance_guard=_Guard(),
    )


def test_bridge_blocking_operations_use_blocking_io_not_serial_actor() -> None:
    group = _ImmediateTaskGroup()
    bridge = object.__new__(JsonlMinecraftBridge)
    bridge._operation_lock = Lock()
    bridge._task_group = group
    bridge._bridge_identity = "fixture"

    result = bridge._call_owned("start", lambda value: value + 1, 41)

    assert result == 42
    assert len(group.specs) == 1
    assert group.specs[0].lane_kind is ExecutionLaneKind.BLOCKING_IO
    assert group.serial_actor_opened is False


def test_minecraft_lifetimes_open_concurrently_across_distinct_assignments() -> None:
    barrier = Barrier(2)

    def opener(context):
        barrier.wait(timeout=2.0)
        return _runtime(f"session:{context.lifetime_id}")

    authority = _Authority(opener)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(authority.session_for, SimpleNamespace(lifetime_id="assignment-a"))
        b = pool.submit(authority.session_for, SimpleNamespace(lifetime_id="assignment-b"))
        assert {a.result(timeout=3.0), b.result(timeout=3.0)} == {
            "session:assignment-a",
            "session:assignment-b",
        }


def test_minecraft_same_lifetime_open_is_single_flight() -> None:
    calls = 0
    calls_lock = Lock()

    def opener(context):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.08)
        return _runtime("shared-session")

    authority = _Authority(opener)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(authority.session_for, SimpleNamespace(lifetime_id="same"))
        second = pool.submit(authority.session_for, SimpleNamespace(lifetime_id="same"))
        assert first.result(timeout=2.0) == "shared-session"
        assert second.result(timeout=2.0) == "shared-session"
    assert calls == 1
