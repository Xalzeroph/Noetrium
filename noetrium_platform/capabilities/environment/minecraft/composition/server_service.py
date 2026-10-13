from __future__ import annotations

import time
from dataclasses import dataclass, field
from collections.abc import Callable, Mapping
from typing import Protocol
import socket
import hashlib
from pathlib import Path
from threading import Lock

from noetrium_platform.substrate.api import (
    ExactServiceRuntimePort,
    MaterializedServiceEnvironment,
    ServiceEnvironmentPort,
    ServiceLaunchContract,
    ServiceLaunchPreflightPort,
    ServiceLaunchPreflightReport,
    ServiceProcessIdentity,
    ServiceProcessLivenessPort,
    ServiceReadinessProbePort,
    ServiceReadyObservation,
    ServiceReconcileObservation,
    ServiceRuntimeFactoryPort,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.foundation.kernel.kernel import (
    add_cost_wait_ns,
    add_cost_work,
    blocking_wait,
    JsonValue,
    canonical_digest,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.kernel.kernel import sha256_file
from ..providers.rcon import MinecraftRconConsole
from ..providers.server_files import prepare_server_files

from ..api import MinecraftDiagnosticsPort, MinecraftServerSpec


class MinecraftServerServiceError(RuntimeError):
    """MC composition could not bind or operate the generic service port."""


class _ReadinessWakePort(Protocol):
    def acknowledge(self) -> None: ...
    def wait_changed_since(
        self, expected_signature: object, *, timeout_seconds: float,
    ) -> bool: ...
    def close(self) -> None: ...


class MinecraftTcpReadinessProbe:
    """Exact TCP readiness executed in the owning BLOCKING_IO lifecycle task.

    Server realization is already scheduled on the platform's blocking-I/O
    authority. Submitting readiness back into another TaskGroup and then
    synchronously joining it creates a nested-pool dependency with no new
    physical ownership semantics and can starve under high frontier load.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        poll_interval_s: float = 0.25,
        wake_factory: Callable[[], _ReadinessWakePort] | None = None,
    ) -> None:
        if not host.strip() or not 1 <= port <= 65535 or poll_interval_s <= 0:
            raise ValueError("Minecraft TCP readiness configuration is invalid")
        self.host = host
        self.port = port
        self.poll_interval_s = poll_interval_s
        self._wake_factory = wake_factory

    def wait_ready(
        self,
        process,
        contract: ServiceLaunchContract,
        backend: ServiceProcessLivenessPort,
    ) -> str:
        return self.wait_ready_until(
            process,
            contract,
            backend,
            deadline=time.monotonic() + contract.readiness_timeout_s,
        )

    def wait_ready_until(
        self,
        process,
        contract: ServiceLaunchContract,
        backend: ServiceProcessLivenessPort,
        *,
        deadline: float,
    ) -> str:
        """Attest TCP readiness against an externally owned absolute deadline."""
        started_cost_ns = time.perf_counter_ns()
        wake = None if self._wake_factory is None else self._wake_factory()
        try:
            while True:
                if wake is not None:
                    # Observe first, after acknowledging the prior event:
                    # a server write between probe and sleep stays pending.
                    wake.acknowledge()
                add_cost_work("minecraft_tcp_probe_attempts", 1)
                if not backend.alive(process):
                    raise MinecraftServerServiceError(
                        "Minecraft server process exited before TCP readiness: "
                        f"{self.host}:{self.port}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MinecraftServerServiceError(
                        "Minecraft TCP readiness deadline expired: "
                        f"{self.host}:{self.port}"
                    )
                connection = None
                try:
                    connection = socket.create_connection(
                        (self.host, self.port),
                        timeout=max(0.001, min(self.poll_interval_s, remaining)),
                    )
                    payload = (
                        f"{contract.digest()}:{process.pid}:{process.start_identity}:"
                        f"{self.host}:{self.port}"
                    )
                    evidence = "minecraft-tcp-ready:" + hashlib.sha256(
                        payload.encode("utf-8")
                    ).hexdigest()
                    if not backend.alive(process):
                        raise MinecraftServerServiceError(
                            "Minecraft server process exited after TCP readiness: "
                            f"{self.host}:{self.port}"
                        )
                    return evidence
                except (OSError, TimeoutError):
                    pass
                finally:
                    if connection is not None:
                        connection.close()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    continue
                if wake is None:
                    blocking_wait(min(self.poll_interval_s, remaining))
                else:
                    # Events give the fast path; the bounded timeout is a hedge
                    # against readiness transitions that emit no subsequent log write.
                    wake.wait_changed_since(
                        None,
                        timeout_seconds=min(self.poll_interval_s, remaining),
                    )
        finally:
            if wake is not None:
                wake.close()
            add_cost_wait_ns(
                "minecraft_tcp_readiness",
                max(0, time.perf_counter_ns() - started_cost_ns),
            )


class MinecraftServerReadinessProbe:
    """Attest TCP and RCON concurrently under one lifecycle deadline."""

    def __init__(
        self,
        *,
        tcp: MinecraftTcpReadinessProbe,
        rcon: MinecraftRconConsole,
        rcon_command: str = "list",
        poll_interval_s: float = 0.25,
        wake_factory: Callable[[], _ReadinessWakePort] | None = None,
    ) -> None:
        if not rcon_command.strip() or poll_interval_s <= 0:
            raise ValueError("Minecraft RCON readiness configuration is invalid")
        self.tcp = tcp
        self.rcon = rcon
        self.rcon_command = rcon_command
        self.poll_interval_s = poll_interval_s
        self._wake_factory = (
            wake_factory if wake_factory is not None
            else getattr(tcp, "_wake_factory", None)
        )

    def _wait_tcp(
        self,
        process,
        contract: ServiceLaunchContract,
        backend: ServiceProcessLivenessPort,
        *,
        deadline: float,
    ) -> str:
        bounded = getattr(self.tcp, "wait_ready_until", None)
        if callable(bounded):
            return bounded(
                process, contract, backend, deadline=deadline
            )
        # Structural test doubles and third-party implementations may only
        # expose the public port. The outer join still enforces the deadline.
        return self.tcp.wait_ready(process, contract, backend)

    def _wait_rcon(
        self,
        process,
        backend: ServiceProcessLivenessPort,
        *,
        deadline: float,
    ):
        started_cost_ns = time.perf_counter_ns()
        last_error = "not-probed"
        wake = None if self._wake_factory is None else self._wake_factory()
        try:
            while True:
                if wake is not None:
                    wake.acknowledge()
                add_cost_work("minecraft_rcon_probe_attempts", 1)
                if not backend.alive(process):
                    raise MinecraftServerServiceError(
                        "Minecraft server process exited before RCON readiness"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MinecraftServerServiceError(
                        "Minecraft RCON readiness deadline expired: " + last_error
                    )
                try:
                    return self.rcon.execute(
                        self.rcon_command,
                        timeout_s=max(0.001, min(self.poll_interval_s, remaining)),
                    )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}:{exc}"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    continue
                if wake is None:
                    blocking_wait(min(self.poll_interval_s, remaining))
                else:
                    wake.wait_changed_since(
                        None,
                        timeout_seconds=min(self.poll_interval_s, remaining),
                    )
        finally:
            if wake is not None:
                wake.close()
            add_cost_wait_ns(
                "minecraft_rcon_readiness",
                max(0, time.perf_counter_ns() - started_cost_ns),
            )

    def wait_ready(
        self,
        process,
        contract: ServiceLaunchContract,
        backend: ServiceProcessLivenessPort,
    ) -> str:
        # Both witnesses share one absolute deadline and execute on the owning
        # lifecycle blocking-I/O lane. RCON is the later server-level witness in
        # normal Minecraft startup; once it succeeds, the TCP game-port proof is
        # ordinarily an immediate attestation. Keeping both probes on the owner
        # lane avoids a private thread pool and preserves the platform's single
        # concurrency authority without extending the overall deadline.
        deadline = time.monotonic() + contract.readiness_timeout_s
        rcon_evidence = self._wait_rcon(
            process, backend, deadline=deadline
        )
        tcp_evidence = self._wait_tcp(
            process, contract, backend, deadline=deadline
        )
        return "minecraft-server-ready:" + canonical_digest(
            {
                "tcp": tcp_evidence,
                "rcon": rcon_evidence.evidence_ref,
            }
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


class MinecraftServerLaunchPreflight:
    """Minecraft-specific validation over the generic Runtime preflight port."""

    def __init__(self, spec: MinecraftServerSpec) -> None:
        if not isinstance(spec, MinecraftServerSpec):
            raise TypeError("Minecraft preflight spec must be typed")
        workdir = Path(spec.workdir)
        self.required_paths = (
            workdir / "eula.txt",
            workdir / "server.properties",
        )

    def validate(
        self,
        contract: ServiceLaunchContract,
        environment: ServiceEnvironmentPort,
    ) -> ServiceLaunchPreflightReport:
        checks: list[tuple[str, bool]] = []
        errors: list[str] = []

        def check(name: str, passed: bool, message: str) -> None:
            checks.append((name, passed))
            if not passed:
                errors.append(message)

        executable = Path(contract.executable)
        cwd = Path(contract.cwd)
        check(
            "executable",
            executable.is_file(),
            f"executable is not a file: {contract.executable}",
        )
        check(
            "cwd",
            cwd.is_dir(),
            f"service cwd is not a directory: {contract.cwd}",
        )
        check(
            "environment_digest",
            environment.digest == contract.environment_digest,
            "materialized environment digest does not match launch contract",
        )
        for required in self.required_paths:
            check(
                "required:" + str(required),
                required.exists(),
                f"required Minecraft server resource is missing: {required}",
            )
        for index, argument in enumerate(contract.argv):
            check(
                f"argv[{index}]",
                bool(argument) and "\x00" not in argument,
                f"service argv[{index}] is empty or contains NUL",
            )
        report = ServiceLaunchPreflightReport(
            contract.digest(),
            tuple(checks),
            tuple(errors),
        )
        if not report.ready:
            raise MinecraftServerServiceError(
                "Minecraft server launch preflight failed: "
                + "; ".join(report.errors)
            )
        return report


def build_minecraft_server_preflight(
    spec: MinecraftServerSpec,
) -> ServiceLaunchPreflightPort:
    return MinecraftServerLaunchPreflight(spec)


def compose_minecraft_server_service_runtime(
    spec: MinecraftServerSpec,
    contract: ServiceLaunchContract,
    *,
    environment: MaterializedServiceEnvironment,
    runtime_factory: ServiceRuntimeFactoryPort,
    preflight: ServiceLaunchPreflightPort | None = None,
    rcon_password_provider: Callable[[], str] | None = None,
) -> ExactServiceRuntimePort:
    """Bind Minecraft readiness through the Runtime-owned service factory port."""

    tcp_readiness = MinecraftTcpReadinessProbe(
        host=spec.host,
        port=spec.bound_port,
    )
    readiness: ServiceReadinessProbePort = tcp_readiness
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

    return runtime_factory.open(
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
    _process: ServiceProcessIdentity | None = field(
        default=None,
        init=False,
        repr=False,
    )

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
        if result.process is None:
            self._process = None
        elif self._process is None:
            # A freshly reconstructed controller may adopt the one process
            # generation proven by Service reconciliation.
            self._process = result.process
        elif self._process != result.process:
            raise MinecraftServerServiceError(
                "Minecraft service process generation drifted during reconcile"
            )
        self._event("MC_SERVER_RECONCILE_END", attributes={"state_present": result.state_present, "has_process": result.process is not None})
        return result

    def start(self) -> ServiceStartOutcome:
        self._event("MC_SERVER_START", level="INFO", attributes={"host": self.spec.host, "port": self.spec.bound_port})
        try:
            result = self.service_runtime.start_exact(self.contract)
        except Exception as exc:
            self._failure("MC_SERVER_START_FAILED", exc)
            raise
        if self._process is not None and self._process != result.process:
            raise MinecraftServerServiceError(
                "Minecraft service start returned a different process generation"
            )
        self._process = result.process
        self._event("MC_SERVER_READY", level="INFO", attributes={"pid": result.process.pid, "ready_ref": result.ready_evidence_ref})
        return result

    def verify_ready(self) -> ServiceReadyObservation:
        try:
            result = self.service_runtime.verify_ready_exact(self.contract)
            if self._process is None:
                self._process = result.process
            elif self._process != result.process:
                raise MinecraftServerServiceError(
                    "Minecraft ready process generation drifted"
                )
            return result
        except Exception as exc:
            self._failure("MC_SERVER_READY_VERIFICATION_FAILED", exc)
            raise

    def stop(self) -> ServiceStopOutcome:
        self._event("MC_SERVER_STOP", level="INFO")
        try:
            if self._process is None:
                observation = self.reconcile()
                if observation.process is None:
                    return ServiceStopOutcome(
                        self.contract.digest(),
                        True,
                        tuple(observation.evidence_refs),
                    )
            assert self._process is not None
            expected = self._process
            result = self.service_runtime.stop_exact(
                self.contract,
                expected,
            )
            if result.stopped:
                self._process = None
        except Exception as exc:
            self._failure("MC_SERVER_STOP_FAILED", exc)
            raise
        self._event("MC_SERVER_STOPPED", level="INFO", attributes={"stopped": result.stopped})
        return result


@dataclass(frozen=True, slots=True)
class MinecraftServerServiceFactoryConfig:
    """Minecraft-owned inputs plus one adjacent Runtime factory port."""

    environment: MaterializedServiceEnvironment
    runtime_factory: ServiceRuntimeFactoryPort
    accept_eula: bool
    rcon_password_provider: Callable[[], str] | None = None
    readiness_timeout_s: float = 120.0
    stop_timeout_s: float = 30.0
    heartbeat_interval_s: float = 5.0

    def __post_init__(self) -> None:
        if min(
            self.readiness_timeout_s,
            self.stop_timeout_s,
            self.heartbeat_interval_s,
        ) <= 0:
            raise ValueError("Minecraft server service timings must be positive")
        if self.rcon_password_provider is not None and not callable(
            self.rcon_password_provider
        ):
            raise ValueError("Minecraft RCON password provider must be callable")


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
        artifact_digest, _artifact_size = sha256_file(Path(spec.jar_path))
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
            runtime_factory=self.config.runtime_factory,
            preflight=build_minecraft_server_preflight(spec),
            rcon_password_provider=(
                (lambda: rcon_password)
                if spec.rcon_endpoint is not None
                else None
            ),
        )
        return MinecraftServerServiceController(spec, contract, runtime)


__all__ = [
    "MinecraftServerServiceController",
    "MinecraftServerServiceFactory",
    "MinecraftServerServiceFactoryConfig",
    "MinecraftServerReadinessProbe",
    "MinecraftServerLaunchPreflight",
    "MinecraftServerServiceError",
    "MinecraftTcpReadinessProbe",
    "build_server_service_contract",
    "build_minecraft_server_preflight",
    "compose_minecraft_server_service_runtime",
]
