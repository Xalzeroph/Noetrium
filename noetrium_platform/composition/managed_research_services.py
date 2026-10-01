from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.capabilities.environment.category.api import (
    EnvironmentCategoryCatalogPort,
)
from noetrium_platform.capabilities.environment.category.composition import (
    default_environment_category_catalog,
)
from noetrium_platform.evidence.data.fact.api import DurableFactStorePort
from noetrium_platform.evidence.data.fact.providers import SQLiteDurableFactStore
from noetrium_platform.evidence.data.query.api import ResearchResultQueryPort
from noetrium_platform.evidence.data.query.cross.composition import (
    compose_builtin_research_result_query,
)
from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    MachineSnapshotStorePort,
)
from noetrium_platform.foundation.portfolio.project.api import ProjectIdentity
from noetrium_platform.research.execution.machines import ResearchProgramHost
from noetrium_platform.research.experimentation.lifecycle.evaluation.composition import (
    bind_paired_evaluation_host,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadMethodCompilerPort,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskExecutionPort,
)
from noetrium_platform.research.experimentation.workload.composition import (
    bind_method_workload,
)

from .platform_meta import PlatformMetaAuthorities


@dataclass(frozen=True, slots=True)
class ManagedResearchServices:
    """Default research-service bus owned by one managed platform runtime.

    These are generic infrastructure authorities. Paper-private benchmark
    semantics still enter through the workload compiler/result-adapter seams.
    """

    facts: DurableFactStorePort
    research_results: ResearchResultQueryPort
    environment_categories: EnvironmentCategoryCatalogPort

    def bind_workload(
        self,
        *,
        compiler: WorkloadMethodCompilerPort,
        result_adapter: WorkloadMethodResultAdapterPort,
    ) -> WorkloadTaskExecutionPort:
        return bind_method_workload(
            compiler=compiler,
            result_adapter=result_adapter,
        )

    def paired_evaluation(
        self,
        *,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> ResearchProgramHost:
        return bind_paired_evaluation_host(
            journal=journal,
            snapshot_store=snapshot_store,
        )

    @staticmethod
    def project_identity(project_id: str, version: str) -> ProjectIdentity:
        return ProjectIdentity(project_id, version)


def build_managed_research_services(
    root: str | Path,
    *,
    meta: PlatformMetaAuthorities,
) -> ManagedResearchServices:
    if not isinstance(meta, PlatformMetaAuthorities):
        raise TypeError(
            "managed research services require PlatformMetaAuthorities"
        )
    resolved = Path(root).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    facts = SQLiteDurableFactStore(resolved / "durable-facts.sqlite")
    research_results = compose_builtin_research_result_query(
        datasets=meta.datasets,
        artifacts=meta.artifacts,
        scopes=meta.scopes,
    )
    return ManagedResearchServices(
        facts=facts,
        research_results=research_results,
        environment_categories=default_environment_category_catalog(),
    )


__all__ = [
    "ManagedResearchServices",
    "build_managed_research_services",
]
