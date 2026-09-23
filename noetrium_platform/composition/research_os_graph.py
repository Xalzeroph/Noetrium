from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.product.research_os import (
    ResearchDefinition,
    ResearchGraphRevision,
    ResearchInputBinding,
    ResearchNode,
    ResearchNodeRef,
    ResearchPortfolio,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphNode,
    ResearchGraphExecutionStorePort,
    ResearchGraphNodeExecutorPort,
    ResearchGraphPlan,
)
from noetrium_platform.research.execution.policy.api import ExecutionPriority


def _graph_node_id(ref: ResearchNodeRef) -> str:
    # Public identifiers cannot contain ':', so this is reversible and collision-free.
    return f"{ref.program_id}::{ref.node_id}"


@dataclass(frozen=True, slots=True)
class CompiledResearchOSInputEdge:
    """Lossless normalized typed edge used by lowering and runtime composition."""

    upstream: ResearchNodeRef
    bindings: tuple[ResearchInputBinding, ...]
    dependency_digest: str

    def __post_init__(self) -> None:
        if type(self.upstream) is not ResearchNodeRef:
            raise TypeError("compiled Research OS edge upstream must be ResearchNodeRef")
        if type(self.bindings) is not tuple or any(
            type(value) is not ResearchInputBinding for value in self.bindings
        ):
            raise TypeError("compiled Research OS edge bindings must be typed")
        bindings = tuple(sorted(self.bindings, key=lambda value: value.input_name))
        names = tuple(value.input_name for value in bindings)
        if len(names) != len(set(names)):
            raise ValueError("compiled Research OS edge input names must be unique")
        require_sha256(
            self.dependency_digest,
            "compiled Research OS dependency_digest",
        )
        object.__setattr__(self, "bindings", bindings)


@dataclass(frozen=True, slots=True)
class CompiledResearchOSGraphNode:
    graph_node_id: str
    ref: ResearchNodeRef
    node: ResearchNode
    definitions: tuple[ResearchDefinition, ...]
    incoming_edges: tuple[CompiledResearchOSInputEdge, ...]
    semantic_digest: str

    def __post_init__(self) -> None:
        if self.graph_node_id != _graph_node_id(self.ref):
            raise ValueError("compiled Research OS graph node identity drift")
        if type(self.node) is not ResearchNode:
            raise TypeError("compiled Research OS graph node requires ResearchNode")
        if type(self.definitions) is not tuple or any(
            type(value) is not ResearchDefinition for value in self.definitions
        ):
            raise TypeError("compiled Research OS graph definitions must be typed")
        if type(self.incoming_edges) is not tuple or any(
            type(value) is not CompiledResearchOSInputEdge
            for value in self.incoming_edges
        ):
            raise TypeError("compiled Research OS incoming edges must be typed")
        ordered_edges = tuple(
            sorted(
                self.incoming_edges,
                key=lambda value: (
                    value.upstream.program_id,
                    value.upstream.node_id,
                    value.dependency_digest,
                ),
            )
        )
        upstream = tuple(value.upstream for value in ordered_edges)
        if len(upstream) != len(set(upstream)):
            raise ValueError(
                "compiled Research OS node cannot have duplicate upstream edges"
            )
        input_names = tuple(
            binding.input_name
            for edge in ordered_edges
            for binding in edge.bindings
        )
        if len(input_names) != len(set(input_names)):
            raise ValueError(
                "compiled Research OS node input names must be globally unique"
            )
        require_sha256(
            self.semantic_digest,
            "compiled Research OS node semantic_digest",
        )
        object.__setattr__(self, "incoming_edges", ordered_edges)

    @property
    def incoming_dependency_digests(self) -> tuple[str, ...]:
        return tuple(value.dependency_digest for value in self.incoming_edges)

    @property
    def upstream_refs(self) -> tuple[ResearchNodeRef, ...]:
        return tuple(value.upstream for value in self.incoming_edges)


@dataclass(frozen=True, slots=True)
class CompiledResearchOSGraph:
    revision: ResearchGraphRevision
    portfolio: ResearchPortfolio
    plan: ResearchGraphPlan
    nodes: tuple[CompiledResearchOSGraphNode, ...]

    def __post_init__(self) -> None:
        if type(self.revision) is not ResearchGraphRevision:
            raise TypeError("compiled Research OS graph requires ResearchGraphRevision")
        if type(self.portfolio) is not ResearchPortfolio:
            raise TypeError("compiled Research OS graph requires ResearchPortfolio")
        if type(self.plan) is not ResearchGraphPlan:
            raise TypeError("compiled Research OS graph requires ResearchGraphPlan")
        if self.revision.portfolio_id != self.portfolio.portfolio_id:
            raise ValueError("compiled Research OS portfolio identity drift")
        if self.revision.portfolio_digest != self.portfolio.portfolio_digest:
            raise ValueError("compiled Research OS portfolio digest drift")
        if self.plan.research_revision_digest != self.revision.revision_digest:
            raise ValueError("compiled Research OS graph revision drift")
        ids = tuple(node.graph_node_id for node in self.nodes)
        if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
            raise ValueError("compiled Research OS nodes must be canonical unique order")

    def node(self, graph_node_id: str) -> CompiledResearchOSGraphNode:
        for node in self.nodes:
            if node.graph_node_id == graph_node_id:
                return node
        raise KeyError(graph_node_id)


def compile_research_portfolio_graph(
    revision: ResearchGraphRevision,
    portfolio: ResearchPortfolio,
) -> CompiledResearchOSGraph:
    if type(revision) is not ResearchGraphRevision:
        raise TypeError("research graph compilation requires ResearchGraphRevision")
    if type(portfolio) is not ResearchPortfolio:
        raise TypeError("research graph compilation requires ResearchPortfolio")
    if revision.portfolio_id != portfolio.portfolio_id:
        raise ValueError("research graph revision/portfolio identity mismatch")
    if revision.portfolio_digest != portfolio.portfolio_digest:
        raise ValueError("research graph revision/portfolio digest mismatch")

    programs = {program.program_id: program for program in portfolio.programs}
    nodes = {
        ResearchNodeRef(program.program_id, node.node_id): node
        for program in portfolio.programs
        for node in program.nodes
    }
    definitions = {
        program.program_id: {
            definition.definition_id: definition
            for definition in program.definitions
        }
        for program in portfolio.programs
    }
    incoming: dict[
        ResearchNodeRef,
        list[tuple[ResearchNodeRef, tuple[ResearchInputBinding, ...], str]],
    ] = {
        ref: [] for ref in nodes
    }

    for program in portfolio.programs:
        for dependency in program.dependencies:
            upstream = ResearchNodeRef(
                program.program_id,
                dependency.upstream_node_id,
            )
            downstream = ResearchNodeRef(
                program.program_id,
                dependency.downstream_node_id,
            )
            incoming[downstream].append(
                (
                    upstream,
                    dependency.bindings,
                    dependency.dependency_digest,
                )
            )
    for dependency in portfolio.dependencies:
        incoming[dependency.downstream].append(
            (
                dependency.upstream,
                dependency.bindings,
                dependency.dependency_digest,
            )
        )

    ordered_refs = tuple(
        sorted(nodes, key=lambda value: (value.program_id, value.node_id))
    )
    node_definitions_by_ref = {
        ref: tuple(
            definitions[ref.program_id][definition_id]
            for definition_id in nodes[ref].definition_ids
        )
        for ref in ordered_refs
    }
    incoming_rows_by_ref = {
        ref: tuple(
            sorted(
                incoming[ref],
                key=lambda row: (
                    row[0].program_id,
                    row[0].node_id,
                    row[2],
                ),
            )
        )
        for ref in ordered_refs
    }
    semantic_digests: dict[ResearchNodeRef, str] = {}

    def semantic_digest(ref: ResearchNodeRef) -> str:
        current = semantic_digests.get(ref)
        if current is not None:
            return current
        node = nodes[ref]
        node_definitions = node_definitions_by_ref[ref]
        incoming_rows = incoming_rows_by_ref[ref]
        value = canonical_digest(
            {
                "node_digest": node.node_digest,
                "definition_digests": tuple(
                    definition.definition_digest
                    for definition in node_definitions
                ),
                "incoming": tuple(
                    {
                        "upstream_graph_node_id": _graph_node_id(upstream),
                        "dependency_digest": dependency_digest,
                        "upstream_semantic_digest": semantic_digest(upstream),
                    }
                    for upstream, _bindings, dependency_digest in incoming_rows
                ),
            }
        )
        semantic_digests[ref] = value
        return value

    for ref in ordered_refs:
        semantic_digest(ref)

    compiled_nodes = []
    graph_nodes = []
    for ref in ordered_refs:
        node = nodes[ref]
        node_definitions = node_definitions_by_ref[ref]
        incoming_rows = incoming_rows_by_ref[ref]
        incoming_edges = tuple(
            CompiledResearchOSInputEdge(
                upstream,
                bindings,
                dependency_digest,
            )
            for upstream, bindings, dependency_digest in incoming_rows
        )
        digest = semantic_digests[ref]
        graph_node_id = _graph_node_id(ref)
        compiled = CompiledResearchOSGraphNode(
            graph_node_id,
            ref,
            node,
            node_definitions,
            incoming_edges,
            digest,
        )
        compiled_nodes.append(compiled)
        graph_nodes.append(
            ResearchGraphNode(
                graph_node_id,
                digest,
                tuple(
                    _graph_node_id(edge.upstream)
                    for edge in compiled.incoming_edges
                ),
            )
        )

    plan = ResearchGraphPlan(
        portfolio.portfolio_id,
        revision.revision_digest,
        tuple(graph_nodes),
    )
    return CompiledResearchOSGraph(
        revision,
        portfolio,
        plan,
        tuple(compiled_nodes),
    )


@runtime_checkable
class ResearchOSNodeExecutionPort(Protocol):
    """Lower systems implement node semantics; the top-level graph owns scheduling only."""

    def execute(
        self,
        context: object,
        node: CompiledResearchOSGraphNode,
        *,
        deadline: Deadline | None,
    ) -> None: ...


class ResearchOSGraphExecutor(ResearchGraphNodeExecutorPort):
    def __init__(
        self,
        compilation: CompiledResearchOSGraph,
        execution: ResearchOSNodeExecutionPort,
    ) -> None:
        if type(compilation) is not CompiledResearchOSGraph:
            raise TypeError("Research OS graph executor requires compiled graph")
        if not isinstance(execution, ResearchOSNodeExecutionPort):
            raise TypeError(
                "Research OS node execution must satisfy ResearchOSNodeExecutionPort"
            )
        self._compilation = compilation
        self._execution = execution

    def execute(self, context, node: ResearchGraphNode, *, deadline) -> None:
        compiled = self._compilation.node(node.node_id)
        if compiled.semantic_digest != node.semantic_digest:
            raise ValueError("Research OS graph node semantic identity drift")
        self._execution.execute(
            context,
            compiled,
            deadline=deadline,
        )


def bind_research_portfolio_scheduler(
    compilation: CompiledResearchOSGraph,
    execution: ResearchOSNodeExecutionPort,
    *,
    execution_pool: ResearchExecutionPool | None = None,
    tenant_id: str | None = None,
    priority: ExecutionPriority = ExecutionPriority.NORMAL,
    task_group_id: str | None = None,
    execution_store: ResearchGraphExecutionStorePort | None = None,
    execution_id: str | None = None,
    lease_seconds: float = 30.0,
    scheduler_owner_id: str | None = None,
) -> ResearchGraphScheduler:
    return ResearchGraphScheduler(
        compilation.plan,
        ResearchOSGraphExecutor(compilation, execution),
        execution_pool=execution_pool,
        tenant_id=tenant_id,
        priority=priority,
        task_group_id=task_group_id,
        execution_store=execution_store,
        execution_id=execution_id,
        lease_seconds=lease_seconds,
        scheduler_owner_id=scheduler_owner_id,
    )


__all__ = [
    "CompiledResearchOSGraph",
    "CompiledResearchOSGraphNode",
    "CompiledResearchOSInputEdge",
    "ResearchOSGraphExecutor",
    "ResearchOSNodeExecutionPort",
    "bind_research_portfolio_scheduler",
    "compile_research_portfolio_graph",
]
