from __future__ import annotations

from noetrium_platform.evidence.data.query.api import ResearchResultSourcePort
from noetrium_platform.evidence.data.query.cross.runtime import CrossAuthorityResearchResultQuery


def compose(
    sources: tuple[ResearchResultSourcePort, ...],
) -> CrossAuthorityResearchResultQuery:
    """Compose only read-side producer projections; no handler or mutable query state exists."""

    return CrossAuthorityResearchResultQuery(sources)


__all__ = ["compose"]
