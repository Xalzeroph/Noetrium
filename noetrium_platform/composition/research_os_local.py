"""Canonical durable local composition for Product Research OS.

All local project/fleet entrypoints must reuse this wiring rather than creating
parallel store, value-authority, execution-pool or runtime compositions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
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
from noetrium_platform.composition.research_os_experiment_artifacts import (
    DirectoryResearchOSExperimentArtifactStoreFactory,
)
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentRuntimeComponents,
)
from noetrium_platform.composition.research_os_runtime import (
    CanonicalResearchOSNodeRuntime,
)
from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSImmutableValueAuthority,
)
from noetrium_platform.composition.research_os_values import ResearchOSValueRouter
from noetrium_platform.evidence.artifact.catalog.providers import (
    SQLiteArtifactRegistry,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
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
    _runtime: CanonicalResearchOSNodeRuntime
    _values: ResearchOSValueRouter
    _experiment_closures: ResearchOSExperimentClosurePort | None
    _artifact_lineage: SQLiteArtifactLineageStore
    _artifact_group: TaskGroupPort | None
    _owns_execution_pool: bool
    _artifact_group_closed: bool = False
    _execution_pool_closed: bool = False
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
            artifact_lineage=self._artifact_lineage,
        )

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        if self._artifact_group is not None and not self._artifact_group_closed:
            try:
                self.execution_pool.close_experiment_group(
                    self._artifact_group,
                    cancel_pending=True,
                )
            except BaseException as exc:
                errors.append(exc)
            else:
                self._artifact_group_closed = True
        if (
            self._owns_execution_pool
            and not self._execution_pool_closed
            and (self._artifact_group is None or self._artifact_group_closed)
        ):
            try:
                self.execution_pool.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._execution_pool_closed = True
        if errors:
            raise ExceptionGroup("local Research OS close failed", errors)
        self._closed = True


def compose_local_research_os(
    state_root: Path,
    *,
    experiment_closures: ResearchOSExperimentClosurePort | None = None,
    experiment_runtime_components: ResearchOSExperimentRuntimeComponents | None = None,
    execution_pool: ResearchExecutionPool | None = None,
) -> LocalResearchOSComposition:
    """Compose the single durable local Research OS implementation.

    Experimentation is enabled only when both closure authority and owner-system
    runtime components are supplied. Callers may inject the platform's canonical
    ResearchExecutionPool; injected pools are borrowed and never closed here.
    Half-bound execution is rejected.
    """

    if type(state_root) is not Path:
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

    root.mkdir(parents=True, exist_ok=True)
    blobs = DirectoryArtifactBlobStore(root / "blobs")
    revisions = SQLitePortfolioRevisionStore(root / "portfolio.sqlite3")
    graph = SQLiteResearchGraphExecutionStore(root / "graph.sqlite3")
    registry = SQLiteArtifactRegistry(root / "artifact-catalog.sqlite3")
    retention = SQLiteArtifactRetentionStore(
        root / "artifact-retention.sqlite3"
    )
    lineage = SQLiteArtifactLineageStore(root / "artifact-lineage.sqlite3")
    checkpoints = DirectoryResearchOSGraphCheckpointStore(
        root / "graph-checkpoints"
    )
    values = ResearchOSValueRouter(
        (ResearchOSImmutableValueAuthority(blobs, registry, retention),)
    )
    owns_execution_pool = execution_pool is None
    pool = ResearchExecutionPool() if execution_pool is None else execution_pool
    if not isinstance(pool, ResearchExecutionPool):
        raise TypeError("local Research OS execution_pool must be ResearchExecutionPool")

    artifact_group: TaskGroupPort | None = None
    try:
        if experiment_runtime_components is None:
            runtime = CanonicalResearchOSNodeRuntime(root / "machine-state")
        else:
            artifact_group = pool.open_experiment_group(
                f"research-os-experiment-artifacts:{uuid4().hex}",
                resource_id="research-os-experiment-artifacts",
            )
            artifact_factory = DirectoryResearchOSExperimentArtifactStoreFactory(
                root / "run-artifacts",
                task_group=artifact_group,
            )
            experiment_bindings = experiment_runtime_components.bind(
                artifact_factory
            )
            runtime = CanonicalResearchOSNodeRuntime(
                root / "machine-state",
                execution_pool=pool,
                experiment_bindings=experiment_bindings,
            )

        control = StrictResearchOSControl(
            graph,
            pool,
            runtime,
            values,
            experiment_closures=experiment_closures,
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
        if artifact_group is not None:
            try:
                pool.close_experiment_group(
                    artifact_group,
                    cancel_pending=True,
                )
            except BaseException as exc:
                cleanup_errors.append(exc)
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
        root,
        research_os,
        revisions,
        graph,
        pool,
        runtime,
        values,
        experiment_closures,
        lineage,
        artifact_group,
        owns_execution_pool,
    )


__all__ = [
    "LocalResearchOSComposition",
    "compose_local_research_os",
]
