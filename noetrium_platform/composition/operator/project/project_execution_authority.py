from __future__ import annotations


from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
)
from noetrium_platform.composition.local_research_execution_authority import (
    build_local_research_execution_authority_materializer,
)
from noetrium_platform.product.research_os import ResearchPortfolio


def materialize_project_execution_authorities(
    context: ResearchExecutionContext,
    portfolio: ResearchPortfolio,
    project_manifest,
) -> ResearchExecutionAuthorities:
    """Resolve every project through the one platform-owned execution seam."""

    if type(portfolio) is not ResearchPortfolio:
        raise TypeError(
            "project authority materialization requires ResearchPortfolio"
        )
    materializer = build_local_research_execution_authority_materializer(
        context,
        project_manifest,
    )
    authorities = materializer.materialize(portfolio)
    if type(authorities) is not ResearchExecutionAuthorities:
        raise TypeError(
            "research execution authority materializer must return "
            "ResearchExecutionAuthorities"
        )
    return authorities


__all__ = ["materialize_project_execution_authorities"]
