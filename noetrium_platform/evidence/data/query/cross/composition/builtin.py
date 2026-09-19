from __future__ import annotations

from noetrium_platform.evidence.artifact.catalog.api import ArtifactRegistryPort
from noetrium_platform.evidence.data.dataset.api import DatasetRegistryPort
from noetrium_platform.evidence.data.query.api import ResearchResultQueryPort
from noetrium_platform.evidence.data.query.cross.providers import DatasetResearchResultSource
from noetrium_platform.foundation.scope.api import ScopeRegistryPort

from .artifact import ArtifactCatalogResearchResultSource
from .default import compose


def compose_builtin_research_result_query(
    *,
    datasets: DatasetRegistryPort,
    artifacts: ArtifactRegistryPort,
    scopes: ScopeRegistryPort,
) -> ResearchResultQueryPort:
    """Wire the built-in portable Dataset and Artifact read projections."""

    return compose(
        (
            DatasetResearchResultSource(datasets, scopes),
            ArtifactCatalogResearchResultSource(artifacts, scopes),
        )
    )


__all__ = ["compose_builtin_research_result_query"]
