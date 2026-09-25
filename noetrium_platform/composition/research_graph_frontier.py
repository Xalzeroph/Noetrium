from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from noetrium_platform.research.execution.graph.api import (
    ResearchGraphNode,
    ResearchGraphNodeResult,
    ResearchGraphNodeState,
    ResearchGraphPlan,
)


_BLOCKING_STATES = {
    ResearchGraphNodeState.FAILED,
    ResearchGraphNodeState.BLOCKED,
    ResearchGraphNodeState.CANCELLED,
}


class ResearchGraphDependencyFrontier:
    """Ephemeral dependency index for one scheduler invocation.

    This object derives readiness from the immutable ResearchGraph plan plus
    already-observed terminal graph results. It owns no durable state, resource
    capacity, control phase, retry policy, or lower execution truth.
    """

    def __init__(
        self,
        plan: ResearchGraphPlan,
        *,
        selected_node_ids: tuple[str, ...],
        terminal_results: Mapping[str, ResearchGraphNodeResult],
    ) -> None:
        if type(plan) is not ResearchGraphPlan:
            raise TypeError("dependency frontier requires ResearchGraphPlan")
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
        by_id = {
            node.node_id: node
            for node in plan.nodes
            if node.node_id in selected
        }
        if set(by_id) != selected:
            raise ValueError("dependency frontier selection differs from plan")
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

        dependents: dict[str, list[str]] = defaultdict(list)
        remaining: dict[str, int] = {}
        blocked_by: dict[str, set[str]] = {}
        ready: set[str] = set()
        terminal = set(terminal_results)

        for node in by_id.values():
            for dependency in node.depends_on_node_ids:
                if dependency not in selected:
                    raise ValueError(
                        "dependency frontier requires dependency-closed selection"
                    )
                dependents[dependency].append(node.node_id)

        for node_id, node in by_id.items():
            if node_id in terminal:
                continue
            unresolved = 0
            blockers: set[str] = set()
            for dependency in node.depends_on_node_ids:
                result = terminal_results.get(dependency)
                if result is None:
                    unresolved += 1
                elif result.state is ResearchGraphNodeState.SUCCEEDED:
                    continue
                elif result.state in _BLOCKING_STATES:
                    blockers.add(dependency)
                else:
                    raise RuntimeError(
                        "dependency frontier observed non-terminal result state"
                    )
            remaining[node_id] = unresolved
            if blockers:
                blocked_by[node_id] = blockers
            elif unresolved == 0:
                ready.add(node_id)

        self._nodes = by_id
        self._dependents = {
            node_id: tuple(sorted(values))
            for node_id, values in dependents.items()
        }
        self._remaining = remaining
        self._blocked_by = blocked_by
        self._ready = ready
        self._terminal = terminal

    def ready_node_ids(self, pending_node_ids: set[str]) -> tuple[str, ...]:
        return tuple(sorted(self._ready.intersection(pending_node_ids)))

    def blocked_nodes(
        self,
        pending_node_ids: set[str],
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
        self._ready.remove(node_id)

    def restore_ready(self, node_id: str) -> None:
        if node_id in self._terminal:
            raise RuntimeError(
                f"dependency frontier cannot restore terminal node: {node_id}"
            )
        if self._blocked_by.get(node_id):
            raise RuntimeError(
                f"dependency frontier cannot restore blocked node: {node_id}"
            )
        if self._remaining.get(node_id) != 0:
            raise RuntimeError(
                f"dependency frontier cannot restore unresolved node: {node_id}"
            )
        self._ready.add(node_id)

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
        self._terminal.add(node_id)
        self._ready.discard(node_id)
        self._blocked_by.pop(node_id, None)

        for dependent_id in self._dependents.get(node_id, ()):
            if dependent_id in self._terminal:
                continue
            if result.state is ResearchGraphNodeState.SUCCEEDED:
                current = self._remaining.get(dependent_id)
                if current is None or current <= 0:
                    raise RuntimeError(
                        "dependency frontier remaining-edge accounting underflow"
                    )
                current -= 1
                self._remaining[dependent_id] = current
                if (
                    current == 0
                    and not self._blocked_by.get(dependent_id)
                ):
                    self._ready.add(dependent_id)
            elif result.state in _BLOCKING_STATES:
                self._blocked_by.setdefault(dependent_id, set()).add(node_id)
                self._ready.discard(dependent_id)
            else:
                raise RuntimeError(
                    "dependency frontier requires terminal graph result"
                )


__all__ = ["ResearchGraphDependencyFrontier"]
