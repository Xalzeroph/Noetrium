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
    def __init__(self) -> None:
        self._branches: dict[tuple[str, str], ResearchBranch] = {}
        self._tags: dict[tuple[str, str], ResearchTag] = {}

    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[ResearchGraphRevision, ...],
        message: str,
    ) -> ResearchGraphRevision:
        return ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            tuple(parent.revision_digest for parent in parents),
            message,
        )

    def diff(
        self,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
    ) -> ResearchRevisionDiff:
        return ResearchRevisionDiff(
            left.portfolio_id,
            left.revision_digest,
            right.revision_digest,
            (),
        )

    def branch(
        self,
        name: str,
        revision: ResearchGraphRevision,
        *,
        expected: ResearchGraphRevision | None,
    ) -> ResearchBranch:
        key = (revision.portfolio_id, name)
        current = self._branches.get(key)
        if current is None:
            if expected is not None:
                raise ValueError("reference branch does not yet exist")
            result = ResearchBranch(
                revision.portfolio_id,
                name,
                revision.revision_digest,
                1,
            )
            self._branches[key] = result
            return result
        if expected is None or current.revision_digest != expected.revision_digest:
            raise ValueError("reference branch expected revision mismatch")
        if current.revision_digest == revision.revision_digest:
            return current
        result = ResearchBranch(
            revision.portfolio_id,
            name,
            revision.revision_digest,
            current.generation + 1,
        )
        self._branches[key] = result
        return result

    def tag(self, name: str, revision: ResearchGraphRevision) -> ResearchTag:
        key = (revision.portfolio_id, name)
        candidate = ResearchTag(
            revision.portfolio_id,
            name,
            revision.revision_digest,
        )
        current = self._tags.get(key)
        if current is not None and current != candidate:
            raise ValueError("reference tag is immutable")
        self._tags[key] = candidate
        return candidate

    def merge(
        self,
        portfolio: ResearchPortfolio,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
        *,
        message: str,
    ) -> ResearchGraphRevision:
        return ResearchGraphRevision(
            portfolio.portfolio_id,
            portfolio.portfolio_digest,
            (left.revision_digest, right.revision_digest),
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
