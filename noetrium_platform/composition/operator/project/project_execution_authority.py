from __future__ import annotations


from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
)
from noetrium_platform.composition.local_research_execution_authority import (
    build_local_research_execution_authority_materializer,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.product.research_unit import require_research_root


def materialize_project_execution_authorities(
    context: ResearchExecutionContext,
    portfolio: NoetriumUnit,
    project_manifests: tuple[NoetriumUnit, ...],
) -> ResearchExecutionAuthorities:
    """Resolve every project through the one platform-owned execution seam."""

    require_research_root(portfolio)
    materializer = build_local_research_execution_authority_materializer(
        context,
        project_manifests,
    )
    authorities = materializer.materialize(portfolio)
    if type(authorities) is not ResearchExecutionAuthorities:
        raise TypeError(
            "research execution authority materializer must return "
            "ResearchExecutionAuthorities"
        )
    return authorities


__all__ = ["materialize_project_execution_authorities"]
