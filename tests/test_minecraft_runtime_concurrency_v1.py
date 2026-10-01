from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from threading import Event, RLock, Thread
import time

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
)
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import (
    JsonlMinecraftBridge,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionAuthority,
    _DockerMinecraftCapsule,
    _DockerMinecraftServer,
    _DockerServerFactory,
)
from noetrium_platform.foundation.kernel.concurrency.api import ContentAddressedSingleFlight
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute


class _RejectSerialTaskGroup:
    def open_serial_actor(self, *args, **kwargs):
        raise AssertionError("Minecraft bridge must not occupy a SERIAL worker")


class _HealthyGuard:
    def assert_healthy(self) -> None:
        return None


def test_minecraft_bridge_constructor_does_not_allocate_serial_actor() -> None:
    JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25565),
        spec=MinecraftBridgeSpec(command=("node",), cwd="."),
        agent=MinecraftAgentSpec(version="1.21.1"),
        operating_system=LocalOperatingSystemRoute(),
        process_supervisor=object(),
        task_group=_RejectSerialTaskGroup(),
    )


def test_minecraft_lifetime_open_is_single_flight_per_lifetime_not_global() -> None:
    authority = object.__new__(LocalMinecraftLifetimeSessionAuthority)
    authority.lock = RLock()
    authority.runtimes = {}
    authority._lifetime_locks = {}
    authority._retirements = {}
    authority._preparations = {}
    authority._preparation_failures = {}
    authority._retirement_failures = []
    authority._retirement_sequence = 0

    first_open_started = Event()
    release_first = Event()
    results: dict[str, object] = {}

    def fake_open(context):
        if context.lifetime_id == "lifetime-a":
            first_open_started.set()
            assert release_first.wait(2.0)
        return SimpleNamespace(
            session=f"session:{context.lifetime_id}",
            instance_guard=_HealthyGuard(),
        )

    authority._open = fake_open

    def acquire(name: str) -> None:
        results[name] = authority.session_for(SimpleNamespace(lifetime_id=name))

    first = Thread(target=acquire, args=("lifetime-a",))
    first.start()
    assert first_open_started.wait(1.0)

    second = Thread(target=acquire, args=("lifetime-b",))
    second.start()
    second.join(0.5)
    assert not second.is_alive(), "unrelated lifetime was serialized behind physical open"
    assert results["lifetime-b"] == "session:lifetime-b"

    release_first.set()
    first.join(1.0)
    assert not first.is_alive()
    assert results["lifetime-a"] == "session:lifetime-a"


class _AsyncRetirementGroup:
    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.specs = []

    def submit(self, spec, fn, /, *args, **kwargs):
        self.specs.append(spec)
        return self.executor.submit(
            lambda: fn(SimpleNamespace(checkpoint=lambda: None), *args, **kwargs)
        )

    def close(self) -> None:
        self.executor.shutdown(wait=True)


def _retirement_authority():
    authority = object.__new__(LocalMinecraftLifetimeSessionAuthority)
    authority.lock = RLock()
    authority.runtimes = {}
    authority._lifetime_locks = {}
    authority._retirements = {}
    authority._preparations = {}
    authority._preparation_failures = {}
    authority._retirement_failures = []
    authority._retirement_sequence = 0
    authority.owner_generation_id = "g" * 64
    authority.task_group = _AsyncRetirementGroup()
    authority._capsule = SimpleNamespace(close=lambda: None)
    return authority


def test_minecraft_release_detaches_before_physical_retirement_finishes() -> None:
    authority = _retirement_authority()
    started = Event()
    finish = Event()
    row = SimpleNamespace(session="finished")
    authority.runtimes["assignment-a"] = row

    def retire(lifetime_id, observed):
        assert lifetime_id == "assignment-a"
        assert observed is row
        started.set()
        assert finish.wait(2.0)

    authority._retire_runtime = retire
    started_at = time.perf_counter()
    authority.release("assignment-a")
    elapsed = time.perf_counter() - started_at

    assert started.wait(1.0)
    assert elapsed < 0.25
    assert "assignment-a" not in authority.runtimes
    handle = authority._retirements["assignment-a"]
    assert not handle.done()

    finish.set()
    handle.result(timeout=2.0)
    authority.task_group.close()


def test_minecraft_retirement_does_not_block_unrelated_lifetime_open() -> None:
    authority = _retirement_authority()
    started = Event()
    finish = Event()
    authority.runtimes["assignment-a"] = SimpleNamespace(session="old")

    def retire(_lifetime_id, _row):
        started.set()
        assert finish.wait(2.0)

    authority._retire_runtime = retire
    authority._open = lambda context: SimpleNamespace(
        session=f"session:{context.lifetime_id}",
        instance_guard=_HealthyGuard(),
    )

    authority.release("assignment-a")
    assert started.wait(1.0)
    assert (
        authority.session_for(SimpleNamespace(lifetime_id="assignment-b"))
        == "session:assignment-b"
    )

    finish.set()
    authority._retirements["assignment-a"].result(timeout=2.0)
    authority.task_group.close()


def test_minecraft_close_drains_retirements_before_capsule_close() -> None:
    authority = _retirement_authority()
    retirement_started = Event()
    finish_retirement = Event()
    capsule_closed = Event()
    authority._capsule = SimpleNamespace(close=capsule_closed.set)
    authority.runtimes["assignment-a"] = SimpleNamespace(session="old")

    def retire(_lifetime_id, _row):
        retirement_started.set()
        assert finish_retirement.wait(2.0)

    authority._retire_runtime = retire
    closer = Thread(target=authority.close)
    closer.start()
    assert retirement_started.wait(1.0)
    time.sleep(0.05)
    assert closer.is_alive()
    assert not capsule_closed.is_set()

    finish_retirement.set()
    closer.join(2.0)
    assert not closer.is_alive()
    assert capsule_closed.is_set()
    authority.task_group.close()


class _CapsuleGuard:
    def __init__(self) -> None:
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def assert_healthy(self) -> None:
        assert self.started and not self.closed


class _CapsuleGuardFactory:
    def __init__(self) -> None:
        self.guard = _CapsuleGuard()
        self.handles = ()

    def create(self, handles):
        self.handles = handles
        return self.guard


class _RecoveringCapsuleAuthority:
    def __init__(self) -> None:
        self.handle = SimpleNamespace(container_name="warm-capsule")
        self.observed = SimpleNamespace(running=True)
        self.runtime = SimpleNamespace(inspect=lambda _name: self.observed)
        self.recover_calls = 0
        self.reserve_calls = 0
        self.release_calls = 0

    def recover(self, **_kwargs):
        self.recover_calls += 1
        return self.handle

    def observe_exact(self, handle):
        assert handle is self.handle
        return self.observed

    def reserve(self, **_kwargs):
        self.reserve_calls += 1
        raise AssertionError("recoverable warm capsule must not allocate a replacement")

    def release(self, _handle):
        self.release_calls += 1
        raise AssertionError("normal warm-capsule detach must not destroy physical runtime")


def _warm_capsule(tmp_path, authority, guard_factory):
    return _DockerMinecraftCapsule(
        authority=authority,
        lease_guard_factory=guard_factory,
        image="noetrium-env-category-minecraft:current",
        image_digest="a" * 64,
        runner=SimpleNamespace(
            run=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("recoverable warm capsule must not launch Docker")
            )
        ),
        instances_root=tmp_path / "instances",
        asset_root=tmp_path / "assets",
        recovery_root=tmp_path / "recovery",
        realization_singleflight=ContentAddressedSingleFlight(tmp_path / "singleflight"),
        runtime_identity_digest="b" * 64,
    )


def test_minecraft_warm_capsule_targeted_recovers_and_detaches(tmp_path) -> None:
    authority = _RecoveringCapsuleAuthority()
    guards = _CapsuleGuardFactory()
    capsule = _warm_capsule(tmp_path, authority, guards)

    capsule.start()

    assert authority.recover_calls == 1
    assert authority.reserve_calls == 0
    assert guards.handles == (authority.handle,)
    assert guards.guard.started
    assert capsule.container_name == "warm-capsule"

    capsule.close()

    assert guards.guard.closed
    assert authority.release_calls == 0


def test_minecraft_warm_capsule_identity_is_process_generation_independent(tmp_path) -> None:
    first = _warm_capsule(
        tmp_path,
        _RecoveringCapsuleAuthority(),
        _CapsuleGuardFactory(),
    )
    second = _warm_capsule(
        tmp_path,
        _RecoveringCapsuleAuthority(),
        _CapsuleGuardFactory(),
    )

    assert first.allocation_id == second.allocation_id
    assert first.generation_digest == second.generation_digest


class _ContainerProcessRunner:
    def __init__(self):
        self.rows = {
            101: {"start": "111", "command": "/opt/java/openjdk/bin/java -jar /asset/server.jar nogui", "alive": True},
            102: {"start": "222", "command": "/usr/local/bin/node /opt/noetrium-environments/minecraft/bridge/bridge.js", "alive": True},
            103: {"start": "333", "command": "/bin/sleep 3600", "alive": True},
        }
        self.signals = []

    def run(self, argv, *, timeout_seconds):
        del timeout_seconds
        command = argv[-1] if argv and argv[-2:-1] == ("-c",) else ""
        if command.startswith("cat /proc/") and command.endswith("/stat"):
            pid = int(command.split("/proc/", 1)[1].split("/", 1)[0])
            row = self.rows.get(pid)
            if row is None or not row["alive"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="missing")
            fields = ["S"] + ["0"] * 18 + [row["start"]]
            return SimpleNamespace(
                returncode=0,
                stdout=f"{pid} (proc) " + " ".join(fields),
                stderr="",
            )
        if "cmdline" in command:
            pid = int(command.split("/proc/", 1)[1].split("/", 1)[0])
            row = self.rows.get(pid)
            if row is None or not row["alive"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="missing")
            return SimpleNamespace(returncode=0, stdout=row["command"], stderr="")
        if command.startswith("kill -"):
            _kill, signal, raw_pid = command.split()
            pid = int(raw_pid)
            self.signals.append((signal, pid))
            if pid in self.rows:
                self.rows[pid]["alive"] = False
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {argv!r}")


def test_minecraft_reopen_reaps_only_exact_stale_lifetime_processes(tmp_path) -> None:
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    (recovery / "minecraft-server-41001.pid").write_text("101 111\n", encoding="utf-8")
    (recovery / "minecraft-bridge-41001.pid").write_text("102 222\n", encoding="utf-8")
    (recovery / "minecraft-server-41002.pid").write_text("103 333\n", encoding="utf-8")

    runner = _ContainerProcessRunner()
    runtime = SimpleNamespace(
        docker_executable="docker",
        inspect=lambda _name: SimpleNamespace(running=True, container_id="container-a"),
    )
    server = object.__new__(_DockerMinecraftServer)
    server.recovery_root = recovery
    server.runner = runner
    server.authority = SimpleNamespace(runtime=runtime)
    server.capsule = SimpleNamespace(
        assert_healthy=lambda: None,
        container_name="warm-minecraft",
    )
    server.contract = SimpleNamespace(stop_timeout_s=0.01)

    server._reconcile_stale_lifetime_processes()

    assert runner.signals == [("-TERM", 101), ("-TERM", 102)]
    assert runner.rows[103]["alive"] is True
    assert not tuple(recovery.glob("minecraft-*.pid"))


class _CaptureProcessSupervisor:
    def __init__(self) -> None:
        self.argv = None
        self.kwargs = None

    def spawn_interactive(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        return object()


def test_minecraft_bridge_publishes_inner_container_pid_for_crash_recovery(tmp_path) -> None:
    supervisor = _CaptureProcessSupervisor()
    factory = object.__new__(_DockerServerFactory)
    factory.lock = RLock()
    factory.by_port = {
        25565: SimpleNamespace(
            container_name="warm-minecraft",
            recovery_root=tmp_path,
        )
    }
    factory.authority = SimpleNamespace(
        runtime=SimpleNamespace(docker_executable="docker")
    )
    factory.process_supervisor = supervisor

    factory.bridge_process_factory(25565)(["ignored"], env={})

    assert supervisor.argv is not None
    assert supervisor.argv[-3:-1] == ("/bin/sh", "-c")
    shell = supervisor.argv[-1]
    assert "minecraft-bridge-25565.pid" in shell
    assert "awk '{print $22}' /proc/$$/stat" in shell
    assert "exec /usr/local/bin/node" in shell
    assert "/opt/noetrium-environments/minecraft/bridge/bridge.js" in shell
