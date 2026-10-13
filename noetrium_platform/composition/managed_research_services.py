from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.capabilities.environment.category.api import (
    EnvironmentCategoryCatalogPort,
)
from noetrium_platform.capabilities.environment.category.composition import (
    default_environment_category_catalog,
)
from noetrium_platform.evidence.data.query.api import ResearchResultQueryPort
from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    MachineSnapshotStorePort,
)

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

from .method_runtime import (
    METHOD_PROGRAM_EXECUTOR_DIGEST,
    execute_standard_method_program,
)
from .platform_meta import PlatformMetaAuthorities


@dataclass(frozen=True, slots=True)
class ManagedResearchServices:
    """Default research-service bus owned by one managed platform runtime.

    These are generic infrastructure authorities. Paper-private benchmark
    semantics still enter through the workload compiler/result-adapter seams.
    """

    research_results: ResearchResultQueryPort
    environment_categories: EnvironmentCategoryCatalogPort

    def bind_workload(
        self,
        *,
        compiler: WorkloadMethodCompilerPort,
        result_adapter: WorkloadMethodResultAdapterPort,
    ) -> WorkloadTaskExecutionPort:
        return bind_method_workload(
            execute_method=execute_standard_method_program,
            executor_digest=METHOD_PROGRAM_EXECUTOR_DIGEST,
            compiler=compiler,
            result_adapter=result_adapter,
        )

    def paired_evaluation(
        self,
        *,
        journal: MachineJournalPort,
        snapshot_store: MachineSnapshotStorePort | None = None,
    ) -> BoundExecutableUnit:
        return bind_paired_evaluation_host(
            journal=journal,
            snapshot_store=snapshot_store,
        )

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
    # ResearchResultQuery is already composed and owned by PlatformMeta.
    # Borrow the same authority; never construct a duplicate projection during
    # each runtime bootstrap.
    return ManagedResearchServices(
        research_results=meta.research_results,
        environment_categories=default_environment_category_catalog(),
    )


__all__ = [
    "ManagedResearchServices",
    "build_managed_research_services",
]
