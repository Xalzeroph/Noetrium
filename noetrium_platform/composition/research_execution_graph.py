from __future__ import annotations

from dataclasses import dataclass, field
from collections import OrderedDict, deque
from threading import RLock
from functools import lru_cache
from hashlib import sha256
import heapq
from types import MappingProxyType
from typing import Mapping, Protocol, runtime_checkable

from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_graph import ResearchGraphScheduler
from noetrium_platform.composition.research_semantics import (
    graph_is_transparent_container,
)
from noetrium_platform.product.research_traits import (
    TRAIT_UNIT_ACTIVATION,
    TRAIT_VERIFIER,
    RELATION_FLOW,
)
from noetrium_platform.foundation.kernel.concurrency.api import Deadline, TaskContextPort
from noetrium_platform.foundation.kernel.dag import deterministic_hypergraph_topological_order
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    require_sha256,
    ComplexityBound,
    ComplexityContract,
)
from noetrium_platform.product.research_control import ResearchGraphRevision
from noetrium_platform.foundation.kernel.structure import (
    CONTROL_TYPE,
    NoetriumUnit,
    NoetriumUnit,
    UnitRef,
    GraphPortMode,
    NoetriumUnit,
    GraphTrigger,
    GraphProgressKind,
    GraphStorageKind,
    NoetriumUnit,
    NoetriumUnit,
)
from noetrium_platform.foundation.kernel.unit import unit_merkle_digest
from noetrium_platform.research.execution.graph.api import (
    ExecutionGraphIndex,
    execution_flow,
    execution_graph,
    execution_graph_index,
    execution_vertex,
    execution_vertex_id,
    ResearchGraphExecutionStorePort,
    ResearchGraphNodeExecutorPort,
)
from noetrium_platform.research.execution.policy.api import ExecutionPriority


_EMPTY_TYPE_MAPPING = MappingProxyType({})


RESEARCH_EXECUTION_TOPOLOGY_COMPLEXITY = ComplexityContract(
    algorithm_id="research.execution.topology.v2",
    implementation_digest=canonical_digest(
        (
            "research.execution.topology.v2",
            "canonical-input-ordered-kahn",
        )
    ),
    time_upper_bound=ComplexityBound.linear_sum(
        "compiled_vertices",
        "compiled_dependency_pairs",
    ),
    space_upper_bound=ComplexityBound.linear_sum(
        "compiled_vertices",
        "compiled_dependency_pairs",
    ),
    assumptions=(
        "compiled refs arrive in canonical order",
        "compiled routed relations preserve canonical graph relation order",
        "dependency-pair de-duplication uses expected O(1) ordered-dict membership",
    ),
    time_lower_bound=ComplexityBound.linear_sum(
        "compiled_vertices",
        "compiled_dependency_pairs",
    ),
    space_lower_bound=ComplexityBound.linear_sum(
        "compiled_vertices",
        "compiled_dependency_pairs",
    ),
)

RESEARCH_EXECUTION_DESCENDANTS_COMPLEXITY = ComplexityContract(
    algorithm_id="research.execution.descendants.v2",
    implementation_digest=canonical_digest(
        (
            "research.execution.descendants.v2",
            "cached-execution-index-output-sensitive-bfs",
        )
    ),
    time_upper_bound=ComplexityBound.linear_sum(
        "affected_vertices",
        "affected_edges",
    ),
    space_upper_bound=ComplexityBound.linear("affected_vertices"),
    assumptions=(
        "the immutable full ExecutionGraphIndex is cached by the compilation view",
        "dependent adjacency preserves deterministic compilation order",
        "hash-set membership is expected O(1)",
    ),
    time_lower_bound=ComplexityBound.linear_sum(
        "affected_vertices",
        "affected_edges",
    ),
    space_lower_bound=ComplexityBound.linear("affected_vertices"),
)


RESEARCH_EXECUTION_SEMANTIC_PROPAGATION_COMPLEXITY = ComplexityContract(
    algorithm_id="research.execution.semantic-propagation.v2",
    implementation_digest=canonical_digest(
        (
            "research.execution.semantic-propagation.v2",
            "topological-transitive-merkle-dp",
        )
    ),
    time_upper_bound=ComplexityBound.linear_sum(
        "compiled_vertices",
        "compiled_input_bindings",
    ),
    space_upper_bound=ComplexityBound.linear("compiled_vertices"),
    assumptions=(
        "the executable graph is a DAG with an already materialized linear topological order",
        "each incoming source-target binding is encoded once",
        "SHA-256/Merkle work per fixed-size digest field is constant",
    ),
    time_lower_bound=ComplexityBound.linear_sum(
        "compiled_vertices",
        "compiled_input_bindings",
    ),
    space_lower_bound=ComplexityBound.linear("compiled_vertices"),
)



def _graph_node_id(ref: UnitRef) -> str:
    if any("::" in part for part in ref.path):
        raise ValueError(
            "executable graph_id cannot contain reserved path delimiter '::'"
        )
    return "::".join(ref.path)


def _graph_ref_from_node_id(node_id: str) -> UnitRef:
    if type(node_id) is not str or not node_id:
        raise KeyError(node_id)
    try:
        ref = UnitRef(tuple(node_id.split("::")))
    except (TypeError, ValueError) as exc:
        raise KeyError(node_id) from exc
    if _graph_node_id(ref) != node_id:
        raise KeyError(node_id)
    return ref


def _merkle_digest(tag: str, *parts: object) -> str:
    return unit_merkle_digest(tag, *parts)


def _projection_edge_digest(
    upstream_node_id: str,
    source_port: str | None,
    target_port: str | None,
    type_digest: str,
    routing_digests: tuple[str, ...],
) -> str:
    hasher = sha256()
    for value in (
        "noetrium.research.input-binding.v3",
        upstream_node_id,
        "" if source_port is None else source_port,
        "" if target_port is None else target_port,
        type_digest,
        str(len(routing_digests)),
        *routing_digests,
    ):
        hasher.update(value.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _projection_node_digest(
    node_id: str,
    semantic_digest: str,
    depends_on_node_ids: tuple[str, ...],
    edge_digests: tuple[str, ...],
) -> str:
    hasher = sha256()
    for value in (
        "noetrium.research.execution-binding.v3",
        node_id,
        semantic_digest,
        str(len(depends_on_node_ids)),
        *depends_on_node_ids,
        str(len(edge_digests)),
        *edge_digests,
    ):
        hasher.update(value.encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


@lru_cache(maxsize=65536)
def _execution_semantic_digest(
    graph_digest,
    symbol_digests,
    incoming_semantic_contract,
):
    return _merkle_digest(
        "noetrium.research.execution-semantic.v4",
        graph_digest,
        symbol_digests,
        incoming_semantic_contract,
    )


@dataclass(frozen=True, slots=True)
class ResearchInputBinding:
    """One normalized typed dependency between executable Research Graph nodes."""

    upstream: UnitRef
    source_port: str | None
    target_port: str | None
    type_ref: NoetriumUnit
    routing_digests: tuple[str, ...] = ()
    edge_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.upstream) is not UnitRef:
            raise TypeError("research execution flow upstream must be UnitRef")
        if self.source_port is not None and (
            type(self.source_port) is not str or not self.source_port
        ):
            raise ValueError("compiled Research execution source_port must be canonical text")
        if self.target_port is not None and (
            type(self.target_port) is not str or not self.target_port
        ):
            raise ValueError("compiled Research execution target_port must be canonical text")
        if type(self.type_ref) is not NoetriumUnit:
            raise TypeError("research execution flow type_ref must be NoetriumUnit")
        if type(self.routing_digests) is not tuple:
            raise TypeError("compiled Research execution routing_digests must be tuple")
        for digest in self.routing_digests:
            require_sha256(digest, "compiled Research execution routing digest")
        object.__setattr__(
            self,
            "edge_digest",
            _projection_edge_digest(
                _graph_node_id(self.upstream),
                self.source_port,
                self.target_port,
                self.type_ref.type_digest,
                self.routing_digests,
            ),
        )

    @property
    def storage_kind(self) -> GraphStorageKind:
        return self.type_ref.storage_kind


@dataclass(frozen=True, slots=True)
class ResearchExecutionBinding:
    graph_node_id: str
    ref: UnitRef
    graph: NoetriumUnit
    symbols: tuple[NoetriumUnit, ...]
    incoming_edges: tuple[ResearchInputBinding, ...]
    semantic_digest: str
    node_digest: str = field(init=False)
    _output_types_by_name: Mapping[str, NoetriumUnit] = field(
        init=False, repr=False, compare=False
    )
    _depends_on_node_ids: tuple[str, ...] = field(
        init=False, repr=False, compare=False
    )
    _upstream_refs: tuple[UnitRef, ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.graph_node_id != _graph_node_id(self.ref):
            raise ValueError("research execution compilation node identity drift")
        if type(self.graph) is not NoetriumUnit:
            raise TypeError("research execution compilation vertex requires NoetriumUnit")
        if type(self.symbols) is not tuple or any(
            type(value) is not NoetriumUnit for value in self.symbols
        ):
            raise TypeError("research execution compilation symbols must be typed")
        if type(self.incoming_edges) is not tuple or any(
            type(value) is not ResearchInputBinding
            for value in self.incoming_edges
        ):
            raise TypeError("compiled Research execution incoming edges must be typed")
        # The compiler feeds this internal type from the canonical routed
        # relation stream. Preserve that order; re-sorting here would duplicate
        # NoetriumUnit/NoetriumUnit canonicalization and add a log factor.
        ordered_edges = self.incoming_edges
        if len(ordered_edges) > 1:
            target_counts: dict[str, int] = {}
            for value in ordered_edges:
                if value.target_port is None:
                    continue
                target_counts[value.target_port] = (
                    target_counts.get(value.target_port, 0) + 1
                )
            for target_name, count in target_counts.items():
                port = self.graph.boundary.input(target_name)
                if (
                    port.mode in {GraphPortMode.ONE, GraphPortMode.OPTIONAL}
                    and count > 1
                ):
                    raise ValueError(
                        "research execution vertex single-valued input port has "
                        f"multiple bindings: node={self.graph_node_id} "
                        f"port={target_name} count={count}"
                    )
        require_sha256(
            self.semantic_digest,
            "research execution vertex semantic_digest",
        )
        if not ordered_edges:
            depends_on_node_ids = ()
            upstream_refs = ()
        elif len(ordered_edges) == 1:
            upstream = ordered_edges[0].upstream
            depends_on_node_ids = (_graph_node_id(upstream),)
            upstream_refs = (upstream,)
        else:
            depends_on_node_ids = tuple(
                dict.fromkeys(
                    _graph_node_id(edge.upstream)
                    for edge in ordered_edges
                )
            )
            upstream_refs = tuple(
                dict.fromkeys(edge.upstream for edge in ordered_edges)
            )
        object.__setattr__(self, "incoming_edges", ordered_edges)
        object.__setattr__(self, "_depends_on_node_ids", depends_on_node_ids)
        object.__setattr__(self, "_upstream_refs", upstream_refs)
        object.__setattr__(
            self,
            "node_digest",
            _projection_node_digest(
                self.graph_node_id,
                self.semantic_digest,
                depends_on_node_ids,
                tuple(edge.edge_digest for edge in ordered_edges),
            ),
        )
        outputs = self.graph.boundary.outputs
        object.__setattr__(
            self,
            "_output_types_by_name",
            (
                _EMPTY_TYPE_MAPPING
                if not outputs
                else MappingProxyType(
                    {output.name: output.type_ref for output in outputs}
                )
            ),
        )

    @property
    def node_id(self) -> str:
        return self.graph_node_id

    @property
    def source_path(self) -> tuple[str, ...]:
        return self.ref.path

    @property
    def depends_on_node_ids(self) -> tuple[str, ...]:
        return self._depends_on_node_ids

    def output_type(self, output_name: str) -> NoetriumUnit:
        try:
            return self._output_types_by_name[output_name]
        except KeyError as exc:
            raise KeyError(output_name) from exc

    def output_kind(self, output_name: str) -> GraphStorageKind:
        return self.output_type(output_name).storage_kind

    @property
    def incoming_dependency_digests(self) -> tuple[str, ...]:
        return tuple(value.edge_digest for value in self.incoming_edges)

    @property
    def upstream_refs(self) -> tuple[UnitRef, ...]:
        return self._upstream_refs


@dataclass(frozen=True, slots=True)
class ResearchCompilationView:
    """Single compiled projection over the canonical recursive Unit."""

    revision: ResearchGraphRevision
    portfolio: NoetriumUnit
    root: "_CompiledScope"
    scopes: Mapping[tuple[str, ...], "_CompiledScope"]
    nodes_by_id: Mapping[str, "_CompiledNode"]
    _canonical_relations: tuple["_RoutedRelation", ...]
    incoming_relation_index: Mapping[str, tuple["_RoutedRelation", ...]]
    relation_rank_by_identity: Mapping[int, int]
    _bindings: tuple[ResearchExecutionBinding, ...] | None = field(
        init=False, default=None, repr=False, compare=False
    )
    _topological_node_ids: tuple[str, ...] | None = field(
        init=False, default=None, repr=False, compare=False
    )
    _execution_unit: NoetriumUnit | None = field(
        init=False, default=None, repr=False, compare=False
    )
    _semantic_digest_cache: dict[UnitRef, str] = field(
        init=False, default_factory=dict, repr=False, compare=False
    )
    _binding_by_ref_cache: dict[UnitRef, ResearchExecutionBinding] = field(
        init=False, default_factory=dict, repr=False, compare=False
    )
    _flat_lock: RLock = field(
        init=False, default_factory=RLock, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.revision) is not ResearchGraphRevision:
            raise TypeError(
                "research execution compilation requires ResearchGraphRevision"
            )
        if type(self.portfolio) is not NoetriumUnit:
            raise TypeError(
                "research execution compilation requires NoetriumUnit"
            )
        if not self.portfolio.has_trait("research.portfolio"):
            raise ValueError(
                "research execution compilation requires research.portfolio root"
            )
        if self.revision.portfolio_id != self.portfolio.unit_id:
            raise ValueError("compiled Research execution portfolio identity drift")
        if self.revision.portfolio_digest != self.portfolio.unit_digest:
            raise ValueError("compiled Research execution portfolio digest drift")
        root_path = (self.portfolio.unit_id,)
        if self.root.path != root_path:
            raise ValueError("research execution compilation lost root scope")
        if self.root.node_count < 1:
            raise ValueError(
                "research portfolio contains no executable graph vertices"
            )

    def _ensure_flat_projection(self) -> None:
        if self._bindings is not None:
            return
        with self._flat_lock:
            if self._bindings is not None:
                return
            bindings, topological = _materialize_flat_projection(self)
            object.__setattr__(self, "_bindings", bindings)
            object.__setattr__(
                self, "_topological_node_ids", topological
            )
            for binding in bindings:
                self._semantic_digest_cache[binding.ref] = binding.semantic_digest
                self._binding_by_ref_cache[binding.ref] = binding

    @property
    def bindings(self) -> tuple[ResearchExecutionBinding, ...]:
        self._ensure_flat_projection()
        assert self._bindings is not None
        return self._bindings

    @property
    def routing_relations(self) -> tuple["_RoutedRelation", ...]:
        return self._canonical_relations

    @property
    def topological_node_ids(self) -> tuple[str, ...]:
        self._ensure_flat_projection()
        assert self._topological_node_ids is not None
        return self._topological_node_ids

    @staticmethod
    def _execution_cost_projection(
        binding: ResearchExecutionBinding,
    ) -> tuple[bool, int]:
        """Derive disposable scheduling cost from the source Unit only."""

        graph = binding.graph
        boundary = graph.boundary
        effect_count = len(boundary.units("effect"))
        state_count = len(boundary.units("state"))
        structural_units = graph.member_walk_count
        symbol_count = len(binding.symbols)
        implementation_count = sum(
            1
            for symbol in binding.symbols
            if symbol.implementation is not None
        )
        platform_symbol_count = symbol_count - implementation_count
        static_cost = max(
            1,
            structural_units
            + symbol_count
            + (2 * state_count)
            + (4 * implementation_count)
            + (2 * platform_symbol_count)
            + (16 * effect_count),
        )
        return effect_count > 0, static_cost

    @property
    def execution_unit(self) -> NoetriumUnit:
        cached = self._execution_unit
        if cached is not None:
            return cached
        vertices = []
        for binding in self.bindings:
            effectful, static_cost = self._execution_cost_projection(binding)
            vertices.append(
                execution_vertex(
                    binding.node_id,
                    binding.semantic_digest,
                    source_path=binding.source_path,
                    effectful=effectful,
                    static_cost=static_cost,
                )
            )
        vertices = tuple(vertices)
        flows = tuple(
            execution_flow(
                relation.source_node_ids,
                relation.target_node_ids,
                routing_digests=relation.routing_digests,
                trigger=relation.trigger,
                progress=relation.progress,
            )
            for relation in self.routing_relations
        )
        value = execution_graph(
            self.portfolio.unit_id,
            self.revision.revision_digest,
            vertices,
            flows,
        )
        object.__setattr__(self, "_execution_unit", value)
        return value

    @property
    def graph_digest(self) -> str:
        return self.execution_unit.semantic_digest

    @property
    def graph_id(self) -> str:
        return self.portfolio.unit_id

    @property
    def research_revision_digest(self) -> str:
        return self.revision.revision_digest

    @property
    def scope_index(self) -> Mapping[tuple[str, ...], "_CompiledScope"]:
        return self.scopes

    @property
    def root_scope(self) -> "_CompiledScope":
        return self.root

    def scope(self, path: tuple[str, ...]) -> "_CompiledScope":
        try:
            return self.scopes[path]
        except KeyError as exc:
            raise KeyError(path) from exc

    def _compiled_node_for_ref(self, ref: UnitRef) -> "_CompiledNode":
        node_id = _graph_node_id(ref)
        try:
            node = self.nodes_by_id[node_id]
        except KeyError as exc:
            raise KeyError(node_id) from exc
        if node.ref != ref:
            raise KeyError(node_id)
        return node

    def _compiled_node_for_id(self, node_id: str) -> "_CompiledNode":
        if type(node_id) is not str or not node_id:
            raise KeyError(node_id)
        try:
            return self.nodes_by_id[node_id]
        except KeyError as exc:
            raise KeyError(node_id) from exc

    def scope_for_node(self, graph_node_id: str) -> "_CompiledScope":
        node = self._compiled_node_for_id(graph_node_id)
        return self.scope(node.ref.parent_path)

    def vertex(self, node_id: str) -> ResearchExecutionBinding:
        return self.binding(node_id)

    def incoming_relations(
        self,
        node_ids: tuple[str, ...],
    ) -> tuple["_RoutedRelation", ...]:
        if (
            type(node_ids) is not tuple
            or not node_ids
            or any(
                type(node_id) is not str or not node_id
                for node_id in node_ids
            )
        ):
            raise TypeError(
                "research execution relation query requires non-empty "
                "text tuple"
            )
        if len(node_ids) != len(set(node_ids)):
            raise ValueError(
                "research execution relation query node ids must be unique"
            )
        unknown = tuple(
            node_id
            for node_id in node_ids
            if node_id not in self.nodes_by_id
        )
        if unknown:
            raise KeyError(unknown[0] if len(unknown) == 1 else unknown)

        index = self.incoming_relation_index
        if len(node_ids) == 1:
            return index.get(node_ids[0], ())

        lists = tuple(index.get(node_id, ()) for node_id in node_ids)
        incidence = sum(len(rows) for rows in lists)
        if incidence == 0:
            return ()

        relation_count = len(self._canonical_relations)
        # Canonical union of k sorted relation-rank lists. Sparse queries use
        # k-way merge; dense queries scan the canonical universe once.
        merge_factor = max(1, (len(node_ids) - 1).bit_length())
        if incidence * merge_factor >= relation_count:
            selected = set(node_ids)
            return tuple(
                relation
                for relation in self._canonical_relations
                if any(
                    target in selected
                    for target in relation.target_node_ids
                )
            )

        rank = self.relation_rank_by_identity
        heap: list[tuple[int, int, int, _RoutedRelation]] = []
        for list_index, rows in enumerate(lists):
            if not rows:
                continue
            relation = rows[0]
            heapq.heappush(
                heap,
                (
                    rank[id(relation)],
                    list_index,
                    0,
                    relation,
                ),
            )
        result: list[_RoutedRelation] = []
        last_rank = -1
        while heap:
            relation_rank, list_index, offset, relation = heapq.heappop(
                heap
            )
            if relation_rank != last_rank:
                result.append(relation)
                last_rank = relation_rank
            next_offset = offset + 1
            rows = lists[list_index]
            if next_offset < len(rows):
                next_relation = rows[next_offset]
                heapq.heappush(
                    heap,
                    (
                        rank[id(next_relation)],
                        list_index,
                        next_offset,
                        next_relation,
                    ),
                )
        return tuple(result)

    def _semantic_digest_for_ref(
        self,
        ref: UnitRef,
    ) -> str:
        cached = self._semantic_digest_cache.get(ref)
        if cached is not None:
            return cached

        # Iterative post-order over the exact ancestor closure. This preserves
        # point-query incrementality without recursion-depth limits.
        stack: list[
            tuple[
                UnitRef,
                bool,
                tuple["_RoutedRelation", ...] | None,
            ]
        ] = [(ref, False, None)]
        active: set[UnitRef] = set()
        while stack:
            current, expanded, incoming = stack.pop()
            if current in self._semantic_digest_cache:
                active.discard(current)
                continue
            if not expanded:
                if current in active:
                    raise ValueError(
                        "top-level executable Research Graph cycle must be "
                        "enclosed in a semantic subgraph"
                    )
                self._compiled_node_for_ref(current)
                incoming = self.incoming_relations(
                    (_graph_node_id(current),)
                )
                active.add(current)
                stack.append((current, True, incoming))
                upstream_refs = tuple(
                    dict.fromkeys(
                        source.ref
                        for edge in incoming
                        for source in edge.sources
                    )
                )
                for upstream_ref in reversed(upstream_refs):
                    if upstream_ref in self._semantic_digest_cache:
                        continue
                    if upstream_ref in active:
                        raise ValueError(
                            "top-level executable Research Graph cycle must "
                            "be enclosed in a semantic subgraph"
                        )
                    stack.append((upstream_ref, False, None))
                continue

            assert incoming is not None
            node = self._compiled_node_for_ref(current)
            upstream = {
                source.ref: self._semantic_digest_cache[source.ref]
                for edge in incoming
                for source in edge.sources
            }
            _rows, digest = _execution_binding_semantics(
                current,
                node.graph,
                node.symbols,
                incoming,
                upstream,
            )
            self._semantic_digest_cache[current] = digest
            active.remove(current)

        return self._semantic_digest_cache[ref]

    def binding(self, graph_node_id: str) -> ResearchExecutionBinding:
        return self.binding_by_ref(
            _graph_ref_from_node_id(graph_node_id)
        )

    def binding_by_ref(self, ref: UnitRef) -> ResearchExecutionBinding:
        if type(ref) is not UnitRef:
            raise KeyError(ref)
        # The compiled Unit is immutable. Bindings remain valid for its entire
        # lifetime; reading one twice must not replay its expensive upstream
        # digest projection. The existing flat lock serializes a cold materialization.
        cached = self._binding_by_ref_cache.get(ref)
        if cached is not None:
            return cached
        with self._flat_lock:
            cached = self._binding_by_ref_cache.get(ref)
            if cached is not None:
                return cached
            node = self._compiled_node_for_ref(ref)
            incoming = self.incoming_relations((_graph_node_id(ref),))
            upstream = {
                source.ref: self._semantic_digest_for_ref(source.ref)
                for edge in incoming
                for source in edge.sources
            }
            result = _materialize_execution_binding(
                node.ref,
                node.graph,
                node.symbols,
                incoming,
                upstream_semantic_digests=upstream,
            )
            self._binding_by_ref_cache[ref] = result
            self._semantic_digest_cache[ref] = result.semantic_digest
            return result

    def descendants(self, root_vertex_id: str) -> tuple[str, ...]:
        index = execution_graph_index(self.execution_unit)
        if root_vertex_id not in index.by_id:
            raise KeyError(root_vertex_id)

        seen: set[str] = {root_vertex_id}
        seen_relations: set[int] = set()
        ready: deque[str] = deque()

        def enqueue_targets(source_id: str) -> None:
            for relation_index in index.outgoing_relation_indices[source_id]:
                if relation_index in seen_relations:
                    continue
                seen_relations.add(relation_index)
                ready.extend(index.relation_targets[relation_index])

        enqueue_targets(root_vertex_id)
        descendants: list[str] = []
        while ready:
            node_id = ready.popleft()
            if node_id in seen:
                continue
            seen.add(node_id)
            descendants.append(node_id)
            enqueue_targets(node_id)
        return tuple(descendants)



@dataclass(frozen=True, slots=True)
class _RoutedSource:
    ref: UnitRef
    port_name: str | None
    type_ref: NoetriumUnit
    routing_digests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RoutedTarget:
    ref: UnitRef
    port_name: str | None
    type_ref: NoetriumUnit
    routing_digests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RoutedRelation:
    sources: tuple[_RoutedSource, ...]
    targets: tuple[_RoutedTarget, ...]
    routing_digests: tuple[str, ...]
    trigger: GraphTrigger = GraphTrigger()
    progress: GraphProgressKind | None = None
    source_node_ids: tuple[str, ...] = field(init=False)
    target_node_ids: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        source_ids = tuple(
            dict.fromkeys(_graph_node_id(source.ref) for source in self.sources)
        )
        target_ids = tuple(
            dict.fromkeys(_graph_node_id(target.ref) for target in self.targets)
        )
        object.__setattr__(self, "source_node_ids", source_ids)
        object.__setattr__(self, "target_node_ids", target_ids)


@dataclass(frozen=True, slots=True)
class _CompiledNode:
    ref: UnitRef
    graph: NoetriumUnit
    symbols: tuple[NoetriumUnit, ...]

    def __post_init__(self) -> None:
        _graph_node_id(self.ref)


@dataclass(frozen=True, slots=True)
class _CompiledScope:
    """Immutable recursive execution projection for one transparent scope."""

    path: tuple[str, ...]
    inputs: Mapping[str, tuple[_RoutedTarget, ...]]
    outputs: Mapping[str, tuple[_RoutedSource, ...]]
    entries: tuple[UnitRef, ...]
    exits: tuple[UnitRef, ...]
    direct_nodes: tuple[_CompiledNode, ...]
    children: tuple["_CompiledScope", ...]
    local_relations: tuple[_RoutedRelation, ...]
    node_count: int = field(init=False)
    relation_count: int = field(init=False)
    incoming_relation_index: Mapping[str, tuple[_RoutedRelation, ...]] = field(
        init=False, repr=False, compare=False
    )
    outgoing_relation_index: Mapping[str, tuple[_RoutedRelation, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_count",
            len(self.direct_nodes) + sum(child.node_count for child in self.children),
        )
        object.__setattr__(
            self, "relation_count",
            len(self.local_relations)
            + sum(child.relation_count for child in self.children),
        )
        incoming: dict[str, list[_RoutedRelation]] = {}
        outgoing: dict[str, list[_RoutedRelation]] = {}
        for relation in self.local_relations:
            for node_id in relation.target_node_ids:
                incoming.setdefault(node_id, []).append(relation)
            for node_id in relation.source_node_ids:
                outgoing.setdefault(node_id, []).append(relation)
        object.__setattr__(
            self,
            "incoming_relation_index",
            MappingProxyType(
                {node_id: tuple(rows) for node_id, rows in incoming.items()}
            ),
        )
        object.__setattr__(
            self,
            "outgoing_relation_index",
            MappingProxyType(
                {node_id: tuple(rows) for node_id, rows in outgoing.items()}
            ),
        )

    @property
    def direct_refs(self) -> tuple[UnitRef, ...]:
        return tuple(node.ref for node in self.direct_nodes)

    @property
    def child_scope_paths(self) -> tuple[tuple[str, ...], ...]:
        return tuple(child.path for child in self.children)




_SCOPE_COMPILATION_CACHE: OrderedDict[
    tuple[object, ...],
    _CompiledScope,
] = OrderedDict()
_SCOPE_COMPILATION_CACHE_LOCK = RLock()
_SCOPE_COMPILATION_CACHE_NODE_BUDGET = 131_072
_SCOPE_COMPILATION_CACHE_MAX_SCOPE_NODES = 2_048
_SCOPE_COMPILATION_CACHE_NODES = 0

_BINDING_CACHE: OrderedDict[tuple[object, ...], ResearchExecutionBinding] = OrderedDict()
_BINDING_CACHE_LOCK = RLock()
_BINDING_CACHE_LIMIT = 131_072


def _binding_cache_get(key: tuple[object, ...]):
    with _BINDING_CACHE_LOCK:
        value = _BINDING_CACHE.get(key)
        if value is not None:
            _BINDING_CACHE.move_to_end(key)
        return value


def _binding_cache_put(
    key: tuple[object, ...],
    value: ResearchExecutionBinding,
) -> None:
    with _BINDING_CACHE_LOCK:
        _BINDING_CACHE[key] = value
        _BINDING_CACHE.move_to_end(key)
        while len(_BINDING_CACHE) > _BINDING_CACHE_LIMIT:
            _BINDING_CACHE.popitem(last=False)


def _scope_compilation_cache_key(
    graph: NoetriumUnit,
    path: tuple[str, ...],
    visible: Mapping[str, NoetriumUnit],
) -> tuple[object, ...]:
    # Compilation emits absolute UnitRefs, so alpha-semantic equality is not
    # sufficient for cache reuse. Keep the exact immutable graph object in the
    # key to prevent id reuse and only reuse structurally shared subtrees.
    return (
        path,
        id(graph),
        graph,
        tuple(
            (symbol_id, symbol.symbol_digest)
            for symbol_id, symbol in visible.items()
        ),
    )


def _scope_compilation_cache_get(key):
    with _SCOPE_COMPILATION_CACHE_LOCK:
        cached = _SCOPE_COMPILATION_CACHE.get(key)
        if cached is not None:
            _SCOPE_COMPILATION_CACHE.move_to_end(key)
        return cached


def _scope_compilation_cache_put(key, value: _CompiledScope) -> None:
    global _SCOPE_COMPILATION_CACHE_NODES
    cost = value.node_count
    if cost > _SCOPE_COMPILATION_CACHE_MAX_SCOPE_NODES:
        return
    with _SCOPE_COMPILATION_CACHE_LOCK:
        previous = _SCOPE_COMPILATION_CACHE.pop(key, None)
        if previous is not None:
            _SCOPE_COMPILATION_CACHE_NODES -= previous.node_count
        _SCOPE_COMPILATION_CACHE[key] = value
        _SCOPE_COMPILATION_CACHE_NODES += cost
        while (
            _SCOPE_COMPILATION_CACHE
            and _SCOPE_COMPILATION_CACHE_NODES
            > _SCOPE_COMPILATION_CACHE_NODE_BUDGET
        ):
            _old_key, old = _SCOPE_COMPILATION_CACHE.popitem(last=False)
            _SCOPE_COMPILATION_CACHE_NODES -= old.node_count


def _compile_hierarchy(
    revision: ResearchGraphRevision,
    portfolio: NoetriumUnit,
) -> ResearchCompilationView:
    """Compile the recursive Unit directly into the single runtime view."""

    graph = portfolio
    path = (graph.unit_id,)
    scopes: dict[tuple[str, ...], _CompiledScope] = {}
    root_visible = {row.symbol_id: row for row in graph.symbols}
    stack: list[tuple[NoetriumUnit, tuple[str, ...], Mapping[str, NoetriumUnit], bool, object | None]] = [
        (graph, path, root_visible, False, None)
    ]

    def child_visible_symbols(
        parent_visible: Mapping[str, NoetriumUnit],
        child: NoetriumUnit,
    ) -> dict[str, NoetriumUnit]:
        # Both sequences are canonical by symbol_id at the Graph boundary.
        # Merge them directly instead of concatenating and sorting again.
        inherited = child.symbol_ids
        owned = child.symbols
        visible: dict[str, NoetriumUnit] = {}
        i = 0
        j = 0
        while i < len(inherited) or j < len(owned):
            inherited_id = (
                inherited[i] if i < len(inherited) else None
            )
            owned_id = (
                owned[j].symbol_id if j < len(owned) else None
            )
            if inherited_id is not None and inherited_id == owned_id:
                raise ValueError(
                    f"graph {child.unit_id!r} shadows bound symbol "
                    f"{owned_id!r}"
                )
            if (
                owned_id is None
                or (
                    inherited_id is not None
                    and inherited_id < owned_id
                )
            ):
                assert inherited_id is not None
                try:
                    visible[inherited_id] = parent_visible[inherited_id]
                except KeyError as exc:
                    raise ValueError(
                        f"graph {child.unit_id!r} binds unknown parent symbol "
                        f"{inherited_id!r}"
                    ) from exc
                i += 1
            else:
                assert owned_id is not None
                visible[owned_id] = owned[j]
                j += 1
        return visible

    type_assignability_cache: dict[tuple[str, str], bool] = {}

    def routed_types_compatible(
        sources: tuple[_RoutedSource, ...],
        targets: tuple[_RoutedTarget, ...],
    ) -> bool:
        source_types = {
            row.type_ref.unit_digest: row.type_ref
            for row in sources
            if row.port_name is not None
        }
        target_types = {
            row.type_ref.unit_digest: row.type_ref
            for row in targets
            if row.port_name is not None
        }
        for source_digest, source_type in source_types.items():
            for target_digest, target_type in target_types.items():
                key = (source_digest, target_digest)
                compatible = type_assignability_cache.get(key)
                if compatible is None:
                    compatible = source_type.is_assignable_to(target_type)
                    type_assignability_cache[key] = compatible
                if not compatible:
                    return False
        return True

    while stack:
        current, current_path, current_visible, exiting, cache_key = stack.pop()
        if not exiting:
            cache_key = _scope_compilation_cache_key(
                current,
                current_path,
                current_visible,
            )
            cached = (
                None
                if current_path == path
                else _scope_compilation_cache_get(cache_key)
            )
            if cached is not None:
                scopes[current_path] = cached
                continue
            stack.append(
                (current, current_path, current_visible, True, cache_key)
            )
            nested = []
            for child in current.members:
                if not graph_is_transparent_container(child):
                    continue
                nested.append(
                    (
                        child,
                        current_path + (child.unit_id,),
                        child_visible_symbols(current_visible, child),
                        False,
                        None,
                    )
                )
            stack.extend(reversed(nested))
            continue

        child_scopes = {
            child.unit_id: scopes[current_path + (child.unit_id,)]
            for child in current.members
            if graph_is_transparent_container(child)
        }
        inputs: dict[str, list[_RoutedTarget]] = {
            row.name: [] for row in current.boundary.inputs
        }
        outputs: dict[str, list[_RoutedSource]] = {
            row.name: [] for row in current.boundary.outputs
        }
        candidate_entries: list[UnitRef] = []
        candidate_exits: list[UnitRef] = []
        direct_nodes: dict[str, _CompiledNode] = {}

        for child in current.members:
            nested = child_scopes.get(child.unit_id)
            if nested is not None:
                candidate_entries.extend(nested.entries)
                candidate_exits.extend(nested.exits)
                continue
            ref = UnitRef(current_path + (child.unit_id,))
            visible = child_visible_symbols(current_visible, child)
            node = _CompiledNode(
                ref,
                child,
                tuple(visible.values()),
            )
            direct_nodes[child.unit_id] = node
            candidate_entries.append(ref)
            candidate_exits.append(ref)

        def source_endpoint(
            endpoint: NoetriumUnit,
        ) -> tuple[_RoutedSource, ...]:
            if endpoint.child_id is None:
                raise ValueError(
                    "graph boundary input is not an executable source"
                )
            nested = child_scopes.get(endpoint.child_id)
            if nested is not None:
                if endpoint.port_name is None:
                    return tuple(
                        _RoutedSource(ref, None, CONTROL_TYPE)
                        for ref in nested.exits
                    )
                try:
                    return nested.outputs[endpoint.port_name]
                except KeyError as exc:
                    raise ValueError(
                        f"nested graph {endpoint.child_id!r} has no output "
                        f"{endpoint.port_name!r}"
                    ) from exc
            try:
                node = direct_nodes[endpoint.child_id]
            except KeyError as exc:
                raise ValueError(
                    "research flow references unknown source graph "
                    f"{endpoint.child_id!r}"
                ) from exc
            if endpoint.port_name is None:
                return (_RoutedSource(node.ref, None, CONTROL_TYPE),)
            return (
                _RoutedSource(
                    node.ref,
                    endpoint.port_name,
                    node.graph.boundary.output(endpoint.port_name).type_ref,
                ),
            )

        def target_endpoint(
            endpoint: NoetriumUnit,
        ) -> tuple[_RoutedTarget, ...]:
            if endpoint.child_id is None:
                raise ValueError(
                    "graph boundary output is not an executable target"
                )
            nested = child_scopes.get(endpoint.child_id)
            if nested is not None:
                if endpoint.port_name is None:
                    return tuple(
                        _RoutedTarget(ref, None, CONTROL_TYPE)
                        for ref in nested.entries
                    )
                try:
                    return nested.inputs[endpoint.port_name]
                except KeyError as exc:
                    raise ValueError(
                        f"nested graph {endpoint.child_id!r} has no input "
                        f"{endpoint.port_name!r}"
                    ) from exc
            try:
                node = direct_nodes[endpoint.child_id]
            except KeyError as exc:
                raise ValueError(
                    "research flow references unknown target graph "
                    f"{endpoint.child_id!r}"
                ) from exc
            if endpoint.port_name is None:
                return (_RoutedTarget(node.ref, None, CONTROL_TYPE),)
            return (
                _RoutedTarget(
                    node.ref,
                    endpoint.port_name,
                    node.graph.boundary.input(endpoint.port_name).type_ref,
                ),
            )

        local_relations: list[_RoutedRelation] = []
        for relation in current.relations:
            if relation.relation_id != RELATION_FLOW:
                continue
            digest = relation.relation_digest
            source_boundary = any(
                endpoint.child_id is None for endpoint in relation.sources
            )
            target_boundary = any(
                endpoint.child_id is None for endpoint in relation.targets
            )
            if source_boundary or target_boundary:
                if len(relation.sources) != 1 or len(relation.targets) != 1:
                    raise ValueError(
                        "graph boundary routing must be unary; hyperrelations "
                        "belong between executable children"
                    )
                relation_source = relation.sources[0]
                relation_target = relation.targets[0]
                if source_boundary and target_boundary:
                    raise ValueError(
                        "transparent graph boundary passthrough requires an "
                        "explicit child graph"
                    )
                if source_boundary:
                    if relation_source.port_name is None:
                        raise ValueError(
                            "research graph boundary input requires a port"
                        )
                    for target in target_endpoint(relation_target):
                        inputs[relation_source.port_name].append(
                            _RoutedTarget(
                                target.ref,
                                target.port_name,
                                target.type_ref,
                                target.routing_digests + (digest,),
                            )
                        )
                    continue
                if target_boundary:
                    if relation_target.port_name is None:
                        raise ValueError(
                            "research graph boundary output requires a port"
                        )
                    for source in source_endpoint(relation_source):
                        outputs[relation_target.port_name].append(
                            _RoutedSource(
                                source.ref,
                                source.port_name,
                                source.type_ref,
                                source.routing_digests + (digest,),
                            )
                        )
                    continue

            routed_sources = tuple(
                item
                for endpoint in relation.sources
                for item in source_endpoint(endpoint)
            )
            routed_targets = tuple(
                item
                for endpoint in relation.targets
                for item in target_endpoint(endpoint)
            )
            if not routed_types_compatible(
                routed_sources,
                routed_targets,
            ):
                raise ValueError("research flow type mismatch")
            routing = tuple(
                dict.fromkeys(
                    (
                        digest,
                        *(
                            routed
                            for item in routed_sources
                            for routed in item.routing_digests
                        ),
                        *(
                            routed
                            for item in routed_targets
                            for routed in item.routing_digests
                        ),
                    )
                )
            )
            local_relations.append(
                _RoutedRelation(
                    routed_sources,
                    routed_targets,
                    routing,
                    relation.trigger,
                    relation.progress,
                )
            )

        incoming_refs = {
            target.ref
            for relation in local_relations
            for target in relation.targets
        }
        outgoing_refs = {
            source.ref
            for relation in local_relations
            for source in relation.sources
        }
        compiled_scope = _CompiledScope(
            current_path,
            MappingProxyType(
                {name: tuple(rows) for name, rows in inputs.items()}
            ),
            MappingProxyType(
                {name: tuple(rows) for name, rows in outputs.items()}
            ),
            tuple(
                ref
                for ref in candidate_entries
                if ref not in incoming_refs
            ),
            tuple(
                ref
                for ref in candidate_exits
                if ref not in outgoing_refs
            ),
            tuple(direct_nodes.values()),
            tuple(
                child_scopes[child.unit_id]
                for child in current.members
                if child.unit_id in child_scopes
            ),
            tuple(local_relations),
        )
        scopes[current_path] = compiled_scope
        if current_path != path and cache_key is not None:
            _scope_compilation_cache_put(cache_key, compiled_scope)

    root = scopes[path]
    scope_index: dict[tuple[str, ...], _CompiledScope] = {}
    pending = [root]
    while pending:
        scope = pending.pop()
        if scope.path in scope_index:
            raise ValueError(
                f"duplicate compiled research scope: {scope.path!r}"
            )
        scope_index[scope.path] = scope
        pending.extend(reversed(scope.children))
    nodes_by_id: dict[str, _CompiledNode] = {}
    relations: list[_RoutedRelation] = []
    incoming_relation_index: dict[str, list[_RoutedRelation]] = {}
    relation_rank_by_identity: dict[int, int] = {}
    for scope in scope_index.values():
        for node in scope.direct_nodes:
            node_id = _graph_node_id(node.ref)
            if node_id in nodes_by_id:
                raise ValueError(
                    f"duplicate compiled research graph: {node.ref.path!r}"
                )
            nodes_by_id[node_id] = node
        for relation in scope.local_relations:
            relation_rank_by_identity[id(relation)] = len(relations)
            relations.append(relation)
            for node_id in relation.target_node_ids:
                incoming_relation_index.setdefault(node_id, []).append(
                    relation
                )
    return ResearchCompilationView(
        revision,
        portfolio,
        root,
        MappingProxyType(scope_index),
        MappingProxyType(nodes_by_id),
        tuple(relations),
        MappingProxyType(
            {
                node_id: tuple(rows)
                for node_id, rows in incoming_relation_index.items()
            }
        ),
        MappingProxyType(relation_rank_by_identity),
    )


def _scope_children_in_graph_order(
    scope: _CompiledScope,
) -> tuple[tuple[bool, object], ...]:
    """Merge direct executable children and transparent child scopes linearly."""

    direct = scope.direct_nodes
    children = scope.children
    rows: list[tuple[bool, object]] = []
    i = 0
    j = 0
    while i < len(direct) or j < len(children):
        direct_id = (
            direct[i].ref.path[-1] if i < len(direct) else None
        )
        child_id = (
            children[j].path[-1] if j < len(children) else None
        )
        if (
            child_id is None
            or (
                direct_id is not None
                and direct_id < child_id
            )
        ):
            rows.append((False, direct[i]))
            i += 1
        else:
            rows.append((True, children[j]))
            j += 1
    return tuple(rows)


def _flatten_compilation(
    compilation: ResearchCompilationView,
) -> dict[UnitRef, tuple[NoetriumUnit, tuple[NoetriumUnit, ...]]] :
    nodes: dict[
        UnitRef,
        tuple[NoetriumUnit, tuple[NoetriumUnit, ...]],
    ] = {}
    # Iterative preorder avoids Python recursion limits.  Every scope's direct
    # nodes and transparent child scopes are disjoint subsequences of the
    # already canonical NoetriumUnit.members order; linear merge restores
    # that order without sorting the flattened V-node set.
    stack: list[tuple[bool, object]] = [(True, compilation.root)]
    while stack:
        is_scope, value = stack.pop()
        if not is_scope:
            node = value
            assert isinstance(node, _CompiledNode)
            if node.ref in nodes:
                raise ValueError(
                    f"duplicate compiled research graph: {node.ref.path!r}"
                )
            nodes[node.ref] = (node.graph, node.symbols)
            continue

        scope = value
        assert isinstance(scope, _CompiledScope)
        ordered_children = _scope_children_in_graph_order(scope)
        stack.extend(reversed(ordered_children))
    return nodes


def _topological_refs(
    refs: tuple[UnitRef, ...],
    relations: tuple[_RoutedRelation, ...],
) -> tuple[UnitRef, ...]:
    """Canonical hypergraph-native ordering over compiled Unit references."""
    hyperrelations = tuple(
        (
            tuple(source.ref for source in relation.sources),
            tuple(target.ref for target in relation.targets),
        )
        for relation in relations
    )
    try:
        return deterministic_hypergraph_topological_order(refs, hyperrelations)
    except ValueError as exc:
        if str(exc) != "DAG contains a cycle":
            raise
        raise ValueError(
            "top-level executable Research Graph cycle must be enclosed in a "
            "semantic subgraph"
        ) from exc


def _execution_binding_semantics(
    ref: UnitRef,
    graph: NoetriumUnit,
    symbols: tuple[NoetriumUnit, ...],
    incoming_edges: tuple[_RoutedRelation, ...],
    upstream_semantic_digests: Mapping[UnitRef, str],
) -> tuple[tuple[ResearchInputBinding, ...], str]:
    incoming_rows = tuple(
        ResearchInputBinding(
            source.ref,
            source.port_name,
            target.port_name,
            source.type_ref,
            edge.routing_digests,
        )
        for edge in incoming_edges
        for target in edge.targets
        if target.ref == ref
        for source in edge.sources
    )
    incoming = incoming_rows
    bound_symbol_digests = tuple(
        row.symbol_digest
        for row in symbols
        if row.symbol_id in graph.symbol_ids
    )
    incoming_semantic_contract = tuple(
        (
            row.upstream.path,
            require_sha256(
                upstream_semantic_digests[row.upstream],
                "upstream research execution semantic digest",
            ),
            row.source_port,
            row.target_port,
            row.type_ref.type_digest,
            row.routing_digests,
        )
        for row in incoming
    )
    semantic_digest = _execution_semantic_digest(
        graph.semantic_digest,
        bound_symbol_digests,
        incoming_semantic_contract,
    )
    return incoming, semantic_digest


def _materialize_execution_binding(
    ref: UnitRef,
    graph: NoetriumUnit,
    symbols: tuple[NoetriumUnit, ...],
    incoming_edges: tuple[_RoutedRelation, ...],
    *,
    upstream_semantic_digests: Mapping[UnitRef, str],
) -> ResearchExecutionBinding:
    incoming, semantic_digest = _execution_binding_semantics(
        ref,
        graph,
        symbols,
        incoming_edges,
        upstream_semantic_digests,
    )
    binding_cache_key = (
        id(graph),
        ref.path,
        semantic_digest,
        tuple(symbol.symbol_digest for symbol in symbols),
        tuple(id(edge) for edge in incoming_edges),
    )
    cached_binding = _binding_cache_get(binding_cache_key)
    if cached_binding is not None:
        return cached_binding

    binding = ResearchExecutionBinding(
        _graph_node_id(ref),
        ref,
        graph,
        symbols,
        incoming,
        semantic_digest,
    )
    _binding_cache_put(binding_cache_key, binding)
    return binding


def _materialize_flat_projection(
    compilation: ResearchCompilationView,
) -> tuple[
    tuple[ResearchExecutionBinding, ...],
    tuple[str, ...],
]:
    compiled_nodes = _flatten_compilation(compilation)
    routed_relations = compilation.routing_relations
    refs = tuple(compiled_nodes)
    topological_refs = _topological_refs(refs, routed_relations)
    incoming_by_ref = {ref: [] for ref in refs}
    for edge in routed_relations:
        for target in edge.targets:
            incoming_by_ref[target.ref].append(edge)

    canonical_incoming_by_ref: dict[
        UnitRef, tuple[_RoutedRelation, ...]
    ] = {}
    for ref in refs:
        rows = incoming_by_ref[ref]
        # routed_relations are emitted by canonical scope preorder, and each
        # scope iterates NoetriumUnit.relations already sorted by relation
        # digest. Filtering that stream preserves canonical incoming order.
        canonical_incoming_by_ref[ref] = tuple(rows)

    # Materialize each binding in dependency order, exactly once. The previous
    # two-phase projection first computed every semantic digest and rebuilt
    # the same incoming edge objects + semantic digest a second time when
    # constructing the binding. The topological order makes all upstream
    # identities available, so construction and propagation share one pass.
    semantic_by_ref: dict[UnitRef, str] = {}
    binding_by_ref: dict[UnitRef, ResearchExecutionBinding] = {}
    for ref in topological_refs:
        incoming = canonical_incoming_by_ref[ref]
        upstream = {
            source.ref: semantic_by_ref[source.ref]
            for edge in incoming
            for source in edge.sources
        }
        binding = _materialize_execution_binding(
            ref,
            compiled_nodes[ref][0],
            compiled_nodes[ref][1],
            incoming,
            upstream_semantic_digests=upstream,
        )
        binding_by_ref[ref] = binding
        semantic_by_ref[ref] = binding.semantic_digest

    # External binding enumeration preserves canonical graph-node order,
    # independent of the dependency order used to construct the identities.
    ordered_bindings = tuple(binding_by_ref[ref] for ref in refs)
    known_ids = {binding.graph_node_id for binding in ordered_bindings}
    for binding in ordered_bindings:
        unknown = tuple(
            dependency
            for dependency in binding.depends_on_node_ids
            if dependency not in known_ids
        )
        if unknown:
            raise ValueError(
                "research execution binding depends on unknown vertex: "
                f"{unknown!r}"
            )
    topological_node_ids = tuple(
        _graph_node_id(ref) for ref in topological_refs
    )
    if (
        len(topological_node_ids) != len(ordered_bindings)
        or set(topological_node_ids) != known_ids
    ):
        raise ValueError(
            "research execution topological order must cover every vertex exactly once"
        )
    return ordered_bindings, topological_node_ids


def compile_research_portfolio_graph(
    revision: ResearchGraphRevision,
    portfolio: NoetriumUnit,
) -> ResearchCompilationView:
    if type(revision) is not ResearchGraphRevision:
        raise TypeError(
            "research graph compilation requires ResearchGraphRevision"
        )
    if type(portfolio) is not NoetriumUnit:
        raise TypeError(
            "research graph compilation requires NoetriumUnit"
        )
    if not portfolio.has_trait("research.portfolio"):
        raise ValueError(
            "research graph compilation requires research.portfolio root"
        )
    if revision.portfolio_id != portfolio.unit_id:
        raise ValueError(
            "research graph revision/portfolio identity mismatch"
        )
    if revision.portfolio_digest != portfolio.unit_digest:
        raise ValueError(
            "research graph revision/portfolio digest mismatch"
        )
    return _compile_hierarchy(revision, portfolio)


@runtime_checkable
class ResearchNodeExecutionPort(Protocol):
    def execute(
        self,
        context: TaskContextPort,
        node: ResearchExecutionBinding,
        *,
        deadline: Deadline | None,
    ) -> None: ...


class _ResearchGraphExecutor(ResearchGraphNodeExecutorPort):
    def __init__(self, compilation: ResearchCompilationView, execution: ResearchNodeExecutionPort) -> None:
        if type(compilation) is not ResearchCompilationView:
            raise TypeError("Research execution executor requires ResearchCompilationView")
        if not isinstance(execution, ResearchNodeExecutionPort):
            raise TypeError("Research execution node execution must satisfy ResearchNodeExecutionPort")
        self._compilation = compilation
        self._execution = execution

    def execute(
        self,
        context: TaskContextPort,
        node: NoetriumUnit,
        *,
        deadline: Deadline | None,
    ) -> None:
        binding = self._compilation.binding(execution_vertex_id(node))
        self._execution.execute(context, binding, deadline=deadline)


def bind_research_portfolio_scheduler(
    compilation: ResearchCompilationView,
    execution: ResearchNodeExecutionPort,
    *,
    execution_pool: ResearchExecutionPool,
    tenant_id: str | None = None,
    priority: ExecutionPriority = ExecutionPriority.NORMAL,
    task_group_id: str | None = None,
    execution_store: ResearchGraphExecutionStorePort,
    execution_id: str,
    lease_seconds: float = 30.0,
    scheduler_owner_id: str | None = None,
    selected_node_ids: tuple[str, ...] | None = None,
) -> ResearchGraphScheduler:
    return ResearchGraphScheduler(
        compilation.execution_unit,
        _ResearchGraphExecutor(compilation, execution),
        execution_pool=execution_pool,
        tenant_id=tenant_id,
        priority=priority,
        task_group_id=task_group_id,
        execution_store=execution_store,
        execution_id=execution_id,
        lease_seconds=lease_seconds,
        scheduler_owner_id=scheduler_owner_id,
        selected_node_ids=selected_node_ids,
    )


__all__ = [
    "ResearchCompilationView",
    "ResearchExecutionBinding",
    "ResearchInputBinding",
    "ResearchNodeExecutionPort",
    "bind_research_portfolio_scheduler",
    "compile_research_portfolio_graph",
]
