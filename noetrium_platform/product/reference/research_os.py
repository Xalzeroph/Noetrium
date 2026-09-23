"""Deterministic Research OS conformance port used only by release qualification."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.product.research_os import (
    ResearchBranch,
    ResearchControlReceipt,
    ResearchControlRequest,
    ResearchGraphRevision,
    ResearchPortfolio,
    ResearchRevisionDiff,
    ResearchTag,
)


class ReferenceResearchOSPort:
    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[str, ...],
        message: str,
    ) -> ResearchGraphRevision:
        return ResearchGraphRevision(
            portfolio.portfolio_digest,
            parents,
            message,
        )

    def diff(
        self,
        left_revision_digest: str,
        right_revision_digest: str,
    ) -> ResearchRevisionDiff:
        return ResearchRevisionDiff(
            left_revision_digest,
            right_revision_digest,
            (),
        )

    def branch(self, name: str, revision_digest: str) -> ResearchBranch:
        return ResearchBranch(name, revision_digest)

    def tag(self, name: str, revision_digest: str) -> ResearchTag:
        return ResearchTag(name, revision_digest)

    def merge(
        self,
        left_revision_digest: str,
        right_revision_digest: str,
        *,
        message: str,
    ) -> ResearchGraphRevision:
        portfolio_digest = canonical_digest(
            {
                "left": left_revision_digest,
                "right": right_revision_digest,
            }
        )
        return ResearchGraphRevision(
            portfolio_digest,
            (left_revision_digest, right_revision_digest),
            message,
        )

    def control(self, request: ResearchControlRequest) -> ResearchControlReceipt:
        return ResearchControlReceipt(
            request.action,
            request.target,
            "accepted",
            canonical_digest(
                {
                    "action": request.action.value,
                    "target": request.target,
                }
            ),
            request.payload,
        )


__all__ = ["ReferenceResearchOSPort"]
