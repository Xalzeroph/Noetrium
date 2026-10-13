from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import math
from pathlib import Path
from typing import cast

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRegistryPort
from noetrium_platform.evidence.data.dataset.api import DatasetRegistryPort
from noetrium_platform.evidence.data.query.api import ResearchResultQueryPort
from noetrium_platform.evidence.data.query.cross.composition import (
    compose_builtin_research_result_query,
)
from noetrium_platform.research.experimentation.api import ExperimentationCatalogPort
from noetrium_platform.research.experimentation.runtime import (
    SQLiteExperimentationCatalog,
)
from noetrium_platform.foundation.governance.evolution.api import SystemEvolutionPort
from noetrium_platform.foundation.governance.evolution.providers import (
    SQLiteEvolutionStore,
)
from noetrium_platform.foundation.governance.evolution.runtime import (
    RegistryDrivenEvolutionController,
)
from noetrium_platform.foundation.governance.system_registry.api import (
    SystemRegistryPort,
)
from noetrium_platform.foundation.governance.system_registry.runtime import (
    build_default_system_registry,
)
from noetrium_platform.foundation.portfolio.api import PortfolioCatalogPort
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioCatalog
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_connection,
)
from noetrium_platform.foundation.scope.api import ScopeIndexPort
from noetrium_platform.foundation.scope.runtime import InMemoryScopeIndex
from noetrium_platform.foundation.governance.architecture.runtime.capability_composition import (
    CapabilityCompositionPlanner,
)

from noetrium_platform.capabilities.environment.catalog.api import (
    ExecutionEnvironmentCatalogPort,
)
from noetrium_platform.capabilities.environment.catalog.runtime import (
    SQLiteExecutionEnvironmentCatalog,
)
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointCandidatePortSourcePort,
    EndpointProbePort,
)
from noetrium_platform.infrastructure.resources.allocation.providers import (
    LocalEndpointCandidateSource,
    SocketEndpointProbe,
)
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeInventoryPort,
    GpuRuntimeObserverPort,
    HostRuntimeObserverPort,
)
from noetrium_platform.infrastructure.resources.compute.runtime.inventory import (
    ComputeInventory,
)


@dataclass(frozen=True, slots=True)
class PlatformMetaAuthorities:
    """Composition root containing one resource Authority and pure fact sources."""

    systems: SystemRegistryPort
    evolution: SystemEvolutionPort
    scopes: ScopeIndexPort
    capability_composition: CapabilityCompositionPlanner
    portfolio: PortfolioCatalogPort
    experimentation: ExperimentationCatalogPort
    environments: ExecutionEnvironmentCatalogPort
    artifacts: ArtifactRegistryPort
    datasets: DatasetRegistryPort
    research_results: ResearchResultQueryPort

    resource_authority: UniversalResourceAuthority
    compute_inventory: ComputeInventoryPort
    endpoint_candidates: EndpointCandidatePortSourcePort
    endpoint_probe: EndpointProbePort
    gpu_runtime_observer: GpuRuntimeObserverPort | None
    host_runtime_observer: HostRuntimeObserverPort | None


def build_platform_meta(
    root: str | Path,
    *,
    resource_authority: UniversalResourceAuthority,
    artifact_root: str | Path | None = None,
    gpu_runtime_observer: GpuRuntimeObserverPort | None = None,
    host_runtime_observer: HostRuntimeObserverPort | None = None,
    timeout_seconds: float = 30.0,
) -> PlatformMetaAuthorities:
    """Build platform metadata around one durable resource Authority.

    Resource ownership, generations, claims, leases, single-flight, bindings
    and reconciliation are one SQLite state machine. Compute inventory and
    physical probes are facts, not independent lifecycle authorities.
    """

    if not isinstance(resource_authority, UniversalResourceAuthority):
        raise TypeError(
            "platform meta requires the sole UniversalResourceAuthority"
        )
    timeout_seconds = float(timeout_seconds)
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(
            "platform meta timeout_seconds must be finite and positive"
        )
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    artifact_root_path = root if artifact_root is None else Path(artifact_root)
    artifact_root_path.mkdir(parents=True, exist_ok=True)
    # This database still owns the active Portfolio catalog. Scope hierarchy
    # itself is an immutable Unit projection, not a dedicated SQLite authority.
    database = root / "platform-meta.sqlite"
    resource_database = resource_authority.path

    # Avoid legacy Scope DDL on each fresh runtime composition. The owning
    # Portfolio catalog opens the same database below.
    scopes = InMemoryScopeIndex()
    systems = build_default_system_registry()
    evolution_store = SQLiteEvolutionStore(
        root / "platform-evolution.sqlite",
        timeout_seconds=timeout_seconds,
        connection_factory=durable_sqlite_connection,
    )
    evolution = RegistryDrivenEvolutionController(systems, store=evolution_store)
    experimentation = SQLiteExperimentationCatalog(
        root / "platform-experimentation.sqlite",
        scopes,
        timeout_seconds=timeout_seconds,
    )
    environments = SQLiteExecutionEnvironmentCatalog(
        root / "platform-environments.sqlite",
        scopes,
        timeout_seconds=timeout_seconds,
    )

    compute_inventory = ComputeInventory(
        resource_database,
        timeout_seconds=timeout_seconds,
    )
    endpoint_candidates = LocalEndpointCandidateSource()
    endpoint_probe = SocketEndpointProbe()

    artifact_registry_type = import_module(
        "noetrium_platform.evidence.artifact.catalog.providers"
    ).SQLiteArtifactRegistry
    artifacts = cast(
        ArtifactRegistryPort,
        artifact_registry_type(
            artifact_registry_type.default_path(
                artifact_root_path,
                "platform-artifacts.sqlite",
            )
        ),
    )
    datasets = cast(
        DatasetRegistryPort,
        import_module(
            "noetrium_platform.evidence.data.dataset.providers.sqlite"
        ).SQLiteDatasetRegistry(root / "platform-datasets.sqlite"),
    )
    research_results = compose_builtin_research_result_query(
        datasets=datasets,
        artifacts=artifacts,
        scopes=scopes,
    )

    return PlatformMetaAuthorities(
        systems=systems,
        evolution=evolution,
        scopes=scopes,
        capability_composition=CapabilityCompositionPlanner(
            systems=systems,
            scopes=scopes,
        ),
        portfolio=SQLitePortfolioCatalog(
            database,
            scopes,
            timeout_seconds=timeout_seconds,
        ),
        experimentation=experimentation,
        environments=environments,
        artifacts=artifacts,
        datasets=datasets,
        research_results=research_results,
        resource_authority=resource_authority,
        compute_inventory=compute_inventory,
        endpoint_candidates=endpoint_candidates,
        endpoint_probe=endpoint_probe,
        gpu_runtime_observer=gpu_runtime_observer,
        host_runtime_observer=host_runtime_observer,
    )


__all__ = ["PlatformMetaAuthorities", "build_platform_meta"]
