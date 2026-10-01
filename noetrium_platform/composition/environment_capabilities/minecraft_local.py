from __future__ import annotations

import os
import shlex
import shutil
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from noetrium_platform.capabilities.environment.api import EnvironmentCapabilityDescriptor, EnvironmentSession
from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentCleanlinessKind,
    EnvironmentCleanlinessProof,
    EnvironmentInstance,
    EnvironmentProfileMaterialization,
    EnvironmentProfileRevision,
)
from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBranchRuntimeRequest,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
    MinecraftEnvironmentSpec,
    MinecraftServerSpec,
    MinecraftWorldBranch,
    minecraft_action_catalog,
)
from noetrium_platform.capabilities.environment.minecraft.composition.branch_runtime import MinecraftBranchRuntimeFactory
from noetrium_platform.capabilities.environment.minecraft.composition.environment import (
    MinecraftEnvironmentAssembly,
    compose_minecraft_environment,
)
from noetrium_platform.capabilities.environment.minecraft.composition.server_service import MinecraftTcpReadinessProbe
from noetrium_platform.capabilities.environment.minecraft.providers.server_files import prepare_server_files
from noetrium_platform.foundation.kernel.concurrency.api import (
    ContentAddressedSingleFlight,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import sha256_file
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessSupervisorPort
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
    ServiceReadyObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.infrastructure.resources.container.runtime import DockerContainerLeaseAuthority
from noetrium_platform.composition.environment_instance_leases import (
    EnvironmentInstanceLeaseAuthority,
    EnvironmentInstanceLeaseHandle,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from .lifetime import EnvironmentLifetimeSessionAuthorityPort

_BRIDGE_ROOT = "/opt/noetrium-environments/minecraft/bridge"
_NODE = "/usr/local/bin/node"
_JAVA = "/opt/java/openjdk/bin/java"


class _DockerMinecraftCapsule:
    """One fenced warm container shared by concurrent Minecraft assignments."""

    def __init__(
        self,
        *,
        authority: DockerContainerLeaseAuthority,
        lease_guard_factory,
        image: str,
        image_digest: str,
        runner: LocalCommandRunnerPort,
        instances_root: Path,
        asset_root: Path,
        recovery_root: Path,
        realization_singleflight: ContentAddressedSingleFlight,
        runtime_identity_digest: str,
    ) -> None:
        self.authority = authority
        self.lease_guard_factory = lease_guard_factory
        self.image = image
        self.image_digest = image_digest
        self.runner = runner
        self.instances_root = instances_root.resolve()
        self.asset_root = asset_root.resolve()
        self.recovery_root = recovery_root.resolve()
        if not isinstance(realization_singleflight, ContentAddressedSingleFlight):
            raise TypeError("Minecraft capsule requires ContentAddressedSingleFlight")
        if (
            type(runtime_identity_digest) is not str
            or len(runtime_identity_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in runtime_identity_digest)
        ):
            raise ValueError("Minecraft capsule runtime identity must be lowercase sha256")
        self.realization_singleflight = realization_singleflight
        self.runtime_identity_digest = runtime_identity_digest
        self.handle = None
        self.guard = None
        self.lock = threading.RLock()
        self.allocation_id = "minecraft-capsule:" + canonical_digest({
            "schema": "noetrium.minecraft-warm-capsule-allocation.v3",
            "runtime_identity_digest": runtime_identity_digest,
            "instances_root": str(self.instances_root),
            "asset_root": str(self.asset_root),
            "recovery_root": str(self.recovery_root),
        })[:28]
        self.generation_digest = canonical_digest({
            "schema": "noetrium.minecraft-warm-capsule.v3",
            "allocation_id": self.allocation_id,
            "runtime_identity_digest": runtime_identity_digest,
        })

    @property
    def container_name(self) -> str:
        handle = self.handle
        if handle is None:
            raise RuntimeError("Minecraft warm capsule is not started")
        return handle.container_name

    def assert_healthy(self) -> None:
        with self.lock:
            if self.handle is None or self.guard is None:
                raise RuntimeError("Minecraft warm capsule is not started")
            self.guard.assert_healthy()
            observed = self.authority.runtime.inspect(self.handle.container_name)
            if observed is None or not observed.running:
                raise RuntimeError("Minecraft warm capsule is not running")

    def _attach_existing_locked(self) -> bool:
        handle = self.authority.recover(
            allocation_id=self.allocation_id,
            image=self.image,
            runtime_identity_digest=self.runtime_identity_digest,
        )
        if handle is None:
            return False
        observed = self.authority.observe_exact(handle)
        if observed is None or not observed.running:
            # A logical generation without a physical realization is not warm
            # state. Converge it before a producer creates the replacement.
            self.authority.release(handle)
            return False
        guard = self.lease_guard_factory.create((handle,))
        try:
            guard.start()
        except BaseException:
            # The recovered durable lease remains fenced; a later controller
            # can retry exact adoption after this process relinquishes control.
            guard.close()
            raise
        self.handle = handle
        self.guard = guard
        return True

    def attach_existing(self) -> bool:
        """Reattach only an already-running capsule; never create/start one."""

        with self.lock:
            if self.handle is not None:
                self.assert_healthy()
                return True
            with self.realization_singleflight.producer(
                "environment-runtime",
                self.runtime_identity_digest,
            ):
                return self._attach_existing_locked()

    def start(self) -> None:
        with self.lock:
            if self.handle is not None:
                self.assert_healthy()
                return
            # Cross-process producer fence: after another producer exits we
            # re-read durable Docker/lease authority and adopt before creating.
            with self.realization_singleflight.producer(
                "environment-runtime",
                self.runtime_identity_digest,
            ):
                if self._attach_existing_locked():
                    return
                handle = self.authority.reserve(
                    allocation_id=self.allocation_id,
                    holder_scope=PLATFORM_SCOPE,
                    image=self.image,
                    runtime_identity_digest=self.runtime_identity_digest,
                )
                try:
                    argv = (
                        *self.authority.docker_run_prefix(handle),
                        "-d",
                        "--user",
                        f"{os.getuid()}:{os.getgid()}",
                        "--network",
                        "host",
                        "--entrypoint",
                        "/bin/sh",
                        "-v",
                        f"{self.instances_root}:{self.instances_root}",
                        "-v",
                        f"{self.asset_root}:{self.asset_root}:ro",
                        "-v",
                        f"{self.recovery_root}:{self.recovery_root}",
                        self.image,
                        "-c",
                        "while :; do sleep 3600; done",
                    )
                    result = self.runner.run(argv, timeout_seconds=60.0)
                    if result.returncode != 0:
                        raise RuntimeError(
                            "Minecraft warm capsule launch failed: "
                            + result.stderr[-2000:]
                        )
                    self.authority.confirm_running(handle, timeout_seconds=30.0)
                    guard = self.lease_guard_factory.create((handle,))
                    guard.start()
                    self.handle = handle
                    self.guard = guard
                except BaseException:
                    try:
                        self.authority.release(handle)
                    finally:
                        self.handle = None
                        self.guard = None
                    raise

    def close(self) -> None:
        """Detach this consumer while retaining the host-scoped warm capsule."""

        with self.lock:
            handle = self.handle
            guard = self.guard
            if handle is None:
                return
            if guard is not None:
                guard.close()
            # Physical retirement is external authority/GC work. Normal run
            # shutdown only relinquishes heartbeat ownership so a later run can
            # targeted-recover the exact still-running capsule generation.
            self.handle = None
            self.guard = None


class _DockerLiveness:
    def __init__(self, server: "_DockerMinecraftServer") -> None:
        self.server = server

    def alive(self, process: ServiceProcessIdentity) -> bool:
        return self.server.alive(process)


class _DockerMinecraftServer:
    def __init__(
        self,
        *,
        spec: MinecraftServerSpec,
        environment_generation: str,
        capsule: _DockerMinecraftCapsule,
        runner: LocalCommandRunnerPort,
        task_group: TaskGroupPort,
        asset_root: Path,
        recovery_root: Path,
    ) -> None:
        self.spec = spec
        self.capsule = capsule
        self.authority = capsule.authority
        self.runner = runner
        self.task_group = task_group
        self.asset_root = asset_root.resolve()
        self.recovery_root = recovery_root.resolve()
        self.process: ServiceProcessIdentity | None = None
        self.pid_path = (
            self.recovery_root
            / f"minecraft-server-{spec.bound_port}.pid"
        )
        Path(spec.workdir).mkdir(parents=True, exist_ok=True)
        self.recovery_root.mkdir(parents=True, exist_ok=True)
        prepared = prepare_server_files(
            spec,
            accept_eula=True,
            rcon_password=None,
        )
        artifact_digest, _ = sha256_file(Path(spec.jar_path))
        docker = (
            shutil.which(self.authority.runtime.docker_executable)
            or "/usr/bin/docker"
        )
        environment_digest = canonical_digest({
            "image": capsule.image,
            "image_digest": capsule.image_digest,
            "capsule_generation": capsule.generation_digest,
        })
        runtime_digest = canonical_digest({
            "schema": "noetrium.minecraft.docker-runtime.v2",
            "environment_generation": environment_generation,
            "image_digest": capsule.image_digest,
            "capsule_generation": capsule.generation_digest,
            "command": spec.command(),
            "properties_digest": prepared.properties_digest,
        })
        self.contract = ServiceLaunchContract(
            service_id=(
                "minecraft:"
                + canonical_digest({
                    "workdir": spec.workdir,
                    "port": spec.bound_port,
                })[:24]
            ),
            generation=canonical_digest({
                "server": spec,
                "environment_generation": environment_generation,
                "capsule_generation": capsule.generation_digest,
            }),
            executable=docker,
            argv=(docker, "exec", capsule.image),
            cwd=spec.workdir,
            environment_digest=environment_digest,
            artifact_digest=artifact_digest,
            runtime_identity_digest=runtime_digest,
            readiness_timeout_s=180.0,
            stop_timeout_s=30.0,
            heartbeat_interval_s=5.0,
        )

    @property
    def container_name(self) -> str:
        return self.capsule.container_name

    def _proc_start_identity(self, pid: int) -> str:
        self.capsule.assert_healthy()
        result = self.runner.run(
            (
                self.authority.runtime.docker_executable,
                "exec",
                self.container_name,
                "/bin/sh",
                "-c",
                f"cat /proc/{pid}/stat",
            ),
            timeout_seconds=10.0,
        )
        if result.returncode != 0:
            raise RuntimeError("Minecraft Java process is not alive")
        raw = result.stdout.strip()
        right = raw.rfind(")")
        if right < 0:
            raise RuntimeError("Minecraft Java procfs identity malformed")
        fields = raw[right + 2 :].split()
        if len(fields) <= 19:
            raise RuntimeError("Minecraft Java procfs identity incomplete")
        observed = self.authority.runtime.inspect(self.container_name)
        if observed is None or not observed.running:
            raise RuntimeError("Minecraft warm capsule disappeared")
        return (
            "docker-exec:"
            + observed.container_id
            + ":"
            + str(pid)
            + ":"
            + fields[19]
        )

    def _process_identity(self) -> ServiceProcessIdentity:
        try:
            raw = self.pid_path.read_text(encoding="utf-8").strip()
            pid = int(raw)
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "Minecraft Java process pid publication is missing"
            ) from exc
        if pid <= 0:
            raise RuntimeError("Minecraft Java process pid is invalid")
        return ServiceProcessIdentity(
            pid,
            self._proc_start_identity(pid),
        )

    def alive(self, process: ServiceProcessIdentity) -> bool:
        for attempt in range(3):
            try:
                current = self._process_identity()
            except BaseException:
                if attempt < 2:
                    time.sleep(0.02)
                    continue
                return False
            return (
                current.pid == process.pid
                and current.start_identity == process.start_identity
            )
        return False

    def _terminate_pid(
        self,
        process: ServiceProcessIdentity,
        *,
        signal: str,
    ) -> None:
        result = self.runner.run(
            (
                self.authority.runtime.docker_executable,
                "exec",
                self.container_name,
                "/bin/sh",
                "-c",
                f"kill -{signal} {process.pid}",
            ),
            timeout_seconds=10.0,
        )
        if result.returncode != 0 and self.alive(process):
            raise RuntimeError(
                f"Minecraft Java process {signal} failed: "
                + result.stderr[-1000:]
            )

    def start(self) -> ServiceStartOutcome:
        if self.process is not None:
            if not self.alive(self.process):
                raise RuntimeError(
                    "Minecraft server process identity became stale"
                )
            return ServiceStartOutcome(
                self.contract.digest(),
                self.process,
                "docker-exec-running:" + self.container_name,
                time.time(),
                (
                    "docker-capsule:" + self.container_name,
                    f"minecraft-java:{self.process.pid}",
                ),
            )
        self.capsule.start()
        self.pid_path.unlink(missing_ok=True)
        workdir = str(Path(self.spec.workdir).resolve())
        log_path = str(
            Path(self.spec.workdir).resolve()
            / "noetrium-minecraft-server.log"
        )
        shell = (
            f"echo $$ > {shlex.quote(str(self.pid_path))}; "
            f"exec {shlex.join(self.spec.command())} "
            f">> {shlex.quote(log_path)} 2>&1"
        )
        try:
            result = self.runner.run(
                (
                    self.authority.runtime.docker_executable,
                    "exec",
                    "-d",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "-w",
                    workdir,
                    self.container_name,
                    "/bin/sh",
                    "-c",
                    shell,
                ),
                timeout_seconds=30.0,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "Minecraft Java launch in warm capsule failed: "
                    + result.stderr[-2000:]
                )
            deadline = time.monotonic() + 10.0
            last_error: BaseException | None = None
            while time.monotonic() < deadline:
                try:
                    self.process = self._process_identity()
                    break
                except BaseException as exc:
                    last_error = exc
                    time.sleep(0.02)
            if self.process is None:
                raise RuntimeError(
                    "Minecraft Java process did not publish identity"
                ) from last_error
            return ServiceStartOutcome(
                self.contract.digest(),
                self.process,
                "docker-exec-running:" + self.container_name,
                time.time(),
                (
                    "docker-capsule:" + self.container_name,
                    f"minecraft-java:{self.process.pid}",
                ),
            )
        except BaseException:
            process = self.process
            if process is not None:
                try:
                    self._terminate_pid(process, signal="KILL")
                except BaseException:
                    pass
            self.process = None
            self.pid_path.unlink(missing_ok=True)
            raise

    def verify_ready(self) -> ServiceReadyObservation:
        if self.process is None:
            raise RuntimeError("Minecraft Docker server is not started")
        self.capsule.assert_healthy()
        evidence = MinecraftTcpReadinessProbe(
            host=self.spec.host,
            port=self.spec.bound_port,
            task_group=self.task_group,
        ).wait_ready(
            self.process,
            self.contract,
            _DockerLiveness(self),
        )
        return ServiceReadyObservation(
            self.contract.digest(),
            self.process,
            evidence,
            time.time(),
            (
                "docker-capsule:" + self.container_name,
                f"minecraft-java:{self.process.pid}",
            ),
        )

    def stop(self) -> ServiceStopOutcome:
        process = self.process
        if process is None:
            self.pid_path.unlink(missing_ok=True)
            return ServiceStopOutcome(
                self.contract.digest(),
                True,
                (),
            )
        if self.alive(process):
            self._terminate_pid(process, signal="TERM")
            deadline = time.monotonic() + self.contract.stop_timeout_s
            while self.alive(process) and time.monotonic() < deadline:
                time.sleep(0.05)
            if self.alive(process):
                self._terminate_pid(process, signal="KILL")
                deadline = time.monotonic() + 5.0
                while self.alive(process) and time.monotonic() < deadline:
                    time.sleep(0.05)
            if self.alive(process):
                raise RuntimeError(
                    "Minecraft Java process survived fenced cleanup"
                )
        self.process = None
        self.pid_path.unlink(missing_ok=True)
        return ServiceStopOutcome(
            self.contract.digest(),
            True,
            (
                f"minecraft-java-stopped:{process.pid}",
                "docker-capsule-retained:" + self.container_name,
            ),
        )


class _DockerServerFactory:
    def __init__(
        self,
        *,
        authority,
        lease_guard_factory,
        image,
        image_digest,
        holder_scope,
        runner,
        task_group,
        process_supervisor,
        asset_root,
        recovery_root,
        capsule,
    ) -> None:
        self.authority = authority
        self.lease_guard_factory = lease_guard_factory
        self.image = image
        self.image_digest = image_digest
        self.holder_scope = holder_scope
        self.runner = runner
        self.task_group = task_group
        self.process_supervisor = process_supervisor
        self.asset_root = asset_root
        self.recovery_root = recovery_root
        self.capsule = capsule
        self.by_port: dict[int, _DockerMinecraftServer] = {}
        self.lock = threading.RLock()

    def create(self, server_spec, *, environment_generation):
        server = _DockerMinecraftServer(
            spec=server_spec,
            environment_generation=environment_generation,
            capsule=self.capsule,
            runner=self.runner,
            task_group=self.task_group,
            asset_root=self.asset_root,
            recovery_root=self.recovery_root,
        )
        with self.lock:
            self.by_port[server_spec.bound_port] = server
        return server

    def bridge_process_factory(self, port: int):
        def spawn(_command: list[str], **process_options: object):
            with self.lock:
                server = self.by_port.get(port)
            if server is None:
                raise RuntimeError("Minecraft bridge has no server generation")
            environment = process_options.get("env")
            if not isinstance(environment, dict):
                environment = os.environ.copy()
            return self.process_supervisor.spawn_interactive(
                (
                    self.authority.runtime.docker_executable,
                    "exec",
                    "-i",
                    "-w",
                    _BRIDGE_ROOT,
                    "-e",
                    f"NODE_PATH={_BRIDGE_ROOT}/node_modules",
                    server.container_name,
                    _NODE,
                    f"{_BRIDGE_ROOT}/bridge.js",
                ),
                cwd="/",
                environment={str(k): str(v) for k, v in environment.items()},
                start_new_session=True,
                creationflags=0,
            )
        return spawn


class _DockerEnvironmentFactory:
    def __init__(self, *, servers, operating_system, process_supervisor, task_group) -> None:
        self.servers = servers
        self.operating_system = operating_system
        self.process_supervisor = process_supervisor
        self.task_group = task_group

    def compose(self, spec: MinecraftEnvironmentSpec, *, checkpoint=None) -> MinecraftEnvironmentAssembly:
        return compose_minecraft_environment(
            spec,
            operating_system=self.operating_system,
            checkpoint=checkpoint,
            process_factory=self.servers.bridge_process_factory(spec.endpoint.bound_port),
            process_supervisor=self.process_supervisor,
            task_group=self.task_group,
        )


@dataclass(slots=True)
class _LifetimeRuntime:
    binding: object
    session: EnvironmentSession
    workdir: Path
    instance_handle: EnvironmentInstanceLeaseHandle
    instance_guard: object


class LocalMinecraftLifetimeSessionAuthority(EnvironmentLifetimeSessionAuthorityPort):
    def __init__(
        self,
        *,
        environment_config: Mapping[str, object],
        state_root: Path,
        asset_root: Path,
        endpoint_allocations,
        endpoint_lease_guard_factory,
        docker_authority,
        docker_lease_guard_factory,
        environment_instance_authority: EnvironmentInstanceLeaseAuthority,
        environment_instance_lease_guard_factory,
        image: str,
        image_digest: str,
        runner,
        operating_system,
        process_supervisor,
        task_group,
        prewarm_task_group,
        owner_generation_id: str,
        realization_singleflight: ContentAddressedSingleFlight,
    ) -> None:
        self.config = dict(environment_config)
        self.state_root = state_root.resolve()
        self.asset_root = asset_root.resolve()
        self.endpoint_allocations = endpoint_allocations
        self.endpoint_lease_guard_factory = endpoint_lease_guard_factory
        self.docker_authority = docker_authority
        self.docker_lease_guard_factory = docker_lease_guard_factory
        if not isinstance(environment_instance_authority, EnvironmentInstanceLeaseAuthority):
            raise TypeError("Minecraft lifetime authority requires EnvironmentInstanceLeaseAuthority")
        self.environment_instance_authority = environment_instance_authority
        self.environment_instance_lease_guard_factory = environment_instance_lease_guard_factory
        self.image = image
        self.image_digest = image_digest
        self.runner = runner
        self.operating_system = operating_system
        self.process_supervisor = process_supervisor
        self.task_group = task_group
        self.prewarm_task_group = prewarm_task_group
        self.owner_generation_id = owner_generation_id
        self.lock = threading.RLock()
        self.runtimes: dict[str, _LifetimeRuntime] = {}
        self._lifetime_locks: dict[str, threading.Lock] = {}
        self._retirements: dict[str, object] = {}
        self._preparations: dict[str, object] = {}
        self._preparation_failures: dict[str, BaseException] = {}
        self._retirement_failures: list[BaseException] = []
        self._retirement_sequence = 0
        self._instance_sequence_lock = threading.Lock()
        self.asset = self.asset_root / "server.jar"
        if not self.asset.is_file():
            raise FileNotFoundError(f"Minecraft server asset missing: {self.asset}")
        self.asset_digest, _ = sha256_file(self.asset)
        self.profile_id = "minecraft.local"
        self.runtime_identity_digest = canonical_digest(
            {
                "implementation_id": "minecraft.mineflayer",
                "image_digest": self.image_digest,
                "asset_digest": self.asset_digest,
            }
        )
        self.profile_revision = canonical_digest(
            {
                "profile_id": self.profile_id,
                "config": self.config,
                "runtime_identity_digest": self.runtime_identity_digest,
            }
        )
        self.profile_materialization = EnvironmentProfileMaterialization(
            profile_id=self.profile_id,
            profile_revision=self.profile_revision,
            build_input_digest=canonical_digest(
                {"config": self.config, "asset_digest": self.asset_digest}
            ),
            runtime_identity_digest=self.runtime_identity_digest,
            deployment_receipt_digest=self.image_digest,
            runtime_reference=self.image,
        )
        catalog = self.environment_instance_authority.catalog
        catalog.register_profile_revision(
            EnvironmentProfileRevision(
                self.profile_id,
                "minecraft",
                self.profile_revision,
            )
        )
        catalog.register_profile_materialization(self.profile_materialization)
        self.instances_root = self.state_root / "environment-instances"
        self.recovery_root = self.state_root / "environment-recovery"
        self.instances_root.mkdir(parents=True, exist_ok=True)
        self.recovery_root.mkdir(parents=True, exist_ok=True)
        self._capsule = _DockerMinecraftCapsule(
            authority=self.docker_authority,
            lease_guard_factory=self.docker_lease_guard_factory,
            image=self.image,
            image_digest=self.image_digest,
            runner=self.runner,
            instances_root=self.instances_root,
            asset_root=self.asset_root,
            recovery_root=self.recovery_root,
            realization_singleflight=realization_singleflight,
            runtime_identity_digest=self.runtime_identity_digest,
        )
        # Materialization is a pure control-plane adoption opportunity. It may
        # reacquire an existing exact warm capsule generation, but never starts
        # a new container. This protects required warm state before generic
        # orphan reconciliation begins.
        self._capsule.attach_existing()
        self._instance_sequence = 0
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.local-minecraft-lifetime-authority.v2",
                "config": self.config,
                "image_digest": image_digest,
                "asset_digest": self.asset_digest,
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def effect_recovery_durability(self) -> str:
        return "crash_durable"

    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]:
        contracts = minecraft_action_catalog()
        version = str(self.config.get("minecraft_version", "1.21.1"))
        return (
            EnvironmentCapabilityDescriptor(
                capability_id="minecraft.world",
                version=version,
                action_types=tuple(contract.action_type for contract in contracts),
                query_types=("capabilities", "state", "entity", "task"),
                metadata={
                    "bridge": "replaceable",
                    "action_contracts": tuple(
                        contract.as_payload() for contract in contracts
                    ),
                },
            ),
        )

    def _open(self, context: ExecutionContext) -> _LifetimeRuntime:
        lifetime_id = context.lifetime_id
        if not lifetime_id:
            raise ValueError("Minecraft runtime requires lifetime_id")
        key = canonical_digest({"lifetime_id": lifetime_id})
        workdir = (self.instances_root / key).resolve()
        recovery = (self.recovery_root / key).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        recovery.mkdir(parents=True, exist_ok=True)
        version = str(self.config.get("minecraft_version", "1.21.1"))
        if version != "1.21.1":
            raise RuntimeError(f"unsupported materialized Minecraft version: {version}")
        branch_id = "assignment-" + key[:24]
        branch_scope = ScopeIdentity(ScopeKind.BRANCH, branch_id)
        catalog = self.environment_instance_authority.catalog
        binding_id = "minecraft-binding:" + key[:24]
        role = "minecraft.assignment." + key[:24]
        try:
            instance_handle = (
                self.environment_instance_authority.acquire_reusable_instance(
                    self.profile_id,
                    self.profile_revision,
                    self.runtime_identity_digest,
                    self.profile_materialization.materialization_digest,
                    binding_id=binding_id,
                    role=role,
                    scope=PLATFORM_SCOPE,
                )
            )
        except KeyError:
            with self._instance_sequence_lock:
                self._instance_sequence += 1
                instance_sequence = self._instance_sequence
            instance_id = (
                "minecraft:"
                + self.owner_generation_id[:16]
                + ":slot:"
                + f"{instance_sequence:08d}"
            )
            instance_handle = (
                self.environment_instance_authority.provision_reusable_instance(
                    EnvironmentInstance(
                        instance_id=instance_id,
                        resolved_spec_digest=canonical_digest({
                            "implementation_id": "minecraft.mineflayer",
                            "config": self.config,
                        }),
                        backend="minecraft.mineflayer",
                        runtime_reference=(
                            self.profile_materialization.runtime_reference
                        ),
                        runtime_identity_digest=self.runtime_identity_digest,
                        materialization_digest=(
                            self.profile_materialization.materialization_digest
                        ),
                        scope=PLATFORM_SCOPE,
                        profile_id=self.profile_id,
                        profile_revision=self.profile_revision,
                    ),
                    binding_id=binding_id,
                    role=role,
                    scope=PLATFORM_SCOPE,
                )
            )
        instance_guard = self.environment_instance_lease_guard_factory.create(
            (instance_handle,)
        )
        instance_guard.start()
        session_generation = canonical_digest(
            {"lifetime_id": lifetime_id, "run_id": context.run_id}
        )
        servers = _DockerServerFactory(
            authority=self.docker_authority,
            lease_guard_factory=self.docker_lease_guard_factory,
            image=self.image,
            image_digest=self.image_digest,
            holder_scope=branch_scope,
            runner=self.runner,
            task_group=self.task_group,
            process_supervisor=self.process_supervisor,
            asset_root=self.asset_root,
            recovery_root=recovery,
            capsule=self._capsule,
        )
        environment_factory = _DockerEnvironmentFactory(
            servers=servers,
            operating_system=self.operating_system,
            process_supervisor=self.process_supervisor,
            task_group=self.task_group,
        )
        branch_factory = MinecraftBranchRuntimeFactory(
            endpoint_allocations=self.endpoint_allocations,
            environment_factory=environment_factory,
            server_factory=servers,
            lease_guard_factory=self.endpoint_lease_guard_factory,
            action_recovery_root=str(recovery),
        )
        if context.assignment_seed is None:
            raise RuntimeError(
                "Minecraft assignment runtime requires Study assignment seed"
            )
        assignment_seed_context = replace(context, task_id=None)
        world_seed = str(
            assignment_seed_context.random_seed("environment:minecraft:world")
        )
        branch = MinecraftWorldBranch(
            branch_id=branch_id,
            cut_id="fresh-world:" + key[:24],
            workdir=str(workdir),
            level_name="research-world",
            manifest_digest=canonical_digest(
                {
                    "schema": "noetrium.fresh-minecraft-world.v1",
                    "lifetime_id": lifetime_id,
                    "minecraft_version": version,
                    "asset_digest": self.asset_digest,
                    "assignment_seed": context.assignment_seed,
                    "world_seed": world_seed,
                }
            ),
            cleanup_ref="lifetime:" + key,
        )
        environment_template = MinecraftEnvironmentSpec(
            endpoint=MinecraftEndpointSpec("127.0.0.1", None),
            bridge=MinecraftBridgeSpec(
                command=(_NODE, f"{_BRIDGE_ROOT}/bridge.js"),
                cwd=_BRIDGE_ROOT,
                action_recovery_root=str(recovery),
            ),
            agent=MinecraftAgentSpec(username="ResearchBot", auth="offline", version=version),
        )
        server_template = MinecraftServerSpec(
            jar_path=str(self.asset),
            workdir=str(workdir),
            java_executable=_JAVA,
            host="127.0.0.1",
            port=None,
            level_name="research-world",
            level_seed=world_seed,
            online_mode=False,
            xms="512M",
            xmx="2G",
        )
        try:
            binding = branch_factory.open(
                MinecraftBranchRuntimeRequest(
                    branch=branch,
                    environment_template=environment_template,
                    server_template=server_template,
                    session_id=(
                        "minecraft:" + key[:24] + ":" + session_generation[:16]
                    ),
                    scope=branch_scope,
                )
            )
            session = binding.open_session(object())
        except BaseException:
            instance_guard.close()
            current_handle = instance_guard.handles[0]
            self.environment_instance_authority.release(current_handle)
            raise
        return _LifetimeRuntime(
            binding,
            session,
            workdir,
            instance_guard.handles[0],
            instance_guard,
        )

    def _reap_completed_retirements(self) -> None:
        with self.lock:
            completed = tuple(
                (lifetime_id, handle)
                for lifetime_id, handle in self._retirements.items()
                if handle.done()
            )
        if not completed:
            return

        failures: list[BaseException] = []
        for lifetime_id, handle in completed:
            try:
                handle.result()
            except BaseException as exc:
                exc.add_note(
                    "Minecraft lifetime retirement failed: " + lifetime_id
                )
                failures.append(exc)

        with self.lock:
            for lifetime_id, handle in completed:
                if self._retirements.get(lifetime_id) is handle:
                    del self._retirements[lifetime_id]
                    self._lifetime_locks.pop(lifetime_id, None)
            self._retirement_failures.extend(failures)

    def _reap_completed_preparations(self) -> None:
        with self.lock:
            completed = tuple(
                (lifetime_id, handle)
                for lifetime_id, handle in self._preparations.items()
                if handle.done()
            )
        for lifetime_id, handle in completed:
            failure = None
            try:
                handle.result()
            except BaseException as exc:
                failure = exc
            with self.lock:
                if self._preparations.get(lifetime_id) is handle:
                    self._preparations.pop(lifetime_id, None)
                    if failure is not None:
                        self._preparation_failures[lifetime_id] = failure

    def prepare(self, context: ExecutionContext) -> None:
        self._reap_completed_preparations()
        lifetime_id = context.lifetime_id
        if type(lifetime_id) is not str or not lifetime_id.strip():
            raise ValueError("Minecraft preparation requires lifetime_id")
        with self.lock:
            if lifetime_id in self.runtimes:
                return
            if lifetime_id in self._retirements:
                raise RuntimeError(
                    "Minecraft lifetime is already retiring or retired: "
                    + lifetime_id
                )
            failure = self._preparation_failures.get(lifetime_id)
            if failure is not None:
                raise RuntimeError(
                    "Minecraft lifetime preparation previously failed: "
                    + lifetime_id
                ) from failure
            if lifetime_id in self._preparations:
                return

        def materialize(_context) -> None:
            self.session_for(context)

        handle = self.prewarm_task_group.submit(
            ExecutionSpec(
                task_id=(
                    "minecraft-lifetime-prewarm:"
                    + canonical_digest(
                        {
                            "lifetime_id": lifetime_id,
                            "run_id": context.run_id,
                            "owner_generation_id": self.owner_generation_id,
                        }
                    )[:32]
                ),
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
            ),
            materialize,
        )
        with self.lock:
            existing = self._preparations.get(lifetime_id)
            if existing is None:
                self._preparations[lifetime_id] = handle
            else:
                # The per-lifetime submission race is harmless but must not
                # leave an untracked task. Wait for the duplicate now.
                handle.result()

    def session_for(self, context: ExecutionContext) -> EnvironmentSession:
        self._reap_completed_retirements()
        self._reap_completed_preparations()
        lifetime_id = context.lifetime_id
        if not lifetime_id:
            raise ValueError("Minecraft runtime requires lifetime_id")
        with self.lock:
            failure = self._preparation_failures.pop(lifetime_id, None)
            if failure is not None:
                raise RuntimeError(
                    "Minecraft lifetime preparation failed: " + lifetime_id
                ) from failure
            lifetime_lock = self._lifetime_locks.get(lifetime_id)
            if lifetime_lock is None:
                lifetime_lock = threading.Lock()
                self._lifetime_locks[lifetime_id] = lifetime_lock
        # Physical environment creation may wait on Docker, server readiness and
        # the Mineflayer handshake. Serialize only identical lifetimes; unrelated
        # assignments must not queue behind one global authority lock.
        with lifetime_lock:
            with self.lock:
                if lifetime_id in self._retirements:
                    raise RuntimeError(
                        "Minecraft lifetime is already retiring or retired: "
                        + lifetime_id
                    )
                row = self.runtimes.get(lifetime_id)
            if row is None:
                opened = self._open(context)
                with self.lock:
                    row = self.runtimes.get(lifetime_id)
                    if row is None:
                        self.runtimes[lifetime_id] = opened
                        row = opened
                if row is not opened:
                    # The per-lifetime lock makes this unreachable in normal use,
                    # but fail closed against future lock-policy drift.
                    opened.binding.close()
                    opened.instance_guard.close()
                    self.environment_instance_authority.release(
                        opened.instance_guard.handles[0]
                    )
            row.instance_guard.assert_healthy()
            return row.session

    def _retire_runtime(
        self,
        lifetime_id: str,
        row: _LifetimeRuntime,
    ) -> None:
        physical_closed = False
        try:
            row.binding.close()
            shutil.rmtree(row.workdir, ignore_errors=False)
            recovery = (
                self.recovery_root
                / canonical_digest({"lifetime_id": lifetime_id})
            ).resolve()
            shutil.rmtree(recovery, ignore_errors=False)
            physical_closed = True
        finally:
            row.instance_guard.close()
            current_handle = row.instance_guard.handles[0]
            if physical_closed:
                proof = EnvironmentCleanlinessProof(
                    instance_id=current_handle.instance.instance_id,
                    profile_revision=current_handle.instance.profile_revision,
                    runtime_identity_digest=(
                        current_handle.instance.runtime_identity_digest
                    ),
                    materialization_digest=(
                        current_handle.instance.materialization_digest
                    ),
                    generation=current_handle.instance.generation,
                    kind=EnvironmentCleanlinessKind.OVERLAY_DESTROYED,
                    proof_digest=canonical_digest(
                        {
                            "schema": (
                                "noetrium.minecraft-instance-cleanliness.v1"
                            ),
                            "instance_id": (
                                current_handle.instance.instance_id
                            ),
                            "generation": current_handle.instance.generation,
                            "workdir": str(row.workdir),
                            "overlay_destroyed": True,
                            "capsule_generation": (
                                self._capsule.generation_digest
                            ),
                        }
                    ),
                )
                self.environment_instance_authority.release(
                    current_handle,
                    cleanliness=proof,
                )
            else:
                self.environment_instance_authority.release(current_handle)

    def release(self, lifetime_id: str) -> None:
        self._reap_completed_retirements()
        self._reap_completed_preparations()
        with self.lock:
            preparation = self._preparations.get(lifetime_id)
        if preparation is not None:
            try:
                preparation.result()
            finally:
                self._reap_completed_preparations()
        with self.lock:
            lifetime_lock = self._lifetime_locks.get(lifetime_id)
            if lifetime_lock is None:
                lifetime_lock = threading.Lock()
                self._lifetime_locks[lifetime_id] = lifetime_lock
        with lifetime_lock:
            with self.lock:
                if lifetime_id in self._retirements:
                    return
                row = self.runtimes.pop(lifetime_id, None)
                if row is None:
                    return
                self._retirement_sequence += 1
                retirement_sequence = self._retirement_sequence

            def retire(_context) -> None:
                self._retire_runtime(lifetime_id, row)

            try:
                handle = self.task_group.submit(
                    ExecutionSpec(
                        task_id=(
                            "minecraft-lifetime-retire:"
                            + canonical_digest(
                                {
                                    "lifetime_id": lifetime_id,
                                    "sequence": retirement_sequence,
                                    "owner_generation_id": (
                                        self.owner_generation_id
                                    ),
                                }
                            )[:32]
                        ),
                        lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    ),
                    retire,
                )
            except BaseException:
                # Structured submission should be available while Trials are
                # running. If the group is already converging, perform the
                # retirement synchronously rather than leaking the lease.
                self._retire_runtime(lifetime_id, row)
                raise

            with self.lock:
                self._retirements[lifetime_id] = handle

    def close(self) -> None:
        with self.lock:
            preparations = tuple(self._preparations.items())
        preparation_errors: list[BaseException] = []
        for lifetime_id, handle in preparations:
            try:
                handle.result()
            except BaseException as exc:
                exc.add_note(
                    "Minecraft lifetime preparation failed during close: "
                    + lifetime_id
                )
                preparation_errors.append(exc)
        self._reap_completed_preparations()

        with self.lock:
            lifetime_ids = tuple(self.runtimes)
        errors: list[BaseException] = list(preparation_errors)
        for lifetime_id in lifetime_ids:
            try:
                self.release(lifetime_id)
            except BaseException as exc:
                errors.append(exc)

        # Physical retirements are allowed off the Trial critical path, but
        # never outside structured lifetime ownership. Drain every retirement
        # before closing the shared warm capsule.
        with self.lock:
            retirements = tuple(self._retirements.items())
            errors.extend(self._retirement_failures)
            self._retirement_failures.clear()
        for lifetime_id, handle in retirements:
            try:
                handle.result()
            except BaseException as exc:
                exc.add_note(
                    "Minecraft lifetime retirement failed: " + lifetime_id
                )
                errors.append(exc)
        with self.lock:
            for lifetime_id, _handle in retirements:
                self._lifetime_locks.pop(lifetime_id, None)
            self._retirements.clear()

        try:
            self._capsule.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ExceptionGroup("Minecraft lifetime cleanup failed", errors)


__all__ = ["LocalMinecraftLifetimeSessionAuthority"]
