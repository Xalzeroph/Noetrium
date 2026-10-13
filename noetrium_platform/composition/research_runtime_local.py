"""Canonical durable local composition for Product Research execution.

All local project/fleet entrypoints must reuse this wiring rather than creating
parallel store, value-authority, execution-pool or runtime compositions.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.research.execution.workflow.api import (
    MethodObservationPort,
    OperationDispatchPort,
    MethodRuntimePortInventory,
)
from noetrium_platform.evidence.observability.api import DiagnosticDegradationPort
from noetrium_platform.foundation.kernel.kernel.complexity import CostObservationSinkPort

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_symbol_authority import (
    ResearchSymbolBindingAuthorityPort,
)
from noetrium_platform.composition.research_control import RootResearchControl
from noetrium_platform.composition.research_execution import (
    PreparedResearchExecution,
    StrictResearchControl,
)
from noetrium_platform.composition.research_checkpoint_store import (
    DirectoryResearchGraphCheckpointStore,
)
from noetrium_platform.composition.research_experiment import (
    ResearchExperimentCompilationPort,
    ResearchExperimentRuntimeBindingPort,
)
from noetrium_platform.composition.research_runtime import (
    CanonicalResearchNodeRuntime,
)
from noetrium_platform.composition.research_value_authorities import (
    ResearchImmutableValueAuthority,
)
from noetrium_platform.composition.research_values import ResearchValueRouter
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
from noetrium_platform.infrastructure.lifecycle.runtime import ResourceLifetimeController
from noetrium_platform.infrastructure.reliability.failure.api import FailureMaterializationPort
from noetrium_platform.evidence.artifact.lineage.relation.providers import (
    SQLiteArtifactLineageStore,
)
from noetrium_platform.evidence.artifact.retention.providers import (
    SQLiteArtifactRetentionStore,
)
from noetrium_platform.foundation.portfolio.runtime import (
    SQLitePortfolioRevisionStore,
)
from noetrium_platform.product.research_control import (
    ResearchExecutionTarget,
    BoundResearchControl,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


@dataclass(slots=True)
class LocalResearchComposition:
    state_root: Path
    control: BoundResearchControl
    revision_store: SQLitePortfolioRevisionStore
    graph_store: SQLiteResearchGraphExecutionStore
    execution_pool: ResearchExecutionPool | None
    content: ResearchExecutionContentAuthorities
    _runtime: CanonicalResearchNodeRuntime
    _execution_control: StrictResearchControl
    _values: ResearchValueRouter
    _experiment_compilation: ResearchExperimentCompilationPort | None
    _symbol_bindings: ResearchSymbolBindingAuthorityPort | None
    _artifact_lineage: SQLiteArtifactLineageStore
    _artifact_retention: SQLiteArtifactRetentionStore
    _owns_content_authorities: bool
    _owns_execution_pool: bool
    _execution_pool_closed: bool = False
    _graph_store_closed: bool = False
    _artifact_lineage_closed: bool = False
    _artifact_retention_closed: bool = False
    _content_closed: bool = False
    _closed: bool = False

    def prepare(
        self,
        target: ResearchExecutionTarget,
        portfolio: NoetriumUnit,
    ) -> PreparedResearchExecution:
        """Run canonical whole-graph admission without creating a durable cut."""

        return self._execution_control.prepare(
            target,
            portfolio,
        )

    def handoff_content_ownership(
        self,
        target: "LocalResearchComposition",
    ) -> None:
        """Atomically move shared content authority ownership to a replacement composition."""
        if self._closed:
            raise RuntimeError("closed local Research execution cannot transfer content ownership")
        if not isinstance(target, LocalResearchComposition):
            raise TypeError("content ownership target must be LocalResearchComposition")
        if target._closed:
            raise RuntimeError("closed local Research execution cannot receive content ownership")
        if self.content is not target.content:
            raise ValueError("content ownership transfer requires identical authority object")
        if not self._owns_content_authorities or self._content_closed:
            raise RuntimeError("source local Research execution does not own live content authorities")
        if target._owns_content_authorities or target._content_closed:
            raise RuntimeError("target local Research execution already owns or closed content authorities")
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
        if not self._graph_store_closed:
            try:
                self.graph_store.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                self._graph_store_closed = True
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
            raise ExceptionGroup("local Research execution close failed", errors)
        self._closed = True


def compose_local_research_runtime(
    state_root: Path,
    *,
    experiment_compilation: ResearchExperimentCompilationPort | None = None,
    experiment_runtime_binding: ResearchExperimentRuntimeBindingPort | None = None,
    symbol_bindings: ResearchSymbolBindingAuthorityPort | None = None,
    execution_pool: ResearchExecutionPool | None = None,
    method_runtime_inventory: MethodRuntimePortInventory | None = None,
    operation_dispatcher: OperationDispatchPort | None = None,
    method_observation: MethodObservationPort | None = None,
    content_authorities: ResearchExecutionContentAuthorities | None = None,
    cost_observation: CostObservationSinkPort | None = None,
    diagnostic_degradation: DiagnosticDegradationPort | None = None,
    failure_materializer: FailureMaterializationPort | None = None,
    lifetime_controller: ResourceLifetimeController | None = None,
    causal_event_refs: tuple[str, ...] = (),
) -> LocalResearchComposition:
    """Compose the single durable local Research execution implementation.

    Experimentation is enabled only when both closure authority and owner-system
    runtime components are supplied. Callers may inject the platform's canonical
    ResearchExecutionPool; injected pools are borrowed and never closed here.
    Half-bound execution is rejected.
    """

    if not isinstance(state_root, Path):
        raise TypeError("local Research execution state_root must be pathlib.Path")
    root = state_root.expanduser().absolute()
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ValueError("local Research execution state_root must be a real directory")
    if (experiment_compilation is None) != (experiment_runtime_binding is None):
        raise ValueError(
            "local Research execution Experimentation requires both closure authority "
            "and runtime binding authority"
        )
    if experiment_compilation is not None and not isinstance(
        experiment_compilation,
        ResearchExperimentCompilationPort,
    ):
        raise TypeError(
            "local Research execution experiment_compilation must satisfy typed port"
        )
    if (
        experiment_runtime_binding is not None
        and not isinstance(
            experiment_runtime_binding,
            ResearchExperimentRuntimeBindingPort,
        )
    ):
        raise TypeError(
            "local Research execution experiment_runtime_binding must satisfy "
            "ResearchExperimentRuntimeBindingPort"
        )
    if symbol_bindings is not None and not isinstance(
        symbol_bindings,
        ResearchSymbolBindingAuthorityPort,
    ):
        raise TypeError(
            "local Research execution symbol_bindings must satisfy typed port"
        )
    if method_runtime_inventory is not None and not isinstance(
        method_runtime_inventory,
        MethodRuntimePortInventory,
    ):
        raise TypeError(
            "local Research execution method_runtime_inventory must be MethodRuntimePortInventory"
        )

    root.mkdir(parents=True, exist_ok=True)
    owns_content_authorities = content_authorities is None
    if content_authorities is None:
        content = ResearchExecutionContentAuthorities(
            root,
            DirectoryArtifactBlobStore(root / "blobs"),
            SQLiteArtifactRegistry(
                SQLiteArtifactRegistry.default_path(root)
            ),
            SQLiteArtifactReferenceStore(root / "artifact-references.sqlite3"),
        )
    else:
        if type(content_authorities) is not ResearchExecutionContentAuthorities:
            raise TypeError(
                "local Research execution content_authorities must be "
                "ResearchExecutionContentAuthorities"
            )
        content = content_authorities
    blobs = content.blobs
    registry = content.artifacts
    revisions = SQLitePortfolioRevisionStore(root / "portfolio.sqlite3")
    graph = SQLiteResearchGraphExecutionStore(
        SQLiteResearchGraphExecutionStore.default_path(root)
    )
    retention = SQLiteArtifactRetentionStore(
        root / "artifact-retention.sqlite3"
    )
    lineage = SQLiteArtifactLineageStore(root / "artifact-lineage.sqlite3")
    checkpoints = DirectoryResearchGraphCheckpointStore(
        root / "graph-checkpoints"
    )
    values = ResearchValueRouter(
        (ResearchImmutableValueAuthority(blobs, registry, retention),)
    )
    pool = execution_pool
    if pool is not None and not isinstance(pool, ResearchExecutionPool):
        raise TypeError(
            "local Research execution execution_pool must be ResearchExecutionPool or None"
        )

    try:
        if experiment_runtime_binding is None:
            runtime = CanonicalResearchNodeRuntime(
                root / "machine-state",
                method_runtime_inventory=method_runtime_inventory,
                operation_dispatcher=operation_dispatcher,
                method_observation=method_observation,
                content_authorities=content,
            )
        else:
            runtime = CanonicalResearchNodeRuntime(
                root / "machine-state",
                execution_pool=pool,
                experiment_bindings=experiment_runtime_binding,
                method_runtime_inventory=method_runtime_inventory,
                operation_dispatcher=operation_dispatcher,
                method_observation=method_observation,
                content_authorities=content,
            )

        control = StrictResearchControl(
            graph,
            pool,
            runtime,
            values,
            experiment_compilation=experiment_compilation,
            symbol_bindings=symbol_bindings,
            artifact_lineage=lineage,
            checkpoints=checkpoints,
            cost_observation=cost_observation,
            diagnostic_degradation=diagnostic_degradation,
            failure_materializer=failure_materializer,
            lifetime_controller=lifetime_controller,
            causal_event_refs=causal_event_refs,
        )
        root_control = RootResearchControl(
            revisions,
            blobs,
            control=control,
        )
    except BaseException as primary:
        cleanup_errors: list[BaseException] = []
        if cleanup_errors:
            raise ExceptionGroup(
                "local Research execution composition failed with cleanup errors",
                [primary, *cleanup_errors],
            )
        raise

    return LocalResearchComposition(
        state_root=root,
        control=root_control,
        revision_store=revisions,
        graph_store=graph,
        execution_pool=pool,
        content=content,
        _runtime=runtime,
        _execution_control=control,
        _values=values,
        _experiment_compilation=experiment_compilation,
        _symbol_bindings=symbol_bindings,
        _artifact_lineage=lineage,
        _artifact_retention=retention,
        _owns_content_authorities=owns_content_authorities,
        _owns_execution_pool=False,
    )


__all__ = [
    "LocalResearchComposition",
    "compose_local_research_runtime",
]
