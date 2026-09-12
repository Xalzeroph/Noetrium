from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable, Mapping
import asyncio
import hashlib
from pathlib import Path
from threading import Lock
import time

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ExactServiceRuntimePort,
    ServiceLaunchContract,
    ServiceReadyObservation,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.infrastructure.lifecycle.service.composition import LocalServiceRuntimeComposer
from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.service.runtime.environment import MaterializedServiceEnvironment
from noetrium_platform.infrastructure.lifecycle.service.runtime.preflight import LocalServiceLaunchPreflight
from noetrium_platform.infrastructure.lifecycle.service.runtime.process_contracts import (
    ExactProcessBackend,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from ..providers.rcon import MinecraftRconConsole
from ..providers.server_files import prepare_server_files, sha256_file

from ..api import MinecraftDiagnosticsPort, MinecraftServerSpec


class MinecraftServerServiceError(RuntimeError):
    """MC composition could not bind or operate the generic service port."""


class MinecraftTcpReadinessProbe:
    """TCP readiness whose network wait is owned by the ASYNC_IO lane."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        task_group: TaskGroupPort,
        poll_interval_s: float = 0.25,
    ) -> None:
        if not host.strip() or not 1 <= port <= 65535 or poll_interval_s <= 0:
            raise ValueError("Minecraft TCP readiness configuration is invalid")
        self.host = host
        self.port = port
        self.poll_interval_s = poll_interval_s
        self._task_group = task_group
        self._sequence = 0
        self._sequence_lock = Lock()

    async def _wait_ready_async(self, context, process, contract: ServiceLaunchContract, backend: ExactProcessBackend) -> str:
        last_error = "not-probed"
        while True:
            context.checkpoint()
            if not backend.alive(process):
                raise MinecraftServerServiceError(
                    f"Minecraft server process exited before TCP readiness: {self.host}:{self.port}"
                )
            writer = None
            try:
                connect_timeout = min(1.0, self.poll_interval_s + 0.5)
                async with asyncio.timeout(connect_timeout):
                    _reader, writer = await asyncio.open_connection(self.host, self.port)
                payload = f"{contract.digest()}:{process.pid}:{process.start_identity}:{self.host}:{self.port}"
                return "minecraft-tcp-ready:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
            except (OSError, TimeoutError) as exc:
                last_error = f"{type(exc).__name__}:{exc}"
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass
            remaining = context.remaining_seconds
            delay = self.poll_interval_s if remaining is None else min(self.poll_interval_s, remaining)
            if delay <= 0:
                context.checkpoint()
            await asyncio.sleep(delay)

    def wait_ready(self, process, contract: ServiceLaunchContract, backend: ExactProcessBackend) -> str:
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        deadline = Deadline.after(contract.readiness_timeout_s)
        readiness_identity = canonical_digest(
            {
                "service_id": contract.service_id,
                "contract_digest": contract.digest(),
                "process_pid": process.pid,
                "process_start_identity": process.start_identity,
                "host": self.host,
                "port": self.port,
            }
        )
        handle = self._task_group.submit(
            ExecutionSpec(
                task_id=f"minecraft-tcp-readiness:{readiness_identity}:{sequence}",
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            self._wait_ready_async,
            process,
            contract,
            backend,
            deadline=deadline,
        )
        try:
            return handle.result(timeout=max(0.001, deadline.remaining_seconds))
        except TimeoutError as exc:
            handle.cancel()
            raise MinecraftServerServiceError(
                f"Minecraft server TCP readiness timed out for {self.host}:{self.port}"
            ) from exc


class MinecraftServerReadinessProbe:
    """Require the game endpoint and the configured RCON control plane."""

    def __init__(
        self,
        *,
        tcp: MinecraftTcpReadinessProbe,
        rcon: MinecraftRconConsole,
        rcon_command: str = "list",
        poll_interval_s: float = 0.25,
    ) -> None:
        if not rcon_command.strip() or poll_interval_s <= 0:
            raise ValueError("Minecraft RCON readiness configuration is invalid")
        self.tcp = tcp
        self.rcon = rcon
        self.rcon_command = rcon_command
        self.poll_interval_s = poll_interval_s

    def wait_ready(self, process, contract: ServiceLaunchContract, backend: ExactProcessBackend) -> str:
        tcp_evidence = self.tcp.wait_ready(process, contract, backend)
        deadline = time.monotonic() + contract.readiness_timeout_s
        last_error = "not-probed"
        while time.monotonic() < deadline:
            if not backend.alive(process):
                raise MinecraftServerServiceError(
                    "Minecraft server process exited before RCON readiness"
                )
            try:
                rcon_evidence = self.rcon.execute(
                    self.rcon_command,
                    timeout_s=min(1.0, max(0.1, deadline - time.monotonic())),
                )
                return "minecraft-server-ready:" + canonical_digest(
                    {
                        "tcp": tcp_evidence,
                        "rcon": rcon_evidence.evidence_ref,
                    }
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"
            time.sleep(self.poll_interval_s)
        raise MinecraftServerServiceError(
            f"Minecraft RCON readiness timed out: {last_error}"
        )


def build_server_service_contract(
    spec: MinecraftServerSpec,
    *,
    environment_digest: str,
    artifact_digest: str,
    runtime_identity_digest: str,
    generation: str = "minecraft-server-v1",
    readiness_timeout_s: float = 120.0,
    stop_timeout_s: float = 30.0,
    heartbeat_interval_s: float = 5.0,
) -> ServiceLaunchContract:
    return ServiceLaunchContract(
        service_id=f"minecraft.server.{spec.level_name}",
        generation=generation,
        executable=spec.java_executable,
        argv=spec.command(),
        cwd=spec.workdir,
        environment_digest=environment_digest,
        artifact_digest=artifact_digest,
        runtime_identity_digest=runtime_identity_digest,
        readiness_timeout_s=readiness_timeout_s,
        stop_timeout_s=stop_timeout_s,
        heartbeat_interval_s=heartbeat_interval_s,
    )


def compose_minecraft_server_service_runtime(
    spec: MinecraftServerSpec,
    contract: ServiceLaunchContract,
    *,
    environment: MaterializedServiceEnvironment,
    state_root: Path,
    intent_root: Path,
    capture_root: Path,
    operating_system: OperatingSystemRoute,
    process_backend: ExactProcessBackend | None = None,
    preflight: LocalServiceLaunchPreflight | None = None,
    rcon_password_provider: Callable[[], str] | None = None,
    task_group: TaskGroupPort,
) -> ExactServiceRuntimePort:
    """Bind MC endpoint readiness to the generic local service lifecycle.

    MC contributes only its endpoint-specific readiness probe. Process launch,
    capture, exact identity, state, stop and crash-recovery remain owned by the
    runtime/service composition module.
    """

    tcp_readiness = MinecraftTcpReadinessProbe(host=spec.host, port=spec.port, task_group=task_group)
    readiness = tcp_readiness
    if spec.rcon_endpoint is not None:
        if rcon_password_provider is None:
            raise MinecraftServerServiceError(
                "Minecraft RCON readiness requires an explicit password provider"
            )
        readiness = MinecraftServerReadinessProbe(
            tcp=tcp_readiness,
            rcon=MinecraftRconConsole(
                spec.rcon_endpoint,
                secret_provider=rcon_password_provider,
            ),
        )

    return LocalServiceRuntimeComposer(
        state_root=state_root,
        intent_root=intent_root,
        capture_root=capture_root,
        operating_system=operating_system,
        task_group=task_group,
        process_backend=process_backend,
    ).open(
        contract,
        environment=environment,
        readiness=readiness,
        preflight=preflight,
    )


@dataclass(slots=True)
class MinecraftServerServiceController:
    """MC composition facade over the platform's exact service lifecycle."""

    spec: MinecraftServerSpec
    contract: ServiceLaunchContract
    service_runtime: ExactServiceRuntimePort
    diagnostics: MinecraftDiagnosticsPort | None = None
    diagnostic_sink_failures: list[str] = field(default_factory=list, init=False, repr=False)

    def _event(
        self,
        event: str,
        *,
        level: str = "DEBUG",
        attributes: Mapping[str, JsonValue] | None = None,
    ) -> None:
        if self.diagnostics is None:
            return
        try:
            self.diagnostics.event(
                phase="server_service",
                event=event,
                level=level,
                attributes={"service_id": self.contract.service_id, **(attributes or {})},
                correlation_refs=(self.contract.digest(),),
            )
        except BaseException as exc:
            self.diagnostic_sink_failures.append(
                f"event:{event}:{type(exc).__name__}:{exc}"
            )
            return

    def _failure(self, code: str, exc: BaseException) -> None:
        if self.diagnostics is None:
            return
        try:
            self.diagnostics.failure(
                phase="server_service",
                code=code,
                message=describe_exception(exc).safe_message,
                exception=exc,
                attributes={"service_id": self.contract.service_id},
                correlation_refs=(self.contract.digest(),),
            )
        except BaseException as sink_exc:
            self.diagnostic_sink_failures.append(
                f"failure:{code}:{type(sink_exc).__name__}:{sink_exc}"
            )
            return

    def reconcile(self) -> ServiceReconcileObservation:
        self._event("MC_SERVER_RECONCILE_START")
        try:
            result = self.service_runtime.reconcile_exact(self.contract)
        except Exception as exc:
            self._failure("MC_SERVER_RECONCILE_FAILED", exc)
            raise
        self._event("MC_SERVER_RECONCILE_END", attributes={"state_present": result.state_present, "has_process": result.process is not None})
        return result

    def start(self) -> ServiceStartOutcome:
        self._event("MC_SERVER_START", level="INFO", attributes={"host": self.spec.host, "port": self.spec.port})
        try:
            result = self.service_runtime.start_exact(self.contract)
        except Exception as exc:
            self._failure("MC_SERVER_START_FAILED", exc)
            raise
        self._event("MC_SERVER_READY", level="INFO", attributes={"pid": result.process.pid, "ready_ref": result.ready_evidence_ref})
        return result

    def verify_ready(self) -> ServiceReadyObservation:
        try:
            return self.service_runtime.verify_ready_exact(self.contract)
        except Exception as exc:
            self._failure("MC_SERVER_READY_VERIFICATION_FAILED", exc)
            raise

    def stop(self) -> ServiceStopOutcome:
        self._event("MC_SERVER_STOP", level="INFO")
        try:
            result = self.service_runtime.stop_exact(self.contract)
        except Exception as exc:
            self._failure("MC_SERVER_STOP_FAILED", exc)
            raise
        self._event("MC_SERVER_STOPPED", level="INFO", attributes={"stopped": result.stopped})
        return result


@dataclass(frozen=True, slots=True)
class MinecraftServerServiceFactoryConfig:
    """All host-owned inputs needed to materialize one managed MC server."""

    environment: MaterializedServiceEnvironment
    state_root: Path
    intent_root: Path
    capture_root: Path
    operating_system: OperatingSystemRoute
    accept_eula: bool
    rcon_password_provider: Callable[[], str] | None = None
    readiness_timeout_s: float = 120.0
    stop_timeout_s: float = 30.0
    heartbeat_interval_s: float = 5.0
    process_backend: ExactProcessBackend | None = None
    task_group: TaskGroupPort | None = None

    def __post_init__(self) -> None:
        for name in ("state_root", "intent_root", "capture_root"):
            if not getattr(self, name).is_absolute():
                raise ValueError(f"Minecraft server service {name} must be absolute")
        if min(self.readiness_timeout_s, self.stop_timeout_s, self.heartbeat_interval_s) <= 0:
            raise ValueError("Minecraft server service timings must be positive")
        if self.rcon_password_provider is not None and not callable(self.rcon_password_provider):
            raise ValueError("Minecraft RCON password provider must be callable")
        if self.task_group is None:
            raise ValueError("Minecraft server service requires an explicit concurrency task_group")


class MinecraftServerServiceFactory:
    """Environment-owned branch server factory over the generic service OS."""

    def __init__(self, config: MinecraftServerServiceFactoryConfig) -> None:
        self.config = config

    def create(
        self,
        spec: MinecraftServerSpec,
        *,
        environment_generation: str,
    ) -> MinecraftServerServiceController:
        if not environment_generation.strip():
            raise MinecraftServerServiceError("environment generation is required")
        try:
            rcon_password = (
                self.config.rcon_password_provider()
                if self.config.rcon_password_provider is not None
                else None
            )
        except BaseException as exc:
            raise MinecraftServerServiceError("Minecraft RCON secret is unavailable") from exc
        prepared = prepare_server_files(
            spec,
            accept_eula=self.config.accept_eula,
            rcon_password=rcon_password,
        )
        artifact_digest = sha256_file(spec.jar_path)
        runtime_identity_digest = canonical_digest({
            "environment_generation": environment_generation,
            "java_executable": spec.java_executable,
            "command": spec.command(),
            "properties_digest": prepared.properties_digest,
        })
        contract = build_server_service_contract(
            spec,
            environment_digest=self.config.environment.digest,
            artifact_digest=artifact_digest,
            runtime_identity_digest=runtime_identity_digest,
            generation=canonical_digest({
                "server_spec": spec,
                "environment_generation": environment_generation,
                "properties_digest": prepared.properties_digest,
            }),
            readiness_timeout_s=self.config.readiness_timeout_s,
            stop_timeout_s=self.config.stop_timeout_s,
            heartbeat_interval_s=self.config.heartbeat_interval_s,
        )
        runtime = compose_minecraft_server_service_runtime(
            spec,
            contract,
            environment=self.config.environment,
            state_root=self.config.state_root,
            intent_root=self.config.intent_root,
            capture_root=self.config.capture_root,
            operating_system=self.config.operating_system,
            process_backend=self.config.process_backend,
            rcon_password_provider=(
                (lambda: rcon_password)
                if spec.rcon_endpoint is not None
                else None
            ),
            task_group=self.config.task_group,
        )
        return MinecraftServerServiceController(spec, contract, runtime)


__all__ = [
    "MinecraftServerServiceController",
    "MinecraftServerServiceFactory",
    "MinecraftServerServiceFactoryConfig",
    "MinecraftServerReadinessProbe",
    "MinecraftServerServiceError",
    "MinecraftTcpReadinessProbe",
    "build_server_service_contract",
    "compose_minecraft_server_service_runtime",
]
