from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.content.api import (
    ArtifactBlobRef,
    ArtifactBlobStorePort,
)
from noetrium_platform.foundation.portfolio.api import (
    PortfolioRevision,
    PortfolioRevisionStorePort,
)
from noetrium_platform.product.research_unit_codec import (
    RESEARCH_UNIT_MEDIA_TYPE,
    decode_research_unit,
    encode_research_unit,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, UnitRef
from noetrium_platform.product.research_traits import RELATION_FLOW
from noetrium_platform.product.research_unit import research_binding_digest, require_research_root
from noetrium_platform.product.research_control import (
    ResearchBranch,
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchControlRequest,
    ResearchExecutionTarget,
    ResearchGraphRevision,
    ResearchImpactState,
    ResearchGraphImpact,
    ResearchRevisionDiff,
    ResearchTag,
)


def _graph_state(portfolio):
    local = {}
    downstream = {}
    root = require_research_root(portfolio)
    stack = [(root, (root.unit_id,))]
    while stack:
        graph, path = stack.pop()
        for child in graph.members:
            ref = UnitRef(path + (child.unit_id,))
            local[ref] = research_binding_digest(portfolio, ref.path)
            downstream.setdefault(ref, set())
        for relation in graph.relations:
            if relation.relation_id != RELATION_FLOW:
                continue
            if relation.sources[0].child_id is None or relation.targets[0].child_id is None:
                continue
            source = UnitRef(path + (relation.sources[0].child_id,))
            target = UnitRef(path + (relation.targets[0].child_id,))
            downstream.setdefault(source, set()).add(target)
            downstream.setdefault(target, set())
        stack.extend(
            reversed(
                tuple(
                    (child, path + (child.unit_id,))
                    for child in graph.members
                )
            )
        )
    return local, downstream



def _reachable_downstream(roots, adjacency):
    seen = set()
    pending = list(roots)
    while pending:
        current = pending.pop()
        for target in adjacency.get(current, ()):
            if target in seen or target in roots:
                continue
            seen.add(target)
            pending.append(target)
    return seen


def diff_research_units(
    left,
    right,
    *,
    left_revision_digest: str,
    right_revision_digest: str,
):
    require_research_root(left)
    require_research_root(right)
    if left.unit_id != right.unit_id:
        raise ValueError("research diff Unit roots must share identity")
    left_local, _left_downstream = _graph_state(left)
    right_local, right_downstream = _graph_state(right)
    refs = set(left_local) | set(right_local)
    changed = {
        ref
        for ref in refs
        if ref in left_local and ref in right_local
        and left_local[ref] != right_local[ref]
    }
    new = set(right_local) - set(left_local)
    stale = _reachable_downstream(changed | new, right_downstream)
    same_revision = left_revision_digest == right_revision_digest
    impacts = []
    for ref in sorted(refs, key=lambda row: row.path):
        if ref not in left_local:
            state = ResearchImpactState.NEW
        elif ref not in right_local:
            state = ResearchImpactState.REMOVED
        elif ref in changed:
            state = ResearchImpactState.INVALIDATED
        elif ref in stale:
            state = ResearchImpactState.STALE
        else:
            state = ResearchImpactState.UNCHANGED if same_revision else ResearchImpactState.REUSABLE
        impacts.append(ResearchGraphImpact(ref.path, state))
    return ResearchRevisionDiff(
        left.unit_id,
        left_revision_digest,
        right_revision_digest,
        tuple(impacts),
    )


@runtime_checkable
class ResearchExecutionControlPort(Protocol):
    """Internal execution control over an already verified immutable portfolio."""

    def control(
        self,
        request: ResearchControlRequest,
        portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt: ...


@runtime_checkable
class ResearchRevisionMigrationPort(Protocol):
    """Internal bridge that binds live execution migration to durable revisions."""

    def active_revision_digest(self, execution_id: str) -> str: ...

    def migrate(
        self,
        request: ResearchControlRequest,
        source_revision: ResearchGraphRevision,
        source_portfolio: NoetriumUnit,
        target_portfolio: NoetriumUnit,
    ) -> ResearchControlReceipt: ...


class RootResearchControl:
    """Durable revision/diff/ref implementation over existing authorities."""

    def __init__(
        self,
        revisions: PortfolioRevisionStorePort,
        blobs: ArtifactBlobStorePort,
        *,
        control: ResearchExecutionControlPort | None = None,
    ) -> None:
        if not isinstance(revisions, PortfolioRevisionStorePort):
            raise TypeError("Research execution revisions must satisfy PortfolioRevisionStorePort")
        if not isinstance(blobs, ArtifactBlobStorePort):
            raise TypeError("Research execution blobs must satisfy ArtifactBlobStorePort")
        if control is not None and not isinstance(control, ResearchExecutionControlPort):
            raise TypeError("Research execution control must satisfy ResearchExecutionControlPort")
        self._revisions = revisions
        self._blobs = blobs
        self._control = control

    @staticmethod
    def _public_revision(value: PortfolioRevision) -> ResearchGraphRevision:
        revision = ResearchGraphRevision(
            value.subject_id,
            value.semantic_digest,
            value.parent_revision_digests,
            value.message,
        )
        if revision.revision_digest != value.revision_digest:
            raise RuntimeError("Research execution revision identity drifted from Portfolio")
        return revision

    def _stored_revision(self, revision: ResearchGraphRevision) -> PortfolioRevision:
        stored = self._revisions.revision(
            revision.portfolio_id,
            revision.revision_digest,
        )
        if self._public_revision(stored) != revision:
            raise ValueError("Research execution revision does not match durable Portfolio state")
        return stored

    def _load(self, revision: ResearchGraphRevision) -> NoetriumUnit:
        stored = self._stored_revision(revision)
        ref = ArtifactBlobRef(
            stored.payload_digest,
            stored.payload_size_bytes,
            RESEARCH_UNIT_MEDIA_TYPE,
        )
        portfolio = decode_research_unit(self._blobs.get(ref))
        if portfolio.unit_id != revision.portfolio_id:
            raise ValueError("Research execution portfolio identity drifted")
        if portfolio.unit_digest != revision.portfolio_digest:
            raise ValueError("Research execution portfolio digest drifted")
        return portfolio

    def commit(
        self,
        portfolio: NoetriumUnit,
        *,
        parents: tuple[ResearchGraphRevision, ...] = (),
        message: str = "",
    ) -> ResearchGraphRevision:
        require_research_root(portfolio)
        if type(parents) is not tuple or any(
            type(parent) is not ResearchGraphRevision for parent in parents
        ):
            raise TypeError("Research execution parents must be ResearchGraphRevision tuple")
        if any(parent.portfolio_id != portfolio.unit_id for parent in parents):
            raise ValueError("Research execution parents must share portfolio identity")
        raw = encode_research_unit(portfolio)
        ref = self._blobs.put(raw, media_type=RESEARCH_UNIT_MEDIA_TYPE)
        stored = self._revisions.commit(
            PortfolioRevision(
                portfolio.unit_id,
                ref.content_sha256,
                ref.size_bytes,
                tuple(parent.revision_digest for parent in parents),
                message,
                portfolio.unit_digest,
            )
        )
        return self._public_revision(stored)

    def diff(
        self,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
    ) -> ResearchRevisionDiff:
        if left.portfolio_id != right.portfolio_id:
            raise ValueError("Research execution diff revisions must share portfolio identity")
        return diff_research_units(
            self._load(left),
            self._load(right),
            left_revision_digest=left.revision_digest,
            right_revision_digest=right.revision_digest,
        )

    def branch(
        self,
        name: str,
        revision: ResearchGraphRevision,
        *,
        expected: ResearchGraphRevision | None = None,
    ) -> ResearchBranch:
        self._stored_revision(revision)
        if expected is not None:
            self._stored_revision(expected)
            if expected.portfolio_id != revision.portfolio_id:
                raise ValueError("Research execution branch revisions must share portfolio identity")
        row = self._revisions.move_branch(
            revision.portfolio_id,
            name,
            revision.revision_digest,
            expected_revision_digest=(
                None if expected is None else expected.revision_digest
            ),
        )
        return ResearchBranch(
            row.subject_id,
            row.name,
            row.revision_digest,
            row.generation,
        )

    def tag(self, name: str, revision: ResearchGraphRevision) -> ResearchTag:
        self._stored_revision(revision)
        row = self._revisions.tag(
            revision.portfolio_id,
            name,
            revision.revision_digest,
        )
        return ResearchTag(row.subject_id, row.name, row.revision_digest)

    def merge(
        self,
        portfolio: NoetriumUnit,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
        *,
        message: str = "",
    ) -> ResearchGraphRevision:
        if left.portfolio_id != portfolio.unit_id or right.portfolio_id != portfolio.unit_id:
            raise ValueError("Research execution merge parents must share resolved portfolio identity")
        self._stored_revision(left)
        self._stored_revision(right)
        return self.commit(
            portfolio,
            parents=(left, right),
            message=message,
        )

    def _dispatch_request(self, request: ResearchControlRequest) -> ResearchControlReceipt:
        if self._control is None:
            raise RuntimeError("research execution control is not bound")
        portfolio = self._load(request.target.revision)
        if portfolio.unit_digest != request.target.revision.portfolio_digest:
            raise ValueError("research control portfolio/revision digest drifted")
        if request.action is ResearchControlAction.MIGRATE:
            if not isinstance(self._control, ResearchRevisionMigrationPort):
                raise RuntimeError(
                    "research migration requires a revision-aware execution control port"
                )
            source_digest = self._control.active_revision_digest(
                request.target.execution_id
            )
            source_stored = self._revisions.revision(
                request.target.portfolio_id,
                source_digest,
            )
            source_revision = self._public_revision(source_stored)
            source_portfolio = self._load(source_revision)
            receipt = self._control.migrate(
                request,
                source_revision,
                source_portfolio,
                portfolio,
            )
        else:
            receipt = self._control.control(request, portfolio)
        if type(receipt) is not ResearchControlReceipt:
            raise TypeError("research control returned invalid receipt")
        if receipt.action is not request.action or receipt.target != request.target:
            raise ValueError("research control receipt identity drifted")
        return receipt


    def _dispatch(
        self,
        action: ResearchControlAction,
        target: ResearchExecutionTarget,
        payload=None,
    ) -> ResearchControlReceipt:
        if type(target) is not ResearchExecutionTarget:
            raise TypeError("research control requires ResearchExecutionTarget")
        return self._dispatch_request(
            ResearchControlRequest(action, target, payload)
        )

    def run(self, target, payload=None):
        return self._dispatch(ResearchControlAction.RUN, target, payload)

    def inspect(self, target, payload=None):
        return self._dispatch(ResearchControlAction.INSPECT, target, payload)

    def pause(self, target, payload=None):
        return self._dispatch(ResearchControlAction.PAUSE, target, payload)

    def drain(self, target, payload=None):
        return self._dispatch(ResearchControlAction.DRAIN, target, payload)

    def interrupt(self, target, payload=None):
        return self._dispatch(ResearchControlAction.INTERRUPT, target, payload)

    def resume(self, target, payload=None):
        return self._dispatch(ResearchControlAction.RESUME, target, payload)

    def retry(self, target, payload=None):
        return self._dispatch(ResearchControlAction.RETRY, target, payload)

    def cancel(self, target, payload=None):
        return self._dispatch(ResearchControlAction.CANCEL, target, payload)

    def checkpoint(self, target, payload=None):
        return self._dispatch(ResearchControlAction.CHECKPOINT, target, payload)

    def reconcile(self, target, payload=None):
        return self._dispatch(ResearchControlAction.RECONCILE, target, payload)

    def migrate(self, target, payload=None):
        return self._dispatch(ResearchControlAction.MIGRATE, target, payload)




__all__ = [
    "RootResearchControl",
    "RESEARCH_UNIT_MEDIA_TYPE",
    "ResearchExecutionControlPort",
    "ResearchRevisionMigrationPort",
    "decode_research_unit",
    "diff_research_units",
    "encode_research_unit",
]
