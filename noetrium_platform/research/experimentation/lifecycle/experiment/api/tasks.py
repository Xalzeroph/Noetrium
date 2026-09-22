from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class ExperimentTaskSpec:
    """Environment-neutral task graph node used by every experiment backend."""

    task_id: str
    family: str
    objective: str
    context: str = ""
    lineage_id: str = ""
    depends_on_task_ids: tuple[str, ...] = ()
    retry_of_task_id: str | None = None
    max_steps: int = 12
    max_seconds: float = 180.0

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.family.strip() or not self.objective.strip():
            raise ValueError("experiment task identity, family and objective are required")
        if not self.lineage_id.strip():
            object.__setattr__(self, "lineage_id", self.task_id)
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or self.max_steps <= 0:
            raise ValueError("experiment task max_steps must be a positive integer")
        if (
            isinstance(self.max_seconds, bool)
            or not isinstance(self.max_seconds, (int, float))
            or not math.isfinite(self.max_seconds)
            or self.max_seconds <= 0
        ):
            raise ValueError("experiment task max_seconds must be finite and positive")
        if len(set(self.depends_on_task_ids)) != len(self.depends_on_task_ids):
            raise ValueError("experiment task dependencies must be unique")
        if self.task_id in self.depends_on_task_ids or self.retry_of_task_id == self.task_id:
            raise ValueError("experiment task cannot depend on or retry itself")


def _task_references(task: ExperimentTaskSpec) -> tuple[str, ...]:
    if task.retry_of_task_id is None:
        return task.depends_on_task_ids
    return task.depends_on_task_ids + (task.retry_of_task_id,)


def _task_index(
    tasks: tuple[ExperimentTaskSpec, ...],
) -> dict[str, ExperimentTaskSpec]:
    by_id: dict[str, ExperimentTaskSpec] = {}
    for task in tasks:
        if task.task_id in by_id:
            raise ValueError(f"duplicate experiment task_id: {task.task_id}")
        by_id[task.task_id] = task
    return by_id


def _require_selected_ids(
    selected_ids: tuple[str, ...],
    by_id: dict[str, ExperimentTaskSpec],
) -> tuple[str, ...]:
    selected = tuple(selected_ids)
    if len(selected) != len(set(selected)):
        raise ValueError("selected experiment task ids must be unique")
    missing = tuple(task_id for task_id in selected if task_id not in by_id)
    if missing:
        raise ValueError(f"selected experiment task ids are missing: {missing}")
    return selected


def _unknown_references(
    task: ExperimentTaskSpec,
    by_id: dict[str, ExperimentTaskSpec],
) -> tuple[str, ...]:
    return tuple(
        reference for reference in _task_references(task) if reference not in by_id
    )


def _require_known_references(
    tasks: tuple[ExperimentTaskSpec, ...],
    by_id: dict[str, ExperimentTaskSpec],
) -> None:
    for task in tasks:
        unknown = _unknown_references(task, by_id)
        if unknown:
            raise ValueError(f"task {task.task_id} references unknown tasks: {unknown}")


def _visit_iterative(
    root_id: str,
    by_id: dict[str, ExperimentTaskSpec],
    states: dict[str, int],
    ordered: list[ExperimentTaskSpec],
) -> None:
    if states.get(root_id) == 2:
        return
    stack: list[tuple[str, int]] = [(root_id, 0)]
    while stack:
        task_id, next_reference = stack[-1]
        if states.get(task_id, 0) == 0:
            states[task_id] = 1
        references = _task_references(by_id[task_id])
        if next_reference < len(references):
            dependency = references[next_reference]
            stack[-1] = (task_id, next_reference + 1)
            dependency_state = states.get(dependency, 0)
            if dependency_state == 1:
                raise ValueError(
                    f"experiment task dependency cycle includes {dependency}"
                )
            if dependency_state == 0:
                stack.append((dependency, 0))
            continue
        states[task_id] = 2
        ordered.append(by_id[task_id])
        stack.pop()


def _topological_order(
    tasks: tuple[ExperimentTaskSpec, ...],
    by_id: dict[str, ExperimentTaskSpec],
) -> tuple[ExperimentTaskSpec, ...]:
    states: dict[str, int] = {}
    ordered: list[ExperimentTaskSpec] = []
    for task in tasks:
        _visit_iterative(task.task_id, by_id, states, ordered)
    return tuple(ordered)


def _append_missing_prerequisites(
    task: ExperimentTaskSpec,
    selected_set: set[str],
    seen: set[str],
    required: list[str],
) -> None:
    for dependency in _task_references(task):
        if dependency not in selected_set and dependency not in seen:
            required.append(dependency)
            seen.add(dependency)


def _missing_selected_prerequisites(
    selected: tuple[str, ...],
    by_id: dict[str, ExperimentTaskSpec],
) -> tuple[str, ...]:
    selected_set = set(selected)
    required: list[str] = []
    seen: set[str] = set()
    for task_id in selected:
        _append_missing_prerequisites(by_id[task_id], selected_set, seen, required)
    return tuple(required)


def validate_task_graph(
    tasks: tuple[ExperimentTaskSpec, ...],
    *,
    selected_ids: tuple[str, ...] = (),
) -> tuple[ExperimentTaskSpec, ...]:
    """Validate and topologically order an immutable task graph."""
    if not tasks:
        raise ValueError("experiment task graph is empty")
    by_id = _task_index(tasks)
    selected = _require_selected_ids(selected_ids, by_id)
    _require_known_references(tasks, by_id)
    ordered = _topological_order(tasks, by_id)
    if not selected:
        return ordered
    required = _missing_selected_prerequisites(selected, by_id)
    if required:
        raise ValueError(f"selected task ids omit prerequisites: {required}")
    selected_set = set(selected)
    return tuple(task for task in ordered if task.task_id in selected_set)


__all__ = ["ExperimentTaskSpec", "validate_task_graph"]
