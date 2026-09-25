from __future__ import annotations

from dataclasses import dataclass
import heapq


class WorkflowGraphError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    operation_type: str
    dependencies: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.step_id, str) or not isinstance(self.operation_type, str):
            raise TypeError("workflow step_id and operation_type must be text")
        if any(not isinstance(item, str) for item in self.dependencies):
            raise TypeError("workflow dependency ids must be text")
        if any(not isinstance(item, str) for item in self.required_capabilities):
            raise TypeError("workflow capability ids must be text")
        step_id = self.step_id.strip()
        operation_type = self.operation_type.strip()
        dependencies = tuple(item.strip() for item in self.dependencies)
        capabilities = tuple(item.strip() for item in self.required_capabilities)
        if not step_id or not operation_type:
            raise ValueError("workflow step_id and operation_type required")
        if any(not item for item in dependencies):
            raise WorkflowGraphError(f"workflow dependency id cannot be blank: {step_id}")
        if len(set(dependencies)) != len(dependencies):
            raise WorkflowGraphError(f"duplicate dependency for step: {step_id}")
        if step_id in dependencies:
            raise WorkflowGraphError(f"workflow step cannot depend on itself: {step_id}")
        if any(not item for item in capabilities) or len(set(capabilities)) != len(capabilities):
            raise WorkflowGraphError(f"workflow required capabilities must be unique non-empty ids: {step_id}")
        object.__setattr__(self, "step_id", step_id)
        object.__setattr__(self, "operation_type", operation_type)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "required_capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class WorkflowGraph:
    """Immutable explicit DAG. Validation and ordering are O(V+E) plus heap ordering."""
    steps: tuple[WorkflowStep, ...]

    def __post_init__(self) -> None:
        mapping = {step.step_id: step for step in self.steps}
        if len(mapping) != len(self.steps):
            raise WorkflowGraphError("duplicate workflow step id")
        ids = set(mapping)
        missing = sorted({dep for step in self.steps for dep in step.dependencies if dep not in ids})
        if missing:
            raise WorkflowGraphError(f"missing workflow dependencies: {missing}")
        self.topological_order()

    def topological_order(self) -> tuple[str, ...]:
        indegree = {step.step_id: len(step.dependencies) for step in self.steps}
        children = {step.step_id: [] for step in self.steps}
        for step in self.steps:
            for dependency in step.dependencies:
                children[dependency].append(step.step_id)
        ready = [step_id for step_id, degree in indegree.items() if degree == 0]
        heapq.heapify(ready)
        order: list[str] = []
        while ready:
            step_id = heapq.heappop(ready)
            order.append(step_id)
            for child in children[step_id]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    heapq.heappush(ready, child)
        if len(order) != len(self.steps):
            blocked = sorted(step_id for step_id, degree in indegree.items() if degree)
            raise WorkflowGraphError(f"workflow dependency cycle among: {blocked}")
        return tuple(order)

    def ready_steps(self, completed: frozenset[str], running: frozenset[str] = frozenset()) -> tuple[str, ...]:
        known = {step.step_id for step in self.steps}
        unknown = (set(completed) | set(running)) - known
        if unknown:
            raise WorkflowGraphError(f"workflow progress references unknown steps: {sorted(unknown)}")
        return tuple(sorted(step.step_id for step in self.steps
                            if step.step_id not in completed and step.step_id not in running
                            and all(dep in completed for dep in step.dependencies)))


__all__ = ["WorkflowGraph", "WorkflowGraphError", "WorkflowStep"]
