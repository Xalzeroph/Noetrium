"""Canonical durable local composition for Product Research OS.

All local project/fleet entrypoints must reuse this wiring rather than creating
parallel store, value-authority, execution-pool or runtime compositions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import StrictResearchOSControl
from noetrium_platform.composition.research_os_experiment import (
    ResearchOSExperimentClosurePort,
    ResearchOSExperimentRuntimeBindingPort,
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
from noetrium_platform.product.research_os import ResearchOS
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

    def close(self) -> None:
        self.execution_pool.close()


def compose_local_research_os(
    state_root: Path,
    *,
    experiment_closures: ResearchOSExperimentClosurePort | None = None,
    experiment_bindings: ResearchOSExperimentRuntimeBindingPort | None = None,
) -> LocalResearchOSComposition:
    """Compose the single durable local Research OS implementation.

    Experimentation is enabled only when both closure authority and exact
    runtime-binding authority are supplied. Half-bound experiment execution is
    rejected at composition time.
    """

    if type(state_root) is not Path:
        raise TypeError("local Research OS state_root must be pathlib.Path")
    root = state_root.expanduser().absolute()
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ValueError("local Research OS state_root must be a real directory")
    if (experiment_closures is None) != (experiment_bindings is None):
        raise ValueError(
            "local Research OS Experimentation requires both closure and "
            "runtime-binding authorities"
        )
    if experiment_closures is not None and not isinstance(
        experiment_closures,
        ResearchOSExperimentClosurePort,
    ):
        raise TypeError(
            "local Research OS experiment_closures must satisfy typed port"
        )
    if experiment_bindings is not None and not isinstance(
        experiment_bindings,
        ResearchOSExperimentRuntimeBindingPort,
    ):
        raise TypeError(
            "local Research OS experiment_bindings must satisfy typed port"
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
    values = ResearchOSValueRouter(
        (ResearchOSImmutableValueAuthority(blobs, registry, retention),)
    )
    pool = ResearchExecutionPool()

    if experiment_bindings is None:
        runtime = CanonicalResearchOSNodeRuntime(root / "machine-state")
    else:
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
    )
    research_os = bind_portfolio_research_os(
        revisions,
        blobs,
        control=control,
    )
    return LocalResearchOSComposition(
        root,
        research_os,
        revisions,
        graph,
        pool,
    )


__all__ = [
    "LocalResearchOSComposition",
    "compose_local_research_os",
]
