from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock, Thread
from types import SimpleNamespace
import threading
import re
import time

import pytest

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
)
from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
    MinecraftTcpReadinessProbe,
)
from noetrium_platform.capabilities.environment.minecraft.providers.jsonl_bridge import (
    JsonlMinecraftBridge,
)
from noetrium_platform.capabilities.environment.minecraft.providers.bridge_distribution import (
    MinecraftBridgeRuntimeDistribution,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionController,
    _DockerMinecraftCapsule,
    _DockerMinecraftServer,
    _DockerServerFactory,
    _MinecraftChildProcessIdentityStale,
    _MinecraftChildProcessInspectionIndeterminate,
    minecraft_lifetime_resource_demand,
    minecraft_server_resource_requirement,
)
from noetrium_platform.foundation.governance.api import ScopeKind, scope_unit
from noetrium_platform.foundation.kernel.concurrency.api import (
    TaskFailureScope,
    UNBOUNDED_EXECUTION_CONTROL,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceProcessIdentity
from noetrium_platform.foundation.kernel.kernel.context import ExecutionContext
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
    is_realization_ticket,
    physical_identity,
    realization_ticket,
    resource_claim,
    resource_observation,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.container.providers.docker_physical import (
    DockerPhysicalProvider,
)


class _RejectSerialTaskGroup:
    def open_serial_actor(self, *args, **kwargs):
        raise AssertionError("Minecraft bridge must not occupy a SERIAL worker")


class _ImmediateHandle:
    def __init__(self, fn):
        self._error = None
        self._value = None
        try:
            self._value = fn()
        except BaseException as exc:
            self._error = exc

    def result(self, timeout=None):
        del timeout
        if self._error is not None:
            raise self._error
        return self._value

    def done(self):
        return True


class _InlineTaskGroup:
    def submit(self, spec, fn, /, *args, **kwargs):
        del spec
        return _ImmediateHandle(
            lambda: fn(SimpleNamespace(checkpoint=lambda: None), *args, **kwargs)
        )


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


class _MemoryDockerProvider(DockerPhysicalProvider):
    def __init__(self) -> None:
        self.rows: dict[str, NoetriumUnit] = {}
        self.ticket_by_physical: dict[str, NoetriumUnit] = {}
        self.realize_calls = 0
        self.retire_calls = 0

    @property
    def docker_executable(self) -> str:
        return "docker"

    def realize(self, spec, ticket: NoetriumUnit) -> NoetriumUnit:
        del spec
        self.realize_calls += 1
        ticket_id = str(ticket_field(ticket, "ticket_id"))
        identity = self.rows.get(ticket_id)
        if identity is None:
            identity = physical_identity(
                "docker",
                "warm-minecraft-" + ticket_id[:12],
                {
                    "ticket_id": ticket_id,
                    "resource_key": ticket_field(ticket, "resource_key"),
                    "generation": ticket_field(ticket, "generation"),
                    "spec_digest": ticket_field(ticket, "spec_digest"),
                },
            )
            self.rows[ticket_id] = identity
        self.ticket_by_physical[identity.unit_digest] = ticket
        return identity

    def observe(self, reference):
        ticket = (
            reference
            if is_realization_ticket(reference)
            else self.ticket_by_physical.get(reference.unit_digest)
        )
        if ticket is None:
            raise TypeError(
                "test Docker provider requires ticket or known physical identity"
            )
        ticket_id = str(ticket_field(ticket, "ticket_id"))
        identity = self.rows.get(ticket_id)
        return resource_observation(
            resource_key=str(ticket_field(ticket, "resource_key")),
            generation=int(ticket_field(ticket, "generation")),
            ticket_id=ticket_id,
            spec_digest=str(ticket_field(ticket, "spec_digest")),
            exists=identity is not None,
            ready=identity is not None,
            physical=identity,
        )

    def retire(self, reference, ticket: NoetriumUnit):
        del reference
        self.retire_calls += 1
        self.rows.pop(str(ticket_field(ticket, "ticket_id")), None)
        return self.observe(ticket)


def test_minecraft_lifetime_resource_demand_matches_physical_contract() -> None:
    compute = minecraft_server_resource_requirement()
    demand = minecraft_lifetime_resource_demand()
    assert demand.cpu_cores_per_permit == compute.cpu_cores
    assert demand.memory_bytes_per_permit == compute.memory_bytes
    # PID/FD fanout is runtime-observed capacity, not a guessed reservation.
    assert demand.pids_per_permit == 0
    assert demand.fds_per_permit == 0


def test_minecraft_bridge_constructor_does_not_allocate_serial_actor() -> None:
    JsonlMinecraftBridge(
        endpoint=MinecraftEndpointSpec(port=25565),
        spec=MinecraftBridgeSpec(command=("node",), cwd="."),
        agent=MinecraftAgentSpec(version="1.21.1"),
        operating_system=LocalOperatingSystemRoute(),
        process_supervisor=object(),
        task_group=_RejectSerialTaskGroup(),
    )


def _bare_lifetime_authority():
    authority = object.__new__(LocalMinecraftLifetimeSessionController)
    authority.lock = RLock()
    authority.runtimes = {}
    authority._lifetime_locks = {}
    authority._retirements = {}
    authority._retirement_rows = {}
    authority._preparations = {}
    authority._preparation_failures = {}
    authority._retirement_failures = {}
    authority._retirement_sequence = 0
    authority.owner_generation_id = "g" * 64
    return authority


def _prepare_context(lifetime_id: str) -> ExecutionContext:
    return ExecutionContext(
        run_id="run-" + lifetime_id,
        trace_id="trace-" + lifetime_id,
        span_id="span-" + lifetime_id,
        lifetime_id=lifetime_id,
    )


def test_minecraft_prepare_waits_until_spawned_session_is_ready() -> None:
    authority = _bare_lifetime_authority()
    authority.prewarm_task_group = _AsyncRetirementGroup()
    started = Event()
    release = Event()
    completed = Event()

    def fake_session_for(context):
        started.set()
        assert release.wait(2.0)
        authority.runtimes[context.lifetime_id] = SimpleNamespace(session="ready")
        return "ready"

    authority.session_for = fake_session_for

    worker = Thread(
        target=lambda: (
            authority.prepare(
                _prepare_context("assignment-ready"),
                UNBOUNDED_EXECUTION_CONTROL,
            ),
            completed.set(),
        )
    )
    worker.start()
    assert started.wait(1.0)
    time.sleep(0.05)
    assert not completed.is_set(), "prepare returned before actor/session readiness"
    release.set()
    worker.join(2.0)
    assert completed.is_set()
    authority.prewarm_task_group.close()


def test_minecraft_prepare_readiness_barrier_preserves_cross_lifetime_concurrency() -> None:
    authority = _bare_lifetime_authority()
    authority.prewarm_task_group = _AsyncRetirementGroup()
    started_a = Event()
    started_b = Event()
    release = Event()

    def fake_session_for(context):
        (started_a if context.lifetime_id == "assignment-a" else started_b).set()
        assert release.wait(2.0)
        authority.runtimes[context.lifetime_id] = SimpleNamespace(session="ready")
        return "ready"

    authority.session_for = fake_session_for
    first = Thread(
        target=authority.prepare,
        args=(_prepare_context("assignment-a"), UNBOUNDED_EXECUTION_CONTROL),
    )
    second = Thread(
        target=authority.prepare,
        args=(_prepare_context("assignment-b"), UNBOUNDED_EXECUTION_CONTROL),
    )
    first.start()
    second.start()
    assert started_a.wait(1.0)
    assert started_b.wait(1.0), "unrelated preparation serialized behind readiness barrier"
    release.set()
    first.join(2.0)
    second.join(2.0)
    assert not first.is_alive() and not second.is_alive()
    authority.prewarm_task_group.close()


def test_minecraft_lifetime_open_is_single_flight_per_lifetime_not_global() -> None:
    authority = _bare_lifetime_authority()
    first_open_started = Event()
    release_first = Event()
    results: dict[str, object] = {}

    def fake_open(context):
        if context.lifetime_id == "lifetime-a":
            first_open_started.set()
            assert release_first.wait(2.0)
        return SimpleNamespace(session=f"session:{context.lifetime_id}")

    authority._open = fake_open

    def acquire(name: str) -> None:
        results[name] = authority.session_for(SimpleNamespace(lifetime_id=name))

    first = Thread(target=acquire, args=("lifetime-a",))
    first.start()
    assert first_open_started.wait(1.0)
    second = Thread(target=acquire, args=("lifetime-b",))
    second.start()
    second.join(0.5)
    assert not second.is_alive(), "unrelated lifetime serialized behind physical open"
    assert results["lifetime-b"] == "session:lifetime-b"
    release_first.set()
    first.join(1.0)
    assert results["lifetime-a"] == "session:lifetime-a"


def _retirement_authority():
    authority = _bare_lifetime_authority()
    authority.task_group = _AsyncRetirementGroup()
    authority.lifecycle_task_group = _AsyncRetirementGroup()
    authority._capsule = SimpleNamespace(close=lambda: None)
    authority._runtime_gc_handles = []
    authority._reconcile_shared_fabric = lambda: 0
    return authority


def test_minecraft_release_detaches_before_physical_retirement_finishes() -> None:
    authority = _retirement_authority()
    started = Event()
    finish = Event()
    row = SimpleNamespace(session="finished")
    authority.runtimes["assignment-a"] = row

    def retire(lifetime_id, observed):
        assert lifetime_id == "assignment-a" and observed is row
        started.set()
        assert finish.wait(2.0)

    authority._retire_runtime = retire
    started_at = time.perf_counter()
    authority.release("assignment-a")
    assert time.perf_counter() - started_at < 0.25
    assert started.wait(1.0)
    assert "assignment-a" not in authority.runtimes
    handle = authority._retirements["assignment-a"]
    assert not handle.done()
    finish.set()
    handle.result(timeout=2.0)
    authority.lifecycle_task_group.close()


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
        session=f"session:{context.lifetime_id}"
    )
    authority.release("assignment-a")
    assert started.wait(1.0)
    assert authority.session_for(SimpleNamespace(lifetime_id="assignment-b")) == "session:assignment-b"
    finish.set()
    authority._retirements["assignment-a"].result(timeout=2.0)
    authority.lifecycle_task_group.close()


def test_minecraft_close_drains_retirements_before_capsule_detach() -> None:
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
    assert closer.is_alive() and not capsule_closed.is_set()
    finish_retirement.set()
    closer.join(2.0)
    assert capsule_closed.is_set()
    authority.lifecycle_task_group.close()


def _capsule(tmp_path, *, authority=None, provider=None, runner=None):
    authority = authority or UniversalResourceAuthority(tmp_path / "resource-authority.sqlite")
    provider = provider or _MemoryDockerProvider()
    runner = runner or _ContainerProcessRunner()
    (tmp_path / "server-runtime-distributions").mkdir(exist_ok=True)
    (tmp_path / "bridge-runtime-distributions").mkdir(exist_ok=True)
    capsule = _DockerMinecraftCapsule(
        authority=authority,
        provider=provider,
        image="noetrium-env-category-minecraft:current",
        image_digest="a" * 64,
        runner=runner,
        task_group=_InlineTaskGroup(),
        instances_root=tmp_path / "instances",
        asset_root=tmp_path / "assets",
        recovery_root=tmp_path / "recovery",
        server_distributions_root=(tmp_path / "server-runtime-distributions"),
        bridge_distributions_root=(tmp_path / "bridge-runtime-distributions"),
        runtime_identity_digest="b" * 64,
    )
    return capsule, authority, provider, runner


def test_minecraft_warm_capsule_is_authority_single_flight_and_restart_adoptable(tmp_path) -> None:
    first, authority, provider, runner = _capsule(tmp_path)
    first.start()
    first_ticket = authority.snapshot().current_ticket_for(first.resource_key)
    assert first_ticket is not None
    first_name = first.container_name
    first_generation = first.generation_digest
    assert provider.realize_calls == 1
    first.close()

    second, _, _, _ = _capsule(
        tmp_path,
        authority=authority,
        provider=provider,
        runner=runner,
    )
    assert second.attach_existing() is True
    assert second.container_name == first_name
    assert second.generation_digest == first_generation
    second.start()
    assert provider.realize_calls == 1
    assert authority.snapshot().binding_for(second.resource_key) is not None


class _ContainerProcessRunner:
    def __init__(self):
        self.rows = {
            101: {"start": "111", "command": "/opt/java/openjdk/bin/java -jar /asset/server.jar nogui", "alive": True},
            102: {"start": "222", "command": "/usr/local/bin/node /opt/noetrium-environments/minecraft/bridge/bridge.js", "alive": True},
            103: {"start": "333", "command": "/bin/sleep 3600", "alive": True},
        }
        self.signals = []
        self.batch_kill_calls = 0
        self.commands: list[str] = []
        self.deleted_overlay_scan = ""

    def run(self, argv, *, timeout_seconds):
        del timeout_seconds
        command = argv[-1] if argv and argv[-2:-1] == ("-c",) else ""
        if command:
            self.commands.append(command)
        if "noetrium-minecraft-batch-alive" in command:
            rows = []
            for raw_pid, expected_start in re.findall(r"(\d+):(\d+)", command):
                pid = int(raw_pid)
                row = self.rows.get(pid)
                if row is not None and row["alive"] and row["start"] == expected_start:
                    rows.append(f"{pid}|{expected_start}")
            return SimpleNamespace(returncode=0, stdout="\n".join(dict.fromkeys(rows)) + ("\n" if rows else ""), stderr="")
        if "noetrium-minecraft-batch-kill" in command:
            self.batch_kill_calls += 1
            for raw_pid, expected_start in re.findall(r"(\d+):(\d+)", command):
                pid = int(raw_pid)
                row = self.rows.get(pid)
                if row is not None and row["alive"] and row["start"] == expected_start:
                    self.signals.append(("-KILL", pid))
                    row["alive"] = False
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "for d in /proc/[0-9]*" in command and "environment-instances" in command:
            return SimpleNamespace(returncode=0, stdout=self.deleted_overlay_scan, stderr="")
        if "/proc/" in command and "/stat" in command and "cat /proc/" in command:
            pid = int(command.split("/proc/", 1)[1].split("/", 1)[0])
            row = self.rows.get(pid)
            if row is None or not row["alive"]:
                return SimpleNamespace(returncode=44, stdout="", stderr="")
            fields = ["S"] + ["0"] * 18 + [row["start"]]
            return SimpleNamespace(returncode=0, stdout=f"{pid} (proc) " + " ".join(fields), stderr="")
        if "cmdline" in command:
            pid = int(command.split("/proc/", 1)[1].split("/", 1)[0])
            row = self.rows.get(pid)
            if row is None or not row["alive"]:
                return SimpleNamespace(returncode=44, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout=row["command"], stderr="")
        if command.startswith("kill -"):
            _kill, signal, raw_pid = command.split()
            pid = int(raw_pid)
            self.signals.append((signal, pid))
            if pid in self.rows:
                self.rows[pid]["alive"] = False
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {argv!r}")


def test_minecraft_pid_recovery_fences_pid_reuse_and_command_drift(tmp_path) -> None:
    runner = _ContainerProcessRunner()
    capsule, *_ = _capsule(tmp_path, runner=runner)
    capsule.start()
    pid_path = capsule.recovery_root / "minecraft-server-41001.pid"
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("101 111\n", encoding="utf-8")
    process = capsule.child_process_identity_from_path(pid_path, expected_command_marker="server.jar")
    assert process == ServiceProcessIdentity(101, "docker-exec:" + capsule.container_name + ":101:111")

    runner.rows[101]["command"] = "/bin/sleep 3600"
    with pytest.raises(_MinecraftChildProcessInspectionIndeterminate):
        capsule.child_process_identity_from_path(pid_path, expected_command_marker="server.jar")
    assert pid_path.exists()

    runner.rows[101]["command"] = "/opt/java/openjdk/bin/java -jar /asset/server.jar nogui"
    runner.rows[101]["start"] = "999"
    with pytest.raises(_MinecraftChildProcessIdentityStale):
        capsule.child_process_identity_from_path(pid_path, expected_command_marker="server.jar")


def test_minecraft_global_recovery_batches_unowned_servers_and_preserves_active(tmp_path) -> None:
    runner = _ContainerProcessRunner()
    active = "b" * 64
    abandoned = "c" * 64
    runner.rows[104] = {"start": "444", "command": "/opt/java/openjdk/bin/java -jar /asset/server.jar nogui", "alive": True}
    runner.rows[105] = {"start": "555", "command": "/opt/java/openjdk/bin/java -jar /asset/server.jar nogui", "alive": True}
    runner.deleted_overlay_scan = (
        f"104|444|/runtime/environment-fabric/minecraft/environment-instances/{active}\n"
        f"105|555|/runtime/environment-fabric/minecraft/environment-instances/{abandoned}\n"
    )
    capsule, *_ = _capsule(tmp_path, runner=runner)
    capsule.start()
    evidence = capsule.reconcile_abandoned_children(
        active_compute_key_prefixes=frozenset({active[:24]})
    )
    assert runner.rows[104]["alive"] is True
    assert runner.rows[105]["alive"] is False
    assert runner.batch_kill_calls == 1
    assert ("-KILL", 105) in runner.signals
    assert any(value.startswith("minecraft-abandoned-child-stopped:105:") for value in evidence)




def test_minecraft_global_recovery_retires_server_with_deleted_cwd(tmp_path) -> None:
    runner = _ContainerProcessRunner()
    runner.rows[106] = {
        "start": "666",
        "command": "/opt/java/openjdk/bin/java -jar /asset/server.jar nogui",
        "alive": True,
    }
    runner.deleted_overlay_scan = "106|666|/ (deleted)\n"
    capsule, *_ = _capsule(tmp_path, runner=runner)
    capsule.start()

    evidence = capsule.reconcile_abandoned_children(
        active_compute_key_prefixes=frozenset()
    )

    assert runner.rows[106]["alive"] is False
    assert runner.batch_kill_calls == 1
    assert ("-KILL", 106) in runner.signals
    assert any(
        value.startswith("minecraft-abandoned-child-stopped:106:")
        for value in evidence
    )


def test_minecraft_lifetime_retirement_uses_owner_cleanup_group() -> None:
    submitted: list[str] = []

    class Handle:
        def result(self, timeout=None):
            del timeout
            return None

        def done(self):
            return False

    class BorrowerGroup:
        def submit(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("borrower task group must not own lifetime retirement")

    class OwnerCleanupGroup:
        def submit(self, spec, fn, /, *args, **kwargs):
            del kwargs
            submitted.append(spec.task_id)
            fn(None, *args)
            return Handle()

    authority = object.__new__(LocalMinecraftLifetimeSessionController)
    authority.task_group = BorrowerGroup()
    authority.lifecycle_task_group = OwnerCleanupGroup()
    authority.owner_generation_id = "owner-generation:test"
    authority._retirement_sequence = 0
    authority._retirements = {}
    authority._retirement_rows = {}
    authority._retirement_failures = {}
    authority._lifetime_locks = {}
    authority.lock = threading.RLock()
    retired: list[str] = []
    authority._retire_runtime = lambda lifetime_id, row: retired.append(lifetime_id)

    row = object()
    authority._submit_retirement("lifetime:test", row)

    assert retired == ["lifetime:test"]
    assert len(submitted) == 1
    assert submitted[0].startswith("minecraft-lifetime-retire:")
    assert "lifetime:test" in authority._retirements

def test_docker_minecraft_tcp_readiness_never_nests_into_task_group(monkeypatch) -> None:
    class Connection:
        def close(self) -> None:
            return None

    calls = []
    def connect(address, timeout):
        calls.append((address, timeout))
        return Connection()

    monkeypatch.setattr(
        "noetrium_platform.capabilities.environment.minecraft.composition.server_service.socket.create_connection",
        connect,
    )
    server = object.__new__(_DockerMinecraftServer)
    server.process = SimpleNamespace(pid=101, start_identity="start-101")
    server.capsule = SimpleNamespace(assert_healthy=lambda: None)
    server.contract = SimpleNamespace(
        service_id="minecraft.server.test",
        readiness_timeout_s=1.0,
        digest=lambda: "contract-digest",
    )
    server.alive = lambda process: process is server.process
    server._tcp_readiness_probe = MinecraftTcpReadinessProbe(
        host="127.0.0.1", port=25565, poll_interval_s=0.001,
    )
    first = server._tcp_ready_evidence()
    second = server._tcp_ready_evidence()
    assert first == second
    assert first.startswith("minecraft-tcp-ready:")
    assert len(calls) == 2


def test_minecraft_stop_re_adopts_durable_pid_when_in_memory_process_is_missing(tmp_path) -> None:
    pid_path = tmp_path / "minecraft-server-41001.pid"
    pid_path.write_text("101 111\n", encoding="utf-8")
    process = ServiceProcessIdentity(101, "docker-exec:container-a:101:111")
    server = object.__new__(_DockerMinecraftServer)
    server.process = None
    server.pid_path = pid_path
    server.contract = SimpleNamespace(stop_timeout_s=0.01, digest=lambda: "contract-digest")
    server.capsule = SimpleNamespace(container_name="warm-minecraft")
    server._process_identity = lambda: process
    live = {"value": True}
    server.alive = lambda observed: live["value"] and observed == process
    signals = []

    def terminate(observed, *, signal):
        signals.append((signal, observed))
        live["value"] = False

    server._terminate_pid = terminate
    released = []
    server._release_pristine_reservation = lambda: released.append(True)
    outcome = server.stop()
    assert outcome.stopped is True
    assert signals == [("TERM", process)]
    assert server.process is None and not pid_path.exists()
    assert released == [True]


def test_minecraft_failed_start_cleanup_preserves_pid_until_exact_death(tmp_path) -> None:
    pid_path = tmp_path / "minecraft-server-41001.pid"
    pid_path.write_text("101 111\n", encoding="utf-8")
    process = ServiceProcessIdentity(101, "docker-exec:container-a:101:111")
    server = object.__new__(_DockerMinecraftServer)
    server.process = process
    server.pid_path = pid_path
    server.contract = SimpleNamespace(stop_timeout_s=0.01)
    server._terminate_recovered_process = lambda _process: (_ for _ in ()).throw(RuntimeError("exact cleanup failure"))
    errors = server._cleanup_failed_start()
    assert len(errors) == 1 and pid_path.exists() and server.process == process

    server._terminate_recovered_process = lambda _process: None
    assert server._cleanup_failed_start() == ()
    assert server.process is None and not pid_path.exists()


class _CaptureProcessSupervisor:
    def __init__(self) -> None:
        self.argv = None

    def spawn_interactive(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        return object()


def test_minecraft_bridge_publishes_inner_container_pid_for_crash_recovery(tmp_path) -> None:
    supervisor = _CaptureProcessSupervisor()
    factory = object.__new__(_DockerServerFactory)
    factory.lock = RLock()
    factory.by_port = {25565: SimpleNamespace(container_name="warm-minecraft", recovery_root=tmp_path)}
    factory.capsule = SimpleNamespace(docker_executable="docker")
    factory.process_supervisor = supervisor
    factory.bridge_runtime = SimpleNamespace(
        root=tmp_path / "bridge", entrypoint=tmp_path / "bridge" / "index.js",
    )
    factory.bridge_process_factory(25565)(["ignored"], env={})
    shell = supervisor.argv[-1]
    assert supervisor.argv[0] == "docker"
    assert "minecraft-bridge-25565.pid" in shell
    assert "awk '{print $22}' /proc/$$/stat" in shell
    assert "exec /usr/local/bin/node" in shell


def test_minecraft_server_launch_waits_for_atomic_pid_publication(tmp_path) -> None:
    captured = {}

    class Supervisor:
        def spawn_interactive(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            return SimpleNamespace(poll=lambda: None)

    process = ServiceProcessIdentity(101, "docker-exec:container-a:101:111")
    server = object.__new__(_DockerMinecraftServer)
    server.process = None
    server.capsule = SimpleNamespace(
        assert_healthy=lambda: None,
        docker_executable="docker",
        container_name="warm-minecraft",
    )
    server.process_supervisor = Supervisor()
    server.pid_path = tmp_path / "recovery" / "minecraft-server-25565.pid"
    server.pid_path.parent.mkdir()
    workdir = tmp_path / "world"
    workdir.mkdir()
    server.spec = SimpleNamespace(
        workdir=str(workdir),
        command=lambda: (
            "/opt/java/openjdk/bin/java", "-Xmx2G", "-jar", "/asset/server.jar", "nogui"
        ),
    )
    server.cpu_cores = 1
    server._process_identity = lambda: process
    server.contract = SimpleNamespace(
        digest=lambda: "contract-digest", readiness_timeout_s=2.0,
    )
    outcome = server.start()
    assert outcome.process == process
    argv = captured["argv"]
    assert argv[0:2] == ("docker", "exec") and "-d" not in argv
    assert "-i" in argv
    shell = argv[-1]
    assert "start=$(awk '{print $22}' /proc/$$/stat)" in shell
    assert ".tmp.$$" in shell and 'mv "$tmp"' in shell
    assert "-XX:ActiveProcessorCount=1" in shell
    assert "exec /opt/java/openjdk/bin/java" in shell
    # The Docker exec process is the actual Java process; no detached
    # background child or host-side fallback is legal.
    assert "child=$!" not in shell
    assert "docker" not in captured["kwargs"].get("cwd", "")


def test_minecraft_retirement_failure_retains_overlay_for_exact_retry(tmp_path) -> None:
    authority = _bare_lifetime_authority()
    authority._capsule = SimpleNamespace(_claims=object(), _spec=object())

    class FailingAuthority:
        def reconcile(self, *args, **kwargs):
            raise RuntimeError("provider retirement not yet converged")

    authority.resource_authority = FailingAuthority()
    workdir = tmp_path / "workdir"
    recovery = tmp_path / "recovery"
    workdir.mkdir()
    recovery.mkdir()
    closed = []
    row = SimpleNamespace(
        binding=SimpleNamespace(close=lambda: closed.append(True)),
        resource_topology_unit=object(),
        providers={"minecraft-server": object()},
        workdir=workdir,
        recovery_root=recovery,
    )
    with pytest.raises(BaseExceptionGroup, match="did not fully converge"):
        authority._retire_runtime("assignment-fail", row)
    assert closed == [True]
    assert workdir.exists() and recovery.exists()



def test_minecraft_binding_close_failure_does_not_mask_scope_convergence(tmp_path) -> None:
    authority = _bare_lifetime_authority()
    authority._capsule = SimpleNamespace(_claims=object(), _spec=object())
    reconciled = []
    released = []

    class Authority:
        def reconcile(self, *args, **kwargs):
            reconciled.append(True)

    def fail_binding_close():
        raise RuntimeError("bridge already disconnected")

    authority.resource_authority = Authority()
    authority._release_branch_scope_guard = (
        lambda guard, run_id: released.append((guard, run_id))
    )
    workdir = tmp_path / "workdir"
    recovery = tmp_path / "recovery"
    workdir.mkdir()
    recovery.mkdir()
    guard = object()
    row = SimpleNamespace(
        binding=SimpleNamespace(close=fail_binding_close),
        resource_topology_unit=object(),
        providers={"minecraft-server": object()},
        branch_scope_lease_guard=guard,
        run_id="run-a",
        workdir=workdir,
        recovery_root=recovery,
    )

    with pytest.raises(BaseExceptionGroup, match="did not fully converge"):
        authority._retire_runtime("assignment-close-error", row)

    assert reconciled == [True]
    assert released == [(guard, "run-a")]
    assert not workdir.exists()
    assert not recovery.exists()

def test_minecraft_failed_async_retirement_retains_exact_row_for_retry() -> None:
    authority = _retirement_authority()
    row = SimpleNamespace(session="owned")
    authority.runtimes["assignment-retry"] = row
    calls = []

    def retire(lifetime_id, observed):
        assert lifetime_id == "assignment-retry" and observed is row
        calls.append(lifetime_id)
        if len(calls) == 1:
            raise RuntimeError("transient retirement failure")

    authority._retire_runtime = retire
    authority.release("assignment-retry")
    first = authority._retirements["assignment-retry"]
    with pytest.raises(RuntimeError):
        first.result(timeout=2.0)
    authority._reap_completed_retirements()
    assert authority._retirement_rows["assignment-retry"] is row
    assert "assignment-retry" in authority._retirement_failures
    authority.release("assignment-retry")
    authority._retirements["assignment-retry"].result(timeout=2.0)
    authority._reap_completed_retirements()
    assert calls == ["assignment-retry", "assignment-retry"]
    assert "assignment-retry" not in authority._retirement_rows
    authority.lifecycle_task_group.close()


def test_minecraft_orphan_scope_server_ticket_recovery_skips_live_scope(tmp_path) -> None:
    stale_prefix = "a" * 24
    live_prefix = "b" * 24
    stale_scope = scope_unit(ScopeKind.BRANCH, "assignment-" + stale_prefix)
    live_scope = scope_unit(ScopeKind.BRANCH, "assignment-" + live_prefix)
    stale_claim = resource_claim(
        claim_id="stale-server-claim",
        resource_key=f"minecraft-branch:{stale_prefix}:server",
        holder_key="branch:stale",
        generation=1,
        owner_scope=stale_scope,
        scope_generation=1,
        scope_lease_id="stale-branch-scope-lease",
        owner_lease_id=None,
        attributes={"kind": "minecraft-server"},
    )
    live_claim = resource_claim(
        claim_id="live-server-claim",
        resource_key=f"minecraft-branch:{live_prefix}:server",
        holder_key="branch:live",
        generation=1,
        owner_scope=live_scope,
        scope_generation=1,
        scope_lease_id="live-branch-scope-lease",
        owner_lease_id=None,
        attributes={"kind": "minecraft-server"},
    )

    class Authority:
        def __init__(self) -> None:
            self.calls = []
            self.orphan_passes = 0

        def snapshot_for_claim_kinds(self, kinds):
            assert kinds == frozenset({"minecraft-server"})
            return SimpleNamespace(claims=(stale_claim, live_claim))

        def reconcile(self, topology, **kwargs):
            self.calls.append((topology, kwargs))
            return SimpleNamespace()

        def reconcile_orphan_claims_for_claim_kinds(self, kinds):
            assert kinds == frozenset({"minecraft-server"})
            self.orphan_passes += 1
            return ()

    authority = Authority()
    controller = object.__new__(LocalMinecraftLifetimeSessionController)
    controller.resource_authority = authority
    controller.recovery_root = tmp_path / "recovery"
    controller.recovery_root.mkdir()
    stale_recovery = controller.recovery_root / (stale_prefix + "c" * 40)
    stale_recovery.mkdir()
    controller.image = "minecraft:test"
    controller.image_digest = "d" * 64
    controller.runner = SimpleNamespace()
    controller.task_group = SimpleNamespace()
    controller.lifecycle_task_group = SimpleNamespace()
    controller.process_supervisor = SimpleNamespace()
    controller.asset_digest = "e" * 64
    controller._capsule = SimpleNamespace()
    controller.pristine_worlds = SimpleNamespace()
    controller.bridge_runtime = MinecraftBridgeRuntimeDistribution(
        "f" * 64, tmp_path / "bridge-runtime"
    )

    recovered = controller._reconcile_expired_server_authority(
        orphan_claim_ids=frozenset({"stale-server-claim"}),
    )

    assert recovered == 1
    assert len(authority.calls) == 1
    topology, kwargs = authority.calls[0]
    assert topology.unit_id == "minecraft-expired-owner-recovery:" + stale_prefix
    assert kwargs["desired_resource_ids"] == frozenset()
    assert set(kwargs["providers"]) == {"minecraft-server"}
    assert authority.orphan_passes == 1
