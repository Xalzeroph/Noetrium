from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskContextPort
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchGraphNode:
    """Canonical scheduler node; domain payload remains owned by its executor."""

    node_id: str
    semantic_digest: str
    depends_on_node_ids: tuple[str, ...] = ()
    node_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.node_id, "research graph node_id")
        require_sha256(self.semantic_digest, "research graph node semantic_digest")
        if type(self.depends_on_node_ids) is not tuple:
            raise TypeError("research graph dependencies must be a tuple")
        dependencies = tuple(
            sorted(
                _text(value, "research graph dependency node_id")
                for value in self.depends_on_node_ids
            )
        )
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("research graph dependencies must be unique")
        if self.node_id in dependencies:
            raise ValueError("research graph node cannot depend on itself")
        object.__setattr__(self, "depends_on_node_ids", dependencies)
        object.__setattr__(
            self,
            "node_digest",
            canonical_digest(
                {
                    "node_id": self.node_id,
                    "semantic_digest": self.semantic_digest,
                    "depends_on_node_ids": dependencies,
                }
            ),
        )


def _validate_graph(nodes: tuple[ResearchGraphNode, ...]) -> None:
    by_id = {node.node_id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("research graph node identities must be unique")
    known = set(by_id)
    for node in nodes:
        unknown = tuple(
            dependency
            for dependency in node.depends_on_node_ids
            if dependency not in known
        )
        if unknown:
            raise ValueError(
                f"research graph node {node.node_id!r} depends on unknown nodes: {unknown}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            raise ValueError(f"research graph dependency cycle at node {node_id!r}")
        visiting.add(node_id)
        for dependency in by_id[node_id].depends_on_node_ids:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(by_id):
        visit(node_id)


@dataclass(frozen=True, slots=True)
class ResearchGraphPlan:
    graph_id: str
    research_revision_digest: str
    nodes: tuple[ResearchGraphNode, ...]
    graph_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.graph_id, "research graph_id")
        require_sha256(
            self.research_revision_digest,
            "research graph research_revision_digest",
        )
        if type(self.nodes) is not tuple or not self.nodes or any(
            type(node) is not ResearchGraphNode for node in self.nodes
        ):
            raise TypeError("research graph nodes must be a non-empty typed tuple")
        nodes = tuple(sorted(self.nodes, key=lambda node: node.node_id))
        _validate_graph(nodes)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(
            self,
            "graph_digest",
            canonical_digest(
                {
                    "graph_id": self.graph_id,
                    "research_revision_digest": self.research_revision_digest,
                    "nodes": tuple(node.node_digest for node in nodes),
                }
            ),
        )


class ResearchGraphNodeState(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ResearchGraphNodeResult:
    node_id: str
    semantic_digest: str
    state: ResearchGraphNodeState
    failure_type: str | None = None
    failure_message: str | None = None
    blocked_by_node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.node_id, "research graph result node_id")
        require_sha256(
            self.semantic_digest,
            "research graph result semantic_digest",
        )
        if not isinstance(self.state, ResearchGraphNodeState):
            raise TypeError("research graph result state must be typed")
        if type(self.blocked_by_node_ids) is not tuple:
            raise TypeError("research graph blockers must be a tuple")
        blockers = tuple(
            sorted(
                _text(value, "research graph blocker node_id")
                for value in self.blocked_by_node_ids
            )
        )
        if len(blockers) != len(set(blockers)):
            raise ValueError("research graph blockers must be unique")
        object.__setattr__(self, "blocked_by_node_ids", blockers)
        if self.state in {
            ResearchGraphNodeState.SUCCEEDED,
            ResearchGraphNodeState.CANCELLED,
        }:
            if self.failure_type is not None or self.failure_message is not None or blockers:
                raise ValueError("successful/cancelled research graph node cannot carry failure metadata")
        elif self.state is ResearchGraphNodeState.FAILED:
            if blockers:
                raise ValueError("failed research graph node cannot carry blockers")
            if not isinstance(self.failure_type, str) or not self.failure_type.strip():
                raise ValueError("failed research graph node requires failure_type")
            if not isinstance(self.failure_message, str) or not self.failure_message.strip():
                raise ValueError("failed research graph node requires failure_message")
        else:
            if self.failure_type is not None or self.failure_message is not None:
                raise ValueError("blocked research graph node cannot carry failure metadata")
            if not blockers:
                raise ValueError("blocked research graph node requires blockers")


@dataclass(frozen=True, slots=True)
class ResearchGraphExecutionReport:
    graph_id: str
    graph_digest: str
    research_revision_digest: str
    nodes: tuple[ResearchGraphNodeResult, ...]

    def __post_init__(self) -> None:
        _text(self.graph_id, "research graph report graph_id")
        require_sha256(self.graph_digest, "research graph report graph_digest")
        require_sha256(
            self.research_revision_digest,
            "research graph report research_revision_digest",
        )
        if type(self.nodes) is not tuple or not self.nodes or any(
            type(node) is not ResearchGraphNodeResult for node in self.nodes
        ):
            raise TypeError("research graph report nodes must be non-empty typed tuple")
        ids = tuple(node.node_id for node in self.nodes)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("research graph report nodes must be unique canonical order")

    @property
    def succeeded_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.nodes
            if node.state is ResearchGraphNodeState.SUCCEEDED
        )

    @property
    def failed_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.nodes
            if node.state is ResearchGraphNodeState.FAILED
        )

    @property
    def cancelled_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.nodes
            if node.state is ResearchGraphNodeState.CANCELLED
        )

    @property
    def blocked_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id
            for node in self.nodes
            if node.state is ResearchGraphNodeState.BLOCKED
        )


@runtime_checkable
class ResearchGraphNodeExecutorPort(Protocol):
    def execute(
        self,
        context: TaskContextPort,
        node: ResearchGraphNode,
        *,
        deadline: Deadline | None,
    ) -> None: ...


__all__ = [
    "ResearchGraphExecutionReport",
    "ResearchGraphNode",
    "ResearchGraphNodeExecutorPort",
    "ResearchGraphNodeResult",
    "ResearchGraphNodeState",
    "ResearchGraphPlan",
]
