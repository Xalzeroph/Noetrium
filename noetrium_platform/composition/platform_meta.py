from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import cast

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRegistryPort
from noetrium_platform.evidence.data.dataset.api import DatasetRegistryPort
from noetrium_platform.evidence.data.fact.api import DurableFactStorePort
from noetrium_platform.evidence.data.fact.composition import (
    compose_sqlite_fact_store,
)
from noetrium_platform.evidence.data.query.api import ResearchResultQueryPort
from noetrium_platform.evidence.data.query.cross.composition import (
    compose_builtin_research_result_query,
)
from noetrium_platform.research.experimentation.api import ExperimentationCatalogPort
from noetrium_platform.research.experimentation.runtime import (
    SQLiteExperimentationCatalog,
)
from noetrium_platform.foundation.governance.evolution.api import SystemEvolutionPort
from noetrium_platform.foundation.governance.evolution.providers import SQLiteEvolutionStore
from noetrium_platform.foundation.governance.evolution.runtime import RegistryDrivenEvolutionController
from noetrium_platform.foundation.governance.system_registry.api import SystemRegistryPort
from noetrium_platform.foundation.governance.system_registry.runtime import build_default_system_registry
from noetrium_platform.foundation.portfolio.api import PortfolioCatalogPort
from noetrium_platform.foundation.portfolio.runtime import (
    SQLitePortfolioCatalog,
)
from noetrium_platform.infrastructure.resources.compute.api import ComputeInventoryPort, ComputeSchedulerPort, GpuRuntimeObserverPort, HostRuntimeObserverPort
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocationPort,
)
from noetrium_platform.infrastructure.resources.allocation.providers import (
    LocalEndpointCandidateSource,
    SocketEndpointProbe,
)
from noetrium_platform.infrastructure.resources.providers import SQLiteEndpointAllocationStore
from noetrium_platform.infrastructure.resources.lease.runtime import ResourceLeaseRegistry
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_connection,
)
from noetrium_platform.infrastructure.resources.allocation.runtime import AtomicEndpointAllocator
from noetrium_platform.infrastructure.resources.compute.composition import compose_compute_authority
from noetrium_platform.infrastructure.resources.lease.api import LeaseClockPort, ResourceLeasePort, ResourceOwnershipPort
from noetrium_platform.infrastructure.resources.lease.runtime import LocalLeaseClock
from noetrium_platform.capabilities.environment.catalog.api import ExecutionEnvironmentCatalogPort
from noetrium_platform.capabilities.environment.catalog.runtime import SQLiteExecutionEnvironmentCatalog
from noetrium_platform.composition.environment_instance_leases import (
    EnvironmentInstanceLeaseAuthority,
)
from noetrium_platform.foundation.scope.api import ScopeRegistryPort
from noetrium_platform.foundation.scope.providers import SQLiteScopeRegistry
from noetrium_platform.foundation.governance.architecture.runtime.capability_composition import (
    CapabilityCompositionPlanner,
)


@dataclass(frozen=True, slots=True)
class PlatformMetaAuthorities:
    """Behavior-free bundle used only by composition roots and top-level management surfaces."""

    systems: SystemRegistryPort
    evolution: SystemEvolutionPort
    scopes: ScopeRegistryPort
    capability_composition: CapabilityCompositionPlanner
    portfolio: PortfolioCatalogPort
    experimentation: ExperimentationCatalogPort
    environments: ExecutionEnvironmentCatalogPort
    environment_instance_leases: EnvironmentInstanceLeaseAuthority
    artifacts: ArtifactRegistryPort
    datasets: DatasetRegistryPort
    facts: DurableFactStorePort
    research_results: ResearchResultQueryPort
    resource_ownership: ResourceOwnershipPort
    resource_leases: ResourceLeasePort
    endpoint_allocations: EndpointAllocationPort
    compute_inventory: ComputeInventoryPort
    compute_scheduler: ComputeSchedulerPort


def build_platform_meta(
    root: str | Path,
    *,
    gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
    host_runtime_observer: HostRuntimeObserverPort | None = None,
    lease_clock: LeaseClockPort | None = None,
) -> PlatformMetaAuthorities:
    """Build the production authority bundle over one durable SQLite root.

    Catalogs that are immutable project inputs remain lightweight registries;
    scope hierarchy, resource ownership/leases, and endpoint allocations share
    one SQLite authority and therefore survive process restart and coordinate
    competing workers.
    """

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    database = root / "platform-meta.sqlite"
    scopes = SQLiteScopeRegistry(database)
    systems = build_default_system_registry()
    evolution_store = SQLiteEvolutionStore(
        root / "platform-evolution.sqlite",
        connection_factory=durable_sqlite_connection,
    )
    evolution = RegistryDrivenEvolutionController(systems, store=evolution_store)
    experimentation = SQLiteExperimentationCatalog(root / "platform-experimentation.sqlite", scopes)
    resolved_lease_clock = lease_clock or LocalLeaseClock()
    resources = ResourceLeaseRegistry(database, clock=resolved_lease_clock)
    environments = SQLiteExecutionEnvironmentCatalog(
        root / "platform-environments.sqlite",
        scopes,
    )
    environment_instance_leases = EnvironmentInstanceLeaseAuthority(
        catalog=environments,
        ownership=resources,
        leases=resources,
    )
    endpoint_candidates = LocalEndpointCandidateSource()
    endpoint_allocations = AtomicEndpointAllocator(
        reservations=SQLiteEndpointAllocationStore(
            database,
            clock=resolved_lease_clock,
        ),
        probe=SocketEndpointProbe(),
        candidates=endpoint_candidates,
    )
    compute = compose_compute_authority(
        database,
        clock=resolved_lease_clock,
        gpu_runtime_observer=gpu_runtime_observer,
        host_runtime_observer=host_runtime_observer,
    )
    compute_inventory = compute.inventory
    compute_scheduler = compute.scheduler
    artifacts = cast(
        ArtifactRegistryPort,
        import_module(
            "noetrium_platform.evidence.artifact.catalog.providers"
        ).SQLiteArtifactRegistry(root / "platform-artifacts.sqlite"),
    )
    datasets = cast(
        DatasetRegistryPort,
        import_module(
            "noetrium_platform.evidence.data.dataset.providers.sqlite"
        ).SQLiteDatasetRegistry(root / "platform-datasets.sqlite"),
    )
    facts = compose_sqlite_fact_store(root / "platform-facts.sqlite")
    research_results = compose_builtin_research_result_query(
        datasets=datasets,
        artifacts=artifacts,
        scopes=scopes,
    )
    return PlatformMetaAuthorities(
        systems=systems,
        evolution=evolution,
        scopes=scopes,
        capability_composition=CapabilityCompositionPlanner(systems=systems, scopes=scopes),
        portfolio=SQLitePortfolioCatalog(database, scopes),
        experimentation=experimentation,
        environments=environments,
        environment_instance_leases=environment_instance_leases,
        artifacts=artifacts,
        datasets=datasets,
        facts=facts,
        research_results=research_results,
        resource_ownership=resources,
        resource_leases=resources,
        endpoint_allocations=endpoint_allocations,
        compute_inventory=compute_inventory,
        compute_scheduler=compute_scheduler,
    )


__all__ = ["PlatformMetaAuthorities", "build_platform_meta"]
