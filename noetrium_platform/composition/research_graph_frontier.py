from __future__ import annotations

from collections import OrderedDict
from collections.abc import Collection, Mapping

from noetrium_platform.foundation.kernel.structure import GraphTriggerKind
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
)
from noetrium_platform.research.execution.graph.api import (
    EXECUTION_PROJECTION_SCHEMA,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
    execution_dependency_source_node_ids,
    execution_dependency_trigger,
    execution_graph_index,
)

RESEARCH_GRAPH_FRONTIER_COMPLEXITY = ComplexityContract(
    algorithm_id="research.graph.frontier-maintenance.v3",
    implementation_digest=canonical_digest(
        (
            "research.graph.frontier-maintenance.v3",
            "hypergraph-incidence-transition-counters",
        )
    ),
    time_upper_bound=ComplexityBound.linear_sum(
        "graph_nodes",
        "graph_relations",
        "source_incidences",
        "target_incidences",
        "blocker_evidence",
    ),
    space_upper_bound=ComplexityBound.linear_sum(
        "graph_nodes",
        "graph_relations",
        "source_incidences",
        "target_incidences",
        "blocker_evidence",
    ),
    assumptions=(
        "the bound is amortized over one complete execution cut",
        "each relation incidence is initialized once and transitioned at most once",
        "blocker_evidence counts exact blocker-to-target evidence that must be retained",
    ),
    time_lower_bound=ComplexityBound.linear_sum(
        "graph_nodes",
        "graph_relations",
        "source_incidences",
        "target_incidences",
        "blocker_evidence",
    ),
)

_BLOCKING_STATES = {
    ResearchGraphNodeState.FAILED,
    ResearchGraphNodeState.BLOCKED,
    ResearchGraphNodeState.CANCELLED,
}


class ResearchGraphDependencyFrontier:
    """Incremental readiness over a non-authoritative execution projection.

    Initialization is O(V+E). Terminal updates touch only relations incident on
    the completed source; unrelated recursive research scopes are never rescanned.
    """

    def __init__(
        self,
        plan: NoetriumUnit,
        *,
        selected_node_ids: tuple[str, ...],
        terminal_results: Mapping[str, ResearchGraphNodeResult],
    ) -> None:
        if type(plan) is not NoetriumUnit or not plan.has_schema(
            EXECUTION_PROJECTION_SCHEMA
        ):
            raise TypeError(
                "dependency frontier requires execution.projection NoetriumUnit"
            )
        if type(selected_node_ids) is not tuple or not selected_node_ids:
            raise TypeError(
                "dependency frontier selected_node_ids must be non-empty tuple"
            )
        if any(
            type(node_id) is not str or not node_id.strip()
            for node_id in selected_node_ids
        ):
            raise TypeError(
                "dependency frontier selected_node_ids must contain text ids"
            )
        selected = set(selected_node_ids)
        plan_index = execution_graph_index(plan, selected_node_ids)
        try:
            by_id = {
                node_id: plan_index.by_id[node_id]
                for node_id in selected_node_ids
            }
        except KeyError as exc:
            raise ValueError(
                "dependency frontier selection differs from plan"
            ) from exc
        if any(node_id not in selected for node_id in terminal_results):
            raise ValueError(
                "dependency frontier terminal result is outside selected graph"
            )
        if any(
            not isinstance(row, ResearchGraphNodeResult)
            for row in terminal_results.values()
        ):
            raise TypeError(
                "dependency frontier terminal_results must contain typed results"
            )

        selected_relation_indices = {
            relation_index
            for node_id in by_id
            for relation_index in plan_index.incoming_relation_indices[node_id]
        }
        for relation_index in selected_relation_indices:
            if any(
                source not in selected
                for source in plan_index.relation_sources[relation_index]
            ):
                raise ValueError(
                    "dependency frontier requires dependency-closed selection"
                )

        self._nodes = by_id
        self._results = dict(terminal_results)
        self._terminal = set(terminal_results)
        self._in_flight: set[str] = set()
        # OrderedDict is the canonical O(1) ordered-set primitive here. The
        # scheduler rotates only the bounded prefix it inspects, so a wide
        # frontier never pays an O(R log R) global sort on every scheduling turn.
        self._ready: OrderedDict[str, None] = OrderedDict()
        self._newly_ready: OrderedDict[str, None] = OrderedDict()
        self._blocked_by: dict[str, set[str]] = {}
        # A newly impossible target is an event, not a persistent request to
        # repeatedly write the same BLOCKED row on every scheduler tick.
        # The queue stores no second graph truth: values remain derived from
        # the exact relation blocker sets until drained.
        self._newly_blocked: OrderedDict[str, None] = OrderedDict()
        self._relations = plan_index.relations
        self._incoming = {
            node_id: tuple(plan_index.incoming_relation_indices[node_id])
            for node_id in selected_node_ids
        }
        self._outgoing = {
            node_id: tuple(plan_index.outgoing_relation_indices[node_id])
            for node_id in selected_node_ids
        }
        self._relation_sources = tuple(
            frozenset(sources)
            for sources in plan_index.relation_sources
        )
        self._relation_targets = tuple(
            tuple(target for target in targets if target in selected)
            for targets in plan_index.relation_targets
        )
        self._relation_thresholds = tuple(
            self._threshold(relation)
            for relation in self._relations
        )
        self._relation_succeeded = [0] * len(self._relations)
        self._relation_unresolved = [
            len(sources) for sources in self._relation_sources
        ]
        self._relation_blockers = [
            set() for _relation in self._relations
        ]
        # 0=pending, 1=satisfied, 2=impossible. Node readiness is maintained
        # from relation transitions instead of rescanning every incoming
        # relation whenever one source finishes.
        self._relation_status = [0] * len(self._relations)
        self._node_unsatisfied = {
            node_id: len(self._incoming[node_id])
            for node_id in selected_node_ids
        }

        # Seed relation counters from durable terminal evidence without
        # propagating node deltas until every relation has its final initial
        # state. This keeps initialization linear in the graph projection.
        for node_id, result in self._results.items():
            self._record_relation_terminal(
                node_id,
                result.state,
                propagate=False,
            )
        for index in range(len(self._relations)):
            status = self._relation_status_value(index)
            self._relation_status[index] = status
            if status == 1:
                for target in self._relation_targets[index]:
                    self._decrement_unsatisfied(target)
            elif status == 2:
                blockers = self._relation_blockers[index]
                for target in self._relation_targets[index]:
                    self._blocked_by.setdefault(target, set()).update(blockers)
                    if target not in self._terminal:
                        self._newly_blocked[target] = None
        # Blocker evidence is a live-frontier projection, not historical truth.
        # Seeded terminal nodes already carry their durable result evidence and
        # must not stay in the scan set for every later scheduling turn.
        for node_id in self._terminal:
            self._blocked_by.pop(node_id, None)
            self._newly_blocked.pop(node_id, None)
        for node_id in selected_node_ids:
            self._refresh_node_ready(node_id)

    @staticmethod
    def _threshold(relation: NoetriumUnit) -> int:
        source_count = len(set(execution_dependency_source_node_ids(relation)))
        trigger = execution_dependency_trigger(relation)
        if trigger.kind is GraphTriggerKind.ALL:
            return source_count
        if trigger.kind is GraphTriggerKind.ANY:
            return 1
        return int(trigger.quorum)

    def _relation_status_value(self, index: int) -> int:
        threshold = self._relation_thresholds[index]
        succeeded = self._relation_succeeded[index]
        if succeeded >= threshold:
            return 1
        if succeeded + self._relation_unresolved[index] < threshold:
            return 2
        return 0

    def _decrement_unsatisfied(self, node_id: str) -> None:
        remaining = self._node_unsatisfied[node_id] - 1
        if remaining < 0:
            raise RuntimeError(
                "dependency frontier node unsatisfied counter underflow"
            )
        self._node_unsatisfied[node_id] = remaining

    def _refresh_node_ready(self, node_id: str) -> None:
        if (
            node_id in self._terminal
            or node_id in self._in_flight
            or self._node_unsatisfied[node_id] != 0
        ):
            self._ready.pop(node_id, None)
            self._newly_ready.pop(node_id, None)
            return
        if node_id not in self._ready:
            self._ready[node_id] = None
            self._newly_ready[node_id] = None

    def _record_relation_terminal(
        self,
        node_id: str,
        state: ResearchGraphNodeState,
        *,
        propagate: bool,
    ) -> None:
        for index in self._outgoing[node_id]:
            if node_id not in self._relation_sources[index]:
                continue
            previous_status = self._relation_status[index] if propagate else 0
            self._relation_unresolved[index] -= 1
            if self._relation_unresolved[index] < 0:
                raise RuntimeError(
                    "dependency frontier relation terminal counter underflow"
                )
            blocker_added = False
            if state is ResearchGraphNodeState.SUCCEEDED:
                self._relation_succeeded[index] += 1
            elif state in _BLOCKING_STATES:
                self._relation_blockers[index].add(node_id)
                blocker_added = True

            if not propagate:
                continue

            current_status = self._relation_status_value(index)
            if previous_status == 0 and current_status == 1:
                self._relation_status[index] = 1
                for target in self._relation_targets[index]:
                    self._decrement_unsatisfied(target)
                    self._refresh_node_ready(target)
                continue
            if previous_status == 0 and current_status == 2:
                self._relation_status[index] = 2
                blockers = self._relation_blockers[index]
                for target in self._relation_targets[index]:
                    self._blocked_by.setdefault(target, set()).update(blockers)
                    if target not in self._terminal:
                        self._newly_blocked[target] = None
                    self._ready.pop(target, None)
                continue
            if previous_status == 2 and current_status == 2 and blocker_added:
                # Once a relation is impossible it cannot recover, but later
                # terminal blockers are still part of exact causal evidence.
                for target in self._relation_targets[index]:
                    self._blocked_by.setdefault(target, set()).add(node_id)
                continue
            if previous_status != current_status:
                raise RuntimeError(
                    "dependency frontier relation state transition is invalid"
                )

    def drain_newly_ready(
        self,
        pending_node_ids: Collection[str],
    ) -> tuple[str, ...]:
        """Transfer ready transitions once without a full-frontier rescan."""
        if not self._newly_ready:
            return ()
        ids = tuple(self._newly_ready)
        self._newly_ready.clear()
        return tuple(
            node_id for node_id in ids
            if node_id in self._ready and node_id in pending_node_ids
        )

    def next_ready_node_ids(
        self,
        pending_node_ids: Collection[str],
        *,
        limit: int,
    ) -> tuple[str, ...]:
        """Return and rotate at most limit dependency-ready candidates.

        Under the scheduler invariant that dependency-ready nodes remain in
        pending_node_ids until admission, this is Theta(k) for a returned
        batch of size k and O(1) auxiliary space. Rotation prevents a
        temporally ineligible ready node from permanently head-of-line
        blocking unrelated ready work.
        """
        if type(limit) is not int or limit < 0:
            raise ValueError("dependency frontier ready limit must be non-negative")
        if limit == 0 or not self._ready:
            return ()
        if limit >= len(self._ready):
            # Inspecting the entire ordered set rotates it back into exactly
            # the same order. Never pay for R OrderedDict removals/insertions:
            # an immutable R-result projection is the output-size lower bound.
            # The membership filter keeps this public method exact even if a
            # diagnostic caller supplies only a subset of pending vertices.
            return tuple(
                node_id for node_id in self._ready
                if node_id in pending_node_ids
            )
        rows: list[str] = []
        scan_budget = len(self._ready)
        while scan_budget > 0 and len(rows) < limit:
            node_id, _ = self._ready.popitem(last=False)
            self._ready[node_id] = None
            scan_budget -= 1
            if node_id in pending_node_ids:
                rows.append(node_id)
        return tuple(rows)

    def ready_node_ids(
        self,
        pending_node_ids: Collection[str],
    ) -> tuple[str, ...]:
        # Canonical sorted introspection remains available for diagnostics and
        # tests. The runtime scheduler intentionally does not use this
        # full-frontier ordering operation.
        return tuple(
            sorted(node_id for node_id in self._ready if node_id in pending_node_ids)
        )

    def drain_newly_blocked(
        self,
        pending_node_ids: Collection[str],
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Drain blocker deltas exactly once for the owning scheduler.

        The authoritative Machine and graph execution stores still decide
        whether the target transitions to BLOCKED. This method is only the
        disposable projected event queue. Total event/enqueue cost is
        O(blocked incidences); quiescent polling is O(1).
        """
        if not self._newly_blocked:
            return ()
        newly_blocked = tuple(self._newly_blocked)
        self._newly_blocked.clear()
        return tuple(
            (node_id, tuple(sorted(self._blocked_by[node_id])))
            for node_id in sorted(newly_blocked)
            if node_id in pending_node_ids
        )

    def blocked_nodes(
        self,
        pending_node_ids: Collection[str],
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple(
            (node_id, tuple(sorted(self._blocked_by[node_id])))
            for node_id in sorted(self._blocked_by)
            if node_id in pending_node_ids
        )

    def consume_ready(self, node_id: str) -> None:
        if node_id not in self._ready:
            raise RuntimeError(
                f"dependency frontier node is not ready: {node_id}"
            )
        del self._ready[node_id]
        self._newly_ready.pop(node_id, None)
        self._in_flight.add(node_id)

    def restore_ready(self, node_id: str) -> None:
        if node_id in self._terminal:
            raise RuntimeError(
                f"dependency frontier cannot restore terminal node: {node_id}"
            )
        if node_id not in self._in_flight:
            raise RuntimeError(
                f"dependency frontier node is not in flight: {node_id}"
            )
        self._in_flight.remove(node_id)
        self._refresh_node_ready(node_id)
        if node_id not in self._ready:
            raise RuntimeError(
                f"dependency frontier cannot restore unresolved node: {node_id}"
            )

    def record_terminal(self, result: ResearchGraphNodeResult) -> None:
        if not isinstance(result, ResearchGraphNodeResult):
            raise TypeError(
                "dependency frontier terminal update requires typed result"
            )
        node_id = result.node_id
        if node_id not in self._nodes:
            raise ValueError(
                f"dependency frontier terminal node is outside selection: {node_id}"
            )
        if node_id in self._terminal:
            raise RuntimeError(
                f"dependency frontier terminal node recorded twice: {node_id}"
            )
        if (
            result.state is not ResearchGraphNodeState.SUCCEEDED
            and result.state not in _BLOCKING_STATES
        ):
            raise RuntimeError(
                "dependency frontier requires terminal graph result"
            )
        self._in_flight.discard(node_id)
        # A node may be cancelled while still dependency-ready, without ever
        # entering the in-flight set. Terminal events must retire it from the
        # ordered ready projection as well, otherwise wide scans keep visiting
        # an impossible-to-admit stale entry for the rest of the execution.
        self._ready.pop(node_id, None)
        self._newly_ready.pop(node_id, None)
        # Once a node is terminal its blocker set has been copied into the
        # durable result. Dropping this derived frontier cache prevents every
        # later blocked_nodes() call from rescanning historical terminals.
        self._blocked_by.pop(node_id, None)
        self._newly_blocked.pop(node_id, None)
        self._terminal.add(node_id)
        self._results[node_id] = result
        self._record_relation_terminal(
            node_id,
            result.state,
            propagate=True,
        )


__all__ = ["RESEARCH_GRAPH_FRONTIER_COMPLEXITY", "ResearchGraphDependencyFrontier"]
