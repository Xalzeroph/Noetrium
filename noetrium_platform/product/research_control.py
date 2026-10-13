"""Research control-plane contracts over immutable NoetriumUnit revisions."""
from __future__ import annotations


from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, UnitRef


@dataclass(frozen=True, slots=True)
class ResearchGraphRevision:
    portfolio_id: str
    portfolio_digest: str
    parent_revision_digests: tuple[str, ...] = ()
    message: str = ""
    revision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.portfolio_id) is not str or not self.portfolio_id.strip():
            raise ValueError("research revision portfolio_id must be non-empty")
        require_sha256(self.portfolio_digest, "research revision portfolio_digest")
        parents = self.parent_revision_digests
        if type(parents) is not tuple:
            raise TypeError("research revision parents must be a tuple")
        for parent in parents:
            require_sha256(parent, "research parent revision")
        if len(parents) != len(set(parents)):
            raise ValueError("research revision parents must not contain duplicates")
        if type(self.message) is not str:
            raise TypeError("research revision message must be text")
        object.__setattr__(
            self,
            "revision_digest",
            canonical_digest(
                {
                    "subject_id": self.portfolio_id,
                    "semantic_digest": self.portfolio_digest,
                    "parents": parents,
                    "message": self.message,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchBranch:
    portfolio_id: str
    name: str
    revision_digest: str
    generation: int

    def __post_init__(self) -> None:
        if type(self.portfolio_id) is not str or not self.portfolio_id.strip():
            raise ValueError("research branch portfolio_id is required")
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("research branch name is required")
        require_sha256(self.revision_digest, "research branch revision")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("research branch generation must be positive")


@dataclass(frozen=True, slots=True)
class ResearchTag:
    portfolio_id: str
    name: str
    revision_digest: str

    def __post_init__(self) -> None:
        if type(self.portfolio_id) is not str or not self.portfolio_id.strip():
            raise ValueError("research tag portfolio_id is required")
        if type(self.name) is not str or not self.name.strip():
            raise ValueError("research tag name is required")
        require_sha256(self.revision_digest, "research tag revision")


class ResearchImpactState(StrEnum):
    UNCHANGED = "unchanged"
    REUSABLE = "reusable"
    NEW = "new"
    STALE = "stale"
    INVALIDATED = "invalidated"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class ResearchGraphImpact:
    path: tuple[str, ...]
    state: ResearchImpactState

    def __post_init__(self) -> None:
        ref = UnitRef(self.path)
        object.__setattr__(self, "path", ref.path)
        if not isinstance(self.state, ResearchImpactState):
            raise TypeError("research impact state must be typed")


@dataclass(frozen=True, slots=True)
class ResearchRevisionDiff:
    portfolio_id: str
    left_revision_digest: str
    right_revision_digest: str
    impacts: tuple[ResearchGraphImpact, ...]

    def __post_init__(self) -> None:
        if type(self.portfolio_id) is not str or not self.portfolio_id.strip():
            raise ValueError("research diff portfolio_id is required")
        require_sha256(self.left_revision_digest, "left research revision")
        require_sha256(self.right_revision_digest, "right research revision")
        if type(self.impacts) is not tuple or any(
            type(row) is not ResearchGraphImpact for row in self.impacts
        ):
            raise TypeError("research revision impacts must be typed tuple")


@dataclass(frozen=True, slots=True)
class ResearchExecutionTarget:
    """Stable execution identity bound to one immutable research revision."""

    execution_id: str
    revision: ResearchGraphRevision
    graph: UnitRef | None = None
    target_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.execution_id) is not str or not self.execution_id.strip():
            raise ValueError("research execution_id must be non-empty")
        if type(self.revision) is not ResearchGraphRevision:
            raise TypeError("research execution target requires ResearchGraphRevision")
        if self.graph is not None and type(self.graph) is not UnitRef:
            raise TypeError("research execution graph must be UnitRef")
        object.__setattr__(
            self,
            "target_digest",
            canonical_digest(
                {
                    "execution_id": self.execution_id,
                    "portfolio_id": self.revision.portfolio_id,
                    "research_revision_digest": self.revision.revision_digest,
                    "graph": None if self.graph is None else self.graph.path,
                }
            ),
        )

    @property
    def portfolio_id(self) -> str:
        return self.revision.portfolio_id

    @property
    def research_revision_digest(self) -> str:
        return self.revision.revision_digest

    def for_graph(self, path: tuple[str, ...]) -> "ResearchExecutionTarget":
        return ResearchExecutionTarget(
            self.execution_id,
            self.revision,
            UnitRef(path),
        )


class ResearchControlAction(StrEnum):
    RUN = "run"
    INSPECT = "inspect"
    PAUSE = "pause"
    DRAIN = "drain"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    RETRY = "retry"
    CANCEL = "cancel"
    CHECKPOINT = "checkpoint"
    RECONCILE = "reconcile"
    MIGRATE = "migrate"


@dataclass(frozen=True, slots=True)
class ResearchControlRequest:
    action: ResearchControlAction
    target: ResearchExecutionTarget
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ResearchControlAction):
            raise TypeError("research control action must be typed")
        if type(self.target) is not ResearchExecutionTarget:
            raise TypeError("research control target requires ResearchExecutionTarget")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class ResearchControlReceipt:
    action: ResearchControlAction
    target: ResearchExecutionTarget
    state: str
    control_revision_digest: str
    payload: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, ResearchControlAction):
            raise TypeError("research control receipt action must be typed")
        if type(self.target) is not ResearchExecutionTarget:
            raise TypeError("research control receipt target must be typed")
        if type(self.state) is not str or not self.state.strip():
            raise ValueError("research control receipt state must be non-empty")
        require_sha256(
            self.control_revision_digest,
            "research control state revision",
        )
        object.__setattr__(self, "state", self.state.strip())
        object.__setattr__(self, "payload", freeze_json(self.payload))




@runtime_checkable
class BoundResearchControl(Protocol):
    def commit(
        self,
        portfolio: NoetriumUnit,
        *,
        parents: tuple[ResearchGraphRevision, ...] = (),
        message: str = "",
    ) -> ResearchGraphRevision: ...

    def diff(
        self,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
    ) -> ResearchRevisionDiff: ...

    def branch(
        self,
        name: str,
        revision: ResearchGraphRevision,
        *,
        expected: ResearchGraphRevision | None = None,
    ) -> ResearchBranch: ...

    def tag(
        self,
        name: str,
        revision: ResearchGraphRevision,
    ) -> ResearchTag: ...

    def merge(
        self,
        portfolio: NoetriumUnit,
        left: ResearchGraphRevision,
        right: ResearchGraphRevision,
        *,
        message: str = "",
    ) -> ResearchGraphRevision: ...

    def run(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def inspect(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def pause(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def drain(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def interrupt(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def resume(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def retry(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def cancel(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def checkpoint(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def reconcile(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...
    def migrate(self, target: ResearchExecutionTarget, payload: JsonInput = None) -> ResearchControlReceipt: ...






__all__ = [
    "ResearchBranch",
    "ResearchControlAction",
    "ResearchControlReceipt",
    "ResearchControlRequest",
    "ResearchExecutionTarget",
    "ResearchGraphRevision",
    "ResearchImpactState",
    "ResearchGraphImpact",
    "BoundResearchControl",
    "ResearchRevisionDiff",
    "ResearchTag",
]
