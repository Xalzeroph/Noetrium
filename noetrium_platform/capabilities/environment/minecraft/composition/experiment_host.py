from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftBranchRuntimeFactoryPort,
    MinecraftBranchServerFactoryPort,
    MinecraftScenarioProvisioningPort,
    MinecraftScenarioReceipt,
    MinecraftServerConsolePort,
    MinecraftServerSpec,
    MinecraftWorldCutPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.allocation.api import EndpointAllocationPort, EndpointLeaseGuardFactoryPort
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceProcessIdentity,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)

from ..providers.world_cut import (
    FilesystemMinecraftWorldCutProvider,
    MinecraftWorldCopier,
)
from ..providers.world_quiescence import MinecraftSaveQuiescenceProvider
from .branch_runtime import (
    MinecraftBranchCheckpointFactoryPort,
    MinecraftBranchEnvironmentFactoryPort,
    MinecraftBranchRuntimeFactory,
)


class MinecraftSourceServerPort(Protocol):
    """The source-server lifecycle facts required by a world-cut host."""

    contract: ServiceLaunchContract

    def start(self) -> ServiceStartOutcome: ...
    def reconcile(self) -> ServiceReconcileObservation: ...
    def stop(self) -> ServiceStopOutcome: ...


@dataclass(slots=True)
class _SourceProcessState:
    """Typed mutable handoff for the source identity during quiescence."""

    process: ServiceProcessIdentity | None = None


@dataclass(frozen=True, slots=True)
class MinecraftExperimentHostInputs:
    """Generic MC host inputs shared by every project experiment.

    Project code supplies only its workload/request composition.  This value
    owns no paper method, task semantics, planner or candidate policy.
    """

    source_server_spec: MinecraftServerSpec
    source_console: MinecraftServerConsolePort
    source_server_factory: MinecraftBranchServerFactoryPort
    branch_server_factory: MinecraftBranchServerFactoryPort
    endpoint_allocations: EndpointAllocationPort
    environment_factory: MinecraftBranchEnvironmentFactoryPort
    snapshot_root: str | Path
    branch_root: str | Path
    source_environment_generation: str
    source_scenario: MinecraftScenarioProvisioningPort | None = None
    copier: MinecraftWorldCopier | None = None
    branch_checkpoint_factory: MinecraftBranchCheckpointFactoryPort | None = None
    lease_guard_factory: EndpointLeaseGuardFactoryPort | None = None

    def __post_init__(self) -> None:
        if not self.source_environment_generation.strip():
            raise ValueError("Minecraft experiment source environment generation is required")
        for name, value in (("snapshot_root", self.snapshot_root), ("branch_root", self.branch_root)):
            if not is_absolute_target_path(Path(value).expanduser().resolve(strict=False)):
                raise ValueError(f"Minecraft experiment {name} must be an absolute path")
        if self.source_server_spec.rcon_endpoint is None:
            raise ValueError("Minecraft experiment source server requires an RCON endpoint for world cuts")


class MinecraftExperimentHost:
    """Reusable source-cut and branch-runtime host for MC experiments."""

    def __init__(
        self,
        *,
        source_server: MinecraftSourceServerPort,
        world_cuts: MinecraftWorldCutPort,
        branch_runtime_factory: MinecraftBranchRuntimeFactoryPort,
        source_process_state: _SourceProcessState,
        source_scenario: MinecraftScenarioProvisioningPort | None = None,
    ) -> None:
        self.source_server = source_server
        self.world_cuts = world_cuts
        self.branch_runtime_factory = branch_runtime_factory
        self._source_process_state = source_process_state
        self._source_scenario = source_scenario
        self._source_scenario_receipt: MinecraftScenarioReceipt | None = None
        self._started = False

    def start_source(self) -> ServiceStartOutcome:
        if self._started:
            raise RuntimeError("Minecraft experiment source server is already started")
        outcome = self.source_server.start()
        self._source_process_state.process = outcome.process
        self._started = True
        if self._source_scenario is not None:
            self._source_scenario_receipt = None
            try:
                self._source_scenario_receipt = self._source_scenario.apply()
            except BaseException as scenario_error:
                try:
                    self.source_server.stop()
                except BaseException as stop_error:
                    raise RuntimeError(
                        "Minecraft source scenario failed and source cleanup also failed: "
                        f"scenario={scenario_error}; cleanup={stop_error}"
                    ) from scenario_error
                finally:
                    self._started = False
                    self._source_process_state.process = None
                raise
        return outcome

    @property
    def source_scenario_receipt(self) -> MinecraftScenarioReceipt | None:
        return self._source_scenario_receipt

    def process_identity_digest(self) -> str:
        observation = self.source_server.reconcile()
        process = observation.process or self._source_process_state.process
        if process is None:
            raise RuntimeError("Minecraft source server process identity is unavailable")
        return canonical_digest(process)

    def stop_source(self) -> ServiceStopOutcome | None:
        if not self._started:
            return None
        try:
            return self.source_server.stop()
        finally:
            self._started = False
            self._source_process_state.process = None

    def __enter__(self) -> "MinecraftExperimentHost":
        self.start_source()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.stop_source()
        return False




class _MissingEndpointLeaseGuardFactory:
    def create(self, allocation_ids: tuple[str, ...]):
        del allocation_ids
        raise RuntimeError("Minecraft experiment host requires an injected endpoint lease guard factory")

class LocalMinecraftExperimentHostFactory:
    """Compose local MC source/world-cut/branch authorities from injected ports."""

    def __init__(self, inputs: MinecraftExperimentHostInputs) -> None:
        self.inputs = inputs

    def open(self) -> MinecraftExperimentHost:
        inputs = self.inputs
        source_server = inputs.source_server_factory.create(
            inputs.source_server_spec,
            environment_generation=inputs.source_environment_generation,
        )
        source_process_state = _SourceProcessState()
        quiescence = MinecraftSaveQuiescenceProvider(
            console=inputs.source_console,
            source_workdir=inputs.source_server_spec.workdir,
            level_name=inputs.source_server_spec.level_name,
            server_contract_digest=source_server.contract.digest(),
            process_identity_digest=lambda: self._source_process_digest(
                source_server,
                source_process_state,
            ),
        )
        world_cuts = FilesystemMinecraftWorldCutProvider(
            quiescence=quiescence,
            snapshot_root=inputs.snapshot_root,
            branch_root=inputs.branch_root,
            copier=inputs.copier,
        )
        branch_runtime_factory = MinecraftBranchRuntimeFactory(
            endpoint_allocations=inputs.endpoint_allocations,
            environment_factory=inputs.environment_factory,
            server_factory=inputs.branch_server_factory,
            checkpoint_factory=inputs.branch_checkpoint_factory,
            lease_guard_factory=(
                inputs.lease_guard_factory
                if inputs.lease_guard_factory is not None
                else _MissingEndpointLeaseGuardFactory()
            ),
            action_recovery_root=str(Path(inputs.branch_root) / ".action-recovery"),
        )
        return MinecraftExperimentHost(
            source_server=source_server,
            world_cuts=world_cuts,
            branch_runtime_factory=branch_runtime_factory,
            source_process_state=source_process_state,
            source_scenario=inputs.source_scenario,
        )

    @staticmethod
    def _source_process_digest(
        source_server: MinecraftSourceServerPort,
        source_process_state: _SourceProcessState,
    ) -> str:
        observation = source_server.reconcile()
        process = observation.process or source_process_state.process
        if process is None:
            raise RuntimeError("Minecraft source server process identity is unavailable")
        return canonical_digest(process)


__all__ = [
    "LocalMinecraftExperimentHostFactory",
    "MinecraftExperimentHost",
    "MinecraftExperimentHostInputs",
    "MinecraftSourceServerPort",
]
