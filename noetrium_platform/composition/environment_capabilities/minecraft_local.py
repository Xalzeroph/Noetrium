from __future__ import annotations

MINECRAFT_LOCAL_IMPLEMENTATION_ID = "minecraft.mineflayer"


import json
from concurrent.futures import CancelledError
import hashlib
import math
import os
import re
import select
import shlex
import signal
import socket
import shutil
import threading
from weakref import WeakValueDictionary
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from noetrium_platform.capabilities.environment.api import EnvironmentCapabilityDescriptor, EnvironmentSession
from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentProfileMaterialization,
    EnvironmentProfileRevision,
    ExecutionEnvironmentCatalogPort,
)
from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftBranchRuntimeRequest,
    MinecraftBridgeSpec,
    MinecraftEndpointSpec,
    MinecraftEnvironmentRuntimeBinding,
    minecraft_environment_unit,
    MinecraftRconEndpoint,
    MinecraftServerSpec,
    MinecraftWorldBranch,
    minecraft_action_catalog,
    minecraft_scenario_from_mapping,
    MINECRAFT_TASK_SETUP_SCHEMAS,
    normalize_minecraft_world_ops,
)
from noetrium_platform.capabilities.environment.minecraft.providers.scenario import (
    RconMinecraftScenarioProvisioner,
)
from noetrium_platform.capabilities.environment.minecraft.providers.task_setup import (
    RconMinecraftWorldSetupProvisioner,
)
from noetrium_platform.capabilities.environment.minecraft.composition.branch_runtime import MinecraftBranchRuntimeFactory
from noetrium_platform.capabilities.environment.minecraft.composition.environment import (
    MinecraftEnvironmentAssembly,
    compose_minecraft_environment,
)
from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
    MinecraftServerReadinessProbe,
    MinecraftServerServiceError,
    MinecraftTcpReadinessProbe,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.errors import (
    MinecraftEnvironmentFailure,
)
from noetrium_platform.capabilities.environment.minecraft.providers.rcon import MinecraftRconConsole
from noetrium_platform.capabilities.environment.minecraft.composition.local_runtime_primitives import (
    MinecraftBridgeRuntimeDistribution,
    MinecraftBridgeRuntimeDistributionCache,
    MinecraftPristineWorldTemplateCache,
    MinecraftPristineWorldTemplateReservation,
    MinecraftServerRuntimeDistributionCache,
    PRISTINE_WORLD_TEMPLATE_SCHEMA,
    execute_local_rcon,
    local_bridge_runtime_source_root,
    local_pristine_world_cache,
    prepare_local_server_files,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionControlPort,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskCancelled,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
    strict_finite_json_text,
    require_sha256,
    blocking_wait,
    InterprocessFileLock,
)
from noetrium_platform.foundation.kernel.kernel import sha256_file, atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability import InterprocessLockBusy
from noetrium_platform.infrastructure.reliability.forensics.providers.directory_change_signal import (
    DirectoryChangeSignal,
)
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessSupervisorPort
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
    ServiceReadyObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.infrastructure.resources.api.topology import (
    resource_node,
    resource_topology,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.authority import (
    DEFAULT_AUTHORITY_LEASE_POLICY,
    LeaseHeartbeatFactory,
    LeaseHeartbeatGuard,
    ResourceRealizationSpec,
    TicketState,
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.resources.authority.api.contracts import (
    ResourceClaimConflict,
    ResourceObservationNotReady,
)
from noetrium_platform.infrastructure.resources.authority import (
    claim_field,
    is_physical_identity,
    is_realization_ticket,
    lease_field,
    observation_field,
    physical_field,
    physical_identity,
    realization_ticket,
    resource_claim,
    resource_observation,
    ticket_field,
)
from noetrium_platform.infrastructure.resources.container.providers.docker_physical import (
    DockerPhysicalProvider,
)
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointCandidatePortSourcePort,
    EndpointProbePort,
)
from noetrium_platform.infrastructure.resources.allocation.placement import (
    EndpointPlacement,
    automatic_endpoint_claim_candidates,
    endpoint_placement_from_claim,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeInventoryPort,
    ComputeRequirement,
    GpuRuntimeObserverPort,
    HostRuntimeObserverPort,
)
from noetrium_platform.infrastructure.resources.compute.placement import (
    ComputePlacement,
    compute_capacity,
    compute_claim_candidates,
    compute_placement_from_claim,
)
from noetrium_platform.substrate.api import PLATFORM_SCOPE, NoetriumUnit, ScopeKind, scope_key, scope_unit
from .lifetime import EnvironmentLifetimeSessionControllerPort, environment_random_seed
from ..shared_host_pressure import ResourceCompetitionDemand

_BRIDGE_ROOT = "/opt/noetrium-environments/minecraft/bridge"
_NODE = "/usr/local/bin/node"
_JAVA = "/opt/java/openjdk/bin/java"
_MINECRAFT_SERVER_XMS = "512M"
_MINECRAFT_SERVER_XMX = "2G"
_MINECRAFT_OVERWORLD_MAX_BUILD_Y = 319
_JVM_MEMORY_UNITS = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
_MINECRAFT_NAMED_INVENTORY_SLOTS = {
    "mainhand": "weapon.mainhand",
    "offhand": "weapon.offhand",
    "head": "armor.head",
    "chest": "armor.chest",
    "legs": "armor.legs",
    "feet": "armor.feet",
}
_MINECRAFT_INDEXED_EQUIPMENT_SLOTS = {
    36: "armor.feet",
    37: "armor.legs",
    38: "armor.chest",
    39: "armor.head",
    40: "weapon.offhand",
}


_MINECRAFT_PRE_AGENT_TRANSIENT_SETUP_CODES = frozenset({
    "MINECRAFT_SETUP_CONTROL_POSTCONDITION_FAILED",
    "MINECRAFT_SETUP_POSTCONDITION_FAILED",
    "MINECRAFT_SETUP_PROOF_MISSING",
})


def _exception_leaves(error: BaseException) -> tuple[BaseException, ...]:
    if isinstance(error, BaseExceptionGroup):
        return tuple(
            leaf
            for child in error.exceptions
            for leaf in _exception_leaves(child)
        )
    return (error,)


def _is_pre_agent_infrastructure_failure(error: BaseException) -> bool:
    """True only for environment faults safe to replay before agent visibility."""
    leaves = _exception_leaves(error)
    if not leaves:
        return False
    for leaf in leaves:
        if isinstance(leaf, (MinecraftServerServiceError, ResourceObservationNotReady)):
            continue
        if (
            isinstance(leaf, MinecraftEnvironmentFailure)
            and leaf.cause_code in _MINECRAFT_PRE_AGENT_TRANSIENT_SETUP_CODES
        ):
            continue
        return False
    return True


def _pre_agent_recovery_decision(
    error: BaseException, *, attempt: int, max_attempts: int
) -> str:
    if type(attempt) is not int or type(max_attempts) is not int:
        raise TypeError("pre-agent recovery attempt counters must be integers")
    if attempt < 1 or max_attempts < 1 or attempt > max_attempts:
        raise ValueError("pre-agent recovery attempt counters are invalid")
    if not _is_pre_agent_infrastructure_failure(error):
        return "fatal"
    return "retry" if attempt < max_attempts else "exhausted"


def _pre_agent_failure_evidence(error: BaseException) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for leaf in _exception_leaves(error):
        row: dict[str, object] = {
            "type": type(leaf).__name__,
            "message": str(leaf)[:4096],
        }
        phase = getattr(leaf, "phase", None)
        if isinstance(phase, str) and phase:
            row["phase"] = phase
        cause_code = getattr(leaf, "cause_code", None)
        if isinstance(cause_code, str) and cause_code:
            row["cause_code"] = cause_code
        rows.append(row)
    return tuple(rows)


def _minecraft_position_voxel(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, Mapping):
        return None
    coordinates: list[int] = []
    for axis in ("x", "y", "z"):
        raw = value.get(axis)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        numeric = float(raw)
        if not math.isfinite(numeric):
            return None
        coordinates.append(math.floor(numeric))
    return coordinates[0], coordinates[1], coordinates[2]


def _minecraft_biome_authority_voxel(
    proof: object,
) -> tuple[int, int, int] | None:
    if not isinstance(proof, Mapping):
        return None
    checks = proof.get("checks", ())
    if not isinstance(checks, (tuple, list)):
        return None
    for row in checks:
        if not isinstance(row, Mapping) or row.get("kind") != "biome_authority":
            continue
        return _minecraft_position_voxel(row.get("position"))
    return None


def _minecraft_rejected_authority_voxel(
    exc: BaseException,
) -> tuple[int, int, int] | None:
    if str(getattr(exc, "cause_code", "")) != "MINECRAFT_SETUP_POSTCONDITION_FAILED":
        return None
    diagnostics = getattr(exc, "diagnostics", None)
    if not isinstance(diagnostics, Mapping):
        return None
    failures = diagnostics.get("failures", ())
    if not isinstance(failures, (tuple, list)) or not failures:
        return None
    rows = [row for row in failures if isinstance(row, Mapping)]
    if len(rows) != len(failures) or any(
        row.get("kind") != "authority_position" for row in rows
    ):
        return None
    observed = rows[0].get("observed_voxel")
    if not isinstance(observed, Mapping):
        return None
    coordinates: list[int] = []
    for axis in ("x", "y", "z"):
        raw = observed.get(axis)
        if isinstance(raw, bool) or not isinstance(raw, int):
            return None
        coordinates.append(raw)
    return coordinates[0], coordinates[1], coordinates[2]


def _minecraft_inventory_slot_destination(raw_slot: object) -> str | None:
    """Translate MineDojo/vanilla player slot ABI to /item destinations."""
    if raw_slot is None:
        return None
    if isinstance(raw_slot, bool):
        raise ValueError("Minecraft initial inventory slot is invalid")
    if isinstance(raw_slot, int):
        index = raw_slot
    else:
        slot_text = str(raw_slot).strip()
        if not slot_text:
            return None
        named = _MINECRAFT_NAMED_INVENTORY_SLOTS.get(slot_text)
        if named is not None:
            return named
        if not slot_text.isdigit():
            raise ValueError(
                "Minecraft initial inventory slot is unsupported: " + slot_text
            )
        index = int(slot_text)
    if not 0 <= index <= 40:
        raise ValueError("Minecraft initial inventory slot index must be in [0, 40]")
    if index <= 8:
        return f"hotbar.{index}"
    if index <= 35:
        return f"inventory.{index - 9}"
    return _MINECRAFT_INDEXED_EQUIPMENT_SLOTS[index]


def _jvm_memory_bytes(value: str) -> int:
    text = value.strip().upper()
    if not text:
        raise ValueError("JVM memory quantity is required")
    unit = text[-1]
    if unit in _JVM_MEMORY_UNITS:
        digits = text[:-1]
        multiplier = _JVM_MEMORY_UNITS[unit]
    else:
        digits = text
        multiplier = 1
    if not digits.isdigit() or int(digits) <= 0:
        raise ValueError(f"invalid JVM memory quantity: {value!r}")
    return int(digits) * multiplier


def minecraft_server_resource_requirement(
    *,
    xmx: str = _MINECRAFT_SERVER_XMX,
) -> ComputeRequirement:
    """Single physical contract for Minecraft launch and steady state."""

    heap = _jvm_memory_bytes(xmx)
    # Reserve only quantities frozen by the physical service contract. JVM
    # off-heap, supervisor PID fanout and descriptor fanout are runtime facts;
    # inventing fixed multipliers here would turn estimates into false Authority
    # truth. Their residual capacity remains observed continuously by the host
    # resource authority and the adaptive pressure gate.
    return ComputeRequirement(
        memory_bytes=heap,
        require_host_runtime=True,
    )


def _minecraft_compute_requirement(spec: MinecraftServerSpec) -> ComputeRequirement:
    return minecraft_server_resource_requirement(xmx=spec.xmx)


def minecraft_lifetime_resource_demand() -> ResourceCompetitionDemand:
    compute = minecraft_server_resource_requirement()
    return ResourceCompetitionDemand(
        cpu_cores_per_permit=compute.cpu_cores,
        memory_bytes_per_permit=compute.memory_bytes,
    )


class _MinecraftChildProcessAbsent(RuntimeError):
    """The exact container-local PID no longer exists."""


class _MinecraftChildProcessIdentityStale(RuntimeError):
    """A durable PID publication refers to a reused process generation."""


class _MinecraftChildProcessInspectionIndeterminate(RuntimeError):
    """Provider truth could not prove child presence or absence safely."""


class _DockerMinecraftCapsule:
    """One warm Docker realization owned solely by UniversalResourceAuthority."""

    def __init__(
        self,
        *,
        authority: UniversalResourceAuthority,
        provider: DockerPhysicalProvider,
        image: str,
        image_digest: str,
        runner: LocalCommandRunnerPort,
        task_group: TaskGroupPort,
        instances_root: Path,
        asset_root: Path,
        recovery_root: Path,
        server_distributions_root: Path,
        bridge_distributions_root: Path,
        runtime_identity_digest: str,
    ) -> None:
        if not isinstance(authority, UniversalResourceAuthority):
            raise TypeError("Minecraft capsule requires UniversalResourceAuthority")
        if not isinstance(provider, DockerPhysicalProvider):
            raise TypeError("Minecraft capsule requires DockerPhysicalProvider")
        if (
            type(runtime_identity_digest) is not str
            or len(runtime_identity_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in runtime_identity_digest)
        ):
            raise ValueError("Minecraft capsule runtime identity must be lowercase sha256")
        if (
            type(image_digest) is not str
            or len(image_digest) != 64
            or any(ch not in "0123456789abcdef" for ch in image_digest)
        ):
            raise ValueError("Minecraft capsule image digest must be lowercase sha256")
        self.authority = authority
        self.provider = provider
        self.image = image
        self.image_digest = image_digest
        self.runner = runner
        self.task_group = task_group
        self.instances_root = instances_root.resolve()
        self.asset_root = asset_root.resolve()
        self.recovery_root = recovery_root.resolve()
        self.server_distributions_root = server_distributions_root.resolve()
        self.bridge_distributions_root = bridge_distributions_root.resolve()
        if not self.server_distributions_root.is_dir():
            raise FileNotFoundError(
                "Minecraft server distribution root is missing: "
                + str(self.server_distributions_root)
            )
        if not self.bridge_distributions_root.is_dir():
            raise FileNotFoundError(
                "Minecraft bridge runtime distribution root is missing: "
                + str(self.bridge_distributions_root)
            )
        self.runtime_identity_digest = runtime_identity_digest
        self.lock = threading.RLock()
        self.allocation_id = "minecraft-capsule:" + canonical_digest({
            "schema": "noetrium.minecraft-warm-capsule.v4",
            "runtime_identity_digest": runtime_identity_digest,
            "instances_root": str(self.instances_root),
            "asset_root": str(self.asset_root),
            "recovery_root": str(self.recovery_root),
            "server_distributions_root": str(self.server_distributions_root),
            "bridge_distributions_root": str(self.bridge_distributions_root),
        })[:28]
        self.resource_key = "container:" + self.allocation_id
        self._ticket: NoetriumUnit | None = None
        self._physical_identity: NoetriumUnit | None = None

    @property
    def docker_executable(self) -> str:
        return self.provider.docker_executable

    def _topology(self):
        return resource_topology(
            "minecraft-capsule-topology:" + self.runtime_identity_digest[:24],
            resources=(
                resource_node(
                    "capsule",
                    kind="container",
                    authority_key=self.resource_key,
                    realization=True,
                ),
            ),
        )

    def _claims(
        self,
        _snapshot,
        generation: int,
    ) -> tuple[NoetriumUnit, ...]:
        return (
            resource_claim(
                claim_id="minecraft-capsule:" + canonical_digest({
                    "resource_key": self.resource_key,
                    "generation": generation,
                    "runtime_identity_digest": self.runtime_identity_digest,
                }),
                resource_key=self.resource_key,
                holder_key=scope_key(PLATFORM_SCOPE),
                generation=generation,
                owner_scope=PLATFORM_SCOPE,
                scope_generation=self.authority.ensure_scope_generation(
                    PLATFORM_SCOPE
                ).generation,
                scope_lease_id=None,
                owner_lease_id=None,
                exclusive=("docker-container:" + self.allocation_id,),
                attributes={
                    "kind": "container",
                    "runtime_identity_digest": self.runtime_identity_digest,
                },
            ),
        )

    def _spec(self, _snapshot) -> ResourceRealizationSpec:
        return ResourceRealizationSpec(
            "docker",
            {
                "run_args": (
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
                    "-v",
                    (
                        f"{self.server_distributions_root}:"
                        f"{self.server_distributions_root}:ro"
                    ),
                    "-v",
                    (
                        f"{self.bridge_distributions_root}:"
                        f"{self.bridge_distributions_root}:ro"
                    ),
                    "sha256:" + self.image_digest,
                    "-c",
                    "while :; do sleep 3600; done",
                ),
            },
        )

    def _authority_ticket(self) -> NoetriumUnit | None:
        snapshot = self.authority.snapshot_for_resource_keys(
            frozenset({self.resource_key})
        )
        return snapshot.current_ticket_for(self.resource_key)

    def _current(self):
        ticket = self._authority_ticket()
        if ticket is None:
            return None
        observation = self.provider.observe(ticket)
        return ticket, observation

    def _adopt_current(self, current) -> bool:
        if current is None:
            return False
        ticket, observation = current
        physical = observation_field(observation, "physical_identity")
        if (
            not observation_field(observation, "exists")
            or not observation_field(observation, "ready")
            or physical is None
        ):
            return False
        with self.lock:
            self._ticket = ticket
            self._physical_identity = physical
        return True

    @property
    def generation_digest(self) -> str:
        ticket = self._authority_ticket()
        generation = 0 if ticket is None else ticket_field(ticket, "generation")
        return canonical_digest({
            "schema": "noetrium.minecraft-warm-capsule-generation.v4",
            "resource_key": self.resource_key,
            "generation": generation,
            "runtime_identity_digest": self.runtime_identity_digest,
        })

    @property
    def container_name(self) -> str:
        with self.lock:
            physical = getattr(self, "_physical_identity", None)
        if physical is None:
            if not self._adopt_current(self._current()):
                raise RuntimeError("Minecraft warm capsule is not running")
            with self.lock:
                physical = self._physical_identity
        if physical is None:
            raise RuntimeError("Minecraft warm capsule lost physical identity")
        return physical_field(physical, "physical_id")

    def assert_healthy(self) -> None:
        # attach_existing/start freeze one Authority-proven exact physical
        # identity. Hot-path checks re-read only Authority truth; they never
        # amplify one warm capsule into O(branches) docker ps+inspect calls.
        # Exact docker exec/readiness remains the physical fail-close fence.
        with self.lock:
            cached_ticket = self._ticket
            cached_physical = getattr(self, "_physical_identity", None)
        if cached_ticket is None or cached_physical is None:
            if not self._adopt_current(self._current()):
                raise RuntimeError("Minecraft warm capsule is not running")
            with self.lock:
                cached_ticket = self._ticket
        current_ticket = self._authority_ticket()
        if (
            current_ticket is None
            or cached_ticket is None
            or ticket_field(current_ticket, "ticket_id")
            != ticket_field(cached_ticket, "ticket_id")
            or ticket_field(current_ticket, "generation")
            != ticket_field(cached_ticket, "generation")
            or ticket_field(current_ticket, "spec_digest")
            != ticket_field(cached_ticket, "spec_digest")
        ):
            raise RuntimeError("Minecraft warm capsule Authority generation drifted")

    def attach_existing(self) -> bool:
        """Adopt only an existing exact ticket realization; never create one."""
        return self._adopt_current(self._current())

    def start(self) -> None:
        self.authority.reconcile(
            self._topology(),
            claim_candidates={"capsule": self._claims},
            realization_specs={"capsule": self._spec},
            providers={"docker": self.provider},
        )
        if not self._adopt_current(self._current()):
            raise RuntimeError("Minecraft capsule realization did not converge")

    def _child_proc_start_identity(self, pid: int) -> str:
        self.assert_healthy()
        result = self.runner.run(
            (
                self.docker_executable,
                "exec",
                self.container_name,
                "/bin/sh",
                "-c",
                (
                    f"if [ ! -r /proc/{pid}/stat ]; then exit 44; fi; "
                    f"cat /proc/{pid}/stat"
                ),
            ),
            timeout_seconds=10.0,
        )
        if result.returncode == 44:
            raise _MinecraftChildProcessAbsent(
                f"Minecraft capsule child process {pid} is absent"
            )
        if result.returncode != 0:
            raise _MinecraftChildProcessInspectionIndeterminate(
                "Minecraft capsule child procfs inspection failed: "
                + result.stderr[-1000:]
            )
        raw = result.stdout.strip()
        right = raw.rfind(")")
        if right < 0:
            raise RuntimeError("Minecraft capsule child procfs identity malformed")
        fields = raw[right + 2 :].split()
        if len(fields) <= 19:
            raise RuntimeError("Minecraft capsule child procfs identity incomplete")
        container_id = self.container_name
        return (
            "docker-exec:"
            + container_id
            + ":"
            + str(pid)
            + ":"
            + fields[19]
        )

    def _child_proc_command(self, pid: int) -> str:
        self.assert_healthy()
        result = self.runner.run(
            (
                self.docker_executable,
                "exec",
                self.container_name,
                "/bin/sh",
                "-c",
                (
                    f"if [ ! -r /proc/{pid}/cmdline ]; then exit 44; fi; "
                    f"tr '\\000' ' ' < /proc/{pid}/cmdline"
                ),
            ),
            timeout_seconds=10.0,
        )
        if result.returncode == 44:
            raise _MinecraftChildProcessAbsent(
                f"Minecraft capsule child process {pid} is absent"
            )
        if result.returncode != 0:
            raise _MinecraftChildProcessInspectionIndeterminate(
                "Minecraft capsule child command inspection failed: "
                + result.stderr[-1000:]
            )
        return result.stdout.strip()

    def child_process_identity_from_path(
        self,
        pid_path: Path,
        *,
        expected_command_marker: str,
    ) -> ServiceProcessIdentity:
        try:
            fields = pid_path.read_text(encoding="utf-8").strip().split()
            pid = int(fields[0])
        except FileNotFoundError as exc:
            # The recovery scan and another successful retirement may race.
            # A publication that vanished after enumeration is already outside
            # the recoverable child namespace and therefore converged.
            raise _MinecraftChildProcessAbsent(
                "Minecraft process pid publication disappeared"
            ) from exc
        except (OSError, ValueError, IndexError) as exc:
            raise RuntimeError(
                "Minecraft process pid publication is malformed or unreadable"
            ) from exc
        if pid <= 0:
            raise RuntimeError("Minecraft process pid is invalid")
        start_identity = self._child_proc_start_identity(pid)
        if len(fields) >= 2 and fields[1] != start_identity.rsplit(":", 1)[-1]:
            raise _MinecraftChildProcessIdentityStale(
                "Minecraft recovered process generation is stale"
            )
        if expected_command_marker not in self._child_proc_command(pid):
            # PID+start-time is the generation identity. A command mismatch can
            # be the short launch-shell -> exec window; preserve evidence and
            # retry rather than declaring convergence.
            raise _MinecraftChildProcessInspectionIndeterminate(
                "Minecraft recovered process command identity is indeterminate"
            )
        return ServiceProcessIdentity(pid, start_identity)

    def child_identity_alive(self, process: ServiceProcessIdentity) -> bool:
        try:
            observed = self._child_proc_start_identity(process.pid)
        except _MinecraftChildProcessAbsent:
            return False
        return observed == process.start_identity

    def terminate_child_pid(
        self,
        process: ServiceProcessIdentity,
        *,
        signal: str,
    ) -> None:
        result = self.runner.run(
            (
                self.docker_executable,
                "exec",
                self.container_name,
                "/bin/sh",
                "-c",
                f"kill -{signal} {process.pid}",
            ),
            timeout_seconds=10.0,
        )
        if result.returncode != 0 and self.child_identity_alive(process):
            raise RuntimeError(
                f"Minecraft child process {signal} failed: "
                + result.stderr[-1000:]
            )

    def terminate_recovered_child(
        self,
        process: ServiceProcessIdentity,
        *,
        stop_timeout_s: float = 30.0,
    ) -> None:
        if not self.child_identity_alive(process):
            return
        self.terminate_child_pid(process, signal="TERM")
        deadline = time.monotonic() + float(stop_timeout_s)
        while (
            self.child_identity_alive(process)
            and time.monotonic() < deadline
        ):
            blocking_wait(0.05)
        if self.child_identity_alive(process):
            self.terminate_child_pid(process, signal="KILL")
            deadline = time.monotonic() + 5.0
            while (
                self.child_identity_alive(process)
                and time.monotonic() < deadline
            ):
                blocking_wait(0.05)
        if self.child_identity_alive(process):
            raise RuntimeError(
                "Minecraft recovered child survived fenced cleanup"
            )

    def _overlay_server_generations(
        self,
        *,
        container_name: str | None = None,
    ) -> tuple[tuple[ServiceProcessIdentity, str | None, bool], ...]:
        """Observe physical Minecraft server generations and overlay keys.

        ``container_name`` may identify any Authority-owned warm Minecraft
        capsule already validated by ``_authority_owned_capsule_containers``.
        Provider truth is fenced by container id, PID and procfs start-time.
        A Java process whose cwd is already deleted has no live world namespace
        and is therefore represented with ``overlay_key=None`` so global
        maintenance can retire it even after its durable PID publication vanished.
        """

        if container_name is None:
            self.assert_healthy()
            container_id = self.container_name
        else:
            container_id = str(container_name).strip()
            if not container_id:
                raise ValueError("Minecraft capsule container identity is required")
        command = (
            "for d in /proc/[0-9]*; do "
            "p=${d#/proc/}; "
            "[ -r \"$d/cmdline\" ] || continue; "
            "exe=$(readlink \"$d/exe\" 2>/dev/null) || continue; "
            "case \"$exe\" in */java) ;; *) continue ;; esac; "
            "cmd=$(tr '\\000' ' ' < \"$d/cmdline\" 2>/dev/null) || continue; "
            "case \"$cmd\" in *server.jar*) ;; *) continue ;; esac; "
            "cwd=$(readlink \"$d/cwd\" 2>/dev/null) || continue; "
            "case \"$cwd\" in "
            "*/environment-fabric/minecraft/environment-instances/*|*' (deleted)') ;; "
            "*) continue ;; esac; "
            "start=$(awk '{print $22}' \"$d/stat\" 2>/dev/null) || continue; "
            "printf '%s|%s|%s\\n' \"$p\" \"$start\" \"$cwd\"; "
            "done"
        )
        result = self.runner.run(
            (
                self.docker_executable,
                "exec",
                container_id,
                "/bin/sh",
                "-c",
                command,
            ),
            timeout_seconds=10.0,
        )
        if result.returncode != 0:
            raise _MinecraftChildProcessInspectionIndeterminate(
                "Minecraft overlay child scan failed: " + result.stderr[-1000:]
            )
        generations: list[tuple[ServiceProcessIdentity, str | None, bool]] = []
        deleted_suffix = " (deleted)"
        for raw in result.stdout.splitlines():
            fields = raw.strip().split("|", 2)
            if len(fields) != 3:
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft overlay child scan returned malformed identity"
                )
            try:
                pid = int(fields[0])
                start = int(fields[1])
            except ValueError as exc:
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft overlay child scan returned invalid identity"
                ) from exc
            if pid <= 0 or start <= 0:
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft overlay child scan returned non-positive identity"
                )
            cwd = fields[2]
            deleted = cwd.endswith(deleted_suffix)
            live_path = cwd.removesuffix(deleted_suffix)
            key = Path(live_path).name
            overlay_key: str | None
            if re.fullmatch(r"[0-9a-f]{64}", key):
                overlay_key = key
            elif deleted:
                # Once cwd itself is unlinked, the world namespace cannot be a
                # legitimate live branch.  Keep the physical generation but do
                # not invent a logical overlay identity.
                overlay_key = None
            else:
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft overlay child scan returned invalid overlay identity"
                )
            generations.append(
                (
                    ServiceProcessIdentity(
                        pid,
                        "docker-exec:"
                        + container_id
                        + ":"
                        + str(pid)
                        + ":"
                        + str(start),
                    ),
                    overlay_key,
                    deleted,
                )
            )
        generations.sort(
            key=lambda row: (row[0].pid, row[0].start_identity, row[1] or "")
        )
        return tuple(generations)

    def _batch_alive_processes(
        self,
        processes: tuple[ServiceProcessIdentity, ...],
        *,
        container_name: str | None = None,
    ) -> tuple[ServiceProcessIdentity, ...]:
        """Recheck many exact container-local generations in one provider call."""

        if not processes:
            return ()
        if container_name is None:
            self.assert_healthy()
            try:
                container_id = self.container_name
            except RuntimeError:
                return ()
        else:
            container_id = str(container_name).strip()
            if not container_id:
                raise ValueError("Minecraft capsule container identity is required")
        specs: list[str] = []
        requested: dict[tuple[int, str], ServiceProcessIdentity] = {}
        for process in processes:
            fields = process.start_identity.rsplit(":", 1)
            if len(fields) != 2 or not fields[1].isdigit():
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft batch recovery received malformed start identity"
                )
            expected_prefix = (
                "docker-exec:" + container_id + ":" + str(process.pid) + ":"
            )
            if not process.start_identity.startswith(expected_prefix):
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft batch recovery container generation drifted"
                )
            start = fields[1]
            specs.append(shlex.quote(f"{process.pid}:{start}"))
            requested[(process.pid, start)] = process
        command = (
            "# noetrium-minecraft-batch-alive\n"
            "for spec in " + " ".join(specs) + "; do "
            "p=${spec%%:*}; expected=${spec#*:}; "
            "[ -r \"/proc/$p/stat\" ] || continue; "
            "if actual=$(awk '{print $22}' \"/proc/$p/stat\" 2>/dev/null); then :; "
            "else [ ! -e \"/proc/$p/stat\" ] && continue; exit 91; fi; "
            "[ \"$actual\" = \"$expected\" ] || continue; "
            "printf '%s|%s\\n' \"$p\" \"$actual\"; "
            "done"
        )
        result = self.runner.run(
            (
                self.docker_executable,
                "exec",
                container_id,
                "/bin/sh",
                "-c",
                command,
            ),
            timeout_seconds=10.0,
        )
        if result.returncode != 0:
            raise _MinecraftChildProcessInspectionIndeterminate(
                "Minecraft batch generation inspection failed "
                f"with exit code {result.returncode}: "
                + result.stderr[-1000:]
            )
        alive: list[ServiceProcessIdentity] = []
        for raw in result.stdout.splitlines():
            fields = raw.strip().split("|", 1)
            if len(fields) != 2 or not fields[0].isdigit() or not fields[1].isdigit():
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft batch generation inspection returned malformed identity"
                )
            process = requested.get((int(fields[0]), fields[1]))
            if process is None:
                raise _MinecraftChildProcessInspectionIndeterminate(
                    "Minecraft batch generation inspection returned unknown identity"
                )
            alive.append(process)
        alive.sort(key=lambda row: (row.pid, row.start_identity))
        return tuple(alive)

    def _terminate_abandoned_children_batch(
        self,
        processes: tuple[ServiceProcessIdentity, ...],
        *,
        container_name: str | None = None,
    ) -> tuple[str, ...]:
        """Physically retire proven-orphan generations with one fenced sweep.

        Normal lifetime retirement remains graceful.  These generations have
        already lost global compute ownership (or their overlay is physically
        deleted), so their disposable child state has no legitimate consumer.
        Recheck PID+procfs start identity immediately before SIGKILL, then prove
        exact absence in batched provider scans.
        """

        unique = tuple(
            sorted(
                {
                    (process.pid, process.start_identity): process
                    for process in processes
                }.values(),
                key=lambda row: (row.pid, row.start_identity),
            )
        )
        if container_name is None:
            container_id = self.container_name
        else:
            container_id = str(container_name).strip()
            if not container_id:
                raise ValueError("Minecraft capsule container identity is required")
        alive = self._batch_alive_processes(
            unique, container_name=container_id
        )
        if not alive:
            return ()
        specs = tuple(
            shlex.quote(
                f"{process.pid}:{process.start_identity.rsplit(':', 1)[-1]}"
            )
            for process in alive
        )
        command = (
            "# noetrium-minecraft-batch-kill\n"
            "set -eu; "
            "for spec in " + " ".join(specs) + "; do "
            "p=${spec%%:*}; expected=${spec#*:}; "
            "[ -r \"/proc/$p/stat\" ] || continue; "
            "if actual=$(awk '{print $22}' \"/proc/$p/stat\" 2>/dev/null); then :; "
            "else [ ! -e \"/proc/$p/stat\" ] && continue; exit 92; fi; "
            "[ \"$actual\" = \"$expected\" ] || continue; "
            "if kill -KILL \"$p\" 2>/dev/null; then :; "
            "else [ ! -e \"/proc/$p/stat\" ] && continue; exit 93; fi; "
            "done"
        )
        result = self.runner.run(
            (
                self.docker_executable,
                "exec",
                container_id,
                "/bin/sh",
                "-c",
                command,
            ),
            timeout_seconds=10.0,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Minecraft abandoned child batch termination failed "
                f"with exit code {result.returncode}: "
                + result.stderr[-1000:]
            )
        deadline = time.monotonic() + 5.0
        pending = alive
        while pending and time.monotonic() < deadline:
            pending = self._batch_alive_processes(
                pending, container_name=container_id
            )
            if pending:
                blocking_wait(0.02)
        if pending:
            sample = ",".join(str(row.pid) for row in pending[:8])
            raise RuntimeError(
                "Minecraft abandoned child batch survived fenced SIGKILL: "
                + sample
            )
        return tuple(
            "minecraft-abandoned-child-stopped:"
            + str(process.pid)
            + ":"
            + process.start_identity
            for process in alive
        )

    def _authority_owned_capsule_containers(self) -> tuple[str, ...]:
        """Return exact live Docker ids for every Authority-owned warm capsule.

        Warm capsules intentionally survive individual research runs and image
        revisions.  Global child maintenance must therefore follow Authority
        tickets rather than only the capsule selected by the current controller.
        """

        orphaned_groups = self.authority.orphaned_claim_groups_for_claim_kinds(
            frozenset({"compute", "minecraft-server"})
        )
        orphan_claim_ids = frozenset(
            str(claim_field(claim, "claim_id"))
            for _lease_id, claims in orphaned_groups
            for claim in claims
        )
        snapshot = self.authority.snapshot_for_claim_kinds(
            frozenset({"container"})
        )
        resource_keys = tuple(
            sorted(
                {
                    str(claim_field(claim, "resource_key"))
                    for claim in snapshot.claims
                    if str(claim_field(claim, "claim_id")) not in orphan_claim_ids
                    for attrs in (dict(claim_field(claim, "attributes") or {}),)
                    if attrs.get("kind") == "container"
                    and re.fullmatch(
                        r"container:minecraft-capsule:[0-9a-f]{28}",
                        str(claim_field(claim, "resource_key")),
                    )
                }
            )
        )
        containers: list[str] = []
        for resource_key in resource_keys:
            ticket = snapshot.current_ticket_for(resource_key)
            if ticket is None:
                continue
            if ticket_field(ticket, "state") is not TicketState.BOUND:
                continue
            if str(ticket_field(ticket, "provider_kind")) != "docker":
                raise RuntimeError(
                    "Minecraft capsule Authority ticket is not Docker-backed"
                )
            observation = self.provider.observe(ticket)
            if (
                not observation_field(observation, "exists")
                or not observation_field(observation, "ready")
                or observation_field(observation, "physical_identity") is None
            ):
                continue
            physical = observation_field(observation, "physical_identity")
            container_id = str(physical_field(physical, "physical_id")).strip()
            if not container_id:
                raise RuntimeError(
                    "Minecraft capsule observation omitted Docker physical id"
                )
            containers.append(container_id)
        return tuple(sorted(set(containers)))

    def reconcile_authority_owned_capsule_children(
        self,
        *,
        active_compute_key_prefixes: frozenset[str],
    ) -> tuple[str, ...]:
        """Retire orphan server generations across every live warm capsule.

        Active branch ownership is global Authority truth.  A server is safe to
        retire only when its overlay is outside that set, or when its cwd has
        already been physically deleted.  Every termination is still fenced by
        exact container id + PID + procfs start-time immediately before kill.
        """

        if type(active_compute_key_prefixes) is not frozenset or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{24}", value) is None
            for value in active_compute_key_prefixes
        ):
            raise TypeError(
                "Minecraft recovery active compute keys must be a frozenset of "
                "24-character lowercase hex prefixes"
            )
        evidence: list[str] = []
        for container_id in self._authority_owned_capsule_containers():
            generations = self._overlay_server_generations(
                container_name=container_id
            )
            abandoned = tuple(
                process
                for process, overlay_key, deleted in generations
                if deleted
                or overlay_key is None
                or overlay_key[:24] not in active_compute_key_prefixes
            )
            evidence.extend(
                self._terminate_abandoned_children_batch(
                    abandoned, container_name=container_id
                )
            )
        return tuple(evidence)

    def _active_compute_key_prefixes(self) -> frozenset[str]:
        """Read the live Minecraft compute ownership set from Authority truth."""
        orphaned_groups = self.authority.orphaned_claim_groups_for_claim_kinds(
            frozenset({"compute", "minecraft-server"})
        )
        orphan_claim_ids = frozenset(
            str(claim_field(claim, "claim_id"))
            for _lease_id, claims in orphaned_groups
            for claim in claims
        )
        snapshot = self.authority.snapshot_for_claim_kinds(
            frozenset({"compute", "minecraft-server"})
        )
        live_compute_prefixes = frozenset(
            consumer.split(":", 1)[1]
            for claim in snapshot.claims
            if str(claim_field(claim, "claim_id")) not in orphan_claim_ids
            for attrs in (dict(claim_field(claim, "attributes") or {}),)
            for consumer in (str(attrs.get("consumer_resource_key") or ""),)
            if attrs.get("kind") == "compute"
            and consumer.startswith("minecraft-branch:")
            and re.fullmatch(r"[0-9a-f]{24}", consumer.split(":", 1)[1])
        )
        # A non-retired ticket is not ownership by itself: an expired Scope can
        # leave PREPARED/BOUND tickets precisely because generic orphan cleanup
        # must wait for physical retirement.  Protect a ticket prefix only while
        # its exact server resource still has a non-orphan claim.  Otherwise the
        # abandoned-child sweep must be allowed to prove the JVM absent in one
        # fenced batch before formal ticket retirement.
        live_server_resource_keys = frozenset(
            str(claim_field(claim, "resource_key"))
            for claim in snapshot.claims
            if str(claim_field(claim, "claim_id")) not in orphan_claim_ids
            for attrs in (dict(claim_field(claim, "attributes") or {}),)
            if attrs.get("kind") == "minecraft-server"
        )
        ticket_owned_prefixes = frozenset(
            match.group(1)
            for ticket in snapshot.tickets
            if ticket_field(ticket, "state") is not TicketState.RETIRED
            for resource_key in (str(ticket_field(ticket, "resource_key")),)
            if resource_key in live_server_resource_keys
            for match in (
                re.fullmatch(
                    r"minecraft-branch:([0-9a-f]{24}):server",
                    resource_key,
                ),
            )
            if match is not None
        )
        return live_compute_prefixes | ticket_owned_prefixes

    def retire_inactive_legacy_capsules(self) -> tuple[str, ...]:
        """Retire superseded warm capsules with no live server ownership.

        Warm reuse is valid only inside one runtime identity. Keeping every
        historical profile generation warm leaks all child processes if a
        request dies before its local controller can retire them. Authority is
        the sole liveness oracle: a legacy capsule is eligible only when no
        non-orphan minecraft-server claim names its runtime identity.
        """

        orphan_claim_ids = frozenset(
            str(claim_field(claim, "claim_id"))
            for _lease_id, claims
            in self.authority.orphaned_claim_groups_for_claim_kinds(
                frozenset({"container", "minecraft-server"})
            )
            for claim in claims
        )
        snapshot = self.authority.snapshot_for_claim_kinds(
            frozenset({"container", "minecraft-server"})
        )
        live_server_runtime_identities = frozenset(
            runtime_identity
            for claim in snapshot.claims
            if str(claim_field(claim, "claim_id")) not in orphan_claim_ids
            for attrs in (dict(claim_field(claim, "attributes") or {}),)
            if attrs.get("kind") == "minecraft-server"
            for runtime_identity in (attrs.get("runtime_identity_digest"),)
            if type(runtime_identity) is str
            and len(runtime_identity) == 64
            and all(ch in "0123456789abcdef" for ch in runtime_identity)
        )
        # A branch/server realization can have its own world runtime digest,
        # distinct from the parent's warm capsule runtime identity. The graph
        # ownership edge is therefore strictly stronger liveness evidence
        # than comparing those unrelated digests. Never request retirement of
        # a capsule while a live child claim still names that exact parent.
        # Even orphan candidates remain protected until Authority actually
        # releases their child claim in a subsequent reconciled snapshot.
        protected_parent_claim_ids = frozenset(
            parent_id
            for child in snapshot.claims
            for attrs in (dict(claim_field(child, "attributes") or {}),)
            for parent_id in (attrs.get("parent_claim_id"),)
            if type(parent_id) is str and parent_id
        )

        stale_resource_keys: list[str] = []
        for claim in snapshot.claims:
            attrs = dict(claim_field(claim, "attributes") or {})
            if attrs.get("kind") != "container":
                continue
            resource_key = str(claim_field(claim, "resource_key"))
            if not resource_key.startswith("container:minecraft-capsule:"):
                continue
            runtime_identity = attrs.get("runtime_identity_digest")
            if (
                type(runtime_identity) is not str
                or len(runtime_identity) != 64
                or any(ch not in "0123456789abcdef" for ch in runtime_identity)
            ):
                raise RuntimeError(
                    "Minecraft capsule claim lost canonical runtime identity: "
                    + resource_key
                )
            if (
                runtime_identity == self.runtime_identity_digest
                or runtime_identity in live_server_runtime_identities
                or str(claim_field(claim, "claim_id")) in protected_parent_claim_ids
            ):
                continue
            stale_resource_keys.append(resource_key)

        retired: list[str] = []
        for resource_key in sorted(stale_resource_keys):
            suffix = resource_key.removeprefix("container:minecraft-capsule:")
            try:
                self.authority.reconcile(
                    resource_topology(
                        "minecraft-legacy-capsule-retirement:" + suffix,
                        resources=(
                            resource_node(
                                "capsule",
                                kind="container",
                                authority_key=resource_key,
                                realization=True,
                            ),
                        ),
                    ),
                    claim_candidates={},
                    realization_specs={},
                    providers={self.provider.provider_kind: self.provider},
                    desired_resource_ids=frozenset(),
                )
            except ResourceClaimConflict:
                # A new server may have acquired this parent after the prior
                # read cut. Verify the exact ownership edge in a fresh
                # Authority snapshot; only that proven admission race makes
                # capsule retirement legitimately inapplicable. Never swallow
                # unrelated claim conflicts or bypass the Authority fence.
                fresh = self.authority.snapshot_for_claim_kinds(
                    frozenset({"container", "minecraft-server"})
                )
                old_parent_ids = {
                    str(claim_field(claim, "claim_id"))
                    for claim in fresh.claims
                    if str(claim_field(claim, "resource_key")) == resource_key
                }
                if not old_parent_ids or not any(
                    dict(claim_field(child, "attributes") or {}).get("parent_claim_id")
                    in old_parent_ids
                    for child in fresh.claims
                ):
                    raise
                continue
            retired.append(resource_key)
        if retired:
            self.authority.reconcile_orphan_claims_for_claim_kinds(
                frozenset({"container"})
            )
        return tuple(retired)

    def reconcile_abandoned_children(
        self,
        root: Path | None = None,
        *,
        active_compute_key_prefixes: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        """Serialize and retire exact abandoned child generations.

        Active ownership is re-read *after* acquiring the physical recovery
        fence. A caller can wait behind another controller for an arbitrary
        duration, so a pre-lock Authority snapshot is never sufficient to fence
        child processes safely.
        """
        if type(active_compute_key_prefixes) is not frozenset or any(
            type(value) is not str or not re.fullmatch(r"[0-9a-f]{24}", value)
            for value in active_compute_key_prefixes
        ):
            raise TypeError(
                "Minecraft recovery active compute keys must be a frozenset of "
                "24-character lowercase hex prefixes"
            )
        with InterprocessFileLock(
            self.recovery_root / ".abandoned-child-recovery.lock"
        ):
            fresh_active = self._active_compute_key_prefixes()
            return self._reconcile_abandoned_children_locked(
                root,
                active_compute_key_prefixes=(
                    fresh_active | active_compute_key_prefixes
                ),
            )

    def _reconcile_abandoned_children_locked(
        self,
        root: Path | None = None,
        *,
        active_compute_key_prefixes: frozenset[str] = frozenset(),
    ) -> tuple[str, ...]:
        """Retire all exact abandoned server/bridge generations in this capsule.

        The warm capsule itself remains reusable. Global provider truth is swept
        first so unowned Java generations converge in one fenced batch; durable
        PID publications then close evidence for stale/bridge generations.
        Healthy overlays are preserved while their global compute generation is
        active, so concurrent projects sharing the capsule remain isolated.
        """

        if type(active_compute_key_prefixes) is not frozenset or any(
            type(value) is not str or not re.fullmatch(r"[0-9a-f]{24}", value)
            for value in active_compute_key_prefixes
        ):
            raise TypeError(
                "Minecraft recovery active compute keys must be a frozenset of "
                "24-character lowercase hex prefixes"
            )

        recovery_root = self.recovery_root if root is None else Path(root).resolve()
        target_overlay_key: str | None = None
        if recovery_root != self.recovery_root:
            try:
                relative = recovery_root.relative_to(self.recovery_root)
            except ValueError as exc:
                raise ValueError(
                    "Minecraft recovery root escaped the capsule recovery authority"
                ) from exc
            if len(relative.parts) != 1 or not re.fullmatch(
                r"[0-9a-f]{64}", relative.parts[0]
            ):
                raise ValueError(
                    "Minecraft lifetime recovery root must identify one exact overlay"
                )
            target_overlay_key = relative.parts[0]

        candidates = (
            tuple(
                (path, "server.jar")
                for path in sorted(recovery_root.glob("**/minecraft-server-*.pid"))
            )
            + tuple(
                (
                    path,
                    str(self.bridge_distributions_root / "distributions"),
                )
                for path in sorted(recovery_root.glob("**/minecraft-bridge-*.pid"))
            )
        )
        current = self._current()
        if (
            current is None
            or not observation_field(current[1], "exists")
            or not observation_field(current[1], "ready")
        ):
            # No live capsule means no container-local child can still exist.
            for pid_path, _marker in candidates:
                pid_path.unlink(missing_ok=True)
            return ()

        evidence: list[str] = []
        errors: list[BaseException] = []

        # Reconcile physical server truth before walking PID publications. This
        # prevents N live abandoned servers from each consuming one long-lived
        # docker-exec teardown worker during crash recovery.
        try:
            overlay_generations = self._overlay_server_generations()
            abandoned_rows = tuple(
                (process, overlay_key)
                for process, overlay_key, deleted in overlay_generations
                if (
                    overlay_key == target_overlay_key
                    if target_overlay_key is not None
                    else (
                        deleted
                        or overlay_key is None
                        or overlay_key[:24] not in active_compute_key_prefixes
                    )
                )
            )
            abandoned_processes = tuple(row[0] for row in abandoned_rows)
            batch_evidence = self._terminate_abandoned_children_batch(
                abandoned_processes
            )
            evidence.extend(batch_evidence)
        except BaseException as exc:
            errors.append(exc)
            abandoned_rows = ()

        terminated_keys = {
            (process.pid, process.start_identity.rsplit(":", 1)[-1])
            for process, _overlay_key in abandoned_rows
        }

        def reconcile_one(_context, pid_path: Path, marker: str) -> str | None:
            overlay_key = pid_path.parent.name
            if (
                target_overlay_key is None
                and re.fullmatch(r"[0-9a-f]{64}", overlay_key)
                and overlay_key[:24] in active_compute_key_prefixes
            ):
                return None
            # Server publications corresponding to the provider batch are now
            # proven physically absent. Close their durable evidence locally
            # without another docker-exec round trip.
            if marker == "server.jar":
                try:
                    fields = pid_path.read_text(encoding="utf-8").strip().split()
                    published = (int(fields[0]), fields[1])
                except (OSError, ValueError, IndexError):
                    published = None
                if published is not None and published in terminated_keys:
                    pid_path.unlink(missing_ok=True)
                    return (
                        f"minecraft-capsule-child-stopped:{published[0]}:"
                        + published[1]
                    )
            try:
                process = self.child_process_identity_from_path(
                    pid_path,
                    expected_command_marker=marker,
                )
            except (
                _MinecraftChildProcessAbsent,
                _MinecraftChildProcessIdentityStale,
            ):
                pid_path.unlink(missing_ok=True)
                return None
            self.terminate_recovered_child(process)
            pid_path.unlink(missing_ok=True)
            return (
                f"minecraft-capsule-child-stopped:{process.pid}:"
                f"{process.start_identity}"
            )

        # Recovery is itself the owner-side physical convergence path. Never
        # hold the global recovery fence while submitting work back into a
        # shared lifecycle pool: concurrent environment initializers can occupy
        # that pool while waiting for this same fence, creating priority
        # inversion or a hard capacity deadlock. The number of residual PID
        # publications is bounded by crashed physical children, not workload
        # parallelism; converge them directly under the recovery owner.
        for pid_path, marker in candidates:
            try:
                result = reconcile_one(None, pid_path, marker)
            except BaseException as exc:
                errors.append(exc)
                continue
            if result is not None:
                evidence.append(result)

        if errors:
            raise ExceptionGroup(
                "Minecraft abandoned child recovery did not converge",
                errors,
            )
        return tuple(evidence)


    def close(self) -> None:
        """Detach this process while retaining the Authority-owned warm capsule."""
        with self.lock:
            self._ticket = None
            self._physical_identity = None


class _DockerLiveness:
    def __init__(self, server: "_DockerMinecraftServer") -> None:
        self.server = server

    def alive(self, process: ServiceProcessIdentity) -> bool:
        return self.server.alive(process)


class _MinecraftReadinessWake:
    """One-shot kernel wake on world writes OR the exact Docker-exec exit.

    Neither event establishes service readiness. The owning probe verifies the
    actual TCP/RCON receipt and Java process identity after every wake. This
    watch does not own or mutate the physical process lifetime.
    """

    def __init__(self, workdir: Path, host_process: object | None) -> None:
        self._watch = DirectoryChangeSignal(workdir, notify_writes=True)
        self._exit_fd: int | None = None
        try:
            pid = getattr(host_process, "pid", None)
            if type(pid) is int and hasattr(os, "pidfd_open"):
                self._exit_fd = os.pidfd_open(pid, 0)
        except BaseException:
            self._watch.close()
            raise

    def acknowledge(self) -> None:
        self._watch.acknowledge()

    def wait_changed_since(
        self, expected_signature: object, *, timeout_seconds: float,
    ) -> bool:
        return self._watch.wait_changed_since(
            expected_signature,
            timeout_seconds=timeout_seconds,
            wakeup_fd=self._exit_fd,
        )

    def close(self) -> None:
        descriptor, self._exit_fd = self._exit_fd, None
        try:
            self._watch.close()
        finally:
            if descriptor is not None:
                os.close(descriptor)


class _DockerMinecraftServer:
    def __init__(
        self,
        *,
        spec: MinecraftServerSpec,
        environment_generation: str,
        capsule: _DockerMinecraftCapsule,
        runner: LocalCommandRunnerPort,
        process_supervisor: ProcessSupervisorPort,
        asset_digest: str,
        recovery_root: Path,
        pristine_worlds: MinecraftPristineWorldTemplateCache,
    ) -> None:
        self.spec = spec
        self.capsule = capsule
        self.runner = runner
        if not callable(getattr(process_supervisor, "spawn_interactive", None)):
            raise TypeError(
                "Minecraft server requires platform process supervision authority"
            )
        self.process_supervisor = process_supervisor
        # Readiness is attested by TCP/RCON, never by log text. A Minecraft
        # server log mutation is only a kernel wakeup to re-test those ports.
        # The factory opens its watch at wait time, after the world directory
        # has been materialized; one shared inotify hub serves all worlds.
        readiness_wake_factory = lambda: _MinecraftReadinessWake(
            Path(spec.workdir), self._host_process,
        )
        self._tcp_readiness_probe = MinecraftTcpReadinessProbe(
            host=spec.host,
            port=spec.bound_port,
            wake_factory=readiness_wake_factory,
        )
        self.cpu_cores = _minecraft_compute_requirement(spec).cpu_cores
        require_sha256(asset_digest, "Minecraft server asset_digest")
        self.asset_digest = asset_digest
        self.recovery_root = recovery_root.resolve()
        if not isinstance(pristine_worlds, MinecraftPristineWorldTemplateCache):
            raise TypeError("Minecraft server requires pristine world template cache")
        self.pristine_worlds = pristine_worlds
        self.process: ServiceProcessIdentity | None = None
        self._host_process = None
        self.pid_path = (
            self.recovery_root
            / f"minecraft-server-{spec.bound_port}.pid"
        )
        Path(spec.workdir).mkdir(parents=True, exist_ok=True)
        self.recovery_root.mkdir(parents=True, exist_ok=True)
        self._pristine_reservation = self.pristine_worlds.prepare(
            spec, asset_digest=self.asset_digest
        )
        self._rcon_password = (
            "noetrium-"
            + canonical_digest({
                "schema": "noetrium.minecraft-rcon-secret.v1",
                "workdir": spec.workdir,
                "environment_generation": environment_generation,
            })[:48]
            if spec.rcon_endpoint is not None
            else None
        )
        self._server_readiness_probe = (
            None
            if spec.rcon_endpoint is None or self._rcon_password is None
            else MinecraftServerReadinessProbe(
                tcp=self._tcp_readiness_probe,
                wake_factory=readiness_wake_factory,
                rcon=MinecraftRconConsole(
                    spec.rcon_endpoint,
                    secret_provider=lambda: self._rcon_password
                    if self._rcon_password is not None
                    else "",
                ),
            )
        )
        prepared = prepare_local_server_files(spec, rcon_password=self._rcon_password)
        artifact_digest = self.asset_digest
        docker = shutil.which(self.capsule.docker_executable) or "/usr/bin/docker"
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
            "command": self._resource_bound_command(),
            "cpu_cores": self.cpu_cores,
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
        return self.capsule._child_proc_start_identity(pid)

    def _proc_command(self, pid: int) -> str:
        return self.capsule._child_proc_command(pid)

    def _resource_bound_command(self) -> tuple[str, ...]:
        """Derive the Java command from the Authority-granted compute realization."""
        command = tuple(self.spec.command())
        if not command:
            raise RuntimeError("Minecraft server command is empty")
        # ActiveProcessorCount constrains JVM internal worker sizing to the
        # compute allocation instead of host CPU cardinality. It is a physical
        # realization detail, never a downstream scheduling knob.
        active = max(1, int(math.ceil(float(self.cpu_cores))))
        return (command[0], f"-XX:ActiveProcessorCount={active}", *command[1:])

    def _process_identity_from_path(
        self,
        pid_path: Path,
        *,
        expected_command_marker: str,
    ) -> ServiceProcessIdentity:
        return self.capsule.child_process_identity_from_path(
            pid_path,
            expected_command_marker=expected_command_marker,
        )

    def _process_identity(self) -> ServiceProcessIdentity:
        return self._process_identity_from_path(
            self.pid_path,
            expected_command_marker="server.jar",
        )

    def _identity_alive(self, process: ServiceProcessIdentity) -> bool:
        return self.capsule.child_identity_alive(process)

    def alive(self, process: ServiceProcessIdentity) -> bool:
        # The attached docker-exec process is the owner-side physical lifetime
        # anchor for the exact Java generation launched by this server object.
        # While that anchor is still attached, liveness is proven locally in
        # O(1) without another Docker CLI round-trip. Recovery/adoption has no
        # such anchor and therefore falls back to the exact container /proc
        # generation proof below.
        if self.process == process:
            host = self._host_process
            if host is not None and host.poll() is None:
                return True
        # Recovered process state has no attached pidfd/owner anchor. The
        # process-generation identity check is the single authoritative
        # observation: duplicate probes separated by an arbitrary sleep do
        # not provide stronger liveness evidence and delay every failure.
        return self._identity_alive(process)

    def _terminate_recovered_process(
        self,
        process: ServiceProcessIdentity,
    ) -> None:
        self.capsule.terminate_recovered_child(
            process,
            stop_timeout_s=self.contract.stop_timeout_s,
        )

    def _terminate_pid(
        self,
        process: ServiceProcessIdentity,
        *,
        signal: str,
    ) -> None:
        self.capsule.terminate_child_pid(process, signal=signal)

    def start(self) -> ServiceStartOutcome:
        if self.process is not None:
            if not self.alive(self.process):
                # The exact prior process identity has been proven absent. It is
                # safe to forget only that physical projection and realize the
                # same Authority ticket again from its frozen spec.
                self.process = None
                self.pid_path.unlink(missing_ok=True)
            else:
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
        # Global capsule crash recovery is owned by the lifetime controller
        # once per controller generation. Re-running a whole-capsule child scan
        # for every assignment turns N independent server starts into O(N^2)
        # Docker control traffic and duplicates provider observation authority.
        self.capsule.assert_healthy()
        self.pid_path.unlink(missing_ok=True)
        workdir = str(Path(self.spec.workdir).resolve())
        log_path = str(
            Path(self.spec.workdir).resolve()
            / "noetrium-minecraft-server.log"
        )
        pid_path = shlex.quote(str(self.pid_path))
        log_target = shlex.quote(log_path)
        # The host docker-exec process is the durable physical ownership anchor.
        # Publish the container shell's exact PID/starttime and exec Java in place
        # so the process identity stays stable for the whole server lifetime.
        # A short-lived shell with a background Java child is forbidden: Docker
        # may tear that child down as soon as the exec session disappears.
        shell = (
            "set -eu; "
            f"tmp={pid_path}.tmp.$$; "
            "cleanup() { rc=$?; rm -f \"$tmp\"; exit \"$rc\"; }; "
            "trap cleanup EXIT HUP INT TERM; "
            "start=$(awk '{print $22}' /proc/$$/stat); "
            "printf '%s %s\\n' \"$$\" \"$start\" > \"$tmp\"; "
            f"mv \"$tmp\" {pid_path}; "
            f"exec {shlex.join(self._resource_bound_command())} >> {log_target} 2>&1"
        )
        # Install the kernel directory watch before launching Docker. The
        # atomic PID publication is an entry rename under recovery_root; this
        # prevents an event lost between launch and the first identity read.
        publication_signal = DirectoryChangeSignal(self.pid_path.parent)
        process_exit_fd: int | None = None
        try:
            self._host_process = self.process_supervisor.spawn_interactive(
                (
                    self.capsule.docker_executable,
                    "exec",
                    "-i",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "-w",
                    workdir,
                    self.container_name,
                    "/bin/sh",
                    "-c",
                    shell,
                ),
                cwd="/",
                environment={str(k): str(v) for k, v in os.environ.items()},
                start_new_session=True,
                creationflags=0,
            )
            host = self._host_process
            host_pid = getattr(host, "pid", None)
            if type(host_pid) is int and hasattr(os, "pidfd_open"):
                # Kernel process exit and directory rename share one blocking
                # selector; no timer-based process-exit probes are required.
                process_exit_fd = os.pidfd_open(host_pid, 0)
            deadline = time.monotonic() + self.contract.readiness_timeout_s
            last_error: BaseException | None = None
            while self.process is None:
                # Acknowledge only BEFORE reading the authoritative PID. A
                # rename after this point remains latched for the next wait.
                publication_signal.acknowledge()
                try:
                    self.process = self._process_identity()
                    continue
                except (
                    _MinecraftChildProcessAbsent,
                    _MinecraftChildProcessInspectionIndeterminate,
                ) as exc:
                    # Publication is an asynchronous launch handshake. Absence
                    # before the docker-exec shell has run is not evidence of
                    # process death; only the exact host ownership anchor exiting
                    # can prove launch failure before publication.
                    last_error = exc
                except BaseException as exc:
                    last_error = exc
                    break

                host = self._host_process
                if host is not None and host.poll() is not None:
                    stderr = ""
                    stream = getattr(host, "stderr", None)
                    if stream is not None:
                        try:
                            stderr = str(stream.read() or "")[-2000:]
                        except BaseException:
                            stderr = ""
                    raise RuntimeError(
                        "Minecraft docker-exec exited before Java PID publication"
                        + (": " + stderr if stderr else "")
                    ) from last_error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                publication_signal.wait_changed_since(
                    None, timeout_seconds=remaining, wakeup_fd=process_exit_fd,
                )
            if self.process is None:
                raise RuntimeError(
                    "Minecraft Java PID publication did not converge before service readiness deadline"
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
        except BaseException as start_error:
            cleanup_errors = self._cleanup_failed_start()
            if cleanup_errors:
                raise ExceptionGroup(
                    "Minecraft start failed and exact process cleanup did not converge",
                    [start_error, *cleanup_errors],
                ) from start_error
            raise
        finally:
            if process_exit_fd is not None:
                os.close(process_exit_fd)
            publication_signal.close()

    def _converge_host_process(self) -> tuple[BaseException, ...]:
        """Retire the exact Docker-exec anchor through Linux process events.

        A pidfd pins process identity and becomes readable on exit. Waiting on
        it requires neither repeated Popen.poll() nor a time-sliced Python
        sleep; the existing service contract supplies the termination budget.
        This is physical lifecycle cleanup, not a model/graph scheduling poll.
        """

        host = getattr(self, "_host_process", None)
        if host is None:
            return ()
        errors: list[BaseException] = []
        descriptor: int | None = None
        try:
            if host.poll() is not None:
                host.wait()
                return ()
            descriptor = os.pidfd_open(host.pid, 0)

            def await_exit() -> bool:
                if host.poll() is not None:
                    return True
                ready, _, _ = select.select(
                    (descriptor,), (), (), self.contract.stop_timeout_s,
                )
                # A readable pidfd proves exit for this generation. Reap only
                # once the kernel has delivered the exit notification.
                if ready:
                    host.wait()
                    return True
                return host.poll() is not None

            def signal_anchor(sig: int) -> None:
                # pidfd signals cannot accidentally target a reused numeric
                # PID. On Linux this is a physical authority primitive.
                signal.pidfd_send_signal(descriptor, sig, None, 0)

            signal_anchor(signal.SIGTERM)
            if not await_exit():
                signal_anchor(signal.SIGKILL)
                if not await_exit():
                    raise RuntimeError(
                        "Minecraft docker-exec ownership anchor did not converge"
                    )
        except ProcessLookupError:
            # Exit racing pidfd acquisition/signaling is legal only if the
            # owning Popen reports the exact child as already terminated.
            if host.poll() is None:
                errors.append(RuntimeError(
                    "Minecraft docker-exec pidfd lost a live process"
                ))
            else:
                host.wait()
        except BaseException as exc:
            errors.append(exc)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            # A failed pidfd signal/wait does NOT prove that the child exited.
            # Retain its original Popen ownership anchor and exact PID until
            # a subsequent convergence attempt observes terminal kernel state.
            # Dropping the only handle here would orphan a live Docker exec.
            if host.poll() is None:
                self._host_process = host
                if not errors:
                    errors.append(RuntimeError(
                        "Minecraft docker-exec remained live after retirement"
                    ))
            else:
                host.wait()
                self._host_process = None
        return tuple(errors)

    def _wait_process_exit(
        self,
        process: ServiceProcessIdentity,
        *,
        timeout_s: float,
    ) -> bool:
        """Wait for exact Java exit, event-driven for an owned docker-exec anchor."""

        host = getattr(self, "_host_process", None)
        if (
            self.process == process
            and host is not None
            and host.poll() is None
            and hasattr(os, "pidfd_open")
        ):
            descriptor: int | None = None
            try:
                descriptor = os.pidfd_open(host.pid, 0)
                ready, _, _ = select.select((descriptor,), (), (), timeout_s)
                if not ready:
                    return False
                # pidfd readability proves the exact host ownership anchor exited.
                # Reap it, then independently prove the in-container generation
                # absent so a Docker transport failure cannot masquerade as Java death.
                host.wait()
                return not self._identity_alive(process)
            except ProcessLookupError:
                if host.poll() is None:
                    return False
                host.wait()
                return not self._identity_alive(process)
            finally:
                if descriptor is not None:
                    os.close(descriptor)

        # Recovery/adoption has no host pidfd anchor. Retain the exact container
        # generation proof and bounded legacy wait only for that exceptional path.
        deadline = time.monotonic() + timeout_s
        while self.alive(process) and time.monotonic() < deadline:
            blocking_wait(0.05)
        return not self.alive(process)

    def _cleanup_failed_start(self) -> tuple[BaseException, ...]:
        """Fail-close cleanup preserving identity evidence until exact death."""
        errors: list[BaseException] = []
        process = self.process
        if process is not None:
            try:
                self._terminate_recovered_process(process)
            except BaseException as exc:
                # Keep PID/starttime proof if exact container termination could
                # not be established; recovery can retry without PID reuse risk.
                errors.append(exc)
            else:
                self.process = None
                self.pid_path.unlink(missing_ok=True)
        errors.extend(self._converge_host_process())
        return tuple(errors)

    def _release_pristine_reservation(self) -> None:
        reservation = self._pristine_reservation
        self._pristine_reservation = None
        if reservation is not None:
            reservation.close()

    def _tcp_ready_evidence(self) -> str:
        if self.process is None:
            raise RuntimeError("Minecraft Docker server is not started")
        self.capsule.assert_healthy()
        return self._tcp_readiness_probe.wait_ready(
            self.process,
            self.contract,
            _DockerLiveness(self),
        )

    def _startup_log_failure_details(self, returncode: int) -> str:
        """Capture bounded startup evidence only after the owned Java process exits."""

        log = Path(self.spec.workdir).resolve() / "noetrium-minecraft-server.log"
        tail = b""
        try:
            with log.open("rb") as source:
                source.seek(0, os.SEEK_END)
                size = source.tell()
                source.seek(max(0, size - 16384), os.SEEK_SET)
                tail = source.read(16384)
        except OSError:
            pass
        details = f"; docker_exec_exit_status={returncode}"
        if tail:
            digest = hashlib.sha256(tail).hexdigest()
            rendered = tail.decode("utf-8", errors="replace")[-4096:].strip()
            details += f"; startup_log_tail_sha256={digest}"
            if rendered:
                lines = tuple(line.strip() for line in rendered.splitlines() if line.strip())
                if lines:
                    # Preserve the established concise diagnostic contract while
                    # retaining the richer bounded tail for root-cause analysis.
                    details += "; last_java_log_line=" + lines[-1]
                details += "; startup_log_tail=" + repr(rendered)
        return details

    def _ready_evidence(self) -> str:
        if self.process is None:
            raise RuntimeError("Minecraft Docker server is not started")
        try:
            endpoint = self.spec.rcon_endpoint
            if endpoint is None:
                return self._tcp_ready_evidence()
            password = self._rcon_password
            if password is None:
                raise RuntimeError("Minecraft RCON endpoint lost its control secret")
            backend = _DockerLiveness(self)
            probe = self._server_readiness_probe
            if probe is None:
                raise RuntimeError("Minecraft RCON readiness probe is unavailable")
            return probe.wait_ready(
                self.process,
                self.contract,
                backend,
            )
        except MinecraftServerServiceError as exc:
            # An early Java process exit is a physical fact, not just an
            # unready TCP port. Preserve the exact Docker-exec exit receipt
            # and its last server-log observation in the same causal failure
            # *before* world/capsule teardown may discard ephemeral logs.
            host = getattr(self, "_host_process", None)
            if host is None:
                raise
            returncode = host.poll()
            if returncode is None:
                raise
            details = self._startup_log_failure_details(returncode)
            raise MinecraftServerServiceError(f"{exc}{details}") from exc

    def verify_ready(self) -> ServiceReadyObservation:
        evidence = self._ready_evidence()
        reservation = self._pristine_reservation
        if reservation is not None:
            # The first generator reaches readiness with no agent connected. Stop
            # cleanly so the world is fully saved, publish the pristine template,
            # then restart this same assignment from the authoritative source world.
            self._pristine_reservation = None
            self.stop()
            try:
                reservation.publish(
                    Path(self.spec.workdir).resolve() / self.spec.level_name
                )
            finally:
                reservation.close()
            self.start()
            evidence = self._ready_evidence()
        if self.process is None:
            raise RuntimeError("Minecraft Docker server is not started after readiness")
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

    def _rcon(self, command: str) -> str:
        endpoint = self.spec.rcon_endpoint
        password = self._rcon_password
        if endpoint is None or password is None:
            raise RuntimeError("Minecraft task setup requires an RCON control endpoint")
        return execute_local_rcon(endpoint, password=password, command=command, timeout_s=10.0)

    def prepare_scientific_player_join(self) -> Mapping[str, object]:
        """Eliminate vanilla join-radius randomness before the research agent joins.

        Assignment/world seeding fixes terrain identity, but vanilla may choose a
        different legal player spawn inside the world's spawn radius for each new
        player.  That makes otherwise paired treatments start from different local
        geometry.  Enforce the server-owned join invariant before Mineflayer opens
        its session, and preserve the exact mutation/verification receipt.
        """
        endpoint = self.spec.rcon_endpoint
        password = self._rcon_password
        if endpoint is None or password is None:
            raise RuntimeError(
                "Minecraft scientific player join requires an RCON control endpoint"
            )
        scenario = minecraft_scenario_from_mapping({
            "scenario_id": "noetrium.minecraft.scientific-player-join",
            "generation": "v1",
            "steps": ({
                "step_id": "deterministic-spawn-radius",
                "command": "gamerule spawnRadius 0",
                "verification_command": "gamerule spawnRadius",
                "expected_response_contains": "spawnRadius = 0",
            },),
        })
        console = MinecraftRconConsole(
            endpoint, secret_provider=lambda: password
        )
        receipt = RconMinecraftScenarioProvisioner(console, scenario).apply()
        from dataclasses import asdict
        receipt_payload = asdict(receipt)
        record = {
            "schema": "noetrium.minecraft-scientific-player-join.v1",
            "scenario_digest": receipt.scenario_digest,
            "receipt": receipt_payload,
        }
        path = (
            Path(self.spec.workdir).resolve()
            / "scientific-session-evidence"
            / (receipt.scenario_digest + ".json")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(
            path, (strict_finite_json_text(record) + "\n").encode("utf-8")
        )
        return {
            **record,
            "evidence_ref": (
                "minecraft:scientific-player-join:" + receipt.scenario_digest
                + ":receipt:" + canonical_digest(receipt_payload)
            ),
        }

    def _materialize_datapack(self, raw: Mapping[str, object]) -> None:
        pack_id = str(raw.get("pack_id", "")).strip()
        if not re.fullmatch(r"[a-z0-9_.-]+", pack_id):
            raise ValueError("Minecraft task datapack pack_id is invalid")
        pack_format = int(raw.get("pack_format", 48))
        if pack_format <= 0:
            raise ValueError("Minecraft task datapack pack_format must be positive")
        files = raw.get("files", {})
        if not isinstance(files, Mapping):
            raise TypeError("Minecraft task datapack files must be a mapping")
        root = (
            Path(self.spec.workdir).resolve()
            / self.spec.level_name
            / "datapacks"
            / pack_id
        )
        root.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(
            root / "pack.mcmeta",
            (
                json.dumps(
                    {
                        "pack": {
                            "pack_format": pack_format,
                            "description": str(
                                raw.get(
                                    "description",
                                    "Noetrium task-scoped datapack",
                                )
                            ),
                        }
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8"),
        )
        for name, value in files.items():
            relative = Path(str(name))
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
                or relative.parts[0] != "data"
            ):
                raise ValueError("Minecraft task datapack file path escaped data/")
            target = (root / relative).resolve()
            if root not in target.parents:
                raise ValueError("Minecraft task datapack file escaped pack root")
            target.parent.mkdir(parents=True, exist_ok=True)
            content = (
                strict_finite_json_text(value) + "\n"
                if isinstance(value, (Mapping, tuple, list))
                else str(value)
            )
            atomic_replace_bytes(target, content.encode("utf-8"))

    def apply_task_setup(
        self,
        setup: Mapping[str, object],
        *,
        settle_session: object | None = None,
    ) -> Mapping[str, object]:
        if setup.get("schema") not in MINECRAFT_TASK_SETUP_SCHEMAS:
            raise ValueError("Minecraft task setup schema drifted")
        evidence_refs: list[str] = []
        command_receipts: list[dict[str, object]] = []

        def setup_rcon(command: str) -> str:
            started_ns = time.perf_counter_ns()
            response = self._rcon(command)
            command_receipts.append({
                "ordinal": len(command_receipts),
                "command": command,
                "response": response,
                "elapsed_ns": time.perf_counter_ns() - started_ns,
            })
            return response
        datapack = setup.get("datapack")
        if datapack is not None:
            if not isinstance(datapack, Mapping):
                raise TypeError("Minecraft task datapack must be an object")
            self._materialize_datapack(datapack)
            setup_rcon("reload")

        dimension = str(setup.get("dimension") or "overworld").strip()
        if dimension not in {"overworld", "the_nether", "the_end"}:
            raise ValueError("Minecraft task setup dimension is invalid")
        biome = setup.get("biome")
        if isinstance(biome, str) and biome.strip():
            requested_biome = biome.strip().removeprefix("minecraft:")

            def locate_position(response: str) -> tuple[int, int, int]:
                bracket = re.search(r"\[([^\]]+)\]", response)
                if bracket is None:
                    raise RuntimeError(
                        "Minecraft task setup could not resolve requested biome: "
                        + requested_biome
                    )
                numbers = re.findall(r"-?\d+", bracket.group(1))
                if len(numbers) < 3:
                    raise RuntimeError("Minecraft biome location response is malformed")
                return int(numbers[0]), int(numbers[1]), int(numbers[2])

            def predicate_passed(response: str) -> bool:
                # Minecraft 1.21.1 execute predicates have a typed terminal
                # response. Treat any other response, including unloaded
                # positions, as a failed authority proof rather than assuming
                # the preceding mutation succeeded.
                return response.strip() == "Test passed"

            # A /locate target may be in an unloaded remote chunk. The former
            # implementation immediately evaluated a heightmap there; vanilla
            # answers "That position is not loaded", which was silently treated
            # as a successful teleport. Stage the server-owned player at each
            # locate result in spectator mode first: the player itself becomes
            # the chunk-load authority, without persistent forceload state.
            setup_rcon("gamemode spectator ResearchBot")
            locate = setup_rcon(
                f"execute in minecraft:{dimension} run locate biome "
                f"minecraft:{requested_biome}"
            )
            seen_positions: set[tuple[int, int, int]] = set()
            while True:
                x, y, z = locate_position(locate)
                candidate = (x, y, z)
                if candidate in seen_positions:
                    raise RuntimeError(
                        "Minecraft biome surface projection did not converge for "
                        + requested_biome
                    )
                seen_positions.add(candidate)
                setup_rcon(
                    f"execute in minecraft:{dimension} run tp ResearchBot {x} {y} {z}"
                )

                exact = setup_rcon(
                    "execute at ResearchBot if biome ~ ~ ~ "
                    f"minecraft:{requested_biome}"
                )
                if not predicate_passed(exact):
                    next_exact_locate = setup_rcon(
                        "execute at ResearchBot run locate biome "
                        f"minecraft:{requested_biome}"
                    )
                    # A repeated 3-D locate after an exact-cell mismatch is not
                    # proof that no playable surface exists. In the overworld,
                    # fall through to the same server-proven surface frontier
                    # used for repeated subterranean locate results. Only a
                    # genuinely new 3-D cell starts another locate iteration.
                    if (
                        dimension != "overworld"
                        or locate_position(next_exact_locate) not in seen_positions
                    ):
                        locate = next_exact_locate
                        continue

                if dimension != "overworld":
                    # Non-overworld heightmaps do not define a generally safe
                    # playable surface (for example the Nether roof). Preserve
                    # the located 3-D biome coordinate and move one block above
                    # it, then let the independent physical verifier fail closed
                    # if the resulting position is not actually in the biome.
                    setup_rcon(
                        f"execute in minecraft:{dimension} run tp "
                        f"ResearchBot {x} {y + 1} {z}"
                    )
                    break

                surface = setup_rcon(
                    "execute at ResearchBot positioned over "
                    "ocean_floor if biome ~ ~ ~ "
                    f"minecraft:{requested_biome}"
                )
                if predicate_passed(surface):
                    setup_rcon(
                        "execute at ResearchBot positioned over "
                        "ocean_floor run tp ResearchBot ~ ~1 ~"
                    )
                    post_surface = setup_rcon(
                        "execute at ResearchBot if biome ~ ~ ~ "
                        f"minecraft:{requested_biome}"
                    )
                    if predicate_passed(post_surface):
                        break

                # /locate biome is a 3-D search. Re-running it from the
                # upper biome field usually moves to a surface-compatible cell,
                # but some biomes can still return the same subterranean cell.
                # Keep that cheap path first. Only on an actual repeated locate
                # do a bounded horizontal surface search, with every candidate
                # independently proven by the server-side biome predicate.
                high_locate = setup_rcon(
                    "execute at ResearchBot positioned ~ "
                    f"{_MINECRAFT_OVERWORLD_MAX_BUILD_Y} ~ run locate biome "
                    f"minecraft:{requested_biome}"
                )
                if locate_position(high_locate) not in seen_positions:
                    locate = high_locate
                    continue

                surface_found = False
                probe_directions = (
                    (1, 0), (-1, 0), (0, 1), (0, -1),
                    (1, 1), (1, -1), (-1, 1), (-1, -1),
                )
                for radius in (16, 32, 64, 128):
                    for dx, dz in probe_directions:
                        probe_x = x + dx * radius
                        probe_z = z + dz * radius
                        setup_rcon(
                            f"execute in minecraft:{dimension} run tp ResearchBot "
                            f"{probe_x} {_MINECRAFT_OVERWORLD_MAX_BUILD_Y} {probe_z}"
                        )
                        probe_surface = setup_rcon(
                            "execute at ResearchBot positioned over "
                            "ocean_floor if biome ~ ~ ~ "
                            f"minecraft:{requested_biome}"
                        )
                        if not predicate_passed(probe_surface):
                            continue
                        setup_rcon(
                            "execute at ResearchBot positioned over "
                            "ocean_floor run tp ResearchBot ~ ~1 ~"
                        )
                        probe_post = setup_rcon(
                            "execute at ResearchBot if biome ~ ~ ~ "
                            f"minecraft:{requested_biome}"
                        )
                        if predicate_passed(probe_post):
                            surface_found = True
                            break
                    if surface_found:
                        break
                if surface_found:
                    break

                # If the local surface neighborhood contains no proven target
                # biome, move the 3-D search origin horizontally and require a
                # genuinely new locate cell before another iteration. This is
                # bounded and deterministic; repeated cells remain fail-closed.
                next_locate = None
                for dx, dz in (
                    (256, 0), (-256, 0), (0, 256), (0, -256),
                    (256, 256), (256, -256), (-256, 256), (-256, -256),
                ):
                    alternate = setup_rcon(
                        f"execute in minecraft:{dimension} positioned "
                        f"{x + dx} {_MINECRAFT_OVERWORLD_MAX_BUILD_Y} {z + dz} "
                        f"run locate biome minecraft:{requested_biome}"
                    )
                    if locate_position(alternate) not in seen_positions:
                        next_locate = alternate
                        break
                if next_locate is None:
                    raise RuntimeError(
                        "Minecraft biome surface projection did not converge for "
                        + requested_biome
                    )
                locate = next_locate

        setup_rcon("gamemode survival ResearchBot")
        anchor_proof: Mapping[str, object] | None = None
        if settle_session is not None:
            wait_anchor = getattr(settle_session, "wait_for_task_setup_anchor", None)
            if not callable(wait_anchor):
                raise RuntimeError(
                    "Minecraft session lacks survival anchor convergence authority"
                )
            anchor_proof = wait_anchor()

        # Agent-relative mutations are applied only after the survival body has
        # reached a physically supported anchor. Otherwise mobs/world ops can be
        # provisioned around a transient teleport coordinate while the player is
        # still falling through a fluid/surface column.
        setup_rcon("clear ResearchBot")
        inventory = setup.get("initial_inventory", ())
        if isinstance(inventory, (str, bytes, bytearray)) or not isinstance(
            inventory, (tuple, list)
        ):
            raise TypeError("Minecraft initial_inventory must be a sequence")
        for raw in inventory:
            if not isinstance(raw, Mapping):
                raise TypeError("Minecraft initial inventory row must be an object")
            item = str(raw.get("item", "")).strip()
            count = int(raw.get("count", 1))
            raw_slot = raw.get("slot")
            if not re.fullmatch(r"[a-z0-9_]+", item) or count <= 0:
                raise ValueError("Minecraft initial inventory item/count is invalid")
            destination = _minecraft_inventory_slot_destination(raw_slot)
            command = (
                f"item replace entity ResearchBot {destination} "
                f"with minecraft:{item} {count}"
                if destination is not None
                else f"give ResearchBot minecraft:{item} {count}"
            )
            setup_rcon(command)

        if bool(setup.get("start_at_night", False)):
            setup_rcon("time set 18000")
        setup_rcon(
            "gamerule doDaylightCycle "
            + ("false" if bool(setup.get("always_night", False)) else "true")
        )
        weather = setup.get("weather")
        if isinstance(weather, str) and weather.strip():
            normalized = {"clear": "clear", "rain": "rain", "thunder": "thunder"}.get(
                weather.strip().lower()
            )
            if normalized is None:
                raise ValueError("Minecraft task setup weather is invalid")
            setup_rcon("weather " + normalized)
        setup_rcon(
            "gamerule doMobSpawning "
            + ("true" if bool(setup.get("allow_mob_spawn", True)) else "false")
        )

        mobs = setup.get("initial_mobs", ())
        if isinstance(mobs, (str, bytes, bytearray)) or not isinstance(
            mobs, (tuple, list)
        ):
            raise TypeError("Minecraft initial_mobs must be a sequence")
        for mob_index, raw in enumerate(mobs):
            if not isinstance(raw, Mapping):
                raise TypeError("Minecraft initial mob row must be an object")
            entity = str(raw.get("entity", "")).strip()
            count = int(raw.get("count", 1))
            if not re.fullmatch(r"[a-z0-9_]+", entity) or count <= 0:
                raise ValueError("Minecraft initial mob entity/count is invalid")
            for index in range(count):
                dx = 2 + ((mob_index + index) % 5)
                dz = 2 + (((mob_index + index) * 3) % 5)
                setup_rcon(
                    "execute at ResearchBot run summon "
                    f"minecraft:{entity} ~{dx} ~ ~{dz}"
                )

        world_ops = normalize_minecraft_world_ops(setup.get("world_ops", ()))
        if world_ops:
            endpoint = self.spec.rcon_endpoint
            if endpoint is None or not self._rcon_password:
                raise RuntimeError(
                    "Minecraft typed world setup requires an Authority-bound RCON endpoint"
                )
            console = MinecraftRconConsole(
                endpoint, secret_provider=lambda: self._rcon_password
            )
            receipt = RconMinecraftWorldSetupProvisioner(console, world_ops).apply()
            from dataclasses import asdict
            record = {
                "schema": "noetrium.minecraft-typed-world-setup-receipt.v1",
                "world_ops": world_ops,
                "receipt": asdict(receipt),
            }
            path = (
                Path(self.spec.workdir).resolve()
                / "world-setup-evidence"
                / (receipt.operations_digest + ".json")
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_replace_bytes(
                path, (strict_finite_json_text(record) + "\n").encode("utf-8")
            )
            evidence_refs.append(
                "minecraft:typed-world-setup:" + receipt.operations_digest
                + ":receipt:" + canonical_digest(asdict(receipt))
            )

        # A downstream-specified scene is an ordinary recursive NoetriumUnit
        # program, executed by the existing RCON Scenario Provisioner through
        # the Resource-bound console. This control-plane setup is never an
        # agent action and is not included in the planner observation.
        scene = setup.get("scenario")
        if scene is not None:
            if not isinstance(scene, Mapping):
                raise TypeError("Minecraft task scenario must be an object")
            unit = minecraft_scenario_from_mapping(scene)
            endpoint = self.spec.rcon_endpoint
            if endpoint is None or not self._rcon_password:
                raise RuntimeError("Minecraft scenario requires an Authority-bound RCON endpoint")
            console = MinecraftRconConsole(
                endpoint, secret_provider=lambda: self._rcon_password
            )
            receipt = RconMinecraftScenarioProvisioner(console, unit).apply()
            from dataclasses import asdict
            record = {
                "schema": "noetrium.minecraft-task-scenario-receipt.v1",
                "scenario": dict(scene),
                "receipt": asdict(receipt),
            }
            path = (
                Path(self.spec.workdir).resolve()
                / "scenario-evidence"
                / (receipt.scenario_digest + ".json")
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_replace_bytes(
                path, (strict_finite_json_text(record) + "\n").encode("utf-8")
            )
            evidence_refs.append(
                "minecraft:scenario:" + receipt.scenario_digest
                + ":receipt:" + canonical_digest(asdict(receipt))
            )
        return {
            "schema": "noetrium.minecraft-task-setup-mutation-receipt.v1",
            "evidence_refs": tuple(evidence_refs),
            "rcon_commands": tuple(command_receipts),
            "survival_anchor_proof": anchor_proof,
        }

    def _persist_task_setup_verification(
        self, record: Mapping[str, object]
    ) -> Path:
        path = (
            Path(self.spec.workdir).resolve()
            / "task-setup-verification"
            / (canonical_digest(record) + ".json")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_replace_bytes(
            path,
            (strict_finite_json_text(record) + "\n").encode("utf-8"),
        )
        return path

    def apply_and_verify_task_setup(
        self, session: object, setup: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Apply setup and close a server/client proof on the final live state.

        Biome relocation ends in survival mode before any proof is accepted. The
        server first binds the required biome to the player's current position;
        Mineflayer then proves the same exact voxel before its biome observation
        is admissible. This coordinate gate lets normal teleport/chunk/physics
        events converge without ever interpreting the biome at a stale client
        position as evidence about the target position. If the server cut loses
        a transport race, one evidence-conditioned rebase is allowed only when
        a fresh server proof names exactly the voxel observed by the rejected
        client proof. No tolerance or time polling is used.
        """
        mutation_receipt = self.apply_task_setup(setup, settle_session=session)
        control_proof: Mapping[str, object] | None = None
        control_proof_history: list[Mapping[str, object]] = []
        physical_proof: Mapping[str, object] | None = None
        authority_rebase = False
        has_biome = isinstance(setup.get("biome"), str) and bool(
            str(setup.get("biome")).strip()
        )
        verification_phase = "control.verify"

        try:
            if not hasattr(session, "verify_task_setup"):
                raise RuntimeError(
                    "Minecraft session lacks typed setup verification authority"
                )

            # Capture server authority before reading any client biome. The
            # physical verifier gates biome evaluation on this exact voxel, so a
            # client still processing the teleport cannot misclassify the biome
            # from its previous location. Its event-driven waiter then converges
            # position/chunk state against this cut.
            control_proof = self.verify_task_setup_control_state(setup)
            control_proof_history.append(control_proof)
            verification_phase = "physical.verify"
            try:
                physical_proof = session.verify_task_setup(
                    setup,
                    control_proof=control_proof,
                )
            except BaseException as first_exc:
                observed_voxel = _minecraft_rejected_authority_voxel(first_exc)
                if not has_biome or observed_voxel is None:
                    raise

                # The rejected client proof is allowed to trigger a new server
                # observation, never to authorize itself. Rebase only when that
                # independent RCON proof names the exact client-observed voxel.
                verification_phase = "control.reverify"
                refreshed = self.verify_task_setup_control_state(setup)
                refreshed_voxel = _minecraft_biome_authority_voxel(refreshed)
                if refreshed_voxel != observed_voxel:
                    raise first_exc
                control_proof = refreshed
                control_proof_history.append(refreshed)
                authority_rebase = True
                verification_phase = "physical.reverify"
                physical_proof = session.verify_task_setup(
                    setup,
                    control_proof=control_proof,
                )
        except BaseException as exc:
            record = {
                "schema": "noetrium.minecraft-task-setup-verification.v2",
                "status": "rejected",
                "task_setup_digest": canonical_digest(setup),
                "mutation_receipt": mutation_receipt,
                "control_proof": control_proof,
                "control_proof_history": tuple(control_proof_history),
                "physical_proof": physical_proof,
                "authority_rebase": authority_rebase,
                "failure": {
                    "phase": verification_phase,
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
            self._persist_task_setup_verification(record)
            raise

        record = {
            "schema": "noetrium.minecraft-task-setup-verification.v2",
            "status": "verified",
            "task_setup_digest": canonical_digest(setup),
            "mutation_receipt": mutation_receipt,
            "control_proof": control_proof,
            "control_proof_history": tuple(control_proof_history),
            "physical_proof": physical_proof,
            "authority_rebase": authority_rebase,
            "failure": None,
        }
        self._persist_task_setup_verification(record)
        return record

    def verify_task_setup_control_state(
        self, setup: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Read back server-global setup state from the same Docker server."""
        checks: list[dict[str, object]] = []

        def gamerule(name: str, expected: bool) -> None:
            response = self._rcon("gamerule " + name)
            values = re.findall(r"\b(true|false)\b", response.casefold())
            observed = None if not values else values[-1] == "true"
            checks.append({
                "kind": "gamerule",
                "name": name,
                "expected": expected,
                "observed": observed,
                "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                "ok": observed is expected,
            })

        gamerule("doDaylightCycle", not bool(setup.get("always_night", False)))
        gamerule("doMobSpawning", bool(setup.get("allow_mob_spawn", True)))

        biome = setup.get("biome")
        if isinstance(biome, str) and biome.strip():
            expected_biome = biome.strip().removeprefix("minecraft:")
            response = self._rcon(
                "execute at ResearchBot if biome ~ ~ ~ "
                f"minecraft:{expected_biome} run data get entity ResearchBot Pos"
            )
            bracket = re.search(r"\[([^\]]+)\]", response)
            position: dict[str, float] | None = None
            if bracket is not None:
                values = re.findall(
                    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?",
                    bracket.group(1),
                )
                if len(values) >= 3:
                    coordinates = tuple(float(value) for value in values[:3])
                    if all(math.isfinite(value) for value in coordinates):
                        position = dict(zip(("x", "y", "z"), coordinates, strict=True))
            checks.append({
                "kind": "biome_authority",
                "expected": expected_biome,
                "observed": "matched" if position is not None else "not_matched",
                "position": position,
                "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                "ok": position is not None,
            })

        datapack = setup.get("datapack")
        if datapack is not None:
            if not isinstance(datapack, Mapping):
                raise TypeError("Minecraft task datapack must be an object")
            pack_id = str(datapack.get("pack_id", "")).strip()
            response = self._rcon("datapack list enabled")
            observed = pack_id in response
            checks.append({
                "kind": "datapack_enabled",
                "pack_id": pack_id,
                "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                "ok": observed,
            })

        failed = tuple(row for row in checks if row.get("ok") is not True)
        proof = {
            "schema": "noetrium.minecraft-task-setup-control-proof.v1",
            "verified": not failed,
            "checks": tuple(checks),
            "failure_count": len(failed),
        }
        if failed:
            proof_digest = canonical_digest(proof)
            raise MinecraftEnvironmentFailure(
                "setup.control.verify",
                "Minecraft task setup server control postconditions failed; "
                + f"proof_digest={proof_digest}; failures={failed!r}",
                cause_code="MINECRAFT_SETUP_CONTROL_POSTCONDITION_FAILED",
                diagnostics={
                    "proof_digest": proof_digest,
                    "failures": failed,
                },
            )
        return proof

    def stop(self) -> ServiceStopOutcome:
        process = self.process
        if process is None and self.pid_path.exists():
            try:
                process = self._process_identity()
            except (
                _MinecraftChildProcessAbsent,
                _MinecraftChildProcessIdentityStale,
            ):
                self.pid_path.unlink(missing_ok=True)
                process = None
            else:
                self.process = process
        if process is None:
            host_errors = self._converge_host_process()
            if host_errors:
                raise BaseExceptionGroup(
                    "Minecraft host ownership convergence failed",
                    list(host_errors),
                )
            self._release_pristine_reservation()
            return ServiceStopOutcome(
                self.contract.digest(),
                True,
                (),
            )
        if self.alive(process):
            self._terminate_pid(process, signal="TERM")
            stopped = self._wait_process_exit(
                process, timeout_s=self.contract.stop_timeout_s
            )
            if not stopped:
                self._terminate_pid(process, signal="KILL")
                stopped = self._wait_process_exit(process, timeout_s=5.0)
            if not stopped:
                raise RuntimeError(
                    "Minecraft Java process survived fenced cleanup"
                )
        self.process = None
        self.pid_path.unlink(missing_ok=True)
        host_errors = self._converge_host_process()
        if host_errors:
            raise BaseExceptionGroup(
                "Minecraft host ownership convergence failed",
                list(host_errors),
            )
        self._release_pristine_reservation()
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
        image,
        image_digest,
        holder_scope,
        runner,
        task_group,
        lifecycle_task_group,
        process_supervisor,
        asset_digest,
        recovery_root,
        capsule,
        pristine_worlds,
        bridge_runtime: MinecraftBridgeRuntimeDistribution,
    ) -> None:
        self.image = image
        self.image_digest = image_digest
        self.holder_scope = holder_scope
        self.runner = runner
        self.task_group = task_group
        self.lifecycle_task_group = lifecycle_task_group
        self.process_supervisor = process_supervisor
        require_sha256(asset_digest, "Minecraft server factory asset_digest")
        self.asset_digest = asset_digest
        self.recovery_root = recovery_root
        self.capsule = capsule
        self.pristine_worlds = pristine_worlds
        if not isinstance(bridge_runtime, MinecraftBridgeRuntimeDistribution):
            raise TypeError("Minecraft server factory requires bridge runtime distribution")
        self.bridge_runtime = bridge_runtime
        self.by_port: dict[int, _DockerMinecraftServer] = {}
        self.lock = threading.RLock()

    def create(self, server_spec, *, environment_generation):
        server = _DockerMinecraftServer(
            spec=server_spec,
            environment_generation=environment_generation,
            capsule=self.capsule,
            runner=self.runner,
            process_supervisor=self.process_supervisor,
            asset_digest=self.asset_digest,
            recovery_root=self.recovery_root,
            pristine_worlds=self.pristine_worlds,
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
            bridge_pid_path = (
                server.recovery_root / f"minecraft-bridge-{port}.pid"
            )
            bridge_root = str(self.bridge_runtime.root)
            bridge_shell = (
                "start=$(awk '{print $22}' /proc/$$/stat); "
                f"printf '%s %s\\n' $$ \"$start\" > "
                f"{shlex.quote(str(bridge_pid_path))}; "
                f"exec {_NODE} {shlex.quote(str(self.bridge_runtime.entrypoint))}"
            )
            return self.process_supervisor.spawn_interactive(
                (
                    self.capsule.docker_executable,
                    "exec",
                    "-i",
                    "-w",
                    bridge_root,
                    "-e",
                    f"NODE_PATH={_BRIDGE_ROOT}/node_modules",
                    server.container_name,
                    "/bin/sh",
                    "-c",
                    bridge_shell,
                ),
                cwd="/",
                environment={str(k): str(v) for k, v in environment.items()},
                start_new_session=True,
                creationflags=0,
            )
        return spawn


def _minecraft_server_to_data(spec: MinecraftServerSpec) -> dict[str, object]:
    rcon = spec.rcon_endpoint
    return {
        "jar_path": spec.jar_path,
        "workdir": spec.workdir,
        "java_executable": spec.java_executable,
        "libraries_dir": spec.libraries_dir,
        "host": spec.host,
        "port": spec.port,
        "level_name": spec.level_name,
        "level_seed": spec.level_seed,
        "online_mode": spec.online_mode,
        "xms": spec.xms,
        "xmx": spec.xmx,
        "rcon_endpoint": (
            None
            if rcon is None
            else {
                "host": rcon.host,
                "port": rcon.port,
                "command_timeout_s": rcon.command_timeout_s,
            }
        ),
    }


def _minecraft_server_from_data(raw: Mapping[str, object]) -> MinecraftServerSpec:
    rcon_raw = raw.get("rcon_endpoint")
    rcon = None
    if rcon_raw is not None:
        if not isinstance(rcon_raw, Mapping):
            raise TypeError("Minecraft server realization RCON data must be an object")
        rcon = MinecraftRconEndpoint(
            host=str(rcon_raw.get("host", "127.0.0.1")),
            port=(None if rcon_raw.get("port") is None else int(rcon_raw["port"])),
            command_timeout_s=float(rcon_raw.get("command_timeout_s", 10.0)),
        )
    return MinecraftServerSpec(
        jar_path=str(raw["jar_path"]),
        workdir=str(raw["workdir"]),
        java_executable=str(raw["java_executable"]),
        libraries_dir=(
            None if raw.get("libraries_dir") is None else str(raw["libraries_dir"])
        ),
        host=str(raw.get("host", "127.0.0.1")),
        port=(None if raw.get("port") is None else int(raw["port"])),
        level_name=str(raw.get("level_name", "research-world")),
        level_seed=str(raw.get("level_seed", "NOETRIUM_FIXED_WORLD_V1")),
        online_mode=bool(raw.get("online_mode", False)),
        xms=str(raw.get("xms", "512M")),
        xmx=str(raw.get("xmx", "2G")),
        rcon_endpoint=rcon,
    )


class _MinecraftServerPhysicalProvider:
    """Ticket-addressable JVM realization inside the shared warm capsule."""

    provider_kind = "minecraft-server"

    def __init__(
        self,
        *,
        servers: _DockerServerFactory,
        capsule: _DockerMinecraftCapsule,
        recovery_root: Path,
    ) -> None:
        self._servers = servers
        self._capsule = capsule
        self._recovery_root = Path(recovery_root).resolve()
        self._recovery_root.mkdir(parents=True, exist_ok=True)
        self._by_ticket: dict[str, _DockerMinecraftServer] = {}
        # Global lock protects only the tiny provider index. Physical lifecycle
        # effects are serialized by exact Authority ticket, never across
        # independent branches. Weak values make the lock registry self-cleaning
        # once no operation retains a ticket lock.
        self._lock = threading.RLock()
        self._ticket_locks = WeakValueDictionary()

    def _ticket_lock(self, ticket: NoetriumUnit):
        ticket_id = ticket_field(ticket, "ticket_id")
        with self._lock:
            lock = self._ticket_locks.get(ticket_id)
            if lock is None:
                lock = threading.RLock()
                self._ticket_locks[ticket_id] = lock
            return lock

    def _marker_path(self, ticket: NoetriumUnit) -> Path:
        return self._recovery_root / (
            "minecraft-server-effect-" + ticket_field(ticket, "ticket_id") + ".json"
        )

    @staticmethod
    def _marker_payload(
        ticket: NoetriumUnit,
        *,
        server_spec: MinecraftServerSpec,
        environment_generation: str,
    ) -> dict[str, object]:
        return {
            "schema": "noetrium.minecraft-server-effect.v1",
            "ticket_id": ticket_field(ticket, "ticket_id"),
            "resource_key": ticket_field(ticket, "resource_key"),
            "generation": ticket_field(ticket, "generation"),
            "spec_digest": ticket_field(ticket, "spec_digest"),
            "provider_kind": ticket_field(ticket, "provider_kind"),
            "environment_generation": environment_generation,
            "server": _minecraft_server_to_data(server_spec),
        }

    def _write_marker(
        self,
        ticket: NoetriumUnit,
        *,
        server_spec: MinecraftServerSpec,
        environment_generation: str,
    ) -> None:
        payload = self._marker_payload(
            ticket,
            server_spec=server_spec,
            environment_generation=environment_generation,
        )
        atomic_replace_bytes(
            self._marker_path(ticket),
            (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
        )

    def _read_marker(self, ticket: NoetriumUnit) -> dict[str, object] | None:
        path = self._marker_path(ticket)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Minecraft server effect marker is unreadable") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("Minecraft server effect marker is malformed")
        expected = {
            "ticket_id": ticket_field(ticket, "ticket_id"),
            "resource_key": ticket_field(ticket, "resource_key"),
            "generation": ticket_field(ticket, "generation"),
            "spec_digest": ticket_field(ticket, "spec_digest"),
            "provider_kind": self.provider_kind,
        }
        for key, value in expected.items():
            if raw.get(key) != value:
                raise RuntimeError(
                    "Minecraft server effect marker crossed Authority ticket: " + key
                )
        server = raw.get("server")
        if not isinstance(server, dict):
            raise RuntimeError("Minecraft server effect marker omitted server spec")
        return raw

    @staticmethod
    def _process_identity(
        capsule: _DockerMinecraftCapsule,
        spec: MinecraftServerSpec,
        recovery_root: Path,
    ) -> ServiceProcessIdentity | None:
        pid_path = recovery_root / f"minecraft-server-{spec.bound_port}.pid"
        if not pid_path.is_file():
            return None
        try:
            process = capsule.child_process_identity_from_path(
                pid_path,
                expected_command_marker="server.jar",
            )
        except (_MinecraftChildProcessAbsent, _MinecraftChildProcessIdentityStale):
            pid_path.unlink(missing_ok=True)
            return None
        if not capsule.child_identity_alive(process):
            pid_path.unlink(missing_ok=True)
            return None
        return process

    @staticmethod
    def _tcp_ready(spec: MinecraftServerSpec) -> bool:
        connection = None
        try:
            connection = socket.create_connection(
                (spec.host, spec.bound_port),
                timeout=0.25,
            )
            return True
        except (OSError, TimeoutError):
            return False
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _identity(
        ticket: NoetriumUnit,
        process: ServiceProcessIdentity,
        spec: MinecraftServerSpec,
    ) -> NoetriumUnit:
        return physical_identity(
            _MinecraftServerPhysicalProvider.provider_kind,
            process.start_identity,
            {
                "ticket_id": ticket_field(ticket, "ticket_id"),
                "resource_key": ticket_field(ticket, "resource_key"),
                "generation": ticket_field(ticket, "generation"),
                "spec_digest": ticket_field(ticket, "spec_digest"),
                "pid": process.pid,
                "process_start_identity": process.start_identity,
                "host": spec.host,
                "port": spec.bound_port,
                "workdir": spec.workdir,
            },
        )

    def observe(
        self,
        reference: NoetriumUnit,
    ) -> NoetriumUnit:
        if is_physical_identity(reference):
            attrs = dict(physical_field(reference, "attributes") or {})
            try:
                ticket = realization_ticket(
                    ticket_id=str(attrs["ticket_id"]),
                    effect_id="observation:" + str(attrs["ticket_id"]),
                    realization_key="observation:" + str(attrs["ticket_id"]),
                    resource_key=str(attrs["resource_key"]),
                    provider_kind=self.provider_kind,
                    generation=int(attrs["generation"]),
                    spec_digest=str(attrs["spec_digest"]),
                    holder_key="observation",
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    "Minecraft physical identity lacks Authority ticket metadata"
                ) from exc
        elif is_realization_ticket(reference):
            ticket = reference
        else:
            raise TypeError(
                "Minecraft server observe requires ticket or physical-identity Unit"
            )
        marker = self._read_marker(ticket)
        if marker is None:
            return resource_observation(
                ticket_field(ticket, "resource_key"),
                ticket_field(ticket, "generation"),
                ticket_field(ticket, "ticket_id"),
                ticket_field(ticket, "spec_digest"),
                False,
                False,
                None,
            )
        capsule_current = self._capsule._current()
        if (
            capsule_current is None
            or not observation_field(capsule_current[1], "exists")
            or not observation_field(capsule_current[1], "ready")
        ):
            return resource_observation(
                ticket_field(ticket, "resource_key"),
                ticket_field(ticket, "generation"),
                ticket_field(ticket, "ticket_id"),
                ticket_field(ticket, "spec_digest"),
                False,
                False,
                None,
                evidence={
                    "marker": str(self._marker_path(ticket)),
                    "capsule": "absent",
                },
            )
        spec = _minecraft_server_from_data(marker["server"])
        process = self._process_identity(
            self._capsule,
            spec,
            self._recovery_root,
        )
        if process is None:
            return resource_observation(
                ticket_field(ticket, "resource_key"),
                ticket_field(ticket, "generation"),
                ticket_field(ticket, "ticket_id"),
                ticket_field(ticket, "spec_digest"),
                False,
                False,
                None,
                evidence={"marker": str(self._marker_path(ticket))},
            )
        ready = self._tcp_ready(spec)
        return resource_observation(
            resource_key=ticket_field(ticket, "resource_key"),
            generation=ticket_field(ticket, "generation"),
            ticket_id=ticket_field(ticket, "ticket_id"),
            spec_digest=ticket_field(ticket, "spec_digest"),
            exists=True,
            ready=ready,
            physical=self._identity(ticket, process, spec),
            evidence={
                "pid": process.pid,
                "process_start_identity": process.start_identity,
                "host": spec.host,
                "port": spec.bound_port,
                "tcp_ready": ready,
                "marker": str(self._marker_path(ticket)),
            },
        )

    def realize(
        self,
        spec: Mapping[str, object],
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        raw_server = spec.get("server")
        if not isinstance(raw_server, Mapping):
            raise TypeError("Minecraft server realization requires server spec data")
        server_spec = _minecraft_server_from_data(raw_server)
        environment_generation = str(spec.get("environment_generation") or "").strip()
        if not environment_generation:
            raise ValueError(
                "Minecraft server realization requires environment_generation"
            )
        ticket_id = ticket_field(ticket, "ticket_id")
        with self._ticket_lock(ticket):
            self._capsule.assert_healthy()
            marker = self._read_marker(ticket)
            if marker is None:
                self._write_marker(
                    ticket,
                    server_spec=server_spec,
                    environment_generation=environment_generation,
                )
            else:
                if marker.get("environment_generation") != environment_generation:
                    raise RuntimeError(
                        "Minecraft server ticket environment generation drifted"
                    )
                if canonical_digest(marker["server"]) != canonical_digest(
                    _minecraft_server_to_data(server_spec)
                ):
                    raise RuntimeError("Minecraft server ticket spec drifted")

            with self._lock:
                server = self._by_ticket.get(ticket_id)
                if server is None:
                    server = self._servers.create(
                        server_spec,
                        environment_generation=environment_generation,
                    )
                    recovered = self._process_identity(
                        self._capsule,
                        server_spec,
                        self._recovery_root,
                    )
                    if recovered is not None:
                        server.process = recovered
                    self._by_ticket[ticket_id] = server
            # JVM launch/readiness may take seconds. Holding the provider-global
            # index lock here would serialize all independent branches.
            server.start()
            readiness = server.verify_ready()
            if readiness.process is None:
                raise MinecraftServerServiceError(
                    "Minecraft server READY evidence omitted process"
                )
            observed = self.observe(ticket)
            if not observation_field(observed, "exists") or not observation_field(observed, "ready") or observation_field(observed, "physical_identity") is None:
                raise MinecraftServerServiceError(
                    "Minecraft server realization did not converge to READY"
                )
            return observation_field(observed, "physical_identity")

    def retire(
        self,
        reference: NoetriumUnit,
        ticket: NoetriumUnit,
    ) -> NoetriumUnit:
        ticket_id = ticket_field(ticket, "ticket_id")
        with self._ticket_lock(ticket):
            with self._lock:
                server = self._by_ticket.get(ticket_id)
            if server is not None:
                server.stop()
                with self._lock:
                    self._by_ticket.pop(ticket_id, None)
            else:
                marker = self._read_marker(ticket)
                if marker is not None:
                    spec = _minecraft_server_from_data(marker["server"])
                    process = self._process_identity(
                        self._capsule,
                        spec,
                        self._recovery_root,
                    )
                    if process is not None:
                        self._capsule.terminate_recovered_child(
                            process,
                            stop_timeout_s=30.0,
                        )
                    pid_path = self._recovery_root / (
                        f"minecraft-server-{spec.bound_port}.pid"
                    )
                    pid_path.unlink(missing_ok=True)
            self._marker_path(ticket).unlink(missing_ok=True)
        final = self.observe(ticket)
        if observation_field(final, "exists"):
            raise RuntimeError("Minecraft server survived Authority retirement")
        return final


class _DockerEnvironmentFactory:
    def __init__(self, *, servers, operating_system, process_supervisor, task_group) -> None:
        self.servers = servers
        self.operating_system = operating_system
        self.process_supervisor = process_supervisor
        self.task_group = task_group

    def compose(
        self,
        environment: NoetriumUnit,
        runtime_binding: MinecraftEnvironmentRuntimeBinding,
        *,
        checkpoint=None,
    ) -> MinecraftEnvironmentAssembly:
        return compose_minecraft_environment(
            environment,
            runtime_binding,
            operating_system=self.operating_system,
            checkpoint=checkpoint,
            process_factory=self.servers.bridge_process_factory(
                runtime_binding.endpoint.bound_port
            ),
            process_supervisor=self.process_supervisor,
            task_group=self.task_group,
        )


@dataclass(slots=True)
class _LifetimeRuntime:
    binding: object
    session: EnvironmentSession
    branch_scope_lease_guard: LeaseHeartbeatGuard
    run_id: str
    workdir: Path
    recovery_root: Path
    compute: ComputePlacement
    endpoint: EndpointPlacement
    rcon_endpoint: EndpointPlacement | None
    resource_topology_unit: object
    providers: Mapping[str, object]
    claim_candidates: Mapping[str, object]
    realization_specs: Mapping[str, object]


class LocalMinecraftLifetimeSessionController(EnvironmentLifetimeSessionControllerPort):
    def __init__(
        self,
        *,
        environment_config: Mapping[str, object],
        state_root: Path,
        asset_root: Path,
        asset_digest: str,
        resource_authority: UniversalResourceAuthority,
        docker_provider: DockerPhysicalProvider,
        compute_inventory: ComputeInventoryPort,
        endpoint_candidates: EndpointCandidatePortSourcePort,
        endpoint_probe: EndpointProbePort,
        gpu_runtime_observer: GpuRuntimeObserverPort | None,
        host_runtime_observer: HostRuntimeObserverPort | None,
        environment_catalog: ExecutionEnvironmentCatalogPort,
        image: str,
        image_digest: str,
        runner,
        operating_system,
        process_supervisor,
        task_group,
        lifecycle_task_group,
        prewarm_task_group,
        resource_lease_guard_factory: LeaseHeartbeatFactory,
        owner_generation_id: str,
        reconcile_shared_fabric: bool = True,
    ) -> None:
        self.config = dict(environment_config)
        raw_pre_agent_attempts = self.config.get(
            "pre_agent_infrastructure_attempts", 3
        )
        if type(raw_pre_agent_attempts) is not int or raw_pre_agent_attempts < 1:
            raise ValueError(
                "Minecraft pre_agent_infrastructure_attempts must be an integer >= 1"
            )
        self.pre_agent_infrastructure_attempts = raw_pre_agent_attempts
        self.state_root = state_root.resolve()
        self.asset_root = asset_root.resolve()
        if not isinstance(resource_authority, UniversalResourceAuthority):
            raise TypeError("Minecraft lifetime requires UniversalResourceAuthority")
        if not isinstance(docker_provider, DockerPhysicalProvider):
            raise TypeError("Minecraft lifetime requires DockerPhysicalProvider")
        self.resource_authority = resource_authority
        self.docker_provider = docker_provider
        required_catalog_methods = (
            "register_profile_revision",
            "register_profile_materialization",
        )
        if any(
            not callable(getattr(environment_catalog, name, None))
            for name in required_catalog_methods
        ):
            raise TypeError(
                "Minecraft lifetime requires ExecutionEnvironmentCatalogPort"
            )
        self.compute_inventory = compute_inventory
        self.endpoint_candidates = endpoint_candidates
        self.endpoint_probe = endpoint_probe
        self.gpu_runtime_observer = gpu_runtime_observer
        self.host_runtime_observer = host_runtime_observer
        self.environment_catalog = environment_catalog
        self.image = image
        self.image_digest = image_digest
        self.runner = runner
        self.operating_system = operating_system
        self.process_supervisor = process_supervisor
        self.task_group = task_group
        self.lifecycle_task_group = lifecycle_task_group
        self.prewarm_task_group = prewarm_task_group
        if not isinstance(resource_lease_guard_factory, LeaseHeartbeatFactory):
            raise TypeError("Minecraft lifetime requires LeaseHeartbeatFactory")
        self.resource_lease_guard_factory = resource_lease_guard_factory
        if (
            type(owner_generation_id) is not str
            or not owner_generation_id.strip()
            or owner_generation_id != owner_generation_id.strip()
        ):
            raise ValueError("Minecraft lifetime owner_generation_id must be canonical text")
        self.owner_generation_id = owner_generation_id
        self.lock = threading.RLock()
        self.runtimes: dict[str, _LifetimeRuntime] = {}
        self._lifetime_locks: dict[str, threading.Lock] = {}
        self._retirements: dict[str, object] = {}
        self._retirement_rows: dict[str, _LifetimeRuntime] = {}
        self._preparations: dict[str, object] = {}
        self._preparation_failures: dict[str, BaseException] = {}
        self._retirement_failures: dict[str, BaseException] = {}
        self._retirement_sequence = 0
        self._runtime_gc_handles: list[object] = []
        self._run_scope_guards: dict[str, LeaseHeartbeatGuard] = {}
        self._run_scope_refcounts: dict[str, int] = {}
        self._run_scope_experiments: dict[str, str] = {}
        self._run_scope_condition = threading.Condition(self.lock)
        self._run_scope_transitions: set[str] = set()
        self.asset = self.asset_root / "server.jar"
        if not self.asset.is_file():
            raise FileNotFoundError(f"Minecraft server asset missing: {self.asset}")
        require_sha256(asset_digest, "Minecraft server asset_digest")
        self.asset_digest = asset_digest
        self.bridge_distributions_root = (
            self.state_root / "bridge-runtime-distributions"
        )
        self.bridge_distributions = MinecraftBridgeRuntimeDistributionCache(
            self.bridge_distributions_root
        )
        self.bridge_runtime = self.bridge_distributions.materialize(
            local_bridge_runtime_source_root()
        )
        self.profile_id = "minecraft.local"
        self.capsule_runtime_identity_digest = canonical_digest(
            {
                "implementation_id": MINECRAFT_LOCAL_IMPLEMENTATION_ID,
                "image_digest": self.image_digest,
                "asset_digest": self.asset_digest,
                "world_materialization_schema": PRISTINE_WORLD_TEMPLATE_SCHEMA,
            }
        )
        self.runtime_identity_digest = canonical_digest(
            {
                "schema": "noetrium.minecraft-runtime-identity.v2",
                "capsule_runtime_identity_digest": (
                    self.capsule_runtime_identity_digest
                ),
                "bridge_runtime_digest": self.bridge_runtime.key,
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
        catalog = self.environment_catalog
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
        self.world_templates_root = self.state_root / "pristine-world-templates"
        self.server_distributions_root = (
            self.state_root / "server-runtime-distributions"
        )
        self.instances_root.mkdir(parents=True, exist_ok=True)
        self.recovery_root.mkdir(parents=True, exist_ok=True)
        self.pristine_worlds = local_pristine_world_cache(self.world_templates_root)
        self.server_distributions = MinecraftServerRuntimeDistributionCache(
            self.server_distributions_root
        )
        self._capsule = _DockerMinecraftCapsule(
            authority=self.resource_authority,
            provider=self.docker_provider,
            image=self.image,
            image_digest=self.image_digest,
            runner=self.runner,
            task_group=self.lifecycle_task_group,
            instances_root=self.instances_root,
            asset_root=self.asset_root,
            recovery_root=self.recovery_root,
            server_distributions_root=self.server_distributions_root,
            bridge_distributions_root=self.bridge_distributions_root,
            runtime_identity_digest=self.capsule_runtime_identity_digest,
        )
        # Materialization is a pure control-plane adoption opportunity. It may
        # reacquire an existing exact warm capsule generation, but never starts
        # a new container. This protects required warm state before generic
        # orphan reconciliation begins.
        self._capsule.attach_existing()
        if type(reconcile_shared_fabric) is not bool:
            raise TypeError("reconcile_shared_fabric must be boolean")
        if reconcile_shared_fabric:
            # Global fabric maintenance is operational hygiene, never a research
            # admission prerequisite. Submit it to the structured BLOCKING_IO
            # lane and return immediately; resource-local admission performs its
            # own linearizable orphan cleanup when contention actually matters.
            # Close joins this handle, so failures remain fail-close and durable.
            self._schedule_shared_fabric_maintenance()
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.local-minecraft-lifetime-controller.v3",
                "config": self.config,
                "image_digest": image_digest,
                "asset_digest": self.asset_digest,
                "bridge_runtime_digest": self.bridge_runtime.key,
            }
        )

    def _reconcile_shared_fabric(self) -> int:
        """Converge global Minecraft physical state from current Authority truth.

        This is the single destructive maintenance implementation. Startup may
        schedule it off the launch path, while terminal close invokes the same
        operation synchronously after local lifetime retirement. No future run
        is required to clean ownership that became orphaned during this run.
        """

        try:
            with InterprocessFileLock(
                self.state_root / ".minecraft-fabric-maintenance.lock",
                blocking=True,
            ):
                minecraft_claim_kinds = frozenset({
                    "container",
                    "compute",
                    "network-endpoint",
                    "minecraft-server",
                })
                self.resource_authority.reconcile_orphan_claims_for_claim_kinds(
                    minecraft_claim_kinds
                )
                self._capsule.retire_inactive_legacy_capsules()

                # Re-read physical ownership behind the destructive child-process
                # fence. A controller may have waited arbitrarily long for this
                # lock, so no pre-lock liveness projection is authoritative.
                with InterprocessFileLock(
                    self.recovery_root / ".abandoned-child-recovery.lock",
                    blocking=True,
                ):
                    active_compute_key_prefixes = (
                        self._capsule._active_compute_key_prefixes()
                    )
                    self._capsule.reconcile_authority_owned_capsule_children(
                        active_compute_key_prefixes=active_compute_key_prefixes,
                    )
                    self._capsule._reconcile_abandoned_children_locked(
                        active_compute_key_prefixes=active_compute_key_prefixes,
                    )

                # Physical retirement can change which ticket-protected orphan
                # claims are now releasable. Reconcile again before deriving the
                # namespace-retention cut.
                self.resource_authority.reconcile_orphan_claims_for_claim_kinds(
                    minecraft_claim_kinds
                )
                orphaned_groups = (
                    self.resource_authority.orphaned_claim_groups_for_claim_kinds(
                        minecraft_claim_kinds
                    )
                )
                orphan_claim_ids = frozenset(
                    str(claim_field(claim, "claim_id"))
                    for _lease_id, claims in orphaned_groups
                    for claim in claims
                )
                snapshot = self.resource_authority.snapshot_for_claim_kinds(
                    frozenset({
                        "compute",
                        "network-endpoint",
                        "minecraft-server",
                    })
                )
                active_runtime_key_prefixes = frozenset(
                    prefix
                    for claim in snapshot.claims
                    if str(claim_field(claim, "claim_id"))
                    not in orphan_claim_ids
                    for candidate in (
                        str(claim_field(claim, "resource_key") or ""),
                        str(
                            dict(
                                claim_field(claim, "attributes") or {}
                            ).get("consumer_resource_key")
                            or ""
                        ),
                    )
                    for match in (
                        re.match(
                            r"^minecraft-branch:([0-9a-f]{24})(?::|$)",
                            candidate,
                        ),
                    )
                    if match is not None
                    for prefix in (match.group(1),)
                )
                retired = self._reconcile_expired_server_authority(
                    orphan_claim_ids=orphan_claim_ids,
                )
                quarantined = self._reconcile_orphaned_runtime_paths(
                    active_key_prefixes=active_runtime_key_prefixes,
                )
                return int(retired) + int(quarantined)
        except InterprocessLockBusy:
            # Defensive only: both fences are blocking, so ordinary contention
            # serializes rather than dropping the convergence cut.
            return 0

    def _schedule_shared_fabric_maintenance(self) -> None:
        """Run the single Authority-proven fabric convergence off launch path."""

        def maintain(_context) -> int:
            return self._reconcile_shared_fabric()

        handle = self.lifecycle_task_group.submit(
            ExecutionSpec(
                task_id=(
                    "minecraft-fabric-maintenance:"
                    + self.runtime_identity_digest[:32]
                ),
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            maintain,
        )
        self._runtime_gc_handles.append(handle)

    def _runtime_gc_pending_root(self) -> Path:
        root = self.state_root / ".gc-pending"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _sweep_quarantined_runtime_paths(self) -> int:
        """Delete disposable paths that were already removed from live namespace.

        Quarantine is durable: a crash during deletion leaves the remaining
        directories under ``.gc-pending`` for the next Runtime-Fabric recovery.
        """

        pending_root = self._runtime_gc_pending_root()
        removed = 0
        with InterprocessFileLock(self.state_root / ".minecraft-runtime-gc.lock"):
            for path in tuple(sorted(pending_root.iterdir())):
                if path.is_symlink():
                    raise RuntimeError(
                        "Minecraft GC quarantine must not contain symlink: "
                        + str(path)
                    )
                if not path.is_dir():
                    continue
                if re.fullmatch(
                    r"(?:instances|recovery)-[0-9a-f]{64}-[0-9a-f]{16}",
                    path.name,
                ) is None:
                    raise RuntimeError(
                        "Minecraft GC quarantine contains unknown directory: "
                        + str(path)
                    )
                shutil.rmtree(path, ignore_errors=False)
                removed += 1
        return removed

    def _schedule_quarantined_runtime_gc(self) -> None:
        pending_root = self._runtime_gc_pending_root()
        pending_names = tuple(
            sorted(path.name for path in pending_root.iterdir() if path.is_dir())
        )
        if not pending_names:
            return

        def sweep(_context) -> int:
            return self._sweep_quarantined_runtime_paths()

        handle = self.lifecycle_task_group.submit(
            ExecutionSpec(
                task_id=(
                    "minecraft-runtime-gc:"
                    + canonical_digest(
                        {
                            "owner_generation_id": self.owner_generation_id,
                            "pending": pending_names,
                        }
                    )[:32]
                ),
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            sweep,
        )
        self._runtime_gc_handles.append(handle)

    def _reconcile_orphaned_runtime_paths(
        self,
        *,
        active_key_prefixes: frozenset[str],
    ) -> int:
        """Atomically quarantine crash-orphaned disposable worlds.

        Authority proves liveness; filesystem rename only removes an already
        dead realization from the live namespace. Recursive deletion is then
        owned by the structured Runtime-Fabric lifecycle group and therefore
        cannot inflate first-episode materialization latency.
        """

        if type(active_key_prefixes) is not frozenset or any(
            type(value) is not str
            or re.fullmatch(r"[0-9a-f]{24}", value) is None
            for value in active_key_prefixes
        ):
            raise TypeError(
                "Minecraft active runtime keys must be 24-character hex prefixes"
            )
        grace_seconds = max(
            60.0,
            float(DEFAULT_AUTHORITY_LEASE_POLICY.ttl_seconds) * 2.0,
        )
        now = time.time()
        pending_root = self._runtime_gc_pending_root()
        quarantined = 0
        with InterprocessFileLock(
            self.state_root / ".minecraft-runtime-path-recovery.lock"
        ):
            # Re-read dynamic ownership *after* acquiring the destructive path
            # fence. A pre-lock claim snapshot can become stale while waiting,
            # and a transient claim/lease gap must never quarantine the workdir
            # of a still-BOUND server generation. Non-RETIRED server tickets
            # therefore protect the physical namespace independently of claims.
            fresh_active_key_prefixes = (
                active_key_prefixes
                | self._capsule._active_compute_key_prefixes()
            )
            for role, root in (
                ("instances", self.instances_root),
                ("recovery", self.recovery_root),
            ):
                for path in tuple(root.iterdir()):
                    if path.is_symlink():
                        raise RuntimeError(
                            "Minecraft disposable runtime path must not be symlink: "
                            + str(path)
                        )
                    if not path.is_dir():
                        continue
                    if re.fullmatch(r"[0-9a-f]{64}", path.name) is None:
                        continue
                    if path.name[:24] in fresh_active_key_prefixes:
                        continue
                    stat = path.stat(follow_symlinks=False)
                    age_seconds = max(0.0, now - stat.st_mtime)
                    if age_seconds < grace_seconds:
                        continue
                    suffix = canonical_digest(
                        {
                            "source": str(path),
                            "inode": int(stat.st_ino),
                            "mtime_ns": int(stat.st_mtime_ns),
                        }
                    )[:16]
                    target = pending_root / f"{role}-{path.name}-{suffix}"
                    if target.exists():
                        raise RuntimeError(
                            "Minecraft GC quarantine identity collision: "
                            + str(target)
                        )
                    path.rename(target)
                    quarantined += 1

        # Also resumes a durable queue left by a crash during a previous sweep.
        self._schedule_quarantined_runtime_gc()
        return quarantined

    def _reconcile_expired_server_authority(
        self,
        *,
        orphan_claim_ids: frozenset[str],
    ) -> int:
        """Retire server tickets whose formal Scope ownership is orphaned.

        Generic orphan-claim cleanup deliberately refuses to release a claim
        while its realization ticket is PREPARED/BOUND/RETIRING. Minecraft
        recovery first proves abandoned child processes absent, then drives
        those protected server tickets through the same physical provider to
        RETIRED. Liveness itself is decided only by Resource Authority.
        """
        if type(orphan_claim_ids) is not frozenset or any(
            type(value) is not str or not value.strip()
            for value in orphan_claim_ids
        ):
            raise TypeError("Minecraft orphan claim ids must be canonical strings")
        snapshot = self.resource_authority.snapshot_for_claim_kinds(
            frozenset({"minecraft-server"})
        )
        stale: list[str] = []
        for claim in snapshot.claims:
            resource_key = str(claim_field(claim, "resource_key"))
            if not re.fullmatch(r"minecraft-branch:[0-9a-f]{24}:server", resource_key):
                continue
            attrs = dict(claim_field(claim, "attributes") or {})
            if attrs.get("kind") != "minecraft-server":
                continue
            if str(claim_field(claim, "claim_id")) not in orphan_claim_ids:
                continue
            stale.append(resource_key)

        for resource_key in sorted(stale):
            prefix = resource_key.split(":", 2)[1]
            matches = tuple(sorted(self.recovery_root.glob(prefix + "*")))
            if len(matches) > 1:
                raise RuntimeError(
                    "Minecraft recovery prefix resolved multiple lifetime roots: "
                    + prefix
                )
            recovery = self.recovery_root if not matches else matches[0].resolve()
            branch_scope = scope_unit(ScopeKind.BRANCH, "assignment-" + prefix)
            servers = _DockerServerFactory(
                image=self.image,
                image_digest=self.image_digest,
                holder_scope=branch_scope,
                runner=self.runner,
                task_group=self.task_group,
                lifecycle_task_group=self.lifecycle_task_group,
                process_supervisor=self.process_supervisor,
                asset_digest=self.asset_digest,
                recovery_root=recovery,
                capsule=self._capsule,
                pristine_worlds=self.pristine_worlds,
                bridge_runtime=self.bridge_runtime,
            )
            provider = _MinecraftServerPhysicalProvider(
                servers=servers,
                capsule=self._capsule,
                recovery_root=recovery,
            )
            topology = resource_topology(
                "minecraft-expired-owner-recovery:" + prefix,
                resources=(
                    resource_node(
                        "server",
                        kind="minecraft-server",
                        authority_key=resource_key,
                        realization=True,
                    ),
                ),
            )
            self.resource_authority.reconcile(
                topology,
                claim_candidates={},
                realization_specs={},
                providers={provider.provider_kind: provider},
                desired_resource_ids=frozenset(),
            )
        if stale:
            self.resource_authority.reconcile_orphan_claims_for_claim_kinds(
                frozenset({"minecraft-server"})
            )
        return len(stale)

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def effect_recovery_durability(self) -> str:
        return "crash_durable"

    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]:
        contracts = minecraft_action_catalog()
        version = str(self.config.get("minecraft_version", "")).strip()
        if not version:
            raise RuntimeError(
                "Minecraft lifetime requires explicit minecraft_version"
            )
        return (
            EnvironmentCapabilityDescriptor(
                capability_id="minecraft.world",
                version=version,
                action_types=tuple(contract.action_type for contract in contracts),
                query_types=("capabilities", "state", "entity", "task"),
                metadata={
                    "bridge": "replaceable",
                    # This live capability descriptor (not a direct session
                    # catalog) is what the Agent Method receives at runtime.
                    "initial_observation_action": {
                        "action_type": "observe_blocks",
                        "arguments": {},
                    },
                    "action_contracts": tuple(
                        contract.as_payload() for contract in contracts
                    ),
                },
            ),
        )

    def _reserve_run_scope_guard(
        self,
        *,
        experiment_id: str,
        run_id: str,
        experiment_scope: NoetriumUnit,
        run_scope: NoetriumUnit,
    ) -> LeaseHeartbeatGuard:
        """Reserve one branch reference without holding metadata lock over I/O.

        Run-scope realization is single-flight per run. Slow Authority/heartbeat
        operations execute outside the controller metadata lock; only O(1)
        identity publication and reference accounting occur inside it.
        """

        condition = self._run_scope_condition
        while True:
            with condition:
                run_guard = self._run_scope_guards.get(run_id)
                if run_guard is not None:
                    if self._run_scope_experiments.get(run_id) != experiment_id:
                        raise RuntimeError(
                            "Minecraft run Scope crossed Experiment parent: "
                            + run_id
                        )
                    current = self._run_scope_refcounts.get(run_id)
                    if current is None or current <= 0:
                        raise RuntimeError(
                            "Minecraft RUN Scope refcount drifted: " + run_id
                        )
                    self._run_scope_refcounts[run_id] = current + 1
                    return run_guard
                if run_id not in self._run_scope_transitions:
                    self._run_scope_transitions.add(run_id)
                    break
                condition.wait()

        run_lease: NoetriumUnit | None = None
        run_guard: LeaseHeartbeatGuard | None = None
        try:
            run_lease = self.resource_authority.acquire_scope_lease(
                scope=run_scope,
                parent_scope=experiment_scope,
                holder_key=scope_key(run_scope),
                ttl_seconds=DEFAULT_AUTHORITY_LEASE_POLICY.ttl_seconds,
                metadata={
                    "owner_generation_id": self.owner_generation_id,
                    "experiment_id": experiment_id,
                    "run_id": run_id,
                },
            )
            run_guard = self.resource_lease_guard_factory.create((run_lease,))
            run_guard.start()
        except BaseException:
            if run_guard is not None:
                try:
                    run_guard.close()
                except BaseException:
                    pass
            if run_lease is not None:
                try:
                    self.resource_authority.release_lease(run_lease)
                except BaseException:
                    pass
            with condition:
                self._run_scope_transitions.discard(run_id)
                condition.notify_all()
            raise

        with condition:
            if run_id in self._run_scope_guards:
                raise RuntimeError(
                    "Minecraft RUN Scope single-flight publication raced: "
                    + run_id
                )
            self._run_scope_guards[run_id] = run_guard
            self._run_scope_refcounts[run_id] = 1
            self._run_scope_experiments[run_id] = experiment_id
            self._run_scope_transitions.discard(run_id)
            condition.notify_all()
        return run_guard

    def _release_run_scope_reference(self, run_id: str) -> None:
        run_guard: LeaseHeartbeatGuard | None = None
        with self._run_scope_condition:
            current = self._run_scope_refcounts.get(run_id)
            if current is None or current <= 0:
                raise RuntimeError(
                    "Minecraft RUN Scope refcount drifted: " + run_id
                )
            if current == 1:
                self._run_scope_refcounts.pop(run_id, None)
                self._run_scope_experiments.pop(run_id, None)
                run_guard = self._run_scope_guards.pop(run_id, None)
            else:
                self._run_scope_refcounts[run_id] = current - 1
        if run_guard is not None:
            run_lease = run_guard.handles[0]
            run_guard.close()
            self.resource_authority.release_lease(run_lease)

    def _acquire_branch_scope_lease(
        self,
        context: ExecutionContext,
        branch_scope: NoetriumUnit,
    ) -> tuple[LeaseHeartbeatGuard, str]:
        experiment_id = context.experiment_id
        run_id = context.run_id
        if type(experiment_id) is not str or not experiment_id.strip():
            raise RuntimeError(
                "Minecraft dynamic Scope requires ExecutionContext.experiment_id"
            )
        if type(run_id) is not str or not run_id.strip():
            raise RuntimeError(
                "Minecraft dynamic Scope requires ExecutionContext.run_id"
            )
        experiment_scope = scope_unit(ScopeKind.EXPERIMENT, experiment_id)
        run_scope = scope_unit(ScopeKind.RUN, run_id)

        run_guard = self._reserve_run_scope_guard(
            experiment_id=experiment_id,
            run_id=run_id,
            experiment_scope=experiment_scope,
            run_scope=run_scope,
        )
        run_lease = run_guard.handles[0]

        branch_lease: NoetriumUnit | None = None
        branch_guard: LeaseHeartbeatGuard | None = None
        try:
            branch_lease = self.resource_authority.acquire_scope_lease(
                scope=branch_scope,
                parent_scope=run_scope,
                parent_scope_lease=run_lease,
                holder_key=scope_key(branch_scope),
                ttl_seconds=DEFAULT_AUTHORITY_LEASE_POLICY.ttl_seconds,
                metadata={
                    "owner_generation_id": self.owner_generation_id,
                    "experiment_id": experiment_id,
                    "run_id": run_id,
                    "lifetime_id": context.lifetime_id,
                },
            )
            branch_guard = self.resource_lease_guard_factory.create(
                (branch_lease,)
            )
            branch_guard.start()
            return branch_guard, run_id
        except BaseException:
            if branch_guard is not None:
                try:
                    branch_guard.close()
                except BaseException:
                    pass
            if branch_lease is not None:
                try:
                    self.resource_authority.release_lease(branch_lease)
                except BaseException:
                    pass
            self._release_run_scope_reference(run_id)
            raise

    def _release_branch_scope_guard(
        self,
        branch_guard: LeaseHeartbeatGuard,
        run_id: str,
    ) -> None:
        # Deactivate renewal first and then release the final authoritative
        # lease row retained by the guard.  Cleanup is retry-safe even when an
        # earlier retirement attempt already removed the heartbeat member.
        branch_guard.close()
        branch_lease = branch_guard.handles[0]
        self.resource_authority.release_lease(branch_lease)
        self._release_run_scope_reference(run_id)

    def _record_pre_agent_recovery(
        self,
        *,
        lifetime_key: str,
        attempt: int,
        status: str,
        scope_generation: int,
        resource_generations: Mapping[str, int],
        failure: BaseException | None,
    ) -> None:
        record = {
            "schema": "noetrium.minecraft-pre-agent-infrastructure-recovery.v1",
            "lifetime_key": lifetime_key,
            "attempt": attempt,
            "max_attempts": self.pre_agent_infrastructure_attempts,
            "status": status,
            "scope_generation": scope_generation,
            "resource_generations": dict(sorted(resource_generations.items())),
            "failure": (
                None if failure is None else _pre_agent_failure_evidence(failure)
            ),
        }
        digest = canonical_digest(record)
        root = self.state_root / "pre-agent-infrastructure-recovery" / lifetime_key
        try:
            root.mkdir(parents=True, exist_ok=True)
            atomic_replace_bytes(
                root / f"attempt-{attempt:04d}-{status}-{digest[:16]}.json",
                (strict_finite_json_text(record) + "\n").encode("utf-8"),
            )
        except OSError:
            # Recovery observability must never become a new physical failure
            # source. The original typed exception remains authoritative.
            return

    def _open(self, context: ExecutionContext) -> _LifetimeRuntime:
        lifetime_id = context.lifetime_id
        if not lifetime_id:
            raise ValueError("Minecraft runtime requires lifetime_id")
        raw_task_setup = context.participant_context.get(
            "environment_task_setup", {}
        )
        minecraft_task_setup: Mapping[str, object] | None = None
        if raw_task_setup:
            if not isinstance(raw_task_setup, Mapping):
                raise TypeError("environment_task_setup must be an object")
            candidate = raw_task_setup.get("minecraft")
            if candidate is not None:
                if not isinstance(candidate, Mapping):
                    raise TypeError("Minecraft environment task setup must be an object")
                minecraft_task_setup = candidate
        key = canonical_digest({
            "lifetime_id": lifetime_id,
            "task_setup": minecraft_task_setup,
        })
        workdir = (self.instances_root / key).resolve()
        recovery = (self.recovery_root / key).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        recovery.mkdir(parents=True, exist_ok=True)

        version = str(self.config.get("minecraft_version", "")).strip()
        if not version:
            raise RuntimeError(
                "Minecraft lifetime requires explicit minecraft_version"
            )
        branch_id = "assignment-" + key[:24]
        branch_scope = scope_unit(ScopeKind.BRANCH, branch_id)
        session_generation = canonical_digest(
            {"lifetime_id": lifetime_id, "run_id": context.run_id}
        )
        servers = _DockerServerFactory(
            image=self.image,
            image_digest=self.image_digest,
            holder_scope=branch_scope,
            runner=self.runner,
            task_group=self.task_group,
            lifecycle_task_group=self.lifecycle_task_group,
            process_supervisor=self.process_supervisor,
            asset_digest=self.asset_digest,
            recovery_root=recovery,
            capsule=self._capsule,
            pristine_worlds=self.pristine_worlds,
            bridge_runtime=self.bridge_runtime,
        )
        environment_factory = _DockerEnvironmentFactory(
            servers=servers,
            operating_system=self.operating_system,
            process_supervisor=self.process_supervisor,
            task_group=self.task_group,
        )
        branch_factory = MinecraftBranchRuntimeFactory(
            environment_factory=environment_factory,
            action_recovery_root=str(recovery),
        )
        if context.assignment_seed is None:
            raise RuntimeError(
                "Minecraft assignment runtime requires Study assignment seed"
            )
        seed_scope = str(
            context.participant_context.get(
                "environment_seed_scope",
                "assignment",
            )
        )
        if seed_scope not in {"assignment", "task"}:
            raise ValueError(
                "Minecraft environment_seed_scope must be 'assignment' or 'task'"
            )
        if seed_scope == "assignment":
            assignment_lifetime_id = context.participant_context.get(
                "environment_assignment_lifetime_id",
                context.lifetime_id,
            )
            seed_context = replace(
                context,
                lifetime_id=str(assignment_lifetime_id),
                task_id=None,
            )
        else:
            seed_context = context
        world_seed = str(
            environment_random_seed(
                seed_context,
                "minecraft:world",
                scope=seed_scope,
            )
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
                    "bridge_runtime_digest": self.bridge_runtime.key,
                    "assignment_seed": context.assignment_seed,
                    "world_seed": world_seed,
                    "task_setup_digest": (
                        None
                        if minecraft_task_setup is None
                        else canonical_digest(minecraft_task_setup)
                    ),
                }
            ),
            cleanup_ref="lifetime:" + key,
        )
        access = (
            minecraft_task_setup.get("agent_access", {})
            if minecraft_task_setup is not None else {}
        )
        if not isinstance(access, Mapping):
            raise TypeError("Minecraft task agent_access must be an object")
        allowed = access.get("allowed_actions")
        if allowed is not None and (
            not isinstance(allowed, (tuple, list)) or
            isinstance(allowed, (str, bytes, bytearray))
        ):
            raise TypeError("Minecraft allowed_actions must be a sequence")
        visible_fields=access.get("observation_fields")
        if visible_fields is not None and (
            isinstance(visible_fields,(str,bytes,bytearray))
            or not isinstance(visible_fields,(tuple,list))
        ):
            raise TypeError("Minecraft observation_fields must be a sequence")
        environment = minecraft_environment_unit(
            "minecraft",
            version,
            agent_username="ResearchBot",
            agent_auth="offline",
            agent_version=version,
            allowed_action_types=(None if allowed is None else tuple(allowed)),
            visible_state_fields=(
                None if visible_fields is None else tuple(visible_fields)
            ),
        )
        environment_runtime_template = MinecraftEnvironmentRuntimeBinding(
            endpoint=MinecraftEndpointSpec("127.0.0.1", None),
            bridge=MinecraftBridgeSpec(
                command=(_NODE, str(self.bridge_runtime.entrypoint)),
                cwd=str(self.bridge_runtime.root),
                action_recovery_root=str(recovery),
            ),
        )
        server_distribution = self.server_distributions.materialize(
            self.asset,
            asset_digest=self.asset_digest,
            version=version,
        )
        server_template = MinecraftServerSpec(
            jar_path=str(server_distribution.server_jar),
            workdir=str(workdir),
            java_executable=_JAVA,
            libraries_dir=str(server_distribution.libraries_dir),
            host="127.0.0.1",
            port=None,
            level_name="research-world",
            level_seed=world_seed,
            online_mode=False,
            xms=_MINECRAFT_SERVER_XMS,
            xmx=_MINECRAFT_SERVER_XMX,
            rcon_endpoint=(
                MinecraftRconEndpoint()
                if minecraft_task_setup is not None
                else None
            ),
        )
        compute_requirement = _minecraft_compute_requirement(server_template)
        hosts = self.compute_inventory.list_hosts()
        if not hosts:
            raise RuntimeError("Minecraft has no enabled compute host")
        self.resource_authority.declare_capacity(compute_capacity(hosts))

        branch_resource_key = "minecraft-branch:" + key[:24]
        resource_keys = {
            "capsule": self._capsule.resource_key,
            "compute": branch_resource_key + ":compute",
            "game-endpoint": branch_resource_key + ":game-endpoint",
            "server": branch_resource_key + ":server",
        }
        if server_template.rcon_endpoint is not None:
            resource_keys["rcon-endpoint"] = branch_resource_key + ":rcon-endpoint"

        resources = [
            resource_node(
                "capsule",
                kind="container",
                authority_key=resource_keys["capsule"],
                realization=True,
            ),
            resource_node(
                "compute",
                kind="compute",
                authority_key=resource_keys["compute"],
            ),
            resource_node(
                "game-endpoint",
                kind="network-endpoint",
                authority_key=resource_keys["game-endpoint"],
            ),
        ]
        if "rcon-endpoint" in resource_keys:
            resources.append(
                resource_node(
                    "rcon-endpoint",
                    kind="network-endpoint",
                    authority_key=resource_keys["rcon-endpoint"],
                )
            )
        resources.append(
            resource_node(
                "server",
                kind="minecraft-server",
                authority_key=resource_keys["server"],
                realization=True,
            )
        )
        requires = [
            ("server", "capsule"),
            ("server", "compute"),
            ("server", "game-endpoint"),
        ]
        if "rcon-endpoint" in resource_keys:
            requires.append(("server", "rcon-endpoint"))
        resource_topology_unit = resource_topology(
            "minecraft-lifetime:" + key[:24],
            resources=tuple(resources),
            requires=tuple(requires),
        )
        server_provider = _MinecraftServerPhysicalProvider(
            servers=servers,
            capsule=self._capsule,
            recovery_root=recovery,
        )

        def compute_candidates(snapshot, generation: int):
            gpu_runtime = (
                None
                if self.gpu_runtime_observer is None
                else self.gpu_runtime_observer.snapshot()
            )
            host_runtime = (
                None
                if self.host_runtime_observer is None
                else self.host_runtime_observer.snapshot()
            )
            return compute_claim_candidates(
                resource_key=resource_keys["compute"],
                holder_key=scope_key(branch_scope),
                generation=generation,
                consumer_resource_key=resource_keys["server"],
                requirement=compute_requirement,
                hosts=hosts,
                authority=snapshot,
                placement_scope=PLATFORM_SCOPE,
                gpu_runtime=gpu_runtime,
                host_runtime=host_runtime,
                owner_scope=branch_scope,
                scope_generation=branch_scope_generation.generation,
                scope_lease_id=branch_scope_lease_id,
                owner_lease_id=None,
            )

        def endpoint_candidates(node_id: str, role: str):
            resource_key = resource_keys[node_id]
            allocation_id = f"{branch_resource_key}:{role}"
            return lambda snapshot, generation: automatic_endpoint_claim_candidates(
                resource_key=resource_key,
                holder_key=scope_key(branch_scope),
                generation=generation,
                consumer_resource_key=resource_keys["server"],
                allocation_id=allocation_id,
                purpose=f"minecraft-branch:{branch.branch_id}:{role}",
                host="127.0.0.1",
                authority=snapshot,
                candidates=self.endpoint_candidates,
                probe=self.endpoint_probe,
                owner_scope=branch_scope,
                scope_generation=branch_scope_generation.generation,
                scope_lease_id=branch_scope_lease_id,
                owner_lease_id=None,
            )

        def server_candidates(_snapshot, generation: int):
            # Dependency admission is one atomic bundle. The capsule parent
            # may be declared in this very bundle and therefore cannot be
            # required to appear in the pre-admission read cut. Compile its
            # exact deterministic candidate from that same cut; Resource
            # Authority proves the parent is live when it commits the child.
            capsule_generation = _snapshot.generation_for(self._capsule.resource_key)
            if capsule_generation is None:
                raise RuntimeError(
                    "Minecraft server cannot bind an ungenerated capsule owner"
                )
            capsule_claims = self._capsule._claims(
                _snapshot, capsule_generation.generation,
            )
            if len(capsule_claims) != 1:
                raise RuntimeError(
                    "Minecraft server requires exactly one capsule owner candidate"
                )
            attrs = {
                "kind": "minecraft-server",
                "branch_key": key[:24],
                "runtime_identity_digest": self.runtime_identity_digest,
                # The durable Authority edge prevents any other research run
                # from retiring the warm physical container while this branch
                # still holds a live server effect in that container.
                "parent_claim_id": str(claim_field(capsule_claims[0], "claim_id")),
                "parent_resource_key": self._capsule.resource_key,
            }
            return (
                resource_claim(
                    claim_id="minecraft-server:"
                    + canonical_digest(
                        {
                            "resource_key": resource_keys["server"],
                            "generation": generation,
                            "holder_key": scope_key(branch_scope),
                            "attributes": attrs,
                        }
                    ),
                    resource_key=resource_keys["server"],
                    holder_key=scope_key(branch_scope),
                    generation=generation,
                    owner_scope=branch_scope,
                    scope_generation=branch_scope_generation.generation,
                    scope_lease_id=branch_scope_lease_id,
                    owner_lease_id=None,
                    attributes=attrs,
                ),
            )

        claim_candidates = {
            "capsule": self._capsule._claims,
            "compute": compute_candidates,
            "game-endpoint": endpoint_candidates("game-endpoint", "game"),
            "server": server_candidates,
        }
        if "rcon-endpoint" in resource_keys:
            claim_candidates["rcon-endpoint"] = endpoint_candidates(
                "rcon-endpoint",
                "rcon",
            )

        def current_claim(snapshot, node_id: str) -> NoetriumUnit:
            rows = snapshot.current_claims_for(resource_keys[node_id])
            if len(rows) != 1:
                raise RuntimeError(
                    "Minecraft Authority did not converge one current claim: "
                    + node_id
                )
            return rows[0]

        def server_spec(snapshot) -> ResourceRealizationSpec:
            endpoint = endpoint_placement_from_claim(
                current_claim(snapshot, "game-endpoint")
            )
            rcon_endpoint = (
                None
                if "rcon-endpoint" not in resource_keys
                else endpoint_placement_from_claim(
                    current_claim(snapshot, "rcon-endpoint")
                )
            )
            bound_server = replace(
                server_template,
                host=endpoint.endpoint.host,
                port=endpoint.endpoint.port,
                workdir=branch.workdir,
                level_name=branch.level_name,
                rcon_endpoint=(
                    server_template.rcon_endpoint
                    if rcon_endpoint is None
                    else replace(
                        server_template.rcon_endpoint,
                        host=rcon_endpoint.endpoint.host,
                        port=rcon_endpoint.endpoint.port,
                    )
                ),
            )
            environment_generation = environment.unit_digest
            return ResourceRealizationSpec(
                _MinecraftServerPhysicalProvider.provider_kind,
                {
                    "server": _minecraft_server_to_data(bound_server),
                    "environment_generation": environment_generation,
                },
            )

        providers = {
            DockerPhysicalProvider.provider_kind: self.docker_provider,
            _MinecraftServerPhysicalProvider.provider_kind: server_provider,
        }
        realization_specs = {
            "capsule": self._capsule._spec,
            "server": server_spec,
        }

        transient_failures: list[BaseException] = []
        for infrastructure_attempt in range(
            1, self.pre_agent_infrastructure_attempts + 1
        ):
            # A prior failed attempt removes these disposable paths only after
            # Authority retirement. Recreate them before acquiring fresh physical
            # ownership; task/seed identity remains unchanged.
            workdir.mkdir(parents=True, exist_ok=True)
            recovery.mkdir(parents=True, exist_ok=True)
            binding = None
            branch_scope_lease_guard, run_scope_id = (
                self._acquire_branch_scope_lease(context, branch_scope)
            )
            branch_scope_generation, branch_scope_lease_id = (
                self.resource_authority.scope_ownership_cut(
                    branch_scope,
                    scope_lease=branch_scope_lease_guard.handles[0],
                )
            )
            try:
                snapshot = self.resource_authority.reconcile(
                    resource_topology_unit,
                    claim_candidates=claim_candidates,
                    realization_specs=realization_specs,
                    providers=providers,
                )
                compute = compute_placement_from_claim(
                    current_claim(snapshot, "compute")
                )
                endpoint = endpoint_placement_from_claim(
                    current_claim(snapshot, "game-endpoint")
                )
                rcon_endpoint = (
                    None
                    if "rcon-endpoint" not in resource_keys
                    else endpoint_placement_from_claim(
                        current_claim(snapshot, "rcon-endpoint")
                    )
                )
                server = servers.by_port.get(endpoint.endpoint.port)
                if server is None or server.process is None:
                    raise RuntimeError(
                        "Minecraft Authority bound server has no local physical projection"
                    )
                request = MinecraftBranchRuntimeRequest(
                    branch=branch,
                    environment=environment,
                    environment_runtime_template=environment_runtime_template,
                    server_template=server_template,
                    session_id=(
                        "minecraft:" + key[:24] + ":" + session_generation[:16]
                    ),
                    scope=branch_scope,
                )
                binding = branch_factory.open_bound(
                    request,
                    server=server,
                    endpoint=endpoint.endpoint,
                    rcon_endpoint=(
                        None if rcon_endpoint is None else rcon_endpoint.endpoint
                    ),
                )
                if minecraft_task_setup is not None:
                    server.prepare_scientific_player_join()
                session = binding.open_session(object())
                if minecraft_task_setup is not None:
                    server.apply_and_verify_task_setup(session, minecraft_task_setup)
            except BaseException as realization_error:
                cleanup_errors: list[BaseException] = []
                if binding is not None:
                    try:
                        binding.close()
                    except BaseException as cleanup_error:
                        cleanup_errors.append(cleanup_error)
                authority_cleanup_ok = False
                cleanup_resource_generations: dict[str, int] = {}
                try:
                    cleanup_snapshot = self.resource_authority.reconcile(
                        resource_topology_unit,
                        claim_candidates={"capsule": self._capsule._claims},
                        realization_specs={"capsule": self._capsule._spec},
                        providers=providers,
                        desired_resource_ids=frozenset({"capsule"}),
                    )
                    cleanup_resource_generations = {
                        node_id: generation.generation
                        for node_id, resource_key in resource_keys.items()
                        if (generation := cleanup_snapshot.generation_for(resource_key))
                        is not None
                    }
                    authority_cleanup_ok = True
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                try:
                    self._release_branch_scope_guard(
                        branch_scope_lease_guard,
                        run_scope_id,
                    )
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                if authority_cleanup_ok:
                    # Local factory projections are not Authority truth. Clear
                    # them only after physical retirement has been proved.
                    with servers.lock:
                        servers.by_port.clear()
                    try:
                        self._remove_disposable_runtime_paths(workdir, recovery)
                    except BaseException as cleanup_error:
                        cleanup_errors.append(cleanup_error)
                if cleanup_errors:
                    raise ExceptionGroup(
                        "Minecraft pre-agent infrastructure transaction failed "
                        "and cleanup did not converge",
                        [realization_error, *cleanup_errors],
                    ) from realization_error

                recovery_decision = _pre_agent_recovery_decision(
                    realization_error,
                    attempt=infrastructure_attempt,
                    max_attempts=self.pre_agent_infrastructure_attempts,
                )
                if recovery_decision != "fatal":
                    transient_failures.append(realization_error)
                    self._record_pre_agent_recovery(
                        lifetime_key=key,
                        attempt=infrastructure_attempt,
                        status=(
                            "retrying"
                            if recovery_decision == "retry"
                            else "exhausted"
                        ),
                        scope_generation=branch_scope_generation.generation,
                        resource_generations=cleanup_resource_generations,
                        failure=realization_error,
                    )
                    if recovery_decision == "retry":
                        continue
                    if len(transient_failures) == 1:
                        raise realization_error
                    raise ExceptionGroup(
                        "Minecraft pre-agent infrastructure recovery attempts exhausted",
                        transient_failures,
                    ) from realization_error
                raise

            if transient_failures:
                self._record_pre_agent_recovery(
                    lifetime_key=key,
                    attempt=infrastructure_attempt,
                    status="recovered",
                    scope_generation=branch_scope_generation.generation,
                    resource_generations={
                        node_id: generation.generation
                        for node_id, resource_key in resource_keys.items()
                        if (generation := snapshot.generation_for(resource_key))
                        is not None
                    },
                    failure=None,
                )
            return _LifetimeRuntime(
                binding=binding,
                session=session,
                branch_scope_lease_guard=branch_scope_lease_guard,
                run_id=run_scope_id,
                workdir=workdir,
                recovery_root=recovery,
                compute=compute,
                endpoint=endpoint,
                rcon_endpoint=rcon_endpoint,
                resource_topology_unit=resource_topology_unit,
                providers=providers,
                claim_candidates=claim_candidates,
                realization_specs=realization_specs,
            )

        raise AssertionError("Minecraft pre-agent recovery loop terminated without outcome")


    def _reap_completed_retirements(self) -> None:
        with self.lock:
            completed = tuple(
                (lifetime_id, handle)
                for lifetime_id, handle in self._retirements.items()
                if handle.done()
            )
        if not completed:
            return

        outcomes: list[tuple[str, object, BaseException | None]] = []
        for lifetime_id, handle in completed:
            failure = None
            try:
                handle.result()
            except BaseException as exc:
                exc.add_note(
                    "Minecraft lifetime retirement failed: " + lifetime_id
                )
                failure = exc
            outcomes.append((lifetime_id, handle, failure))

        with self.lock:
            for lifetime_id, handle, failure in outcomes:
                if self._retirements.get(lifetime_id) is not handle:
                    continue
                del self._retirements[lifetime_id]
                if failure is None:
                    self._retirement_rows.pop(lifetime_id, None)
                    self._retirement_failures.pop(lifetime_id, None)
                    self._lifetime_locks.pop(lifetime_id, None)
                else:
                    # Keep the exact runtime ownership row and lifetime lock. A
                    # later release/reap/close can retry the idempotent teardown
                    # instead of turning a transient physical failure into a leak.
                    self._retirement_failures[lifetime_id] = failure

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

    def prepare(
        self,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> None:
        """Prepare one assignment and return only after Mineflayer spawned.

        Physical creation still runs on the shared prewarm task group, preserving
        platform-managed concurrency across independent assignments. The caller
        observes a readiness barrier: scientific task time must not begin while
        Docker, Minecraft readiness, pristine-world publication, or the bridge
        spawn handshake are still in flight.
        """
        if not isinstance(control, ExecutionControlPort):
            raise TypeError("Minecraft preparation requires ExecutionControlPort")
        control.checkpoint()
        self._reap_completed_preparations()
        lifetime_id = context.lifetime_id
        if type(lifetime_id) is not str or not lifetime_id.strip():
            raise ValueError("Minecraft preparation requires lifetime_id")

        def materialize(task_control) -> None:
            control.checkpoint()
            task_control.checkpoint()
            # session_for() returns only after _open() has observed server READY
            # and MinecraftEnvironmentSession has completed bridge.start(). The
            # bridge handshake itself requires bridge_status=spawned.
            self.session_for(context)

        # Submission may synchronously wait on admission. Never hold the
        # controller-wide lock across that wait: a started prewarm task must be
        # able to publish its ready runtime through session_for() independently.
        # The existing per-lifetime lock provides the exact single-flight
        # boundary needed to prevent duplicate submissions for one lifetime.
        with self.lock:
            if lifetime_id in self.runtimes:
                return
            if lifetime_id in self._retirements or lifetime_id in self._retirement_rows:
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
            lifetime_lock = self._lifetime_locks.get(lifetime_id)
            if lifetime_lock is None:
                lifetime_lock = threading.Lock()
                self._lifetime_locks[lifetime_id] = lifetime_lock

        with lifetime_lock:
            with self.lock:
                if lifetime_id in self.runtimes:
                    return
                if (
                    lifetime_id in self._retirements
                    or lifetime_id in self._retirement_rows
                ):
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
                handle = self._preparations.get(lifetime_id)

            if handle is None:
                submitted = self.prewarm_task_group.submit(
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
                        failure_scope=TaskFailureScope.CALLER,
                    ),
                    materialize,
                )
                with self.lock:
                    existing = self._preparations.get(lifetime_id)
                    if existing is not None:
                        raise RuntimeError(
                            "Minecraft prewarm single-flight publication drifted: "
                            + lifetime_id
                        )
                    self._preparations[lifetime_id] = submitted
                    handle = submitted

        # Infrastructure readiness is outside the scientific task budget.
        # Wake exactly on physical task completion or caller cancellation; do
        # not time-slice a Future.result() loop. A finite execution deadline is
        # the only timer and remains owned by ExecutionControlPort.
        unsubscribe_cancel = None
        try:
            control.checkpoint()
            if not handle.done():
                completion = threading.Event()
                handle.add_done_callback(lambda _handle: completion.set())
                # Completion may race callback registration. Avoid installing a
                # cancellation subscriber when the physical task is already done.
                if not handle.done():
                    unsubscribe_cancel = control.subscribe_cancel(completion.set)
                    remaining = control.remaining_seconds
                    if remaining is not None and remaining <= 0.0:
                        control.checkpoint()
                    completion.wait(timeout=remaining)
            control.checkpoint()
            # The completion callback is published only after physical task
            # completion/permit release, so this non-blocking join cannot add a
            # periodic readiness delay.
            handle.result(timeout=0.0)
        finally:
            if unsubscribe_cancel is not None:
                unsubscribe_cancel()
            self._reap_completed_preparations()

        control.checkpoint()
        with self.lock:
            failure = self._preparation_failures.get(lifetime_id)
            ready = lifetime_id in self.runtimes
        if failure is not None:
            raise RuntimeError(
                "Minecraft lifetime preparation failed: " + lifetime_id
            ) from failure
        if not ready:
            raise RuntimeError(
                "Minecraft preparation completed without a spawned session: "
                + lifetime_id
            )

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
                    # Per-lifetime locking should make this unreachable. If it
                    # ever happens, retire the duplicate through the same exact
                    # resource topology rather than leaking a second lifecycle.
                    opened.binding.close()
                    self.resource_authority.reconcile(
                        opened.resource_topology_unit,
                        claim_candidates={"capsule": self._capsule._claims},
                        realization_specs={"capsule": self._capsule._spec},
                        providers=opened.providers,
                        desired_resource_ids=frozenset({"capsule"}),
                    )
                    self._release_branch_scope_guard(
                        opened.branch_scope_lease_guard,
                        opened.run_id,
                    )
                    self._remove_disposable_runtime_paths(
                        opened.workdir,
                        opened.recovery_root,
                    )
            return row.session

    @staticmethod
    def _remove_disposable_runtime_paths(
        workdir: Path,
        recovery_root: Path,
    ) -> None:
        for path in (workdir, recovery_root):
            if path.exists():
                shutil.rmtree(path, ignore_errors=False)

    def _retire_runtime(
        self,
        lifetime_id: str,
        row: _LifetimeRuntime,
    ) -> None:
        """Converge one lifetime without letting one failed cleanup mask others.

        Resource reconciliation is the proof boundary for releasing BRANCH/RUN
        scope ownership. Session close is attempted first but a close exception
        cannot prevent Authority from observing/retiring already-dead physical
        resources. Scope leases remain fenced whenever reconciliation itself
        fails.
        """

        errors: list[BaseException] = []
        try:
            row.binding.close()
        except BaseException as exc:
            exc.add_note(
                "Minecraft session close failed during lifetime retirement: "
                + lifetime_id
            )
            errors.append(exc)

        reconciled = False
        try:
            self.resource_authority.reconcile(
                row.resource_topology_unit,
                claim_candidates={"capsule": self._capsule._claims},
                realization_specs={"capsule": self._capsule._spec},
                providers=row.providers,
                desired_resource_ids=frozenset({"capsule"}),
            )
        except BaseException as exc:
            exc.add_note(
                "Minecraft resource reconciliation failed during lifetime retirement: "
                + lifetime_id
            )
            errors.append(exc)
        else:
            reconciled = True

        if reconciled:
            try:
                self._release_branch_scope_guard(
                    row.branch_scope_lease_guard,
                    row.run_id,
                )
            except BaseException as exc:
                exc.add_note(
                    "Minecraft scope ownership release failed during lifetime retirement: "
                    + lifetime_id
                )
                errors.append(exc)
            try:
                self._remove_disposable_runtime_paths(
                    row.workdir,
                    row.recovery_root,
                )
            except BaseException as exc:
                exc.add_note(
                    "Minecraft disposable runtime cleanup failed: " + lifetime_id
                )
                errors.append(exc)

        if errors:
            raise BaseExceptionGroup(
                "Minecraft lifetime retirement did not fully converge",
                errors,
            )

    def _submit_retirement(
        self,
        lifetime_id: str,
        row: _LifetimeRuntime,
    ) -> None:
        self._retirement_sequence += 1
        retirement_sequence = self._retirement_sequence

        def retire(_context) -> None:
            self._retire_runtime(lifetime_id, row)

        try:
            handle = self.lifecycle_task_group.submit(
                ExecutionSpec(
                    task_id=(
                        "minecraft-lifetime-retire:"
                        + canonical_digest(
                            {
                                "lifetime_id": lifetime_id,
                                "sequence": retirement_sequence,
                                "owner_generation_id": self.owner_generation_id,
                            }
                        )[:32]
                    ),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                retire,
            )
        except BaseException:
            # If structured submission is already converging, make one synchronous
            # attempt while the exact ownership row is still retained. Failure
            # leaves the row available to close/recovery rather than losing it.
            self._retire_runtime(lifetime_id, row)
            with self.lock:
                self._retirement_rows.pop(lifetime_id, None)
                self._retirement_failures.pop(lifetime_id, None)
                self._lifetime_locks.pop(lifetime_id, None)
            return
        with self.lock:
            self._retirements[lifetime_id] = handle

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
                row = self._retirement_rows.get(lifetime_id)
                if row is None:
                    row = self.runtimes.pop(lifetime_id, None)
                    if row is None:
                        return
                    self._retirement_rows[lifetime_id] = row
                self._retirement_failures.pop(lifetime_id, None)
            self._submit_retirement(lifetime_id, row)

    def close(self) -> None:
        with self.lock:
            preparations = tuple(self._preparations.items())
        preparation_errors: list[BaseException] = []

        # Terminal teardown revokes startup authority before joining preparation.
        # Waiting first can dequeue a pending prewarm task whose materializer calls
        # session_for(), causing close() itself to create a new branch/session.
        # Cancellation is cooperative for already-running work; result() remains
        # the physical convergence fence before any materialized runtime retires.
        for lifetime_id, handle in preparations:
            try:
                handle.cancel()
            except BaseException as exc:
                exc.add_note(
                    "Minecraft lifetime preparation cancellation failed during close: "
                    + lifetime_id
                )
                preparation_errors.append(exc)

        for lifetime_id, handle in preparations:
            failure: BaseException | None = None
            try:
                handle.result()
            except (TaskCancelled, CancelledError):
                # Close owns this cancellation; it is a successful prevention of
                # new physical startup, not a provider/preparation failure.
                pass
            except BaseException as exc:
                exc.add_note(
                    "Minecraft lifetime preparation failed during close: "
                    + lifetime_id
                )
                failure = exc
                preparation_errors.append(exc)
            finally:
                with self.lock:
                    if self._preparations.get(lifetime_id) is handle:
                        self._preparations.pop(lifetime_id, None)
                        if failure is not None:
                            self._preparation_failures[lifetime_id] = failure
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
        for _lifetime_id, handle in retirements:
            try:
                handle.result()
            except BaseException:
                # Reaped below; the retained ownership row is retried once after
                # all concurrent retirement tasks have quiesced.
                pass
        self._reap_completed_retirements()

        with self.lock:
            retry_rows = tuple(
                (lifetime_id, row)
                for lifetime_id, row in self._retirement_rows.items()
                if lifetime_id not in self._retirements
            )
        for lifetime_id, row in retry_rows:
            try:
                self._retire_runtime(lifetime_id, row)
            except BaseException as exc:
                exc.add_note(
                    "Minecraft lifetime retirement failed after close retry: "
                    + lifetime_id
                )
                errors.append(exc)
            else:
                with self.lock:
                    self._retirement_rows.pop(lifetime_id, None)
                    self._retirement_failures.pop(lifetime_id, None)
                    self._lifetime_locks.pop(lifetime_id, None)

        # A startup maintenance pass cannot see ownership that becomes orphaned
        # later in the run. Terminal physical close therefore takes one final
        # authoritative convergence cut after every local lifetime retirement
        # has quiesced. This is lifecycle convergence, not best-effort hygiene.
        try:
            self._reconcile_shared_fabric()
        except BaseException as exc:
            exc.add_note(
                "Minecraft terminal fabric reconciliation failed before capsule close"
            )
            errors.append(exc)

        runtime_gc_handles = getattr(self, "_runtime_gc_handles", None)
        for handle in tuple(() if runtime_gc_handles is None else runtime_gc_handles):
            try:
                handle.result()
            except BaseException as exc:
                exc.add_note(
                    "Minecraft quarantined runtime GC failed; pending paths remain durable"
                )
                errors.append(exc)
        if runtime_gc_handles is not None:
            runtime_gc_handles.clear()

        try:
            self._capsule.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise BaseExceptionGroup("Minecraft lifetime cleanup failed", errors)


__all__ = ["LocalMinecraftLifetimeSessionController", "MINECRAFT_LOCAL_IMPLEMENTATION_ID"]
