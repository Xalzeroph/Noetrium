"""Canonical durable local composition for Product Research OS.

All local project/fleet entrypoints must reuse this wiring rather than creating
parallel store, value-authority, execution-pool or runtime compositions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.research.execution.workflow.api import MethodObservationPort, OperationDispatchPort
from noetrium_platform.research.execution.workflow.api.runtime_binding import (
    MethodRuntimePortInventory,
)

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.shared_host_pressure import (
    LocalSharedNetworkPressureObserver,
    LocalSharedStoragePressureObserver,
)
from noetrium_platform.infrastructure.resources.compute.providers import (
    LocalHostRuntimeObserver,
)
from noetrium_platform.composition.research_definition_authority import (
    ResearchDefinitionBindingAuthorityPort,
)
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import (
    PreparedResearchOSExecution,
    StrictResearchOSControl,
    prepare_research_os_execution,
)
from noetrium_platform.composition.research_os_checkpoint_store import (
    DirectoryResearchOSGraphCheckpointStore,
)
from noetrium_platform.composition.research_os_experiment import (
    ResearchOSExperimentClosurePort,
)
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentRuntimeComponents,
)
from noetrium_platform.composition.research_os_runtime import (
    CanonicalResearchOSNodeRuntime,
)
from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSArtifactValueAuthority,
)
from noetrium_platform.composition.research_os_values import ResearchOSValueRouter
from noetrium_platform.evidence.artifact.catalog.providers import (
    SQLiteArtifactRegistry,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.evidence.artifact.reference.providers import (
    SQLiteArtifactReferenceStore,
)
from noetrium_platform.composition.research_execution_content import (
    ResearchExecutionContentAuthorities,
)
from noetrium_platform.evidence.artifact.lineage.relation.providers import (
    SQLiteArtifactLineageStore,
)
from noetrium_platform.evidence.artifact.retention.providers import (
    SQLiteArtifactRetentionStore,
)
from noetrium_platform.foundation.portfolio.runtime import (
    SQLitePortfolioRevisionStore,
)
from noetrium_platform.product.research_os import (
    ResearchExecutionTarget,
    ResearchOS,
    ResearchPortfolio,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


@dataclass(slots=True)
class LocalResearchOSComposition:
    state_root: Path
    research_os: ResearchOS
    revision_store: SQLitePortfolioRevisionStore
    graph_store: SQLiteResearchGraphExecutionStore
    execution_pool: ResearchExecutionPool
    content: ResearchExecutionContentAuthorities
    _runtime: CanonicalResearchOSNodeRuntime
    _values: ResearchOSValueRouter
    _experiment_closures: ResearchOSExperimentClosurePort | None
    _definition_bindings: ResearchDefinitionBindingAuthorityPort | None
    _artifact_lineage: SQLiteArtifactLineageStore
    _artifact_retention: SQLiteArtifactRetentionStore
    _owns_content_authorities: bool
    _owns_execution_pool: bool
    _execution_pool_closed: bool = False
    _artifact_lineage_closed: bool = False
    _artifact_retention_closed: bool = False
    _content_closed: bool = False
    _closed: bool = False

    def prepare(
        self,
        target: ResearchExecutionTarget,
        portfolio: ResearchPortfolio,
    ) -> PreparedResearchOSExecution:
        """Run canonical whole-graph admission without creating a durable cut."""

        return prepare_research_os_execution(
            target,
            portfolio,
            self._runtime,
            self._values,
            experiment_closures=self._experiment_closures,
            definition_bindings=self._definition_bindings,
            artifact_lineage=self._artifact_lineage,
        )

    def handoff_content_ownership(
        self,
        target: "LocalResearchOSComposition",
    ) -> None:
        """Atomically move shared content authority ownership to a replacement composition."""
        if self._closed:
            raise RuntimeError("closed local Research OS cannot transfer content ownership")
        if not isinstance(target, LocalResearchOSComposition):
            raise TypeError("content ownership target must be LocalResearchOSComposition")
        if target._closed:
            raise RuntimeError("closed local Research OS cannot receive content ownership")
        if self.content is not target.content:
            raise ValueError("content ownership transfer requires identical authority object")
        if not self._owns_content_authorities or self._content_closed:
            raise RuntimeError("source local Research OS does not own live content authorities")
        if target._owns_content_authorities or target._content_closed:
            raise RuntimeError("target local Research OS already owns or closed content authorities")
        self._owns_content_authorities = False
        target._owns_content_authorities = True

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        if self._owns_execution_pool and not self._execution_pool_closed:
            try:
                self.execution_pool.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._execution_pool_closed = True
        if not self._artifact_lineage_closed:
            try:
                self._artifact_lineage.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._artifact_lineage_closed = True
        if not self._artifact_retention_closed:
            try:
                self._artifact_retention.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._artifact_retention_closed = True
        if self._owns_content_authorities and not self._content_closed:
            try:
                self.content.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._content_closed = True
        if errors:
            raise ExceptionGroup("local Research OS close failed", errors)
        self._closed = True


def compose_local_research_os(
    state_root: Path,
    *,
    experiment_closures: ResearchOSExperimentClosurePort | None = None,
    experiment_runtime_components: ResearchOSExperimentRuntimeComponents | None = None,
    definition_bindings: ResearchDefinitionBindingAuthorityPort | None = None,
    execution_pool: ResearchExecutionPool | None = None,
    method_runtime_inventory: MethodRuntimePortInventory | None = None,
    operation_dispatcher: OperationDispatchPort | None = None,
    method_observation: MethodObservationPort | None = None,
    content_authorities: ResearchExecutionContentAuthorities | None = None,
) -> LocalResearchOSComposition:
    """Compose the single durable local Research OS implementation.

    Experimentation is enabled only when both closure authority and owner-system
    runtime components are supplied. Callers may inject the platform's canonical
    ResearchExecutionPool; injected pools are borrowed and never closed here.
    Half-bound execution is rejected.
    """

    if not isinstance(state_root, Path):
        raise TypeError("local Research OS state_root must be pathlib.Path")
    root = state_root.expanduser().absolute()
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ValueError("local Research OS state_root must be a real directory")
    if (experiment_closures is None) != (experiment_runtime_components is None):
        raise ValueError(
            "local Research OS Experimentation requires both closure authority "
            "and runtime components"
        )
    if experiment_closures is not None and not isinstance(
        experiment_closures,
        ResearchOSExperimentClosurePort,
    ):
        raise TypeError(
            "local Research OS experiment_closures must satisfy typed port"
        )
    if (
        experiment_runtime_components is not None
        and type(experiment_runtime_components)
        is not ResearchOSExperimentRuntimeComponents
    ):
        raise TypeError(
            "local Research OS experiment_runtime_components must be typed"
        )
    if definition_bindings is not None and not isinstance(
        definition_bindings,
        ResearchDefinitionBindingAuthorityPort,
    ):
        raise TypeError(
            "local Research OS definition_bindings must satisfy typed port"
        )
    if method_runtime_inventory is not None and not isinstance(
        method_runtime_inventory,
        MethodRuntimePortInventory,
    ):
        raise TypeError(
            "local Research OS method_runtime_inventory must be MethodRuntimePortInventory"
        )

    root.mkdir(parents=True, exist_ok=True)
    owns_content_authorities = content_authorities is None
    if content_authorities is None:
        content = ResearchExecutionContentAuthorities(
            root,
            DirectoryArtifactBlobStore(root / "blobs"),
            SQLiteArtifactRegistry(root / "artifact-catalog.sqlite3"),
            SQLiteArtifactReferenceStore(root / "artifact-references.sqlite3"),
        )
    else:
        if type(content_authorities) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "local Research OS content_authorities must be "
                "ResearchExecutionContentAuthorities"
            )
        content = content_authorities
    blobs = content.blobs
    registry = content.artifacts
    revisions = SQLitePortfolioRevisionStore(root / "portfolio.sqlite3")
    graph = SQLiteResearchGraphExecutionStore(root / "graph.sqlite3")
    retention = SQLiteArtifactRetentionStore(
        root / "artifact-retention.sqlite3"
    )
    lineage = SQLiteArtifactLineageStore(root / "artifact-lineage.sqlite3")
    checkpoints = DirectoryResearchOSGraphCheckpointStore(
        root / "graph-checkpoints"
    )
    values = ResearchOSValueRouter(
        (ResearchOSArtifactValueAuthority(blobs, registry, retention),)
    )
    owns_execution_pool = execution_pool is None
    pool = (
        ResearchExecutionPool(
            host_runtime_observer=LocalHostRuntimeObserver(),
            storage_pressure_observer=LocalSharedStoragePressureObserver((root,)),
            network_pressure_observer=LocalSharedNetworkPressureObserver(),
        )
        if execution_pool is None
        else execution_pool
    )
    if not isinstance(pool, ResearchExecutionPool):
        raise TypeError("local Research OS execution_pool must be ResearchExecutionPool")

    try:
        if experiment_runtime_components is None:
            runtime = CanonicalResearchOSNodeRuntime(
                root / "machine-state",
                method_runtime_inventory=method_runtime_inventory,
                operation_dispatcher=operation_dispatcher,
                method_observation=method_observation,
                content_authorities=content,
            )
        else:
            experiment_bindings = experiment_runtime_components.bind()
            runtime = CanonicalResearchOSNodeRuntime(
                root / "machine-state",
                execution_pool=pool,
                experiment_bindings=experiment_bindings,
                method_runtime_inventory=method_runtime_inventory,
                operation_dispatcher=operation_dispatcher,
                method_observation=method_observation,
                content_authorities=content,
            )

        control = StrictResearchOSControl(
            graph,
            pool,
            runtime,
            values,
            experiment_closures=experiment_closures,
            definition_bindings=definition_bindings,
            artifact_lineage=lineage,
            checkpoints=checkpoints,
        )
        research_os = bind_portfolio_research_os(
            revisions,
            blobs,
            control=control,
        )
    except BaseException as primary:
        cleanup_errors: list[BaseException] = []
        if owns_execution_pool:
            try:
                pool.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            raise ExceptionGroup(
                "local Research OS composition failed with cleanup errors",
                [primary, *cleanup_errors],
            )
        raise

    return LocalResearchOSComposition(
        state_root=root,
        research_os=research_os,
        revision_store=revisions,
        graph_store=graph,
        execution_pool=pool,
        content=content,
        _runtime=runtime,
        _values=values,
        _experiment_closures=experiment_closures,
        _definition_bindings=definition_bindings,
        _artifact_lineage=lineage,
        _artifact_retention=retention,
        _owns_content_authorities=owns_content_authorities,
        _owns_execution_pool=owns_execution_pool,
    )


__all__ = [
    "LocalResearchOSComposition",
    "compose_local_research_os",
]
