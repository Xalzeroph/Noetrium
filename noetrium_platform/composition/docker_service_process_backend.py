from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from threading import RLock

from noetrium_platform.foundation.governance.api import ScopeIdentity
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.lifecycle.service.api import (
    MaterializedServiceEnvironment,
    ServiceLaunchContract,
    ServiceProcessIdentity,
)
from noetrium_platform.infrastructure.resources.container.api import (
    DockerCommandRunnerPort,
    DockerContainerLeaseGuardFactoryPort,
    DockerContainerLeaseGuardPort,
    ManagedDockerContainerLease,
)
from noetrium_platform.infrastructure.resources.container.runtime import (
    DockerContainerLeaseAuthority,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.capture_paths import ServiceCapturePaths
from noetrium_platform.infrastructure.lifecycle.service.runtime.prepared_start import (
    PreparedServiceStartReconcileResult,
    PreparedServiceStartStatus,
    ServiceStartRecoveryHandle,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.process_contracts import (
    ProcessReconcileResult,
    ProcessReconcileStatus,
    ServiceProcessDrift,
)


_DOCKER_PREPARED_START_SCHEMA = "noetrium.docker-service-start.v1"

def _docker_gpu_device_request(gpu_devices: tuple[str, ...]) -> str:
    """Encode an exact Docker --gpus device request.

    Docker's --gpus flag is parsed as CSV. A multi-device value therefore
    needs an embedded quoted CSV field; passing device=GPU-a,GPU-b as one
    argv token is still split by Docker into two request fields.
    """
    if not gpu_devices or any(type(value) is not str or not value.strip() for value in gpu_devices):
        raise ValueError("Docker GPU device request requires non-empty device identities")
    return '"device=' + ",".join(gpu_devices) + '"'


@dataclass(frozen=True, slots=True)
class DockerServiceBindMount:
    source: Path
    target: Path
    read_only: bool = True

    def __post_init__(self) -> None:
        source = Path(self.source).expanduser().resolve(strict=False)
        if not source.is_absolute():
            raise ValueError("Docker service bind source must be absolute")
        target = Path(self.target)
        if not target.is_absolute():
            raise ValueError("Docker service bind target must be absolute")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "target", target)
        if type(self.read_only) is not bool:
            raise TypeError("Docker service bind read_only must be bool")


@dataclass(frozen=True, slots=True)
class DockerServiceTmpfsMount:
    target: Path
    size_bytes: int
    mode: int = 0o1777
    executable: bool = False

    def __post_init__(self) -> None:
        target = Path(self.target)
        if not target.is_absolute() or target == Path("/"):
            raise ValueError("Docker service tmpfs target must be absolute and non-root")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ValueError("Docker service tmpfs size_bytes must be positive integer")
        if type(self.mode) is not int or not (0 <= self.mode <= 0o7777):
            raise ValueError("Docker service tmpfs mode must be valid permission bits")
        if type(self.executable) is not bool:
            raise TypeError("Docker service tmpfs executable must be bool")
        object.__setattr__(self, "target", target)

    @property
    def docker_option(self) -> str:
        execution = "exec" if self.executable else "noexec"
        return (
            f"{self.target}:rw,{execution},nosuid,nodev,"
            f"size={self.size_bytes},mode={self.mode:o}"
        )


@dataclass(frozen=True, slots=True)
class DockerServiceProcessConfiguration:
    image_digest: str
    holder_scope: ScopeIdentity
    mounts: tuple[DockerServiceBindMount, ...] = ()
    tmpfs_mounts: tuple[DockerServiceTmpfsMount, ...] = ()
    gpu_devices: tuple[str, ...] = ()
    network_host: bool = True
    ipc_host: bool = False
    user_uid: int | None = None
    user_gid: int | None = None

    def __post_init__(self) -> None:
        if (
            type(self.image_digest) is not str
            or len(self.image_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in self.image_digest)
        ):
            raise ValueError("Docker service image_digest must be lowercase SHA-256")
        if not isinstance(self.holder_scope, ScopeIdentity):
            raise TypeError("Docker service holder_scope must be ScopeIdentity")
        if type(self.mounts) is not tuple or any(
            type(row) is not DockerServiceBindMount for row in self.mounts
        ):
            raise TypeError("Docker service mounts must be DockerServiceBindMount values")
        if type(self.tmpfs_mounts) is not tuple or any(
            type(row) is not DockerServiceTmpfsMount for row in self.tmpfs_mounts
        ):
            raise TypeError("Docker service tmpfs_mounts must be DockerServiceTmpfsMount values")
        tmpfs_targets = tuple(str(row.target) for row in self.tmpfs_mounts)
        if len(set(tmpfs_targets)) != len(tmpfs_targets):
            raise ValueError("Docker service tmpfs targets must be unique")
        bind_targets = {str(row.target) for row in self.mounts}
        overlap = bind_targets.intersection(tmpfs_targets)
        if overlap:
            raise ValueError(
                "Docker service tmpfs target conflicts with bind target: "
                + sorted(overlap)[0]
            )
        if type(self.gpu_devices) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.gpu_devices
        ):
            raise TypeError("Docker service gpu_devices must be non-empty strings")
        if len(set(self.gpu_devices)) != len(self.gpu_devices):
            raise ValueError("Docker service gpu_devices must be unique")
        for name in ("network_host", "ipc_host"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"Docker service {name} must be bool")
        if (self.user_uid is None) != (self.user_gid is None):
            raise ValueError("Docker service user uid/gid must be specified together")
        for name in ("user_uid", "user_gid"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"Docker service {name} must be non-negative integer")

    @property
    def image(self) -> str:
        return f"sha256:{self.image_digest}"

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "image_digest": self.image_digest,
                "holder_scope": self.holder_scope,
                "mounts": tuple(
                    (str(row.source), str(row.target), row.read_only)
                    for row in self.mounts
                ),
                "tmpfs_mounts": tuple(
                    (str(row.target), row.size_bytes, row.mode, row.executable)
                    for row in self.tmpfs_mounts
                ),
                "gpu_devices": self.gpu_devices,
                "network_host": self.network_host,
                "ipc_host": self.ipc_host,
                "user_uid": self.user_uid,
                "user_gid": self.user_gid,
            }
        )


class DockerContainerProcessBackend:
    """ExactProcessBackend over one Resource-fenced Docker container generation.

    Service WAL/state remains owned by ExactServiceSupervisor. Docker resource
    identity, fencing and physical cleanup remain owned by
    DockerContainerLeaseAuthority. This backend is only the process transport.
    """

    start_recovery_durability = "crash_durable"

    def __init__(
        self,
        *,
        authority: DockerContainerLeaseAuthority,
        runner: DockerCommandRunnerPort,
        lease_guard_factory: DockerContainerLeaseGuardFactoryPort,
        configuration: DockerServiceProcessConfiguration,
        command_timeout_seconds: float = 60.0,
    ) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("Docker service command timeout must be positive")
        self._authority = authority
        self._runner = runner
        self._guard_factory = lease_guard_factory
        self._configuration = configuration
        self._timeout = float(command_timeout_seconds)
        self._lock = RLock()
        self._handle: ManagedDockerContainerLease | None = None
        self._guard: DockerContainerLeaseGuardPort | None = None

    def _allocation_id(self, contract: ServiceLaunchContract) -> str:
        return "service:" + canonical_digest(
            {
                "service_id": contract.service_id,
                "generation": contract.generation,
                "contract_digest": contract.digest(),
                "container_configuration_digest": self._configuration.digest,
            }
        )

    def _prepared_payload(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        *,
        intent_id: str,
        attempt: int,
    ) -> bytes:
        return json.dumps(
            {
                "allocation_id": self._allocation_id(contract),
                "attempt": attempt,
                "captures": (
                    str(captures.stdout_path),
                    str(captures.stderr_path),
                ),
                "configuration_digest": self._configuration.digest,
                "contract_digest": contract.digest(),
                "environment_digest": environment.digest,
                "intent_id": intent_id,
                "schema": _DOCKER_PREPARED_START_SCHEMA,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _decode_prepared(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> dict[str, object]:
        if handle.provider_schema != _DOCKER_PREPARED_START_SCHEMA:
            raise ServiceProcessDrift("Docker prepared-start provider schema drift")
        try:
            value = json.loads(handle.opaque_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServiceProcessDrift("Docker prepared-start payload is invalid") from exc
        expected = {
            "allocation_id": self._allocation_id(contract),
            "attempt": value.get("attempt"),
            "captures": [
                str(captures.stdout_path),
                str(captures.stderr_path),
            ],
            "configuration_digest": self._configuration.digest,
            "contract_digest": contract.digest(),
            "environment_digest": environment.digest,
            "intent_id": value.get("intent_id"),
            "schema": _DOCKER_PREPARED_START_SCHEMA,
        }
        if value != expected:
            raise ServiceProcessDrift("Docker prepared-start payload drifted")
        if type(value.get("attempt")) is not int or int(value["attempt"]) <= 0:
            raise ServiceProcessDrift("Docker prepared-start attempt is invalid")
        if type(value.get("intent_id")) is not str or not str(value["intent_id"]):
            raise ServiceProcessDrift("Docker prepared-start intent identity is invalid")
        return value

    def _verify_image(self) -> None:
        docker = self._authority.runtime.docker_executable
        result = self._runner.run(
            (
                docker,
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                self._configuration.image,
            ),
            timeout_seconds=self._timeout,
        )
        expected = self._configuration.image
        if result.returncode != 0 or result.stdout.strip() != expected:
            raise RuntimeError(
                "Docker service immutable image is unavailable or identity-drifted: "
                + expected
            )

    def _recover_handle(
        self,
        contract: ServiceLaunchContract,
    ) -> ManagedDockerContainerLease | None:
        handle = self._authority.recover(
            allocation_id=self._allocation_id(contract),
            image=self._configuration.image,
            runtime_identity_digest=contract.runtime_identity_digest,
        )
        if handle is not None:
            self._handle = handle
        return handle

    def _ensure_guard(self, handle: ManagedDockerContainerLease) -> None:
        if self._guard is not None:
            self._guard.assert_healthy()
            return
        guard = self._guard_factory.create((handle,))
        guard.start()
        self._guard = guard

    def _close_guard(self) -> None:
        guard = self._guard
        self._guard = None
        if guard is not None:
            guard.close()

    def _process_observation(
        self,
        handle: ManagedDockerContainerLease,
    ):
        observed = self._authority.observe_exact(handle)
        if observed is None or not observed.running:
            return None
        process = self._authority.runtime.inspect_process(observed.container_id)
        if process is None:
            return None
        return process

    @staticmethod
    def _identity(observation) -> ServiceProcessIdentity:
        return ServiceProcessIdentity(
            pid=observation.pid,
            start_identity=(
                "docker:"
                + observation.container.container_id
                + ":"
                + observation.started_at
            ),
        )

    def _mount_args(
        self,
        captures: ServiceCapturePaths,
    ) -> tuple[str, ...]:
        mounts = list(self._configuration.mounts)
        capture_root = captures.stdout_path.parent.resolve()
        capture_mount = DockerServiceBindMount(
            capture_root,
            capture_root,
            read_only=False,
        )
        if all(
            not (
                row.source == capture_mount.source
                and row.target == capture_mount.target
            )
            for row in mounts
        ):
            mounts.append(capture_mount)

        values: list[str] = []
        seen_targets: set[str] = set()
        for row in mounts:
            target = str(row.target)
            if target in seen_targets:
                raise ValueError(f"duplicate Docker service bind target: {target}")
            seen_targets.add(target)
            mount = f"type=bind,src={row.source},dst={row.target}"
            if row.read_only:
                mount += ",readonly"
            values.extend(("--mount", mount))
        return tuple(values)

    def _docker_argv(
        self,
        handle: ManagedDockerContainerLease,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> tuple[str, ...]:
        stdout = captures.stdout_path
        stderr = captures.stderr_path
        stdout.parent.mkdir(parents=True, exist_ok=True)
        stderr.parent.mkdir(parents=True, exist_ok=True)
        stdout.touch(exist_ok=True)
        stderr.touch(exist_ok=True)

        argv = list(self._authority.docker_run_prefix(handle))
        argv.append("-d")
        if self._configuration.network_host:
            argv.extend(("--network", "host"))
        if self._configuration.ipc_host:
            argv.extend(("--ipc", "host"))
        if self._configuration.user_uid is not None:
            argv.extend(
                (
                    "--user",
                    f"{self._configuration.user_uid}:{self._configuration.user_gid}",
                )
            )
        for row in self._configuration.tmpfs_mounts:
            argv.extend(("--tmpfs", row.docker_option))
        if self._configuration.gpu_devices:
            argv.extend(
                (
                    "--gpus",
                    _docker_gpu_device_request(self._configuration.gpu_devices),
                )
            )
        argv.extend(self._mount_args(captures))
        argv.extend(("-w", str(contract.cwd)))

        environment_values = dict(environment.variables)
        environment_values.setdefault("HOME", "/tmp")
        if self._configuration.user_uid is not None:
            numeric_user = str(self._configuration.user_uid)
            environment_values.setdefault("USER", numeric_user)
            environment_values.setdefault("LOGNAME", numeric_user)
        for key, value in sorted(environment_values.items()):
            argv.extend(("-e", f"{key}={value}"))

        command = (
            "exec "
            + shlex.join(contract.argv)
            + " >> "
            + shlex.quote(str(stdout))
            + " 2>> "
            + shlex.quote(str(stderr))
        )
        argv.extend(
            (
                "--entrypoint",
                "/bin/sh",
                self._configuration.image,
                "-c",
                command,
            )
        )
        return tuple(argv)

    def _start_exact(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        self._verify_image()
        with self._lock:
            handle = self._recover_handle(contract)
            if handle is None:
                handle = self._authority.reserve(
                    allocation_id=self._allocation_id(contract),
                    holder_scope=self._configuration.holder_scope,
                    image=self._configuration.image,
                    runtime_identity_digest=contract.runtime_identity_digest,
                )
                self._handle = handle

            current = self._process_observation(handle)
            if current is not None:
                self._ensure_guard(handle)
                identity = self._identity(current)
                return identity, (
                    f"docker-container:{current.container.container_id}",
                    f"docker-lease:{handle.lease.lease_id}:{handle.lease.fencing_token}",
                )

            observed = self._authority.observe_exact(handle)
            if observed is not None:
                raise ServiceProcessDrift(
                    "Docker service generation exists but is not running"
                )
            result = self._runner.run(
                self._docker_argv(handle, contract, environment, captures),
                timeout_seconds=self._timeout,
            )
            if result.returncode != 0:
                try:
                    self._authority.release(handle)
                finally:
                    self._handle = None
                raise RuntimeError(
                    "Docker service start failed with exit code "
                    f"{result.returncode}: {result.stderr.strip()}"
                )
            try:
                self._authority.confirm_running(
                    handle,
                    timeout_seconds=min(30.0, self._timeout),
                )
                self._ensure_guard(handle)
                process = self._process_observation(handle)
                if process is None:
                    raise RuntimeError(
                        "Docker service container is running without exact process observation"
                    )
            except BaseException:
                self._close_guard()
                try:
                    self._authority.release(handle)
                finally:
                    self._handle = None
                raise

            identity = self._identity(process)
            return identity, (
                f"docker-container:{process.container.container_id}",
                f"docker-lease:{handle.lease.lease_id}:{handle.lease.fencing_token}",
            )

    def prepare_start_recovery(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        *,
        intent_id: str,
        attempt: int,
    ) -> ServiceStartRecoveryHandle:
        if type(attempt) is not int or attempt <= 0:
            raise ValueError("Docker prepared-start attempt must be positive")
        if type(intent_id) is not str or not intent_id:
            raise ValueError("Docker prepared-start intent identity is required")
        return ServiceStartRecoveryHandle.from_payload(
            _DOCKER_PREPARED_START_SCHEMA,
            self._prepared_payload(
                contract,
                environment,
                captures,
                intent_id=intent_id,
                attempt=attempt,
            ),
        )

    def start_prepared(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        self._decode_prepared(contract, environment, captures, handle)
        return self._start_exact(contract, environment, captures)

    def reconcile_prepared_start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
        handle: ServiceStartRecoveryHandle,
    ) -> PreparedServiceStartReconcileResult:
        self._decode_prepared(contract, environment, captures, handle)
        with self._lock:
            recovered = self._recover_handle(contract)
            if recovered is None:
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.NOT_STARTED,
                    None,
                    (),
                )
            observed = self._authority.observe_exact(recovered)
            if observed is None:
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.NOT_STARTED,
                    None,
                    (
                        f"docker-lease:{recovered.lease.lease_id}:"
                        f"{recovered.lease.fencing_token}",
                    ),
                )
            if not observed.running:
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.DRIFT,
                    None,
                    (f"docker-container:{observed.container_id}",),
                    "prepared Docker service container exists but is stopped",
                )
            process = self._authority.runtime.inspect_process(observed.container_id)
            if process is None:
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.UNKNOWN,
                    None,
                    (f"docker-container:{observed.container_id}",),
                    "running Docker service process identity is unobservable",
                )
            self._ensure_guard(recovered)
            identity = self._identity(process)
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.PROCESS_CONFIRMED,
                identity,
                (
                    f"docker-container:{observed.container_id}",
                    f"docker-lease:{recovered.lease.lease_id}:"
                    f"{recovered.lease.fencing_token}",
                ),
            )

    def start(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        return self._start_exact(contract, environment, captures)

    def reconcile(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
    ) -> ProcessReconcileResult:
        del environment
        with self._lock:
            handle = self._recover_handle(contract)
            if handle is None:
                return ProcessReconcileResult(
                    ProcessReconcileStatus.MISSING,
                    (),
                    "Docker service lease is missing",
                )
            observed = self._process_observation(handle)
            if observed is None:
                return ProcessReconcileResult(
                    ProcessReconcileStatus.MISSING,
                    (
                        f"docker-lease:{handle.lease.lease_id}:"
                        f"{handle.lease.fencing_token}",
                    ),
                    "Docker service container is missing or stopped",
                )
            identity = self._identity(observed)
            refs = (
                f"docker-container:{observed.container.container_id}",
                f"docker-lease:{handle.lease.lease_id}:{handle.lease.fencing_token}",
            )
            if identity == process:
                self._ensure_guard(handle)
                return ProcessReconcileResult(
                    ProcessReconcileStatus.EXACT,
                    refs,
                )
            return ProcessReconcileResult(
                ProcessReconcileStatus.DRIFT,
                refs,
                "Docker service physical process generation drifted",
            )

    def alive(self, process: ServiceProcessIdentity) -> bool:
        with self._lock:
            handle = self._handle
            if handle is None:
                return False
            try:
                observed = self._process_observation(handle)
            except BaseException:
                return False
            return observed is not None and self._identity(observed) == process

    def close(self) -> None:
        """Stop only lease heartbeat ownership; physical cleanup stays external."""

        with self._lock:
            self._close_guard()

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        with self._lock:
            handle = self._recover_handle(contract)
            if handle is None:
                self._close_guard()
                self._handle = None
                return ()
            observed = self._process_observation(handle)
            if observed is not None and self._identity(observed) != process:
                raise ServiceProcessDrift(
                    "refusing to stop a different Docker service process generation"
                )
            refs = []
            physical = self._authority.observe_exact(handle)
            if physical is not None:
                refs.append(f"docker-container:{physical.container_id}")
            refs.append(
                f"docker-lease:{handle.lease.lease_id}:{handle.lease.fencing_token}"
            )
            self._close_guard()
            self._authority.release(handle)
            self._handle = None
            return tuple(refs)


__all__ = [
    "DockerContainerProcessBackend",
    "DockerServiceBindMount",
    "DockerServiceProcessConfiguration",
]
