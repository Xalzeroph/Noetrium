from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cache
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskContextPort
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    freeze_json,
    require_sha256,
    ComplexityBound,
    ComplexityContract,
)
from noetrium_platform.foundation.kernel.structure import GraphProgressKind, GraphTrigger
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, role


EXECUTION_VERTEX_SCHEMA = "execution.vertex"
EXECUTION_DEPENDENCY_SCHEMA = "execution.dependency"
EXECUTION_PROJECTION_SCHEMA = "execution.projection"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be non-empty canonical text")
    return value


def _require_unit_schema(
    value: NoetriumUnit,
    schema: str,
    label: str,
) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_schema(schema):
        raise TypeError(f"{label} must be a {schema} NoetriumUnit")
    return value


def execution_vertex(
    vertex_id: str,
    semantic_digest: str,
    *,
    boundary=None,
    source_path: tuple[str, ...] = (),
    effectful: bool = False,
    static_cost: int = 1,
) -> NoetriumUnit:
    del boundary
    node_id = _text(vertex_id, "execution node_id")
    require_sha256(semantic_digest, "execution semantic_digest")
    if type(source_path) is not tuple or any(
        type(part) is not str or not part for part in source_path
    ):
        raise TypeError("execution source_path must be a text tuple")
    if type(effectful) is not bool:
        raise TypeError("execution effectful projection must be boolean")
    if type(static_cost) is not int or static_cost <= 0:
        raise ValueError("execution static_cost projection must be positive integer")
    attributes = {
        "kind": "execution-vertex",
        "node_id": node_id,
        "semantic_digest": semantic_digest,
        "source_path": source_path,
        "effectful": effectful,
        "static_cost": static_cost,
    }
    # All semantic fields are verified above. Freeze once, derive the exact
    # historical identity from that immutable canonical cut, and reuse the
    # kernel's trusted normalized constructor. Calling the public Unit
    # constructor here would repeat tokenization, schema sorting, attribute
    # freezing and role normalization for every execution vertex.
    frozen = freeze_json(attributes)
    return NoetriumUnit._from_normalized(
        unit_id=f"execution-vertex:{canonical_digest(frozen)}",
        schemas=(EXECUTION_VERTEX_SCHEMA,),
        attributes=frozen,
        roles=(),
    )


def execution_vertex_id(vertex: NoetriumUnit) -> str:
    value = _require_unit_schema(
        vertex,
        EXECUTION_VERTEX_SCHEMA,
        "execution vertex",
    ).attributes.get("node_id")
    return _text(value, "execution node_id")


def execution_vertex_semantic_digest(vertex: NoetriumUnit) -> str:
    value = _require_unit_schema(
        vertex,
        EXECUTION_VERTEX_SCHEMA,
        "execution vertex",
    ).attributes.get("semantic_digest")
    return require_sha256(value, "execution vertex semantic_digest")


def execution_vertex_digest(vertex: NoetriumUnit) -> str:
    return _require_unit_schema(
        vertex,
        EXECUTION_VERTEX_SCHEMA,
        "execution vertex",
    ).semantic_digest


def execution_vertex_source_path(vertex: NoetriumUnit) -> tuple[str, ...]:
    value = _require_unit_schema(
        vertex,
        EXECUTION_VERTEX_SCHEMA,
        "execution vertex",
    ).attributes.get("source_path")
    if type(value) is not tuple or any(
        type(part) is not str or not part for part in value
    ):
        raise TypeError("execution vertex source_path projection is invalid")
    return value


def execution_vertex_effectful(vertex: NoetriumUnit) -> bool:
    value = _require_unit_schema(
        vertex,
        EXECUTION_VERTEX_SCHEMA,
        "execution vertex",
    ).attributes.get("effectful")
    if type(value) is not bool:
        raise TypeError("execution vertex effectful projection is invalid")
    return value


def execution_vertex_static_cost(vertex: NoetriumUnit) -> int:
    value = _require_unit_schema(
        vertex,
        EXECUTION_VERTEX_SCHEMA,
        "execution vertex",
    ).attributes.get("static_cost")
    if type(value) is not int or value <= 0:
        raise TypeError("execution vertex static_cost projection is invalid")
    return value


def execution_flow(
    source_vertex_ids: str | tuple[str, ...],
    target_vertex_ids: str | tuple[str, ...],
    *,
    source_port: str | None = None,
    target_port: str | None = None,
    routing_digests: tuple[str, ...] = (),
    trigger: GraphTrigger = GraphTrigger(),
    progress: GraphProgressKind | None = None,
) -> NoetriumUnit:
    del source_port, target_port
    raw_sources = (
        (source_vertex_ids,)
        if type(source_vertex_ids) is str
        else source_vertex_ids
    )
    raw_targets = (
        (target_vertex_ids,)
        if type(target_vertex_ids) is str
        else target_vertex_ids
    )
    if type(raw_sources) is not tuple or not raw_sources:
        raise TypeError("execution dependency sources must be non-empty tuple")
    if type(raw_targets) is not tuple or not raw_targets:
        raise TypeError("execution dependency targets must be non-empty tuple")
    sources = tuple(
        sorted(_text(row, "execution dependency source") for row in raw_sources)
    )
    targets = tuple(
        sorted(_text(row, "execution dependency target") for row in raw_targets)
    )
    if len(sources) != len(set(sources)) or len(targets) != len(set(targets)):
        raise ValueError("execution dependency endpoints must be unique")
    if set(sources) & set(targets):
        raise ValueError("execution dependency cannot self-depend")
    if type(trigger) is not GraphTrigger:
        raise TypeError("execution dependency trigger must be GraphTrigger")
    if progress is not None and not isinstance(progress, GraphProgressKind):
        raise TypeError("execution dependency progress must be typed")
    if type(routing_digests) is not tuple:
        raise TypeError("execution dependency routing_digests must be tuple")
    routing = tuple(sorted(routing_digests))
    for digest in routing:
        require_sha256(digest, "execution dependency routing digest")
    attributes = {
        "kind": "execution-dependency",
        "source_node_ids": sources,
        "target_node_ids": targets,
        "trigger_kind": trigger.kind.value,
        "trigger_quorum": trigger.quorum,
        "progress": None if progress is None else progress.value,
        "routing_digests": routing,
    }
    return NoetriumUnit(
        unit_id=f"execution-dependency:{canonical_digest(attributes)}",
        schemas=(EXECUTION_DEPENDENCY_SCHEMA,),
        attributes=attributes,
    )


def execution_dependency_source_node_ids(
    relation: NoetriumUnit,
) -> tuple[str, ...]:
    value = _require_unit_schema(
        relation,
        EXECUTION_DEPENDENCY_SCHEMA,
        "execution dependency",
    ).attributes.get("source_node_ids")
    if type(value) is not tuple or any(type(row) is not str for row in value):
        raise TypeError("execution dependency source projection is invalid")
    return value


def execution_dependency_target_node_ids(
    relation: NoetriumUnit,
) -> tuple[str, ...]:
    value = _require_unit_schema(
        relation,
        EXECUTION_DEPENDENCY_SCHEMA,
        "execution dependency",
    ).attributes.get("target_node_ids")
    if type(value) is not tuple or any(type(row) is not str for row in value):
        raise TypeError("execution dependency target projection is invalid")
    return value


def execution_dependency_trigger(relation: NoetriumUnit) -> GraphTrigger:
    row = _require_unit_schema(
        relation,
        EXECUTION_DEPENDENCY_SCHEMA,
        "execution dependency",
    )
    from noetrium_platform.foundation.kernel.structure import GraphTriggerKind
    return GraphTrigger(
        GraphTriggerKind(str(row.attributes.get("trigger_kind"))),
        row.attributes.get("trigger_quorum"),
    )


def execution_dependency_progress(
    relation: NoetriumUnit,
) -> GraphProgressKind | None:
    value = _require_unit_schema(
        relation,
        EXECUTION_DEPENDENCY_SCHEMA,
        "execution dependency",
    ).attributes.get("progress")
    return None if value is None else GraphProgressKind(str(value))


def execution_dependency_routing_digests(
    relation: NoetriumUnit,
) -> tuple[str, ...]:
    value = _require_unit_schema(
        relation,
        EXECUTION_DEPENDENCY_SCHEMA,
        "execution dependency",
    ).attributes.get("routing_digests")
    if type(value) is not tuple or any(type(row) is not str for row in value):
        raise TypeError("execution dependency routing projection is invalid")
    return value


def execution_dependency_digest(relation: NoetriumUnit) -> str:
    return _require_unit_schema(
        relation,
        EXECUTION_DEPENDENCY_SCHEMA,
        "execution dependency",
    ).semantic_digest


def execution_graph(
    graph_id: str,
    research_revision_digest: str,
    vertices: tuple[NoetriumUnit, ...],
    flows: tuple[NoetriumUnit, ...] = (),
) -> NoetriumUnit:
    graph_id = _text(graph_id, "execution graph_id")
    require_sha256(
        research_revision_digest,
        "execution research_revision_digest",
    )
    if type(vertices) is not tuple or not vertices:
        raise TypeError("execution projection vertices must be non-empty tuple")
    if type(flows) is not tuple:
        raise TypeError("execution projection relations must be tuple")
    nodes = tuple(
        sorted(
            (
                _require_unit_schema(
                    vertex,
                    EXECUTION_VERTEX_SCHEMA,
                    "execution vertex",
                )
                for vertex in vertices
            ),
            key=execution_vertex_id,
        )
    )
    node_ids = tuple(execution_vertex_id(node) for node in nodes)
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("execution projection node identities must be unique")
    relations = tuple(
        sorted(
            (
                _require_unit_schema(
                    relation,
                    EXECUTION_DEPENDENCY_SCHEMA,
                    "execution dependency",
                )
                for relation in flows
            ),
            key=execution_dependency_digest,
        )
    )
    known = set(node_ids)
    for relation in relations:
        endpoints = (
            execution_dependency_source_node_ids(relation)
            + execution_dependency_target_node_ids(relation)
        )
        if any(node_id not in known for node_id in endpoints):
            raise ValueError("execution dependency references unknown node")
    attributes = {
        "kind": "execution-projection",
        "graph_id": graph_id,
        "research_revision_digest": research_revision_digest,
    }
    graph = NoetriumUnit(
        unit_id=f"execution-projection:{canonical_digest((attributes, tuple(x.unit_digest for x in nodes), tuple(x.unit_digest for x in relations)))}",
        schemas=(EXECUTION_PROJECTION_SCHEMA,),
        attributes=attributes,
        roles=(
            role("member", *nodes),
            role("relation", *relations),
        ),
    )
    execution_graph_index(graph)
    return graph


def execution_graph_id(plan: NoetriumUnit) -> str:
    value = _require_unit_schema(
        plan,
        EXECUTION_PROJECTION_SCHEMA,
        "execution projection",
    ).attributes.get("graph_id")
    return _text(value, "execution graph_id")


def execution_graph_digest(plan: NoetriumUnit) -> str:
    return _require_unit_schema(
        plan,
        EXECUTION_PROJECTION_SCHEMA,
        "execution projection",
    ).semantic_digest


def execution_graph_research_revision_digest(plan: NoetriumUnit) -> str:
    value = _require_unit_schema(
        plan,
        EXECUTION_PROJECTION_SCHEMA,
        "execution projection",
    ).attributes.get("research_revision_digest")
    return require_sha256(
        value,
        "execution research_revision_digest",
    )


def execution_graph_vertices(plan: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    row = _require_unit_schema(
        plan,
        EXECUTION_PROJECTION_SCHEMA,
        "execution projection",
    )
    vertices = row.units("member")
    if any(not vertex.has_schema(EXECUTION_VERTEX_SCHEMA) for vertex in vertices):
        raise TypeError("execution projection contains non-vertex member")
    return vertices


def execution_graph_relations(plan: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    row = _require_unit_schema(
        plan,
        EXECUTION_PROJECTION_SCHEMA,
        "execution projection",
    )
    relations = row.units("relation")
    if any(
        not relation.has_schema(EXECUTION_DEPENDENCY_SCHEMA)
        for relation in relations
    ):
        raise TypeError("execution projection contains non-dependency relation")
    return relations


EXECUTION_GRAPH_INDEX_COMPLEXITY = ComplexityContract(
    algorithm_id="research.execution.incidence-index.v1",
    implementation_digest=canonical_digest(
        (
            "research.execution.incidence-index.v1",
            "hypergraph-incidence-kahn-no-pairwise-expansion",
        )
    ),
    time_upper_bound=ComplexityBound.linear_sum(
        "graph_nodes",
        "graph_relations",
        "source_incidences",
        "target_incidences",
    ),
    space_upper_bound=ComplexityBound.linear_sum(
        "graph_nodes",
        "graph_relations",
        "source_incidences",
        "target_incidences",
    ),
    assumptions=(
        "relation source and target endpoint lists are already canonical Units",
        "cycle detection uses relation-incidence Kahn traversal",
        "no source-target Cartesian adjacency is materialized",
    ),
    time_lower_bound=ComplexityBound.linear_sum(
        "graph_nodes",
        "graph_relations",
        "source_incidences",
        "target_incidences",
    ),
    space_lower_bound=ComplexityBound.linear_sum(
        "graph_nodes",
        "graph_relations",
        "source_incidences",
        "target_incidences",
    ),
)


SELECTED_EXECUTION_GRAPH_INDEX_COMPLEXITY = ComplexityContract(
    algorithm_id="research.execution.selected-index.v5",
    implementation_digest=canonical_digest(
        (
            "research.execution.selected-index.v5",
            "incidence-closure-target-projection-no-pairwise-expansion",
        )
    ),
    time_upper_bound=ComplexityBound.linear_sum(
        "selected_nodes",
        "selected_relations",
        "selected_source_incidences",
        "selected_target_incidences",
    ),
    space_upper_bound=ComplexityBound.linear_sum(
        "selected_nodes",
        "selected_relations",
        "selected_source_incidences",
        "selected_target_incidences",
    ),
    assumptions=(
        "the immutable full Unit-derived ExecutionGraphIndex is already materialized",
        "dependency closure traverses each selected incoming relation at most once",
        "multi-target hyperedges are projected only onto selected target vertices",
    ),
    time_lower_bound=ComplexityBound.linear_sum(
        "selected_nodes",
        "selected_relations",
        "selected_source_incidences",
        "selected_target_incidences",
    ),
    space_lower_bound=ComplexityBound.linear_sum(
        "selected_nodes",
        "selected_relations",
        "selected_source_incidences",
        "selected_target_incidences",
    ),
)


@dataclass(frozen=True, slots=True)
class ExecutionGraphIndex:
    nodes: tuple[NoetriumUnit, ...]
    by_id: Mapping[str, NoetriumUnit]
    relations: tuple[NoetriumUnit, ...]
    relation_sources: tuple[tuple[str, ...], ...]
    relation_targets: tuple[tuple[str, ...], ...]
    incoming_relation_indices: Mapping[str, tuple[int, ...]]
    outgoing_relation_indices: Mapping[str, tuple[int, ...]]
    topological_order: tuple[str, ...]


@cache
def _full_execution_graph_index(plan: NoetriumUnit) -> ExecutionGraphIndex:
    nodes = execution_graph_vertices(plan)
    relations = execution_graph_relations(plan)
    by_id: dict[str, NoetriumUnit] = {}
    for node in nodes:
        node_id = execution_vertex_id(node)
        if node_id in by_id:
            raise ValueError("execution projection node identities must be unique")
        by_id[node_id] = node

    incoming_relation_indices = {node_id: [] for node_id in by_id}
    outgoing_relation_indices = {node_id: [] for node_id in by_id}
    relation_sources: list[tuple[str, ...]] = []
    relation_targets: list[tuple[str, ...]] = []
    unresolved_incoming_relations = {node_id: 0 for node_id in by_id}

    for relation_index, relation in enumerate(relations):
        sources = execution_dependency_source_node_ids(relation)
        targets = execution_dependency_target_node_ids(relation)
        if any(node_id not in by_id for node_id in sources + targets):
            raise ValueError("execution dependency references unknown node")
        relation_sources.append(sources)
        relation_targets.append(targets)
        for target in targets:
            incoming_relation_indices[target].append(relation_index)
            unresolved_incoming_relations[target] += 1
        for source in sources:
            outgoing_relation_indices[source].append(relation_index)

    # Hypergraph-native Kahn traversal. Treat each relation as an implicit
    # auxiliary node: a relation becomes structurally satisfied only after all
    # of its source vertices have been emitted, then it releases every target.
    # This is Θ(V + R + source-incidences + target-incidences), unlike the old
    # pairwise source×target expansion.
    relation_unresolved_sources = [
        len(sources) for sources in relation_sources
    ]
    ready = deque(
        node_id
        for node_id, count in unresolved_incoming_relations.items()
        if count == 0
    )
    topological: list[str] = []
    while ready:
        node_id = ready.popleft()
        topological.append(node_id)
        for relation_index in outgoing_relation_indices[node_id]:
            remaining = relation_unresolved_sources[relation_index] - 1
            if remaining < 0:
                raise RuntimeError(
                    "execution relation source counter underflow"
                )
            relation_unresolved_sources[relation_index] = remaining
            if remaining != 0:
                continue
            for target in relation_targets[relation_index]:
                count = unresolved_incoming_relations[target] - 1
                if count < 0:
                    raise RuntimeError(
                        "execution target relation counter underflow"
                    )
                unresolved_incoming_relations[target] = count
                if count == 0:
                    ready.append(target)
    if len(topological) != len(by_id):
        blocked = tuple(sorted(set(by_id) - set(topological)))
        raise ValueError(f"execution dependency cycle among: {blocked[:16]!r}")

    return ExecutionGraphIndex(
        nodes,
        MappingProxyType(by_id),
        relations,
        tuple(relation_sources),
        tuple(relation_targets),
        MappingProxyType(
            {
                key: tuple(value)
                for key, value in incoming_relation_indices.items()
            }
        ),
        MappingProxyType(
            {
                key: tuple(value)
                for key, value in outgoing_relation_indices.items()
            }
        ),
        tuple(topological),
    )


def execution_graph_index(
    plan: NoetriumUnit,
    selected_node_ids: tuple[str, ...] | None = None,
) -> ExecutionGraphIndex:
    _require_unit_schema(
        plan,
        EXECUTION_PROJECTION_SCHEMA,
        "execution projection",
    )
    full = _full_execution_graph_index(plan)
    if selected_node_ids is None:
        return full
    if (
        type(selected_node_ids) is not tuple
        or not selected_node_ids
        or any(
            type(node_id) is not str or not node_id.strip()
            for node_id in selected_node_ids
        )
    ):
        raise TypeError(
            "execution graph selection requires a non-empty text tuple"
        )
    selected = set(selected_node_ids)
    if len(selected_node_ids) != len(selected):
        raise ValueError("execution graph selection node ids must be unique")
    unknown = selected.difference(full.by_id)
    if unknown:
        raise KeyError(tuple(sorted(unknown)))

    closure = set(selected)
    pending = list(selected)
    closure_relation_indices: dict[int, None] = {}
    while pending:
        node_id = pending.pop()
        for relation_index in full.incoming_relation_indices[node_id]:
            if relation_index in closure_relation_indices:
                continue
            closure_relation_indices[relation_index] = None
            for dependency in full.relation_sources[relation_index]:
                if dependency not in closure:
                    closure.add(dependency)
                    pending.append(dependency)

    ordered_ids = tuple(
        node_id for node_id in full.topological_order if node_id in closure
    )
    nodes = tuple(full.by_id[node_id] for node_id in ordered_ids)

    projected_relations: list[NoetriumUnit] = []
    for relation_index in closure_relation_indices:
        relation = full.relations[relation_index]
        sources = full.relation_sources[relation_index]
        if any(source not in closure for source in sources):
            raise RuntimeError(
                "dependency-closed execution selection lost relation source"
            )
        original_targets = full.relation_targets[relation_index]
        targets = tuple(
            target for target in original_targets if target in closure
        )
        if not targets:
            continue
        if targets == original_targets:
            projected_relations.append(relation)
            continue
        projected_relations.append(
            execution_flow(
                sources,
                targets,
                routing_digests=execution_dependency_routing_digests(
                    relation
                ),
                trigger=execution_dependency_trigger(relation),
                progress=execution_dependency_progress(relation),
            )
        )
    relations = tuple(projected_relations)
    subgraph = execution_graph(
        execution_graph_id(plan),
        execution_graph_research_revision_digest(plan),
        nodes,
        relations,
    )
    return _full_execution_graph_index(subgraph)


def validate_execution_graph(plan: NoetriumUnit) -> None:
    execution_graph_index(plan)


def execution_vertex_dependencies(
    plan: NoetriumUnit,
    vertex_id: str,
) -> tuple[str, ...]:
    vertex_id = _text(vertex_id, "execution vertex_id")
    index = execution_graph_index(plan)
    if vertex_id not in index.by_id:
        raise LookupError(f"execution graph has no vertex {vertex_id!r}")
    rows: dict[str, None] = {}
    for relation_index in index.incoming_relation_indices[vertex_id]:
        for source in index.relation_sources[relation_index]:
            rows.setdefault(source, None)
    return tuple(rows)


def execution_vertex_dependents(
    plan: NoetriumUnit,
    vertex_id: str,
) -> tuple[str, ...]:
    vertex_id = _text(vertex_id, "execution vertex_id")
    index = execution_graph_index(plan)
    if vertex_id not in index.by_id:
        raise LookupError(f"execution graph has no vertex {vertex_id!r}")
    rows: dict[str, None] = {}
    for relation_index in index.outgoing_relation_indices[vertex_id]:
        for target in index.relation_targets[relation_index]:
            rows.setdefault(target, None)
    return tuple(rows)


def execution_graph_vertex_digest(
    plan: NoetriumUnit,
    vertex_id: str,
) -> str:
    vertex_id = _text(vertex_id, "execution vertex_id")
    try:
        return execution_vertex_digest(execution_graph_index(plan).by_id[vertex_id])
    except KeyError as exc:
        raise LookupError(f"execution graph has no vertex {vertex_id!r}") from exc


@dataclass(frozen=True, slots=True)
class ResearchGraphFailureProvenance:
    """Durable graph projection of lower failure provenance; Graph does not own failure truth."""

    qualified_type: str
    error_digest: str
    safe_message: str
    traceback_frames: tuple[str, ...] = ()
    cause_chain: tuple[str, ...] = ()
    failure_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    lower_refs: tuple[str, ...] = ()
    provenance_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.qualified_type, "research graph failure qualified_type")
        require_sha256(self.error_digest, "research graph failure error_digest")
        _text(self.safe_message, "research graph failure safe_message")
        for field_name in ("traceback_frames", "cause_chain", "evidence_refs", "lower_refs"):
            value = getattr(self, field_name)
            if type(value) is not tuple:
                raise TypeError(f"research graph failure {field_name} must be a tuple")
            for item in value:
                _text(item, f"research graph failure {field_name} item")
        if self.failure_id is not None:
            _text(self.failure_id, "research graph failure failure_id")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("research graph failure evidence_refs must be unique")
        if len(self.lower_refs) != len(set(self.lower_refs)):
            raise ValueError("research graph failure lower_refs must be unique")
        object.__setattr__(
            self,
            "provenance_digest",
            canonical_digest(
                {
                    "qualified_type": self.qualified_type,
                    "error_digest": self.error_digest,
                    "safe_message": self.safe_message,
                    "traceback_frames": self.traceback_frames,
                    "cause_chain": self.cause_chain,
                    "failure_id": self.failure_id,
                    "evidence_refs": tuple(sorted(self.evidence_refs)),
                    "lower_refs": tuple(sorted(self.lower_refs)),
                }
            ),
        )

    def as_payload(self) -> dict[str, object]:
        return {
            "qualified_type": self.qualified_type,
            "error_digest": self.error_digest,
            "safe_message": self.safe_message,
            "traceback_frames": self.traceback_frames,
            "cause_chain": self.cause_chain,
            "failure_id": self.failure_id,
            "evidence_refs": self.evidence_refs,
            "lower_refs": self.lower_refs,
            "provenance_digest": self.provenance_digest,
        }


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
    failure_provenance: ResearchGraphFailureProvenance | None = None
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
            if (
                self.failure_type is not None
                or self.failure_message is not None
                or self.failure_provenance is not None
                or blockers
            ):
                raise ValueError("successful/cancelled research graph node cannot carry failure metadata")
        elif self.state is ResearchGraphNodeState.FAILED:
            if blockers:
                raise ValueError("failed research graph node cannot carry blockers")
            if not isinstance(self.failure_type, str) or not self.failure_type.strip():
                raise ValueError("failed research graph node requires failure_type")
            if not isinstance(self.failure_message, str) or not self.failure_message.strip():
                raise ValueError("failed research graph node requires failure_message")
            if not isinstance(
                self.failure_provenance, ResearchGraphFailureProvenance
            ):
                raise TypeError("failed research graph node requires typed failure_provenance")
        else:
            if (
                self.failure_type is not None
                or self.failure_message is not None
                or self.failure_provenance is not None
            ):
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
        node: NoetriumUnit,
        *,
        deadline: Deadline | None,
    ) -> None: ...


__all__ = [
    "EXECUTION_DEPENDENCY_SCHEMA",
    "EXECUTION_GRAPH_INDEX_COMPLEXITY",
    "EXECUTION_PROJECTION_SCHEMA",
    "EXECUTION_VERTEX_SCHEMA",
    "ExecutionGraphIndex",
    "ResearchGraphExecutionReport",
    "ResearchGraphNodeExecutorPort",
    "ResearchGraphNodeResult",
    "ResearchGraphNodeState",
    "execution_dependency_digest",
    "execution_dependency_progress",
    "execution_dependency_routing_digests",
    "execution_dependency_source_node_ids",
    "execution_dependency_target_node_ids",
    "execution_dependency_trigger",
    "execution_flow",
    "execution_graph",
    "execution_graph_digest",
    "execution_graph_id",
    "execution_graph_index",
    "execution_graph_relations",
    "execution_graph_research_revision_digest",
    "execution_graph_vertex_digest",
    "execution_graph_vertices",
    "execution_vertex",
    "execution_vertex_dependencies",
    "execution_vertex_dependents",
    "execution_vertex_digest",
    "execution_vertex_effectful",
    "execution_vertex_id",
    "execution_vertex_semantic_digest",
    "execution_vertex_source_path",
    "execution_vertex_static_cost",
    "validate_execution_graph",
]
