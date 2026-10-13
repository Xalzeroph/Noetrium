from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from threading import RLock

from noetrium_platform.foundation.governance.api import scope_key
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.lifecycle.service.api import (
    MaterializedServiceEnvironment,
    ServiceLaunchContract,
    ServiceProcessIdentity,
)
from noetrium_platform.infrastructure.resources.container.api import (
    DockerCommandRunnerPort,
)
from noetrium_platform.infrastructure.resources.container.providers.docker_physical import (
    DockerPhysicalProvider,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.authority import (
    ResourceRealizationSpec,
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.resources.authority import (
    observation_field,
    physical_field,
    resource_claim,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.api.topology import (
    resource_node,
    resource_topology,
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
    holder_scope: NoetriumUnit
    holder_scope_lease: NoetriumUnit | None = None
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
        if not isinstance(self.holder_scope, NoetriumUnit):
            raise TypeError("Docker service holder_scope must be NoetriumUnit")
        if self.holder_scope_lease is not None and not isinstance(
            self.holder_scope_lease,
            NoetriumUnit,
        ):
            raise TypeError(
                "Docker service holder_scope_lease must be NoetriumUnit or None"
            )
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
    """ExactProcessBackend over one Authority-ticketed Docker realization.

    Service WAL/state remains owned by ExactServiceSupervisor. Recursive graph
    structure is the desired truth, UniversalResourceAuthority owns the sole
    mutable resource truth, and DockerPhysicalProvider is only the physical ISA.
    """

    start_recovery_durability = "crash_durable"

    def __init__(
        self,
        *,
        authority: UniversalResourceAuthority,
        provider: DockerPhysicalProvider,
        runner: DockerCommandRunnerPort,
        configuration: DockerServiceProcessConfiguration,
        command_timeout_seconds: float = 60.0,
    ) -> None:
        if not isinstance(authority, UniversalResourceAuthority):
            raise TypeError("Docker service requires UniversalResourceAuthority")
        if not isinstance(provider, DockerPhysicalProvider):
            raise TypeError("Docker service requires DockerPhysicalProvider")
        if command_timeout_seconds <= 0:
            raise ValueError("Docker service command timeout must be positive")
        self._authority = authority
        self._provider = provider
        self._runner = runner
        self._configuration = configuration
        self._timeout = float(command_timeout_seconds)
        self._lock = RLock()
        self._active_contract: ServiceLaunchContract | None = None

    def _allocation_id(self, contract: ServiceLaunchContract) -> str:
        return "service:" + canonical_digest(
            {
                "service_id": contract.service_id,
                "generation": contract.generation,
                "contract_digest": contract.digest(),
                "container_configuration_digest": self._configuration.digest,
            }
        )

    def _resource_key(self, contract: ServiceLaunchContract) -> str:
        return "container:" + self._allocation_id(contract)

    def _topology(self, contract: ServiceLaunchContract):
        allocation_id = self._allocation_id(contract)
        return resource_topology(
            "docker-service:" + canonical_digest(allocation_id)[:24],
            resources=(
                resource_node(
                    "container",
                    kind="container",
                    authority_key=self._resource_key(contract),
                    realization=True,
                ),
            ),
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
        result = self._runner.run(
            (
                self._provider.docker_executable,
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
    def _docker_run_args(
        self,
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

        argv = ["-d", "--restart", "no", "--init"]
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
    def _claim_candidates(
        self,
        contract: ServiceLaunchContract,
        generation: int,
        *,
        scope_generation: int,
        scope_lease_id: str | None,
    ) -> tuple[NoetriumUnit, ...]:
        resource_key = self._resource_key(contract)
        holder_key = scope_key(self._configuration.holder_scope)
        allocation_id = self._allocation_id(contract)
        claim_id = "container:" + canonical_digest(
            {
                "resource_key": resource_key,
                "generation": generation,
                "holder_key": holder_key,
                "allocation_id": allocation_id,
            }
        )
        return (
            resource_claim(
                claim_id=claim_id,
                resource_key=resource_key,
                holder_key=holder_key,
                generation=generation,
                owner_scope=self._configuration.holder_scope,
                scope_generation=scope_generation,
                scope_lease_id=scope_lease_id,
                owner_lease_id=None,
                exclusive=("docker-container:" + allocation_id,),
                attributes={
                    "kind": "container",
                    "allocation_id": allocation_id,
                    "runtime_identity_digest": contract.runtime_identity_digest,
                },
            ),
        )

    def _realization_spec(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> ResourceRealizationSpec:
        return ResourceRealizationSpec(
            "docker",
            {
                "run_args": self._docker_run_args(
                    contract,
                    environment,
                    captures,
                ),
            },
        )

    def _converge_desired(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> tuple[NoetriumUnit, NoetriumUnit]:
        topology = self._topology(contract)
        scope_generation, scope_lease_id = self._authority.scope_ownership_cut(
            self._configuration.holder_scope,
            scope_lease=self._configuration.holder_scope_lease,
        )
        self._authority.reconcile(
            topology,
            claim_candidates={
                "container": lambda _snapshot, generation: self._claim_candidates(
                    contract,
                    generation,
                    scope_generation=scope_generation.generation,
                    scope_lease_id=scope_lease_id,
                )
            },
            realization_specs={
                "container": lambda _snapshot: self._realization_spec(
                    contract,
                    environment,
                    captures,
                )
            },
            providers={"docker": self._provider},
        )
        resource_key = self._resource_key(contract)
        snapshot = self._authority.snapshot_for_resource_keys(
            frozenset({resource_key})
        )
        ticket = snapshot.current_ticket_for(resource_key)
        if ticket is None:
            raise RuntimeError("Docker service Authority converged without a ticket")
        observation = self._provider.observe(ticket)
        if not observation_field(observation, "exists") or not observation_field(observation, "ready"):
            raise RuntimeError(
                "Docker service Authority converged without a ready realization"
            )
        self._active_contract = contract
        return ticket, observation
    def _current_observation(
        self,
        contract: ServiceLaunchContract,
        *,
        commit_binding: bool = False,
    ) -> tuple[NoetriumUnit, NoetriumUnit] | None:
        resource_key = self._resource_key(contract)
        snapshot = self._authority.snapshot_for_resource_keys(
            frozenset({resource_key})
        )
        ticket = snapshot.current_ticket_for(resource_key)
        if ticket is None:
            return None
        observation = self._provider.observe(ticket)
        if (
            commit_binding
            and observation_field(observation, "exists")
            and observation_field(observation, "ready")
            and snapshot.binding_for(ticket_field(ticket, "resource_key")) is None
        ):
            self._authority.bind(ticket_field(ticket, "ticket_id"), observation)
        return ticket, observation

    @staticmethod
    def _identity(observation: NoetriumUnit) -> ServiceProcessIdentity:
        identity = observation_field(observation, "physical_identity")
        if identity is None:
            raise ServiceProcessDrift(
                "Docker observation has no physical identity"
            )
        attributes = dict(physical_field(identity, "attributes") or {})
        pid = attributes.get("pid")
        started_at = attributes.get("started_at")
        if type(pid) is not int or pid <= 0:
            raise ServiceProcessDrift(
                "Docker physical identity has no positive pid"
            )
        if type(started_at) is not str or not started_at.strip():
            raise ServiceProcessDrift(
                "Docker physical identity has no start identity"
            )
        return ServiceProcessIdentity(
            pid=pid,
            start_identity=(
                "docker:"
                + physical_field(identity, "physical_id")
                + ":"
                + started_at
            ),
        )

    @staticmethod
    def _refs(
        ticket: NoetriumUnit,
        observation: NoetriumUnit,
    ) -> tuple[str, ...]:
        rows = [f"resource-ticket:{ticket_field(ticket, "ticket_id")}:{ticket_field(ticket, "generation")}"]
        identity = observation_field(observation, "physical_identity")
        if identity is not None:
            rows.insert(
                0,
                "docker-container:" + str(physical_field(identity, "physical_id")),
            )
        return tuple(rows)

    def _start_exact(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
        captures: ServiceCapturePaths,
    ) -> tuple[ServiceProcessIdentity, tuple[str, ...]]:
        self._verify_image()
        with self._lock:
            ticket, observation = self._converge_desired(
                contract,
                environment,
                captures,
            )
            return self._identity(observation), self._refs(ticket, observation)
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
            current = self._current_observation(
                contract,
                commit_binding=True,
            )
            if current is None:
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.NOT_STARTED,
                    None,
                    (),
                )
            ticket, observation = current
            refs = self._refs(ticket, observation)
            if not observation_field(observation, "exists"):
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.NOT_STARTED,
                    None,
                    refs,
                )
            if not observation_field(observation, "ready"):
                return PreparedServiceStartReconcileResult(
                    PreparedServiceStartStatus.DRIFT,
                    None,
                    refs,
                    "prepared Docker service container exists but is stopped",
                )
            self._active_contract = contract
            return PreparedServiceStartReconcileResult(
                PreparedServiceStartStatus.PROCESS_CONFIRMED,
                self._identity(observation),
                refs,
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
            current = self._current_observation(contract)
            if current is None:
                return ProcessReconcileResult(
                    ProcessReconcileStatus.MISSING,
                    (),
                    "Docker service Authority ticket is missing",
                )
            ticket, observation = current
            refs = self._refs(ticket, observation)
            if not observation_field(observation, "exists") or not observation_field(observation, "ready"):
                return ProcessReconcileResult(
                    ProcessReconcileStatus.MISSING,
                    refs,
                    "Docker service container is missing or stopped",
                )
            identity = self._identity(observation)
            if identity == process:
                self._active_contract = contract
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
            contract = self._active_contract
            if contract is None:
                return False
            try:
                current = self._current_observation(contract)
                if current is None:
                    return False
                _ticket, observation = current
                return (
                    observation_field(observation, "exists")
                    and observation_field(observation, "ready")
                    and self._identity(observation) == process
                )
            except BaseException:
                return False

    def close(self) -> None:
        """Detach the local service consumer without retiring warm realization."""
        self._active_contract = None

    def stop(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
    ) -> tuple[str, ...]:
        with self._lock:
            current = self._current_observation(contract)
            if current is None:
                self._active_contract = None
                return ()
            ticket, observation = current
            if (
                observation_field(observation, "exists")
                and observation_field(observation, "ready")
                and self._identity(observation) != process
            ):
                raise ServiceProcessDrift(
                    "refusing to stop a different Docker service process generation"
                )
            refs = self._refs(ticket, observation)
            self._authority.reconcile(
                self._topology(contract),
                claim_candidates={},
                realization_specs={},
                providers={"docker": self._provider},
                desired_resource_ids=frozenset(),
            )
            self._active_contract = None
            return refs


__all__ = [
    "DockerContainerProcessBackend",
    "DockerServiceBindMount",
    "DockerServiceProcessConfiguration",
]
