from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, freeze_json, thaw_json

_FLOW_STATUSES = {"pending", "in_progress", "completed", "failed"}


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value.strip()):
        raise ValueError(f"Flow {field} must be text")
    return value.strip() if not allow_empty else value


def _ids(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"Flow {field} must be a sequence")
    rows = tuple(_text(row, field) for row in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"Flow {field} must be unique")
    return rows


def normalize_flow_task(task_id: str, value: object) -> JsonObject:
    task_id = _text(task_id, "task_id")
    if not isinstance(value, Mapping):
        raise TypeError("Flow task must be an object")
    status = value.get("status", "pending")
    if type(status) is not str or status not in _FLOW_STATUSES:
        raise ValueError("Flow task status drifted")
    history = value.get("history", ())
    if isinstance(history, (str, bytes, bytearray)) or not isinstance(history, Sequence):
        raise TypeError("Flow task history must be a sequence")
    return freeze_json({
        "id": task_id,
        "objective": _text(
            value.get("objective", value.get("subtask_requirement")),
            "task objective",
        ),
        "agent_id": _text(
            str(value.get("agent_id", value.get("agent", "unassigned"))),
            "agent_id",
        ),
        "agent": _text(
            str(value.get("agent", value.get("agent_id", "unassigned"))),
            "agent",
        ),
        "prev": _ids(value.get("prev", ()), "task prev"),
        "next": _ids(
            value.get("next", value.get("child", ())),
            "task next",
        ),
        "status": status,
        "history": tuple(freeze_json(row) for row in history),
        "output_format": _text(
            str(value.get("output_format", "")),
            "output_format",
            allow_empty=True,
        ),
        "data": freeze_json(value.get("data")),
        "validation_attempts": int(value.get("validation_attempts", 0)),
    })


def normalize_flow_workflow(value: object) -> JsonObject:
    if isinstance(value, Mapping) and "workflow" in value:
        value = value["workflow"]
    if not isinstance(value, Mapping) or not value:
        raise TypeError("Flow workflow must be a non-empty object")
    tasks = {
        _text(str(task_id), "workflow task id"): normalize_flow_task(
            str(task_id), raw
        )
        for task_id, raw in value.items()
    }
    ids = set(tasks)
    for task_id, raw in tasks.items():
        for parent in raw["prev"]:
            if parent not in ids:
                raise ValueError(f"Flow task {task_id} references unknown parent {parent}")
        for child in raw["next"]:
            if child not in ids:
                raise ValueError(f"Flow task {task_id} references unknown child {child}")

    # Reject cycles: AOV is a directed acyclic graph.
    indegree = {task_id: len(tuple(raw["prev"])) for task_id, raw in tasks.items()}
    ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for child in tasks[current]["next"]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(visited) != len(tasks):
        raise ValueError("Flow AOV workflow must be acyclic")
    return freeze_json(tasks)


def flow_average_parallelism(workflow: Mapping[str, JsonValue]) -> float:
    tasks = normalize_flow_workflow(workflow)
    depths: dict[str, int] = {}
    pending = set(tasks)
    while pending:
        progressed = False
        for task_id in sorted(tuple(pending)):
            parents = tuple(tasks[task_id]["prev"])
            if all(parent in depths for parent in parents):
                depths[task_id] = (
                    0 if not parents else 1 + max(depths[parent] for parent in parents)
                )
                pending.remove(task_id)
                progressed = True
        if not progressed:
            raise ValueError("Flow AOV depth computation stalled")
    counts: dict[int, int] = {}
    for depth in depths.values():
        counts[depth] = counts.get(depth, 0) + 1
    return sum(counts.values()) / len(counts)


def flow_dependency_complexity(workflow: Mapping[str, JsonValue]) -> float:
    tasks = normalize_flow_workflow(workflow)
    degrees = tuple(
        len(tuple(raw["prev"])) + len(tuple(raw["next"]))
        for raw in tasks.values()
    )
    mean = sum(degrees) / len(degrees)
    return math.sqrt(sum((degree - mean) ** 2 for degree in degrees) / len(degrees))


def flow_candidate_scores(
    candidates: Sequence[Mapping[str, JsonValue]],
    *,
    epsilon: float = 0.01,
) -> tuple[float, ...]:
    if not candidates:
        raise ValueError("Flow candidate scoring requires candidates")
    complexities = tuple(flow_dependency_complexity(row) for row in candidates)
    parallelism = tuple(flow_average_parallelism(row) for row in candidates)
    mean_c = sum(complexities) / len(complexities)
    mean_p = sum(parallelism) / len(parallelism)
    std_c = math.sqrt(sum((x - mean_c) ** 2 for x in complexities) / len(complexities))
    std_p = math.sqrt(sum((x - mean_p) ** 2 for x in parallelism) / len(parallelism))
    return tuple(
        ((c - mean_c) / (std_c + epsilon))
        - ((p - mean_p) / (std_p + epsilon))
        for c, p in zip(complexities, parallelism, strict=True)
    )


def flow_select_candidate(
    candidates: Sequence[Mapping[str, JsonValue]],
) -> tuple[int, tuple[float, ...]]:
    scores = flow_candidate_scores(candidates)
    return min(range(len(scores)), key=scores.__getitem__), scores


def flow_ready_task_ids(workflow: Mapping[str, JsonValue]) -> tuple[str, ...]:
    tasks = normalize_flow_workflow(workflow)
    return tuple(
        task_id
        for task_id in sorted(tasks)
        if tasks[task_id]["status"] in ("pending", "failed")
        and all(tasks[parent]["status"] == "completed" for parent in tasks[task_id]["prev"])
    )


def flow_all_completed(workflow: Mapping[str, JsonValue]) -> bool:
    tasks = normalize_flow_workflow(workflow)
    return all(raw["status"] == "completed" for raw in tasks.values())


def flow_merge_refinement(
    current: Mapping[str, JsonValue],
    proposed: Mapping[str, JsonValue],
) -> JsonObject:
    old = normalize_flow_workflow(current)
    new = normalize_flow_workflow(proposed)
    merged: dict[str, JsonValue] = {}
    for task_id, fresh in new.items():
        previous = old.get(task_id)
        if not isinstance(previous, Mapping):
            merged[task_id] = fresh
            continue
        structurally_same = (
            previous["objective"] == fresh["objective"]
            and tuple(previous["prev"]) == tuple(fresh["prev"])
            and previous["agent_id"] == fresh["agent_id"]
        )
        if structurally_same and previous["status"] == "completed":
            row = dict(thaw_json(fresh))
            row["status"] = "completed"
            row["history"] = thaw_json(previous["history"])
            row["data"] = thaw_json(previous["data"])
            row["validation_attempts"] = previous["validation_attempts"]
            merged[task_id] = freeze_json(row)
        else:
            row = dict(thaw_json(fresh))
            row["status"] = "pending"
            row["history"] = ()
            row["data"] = None
            row["validation_attempts"] = 0
            merged[task_id] = freeze_json(row)
    return normalize_flow_workflow(merged)


__all__ = [
    "flow_all_completed",
    "flow_average_parallelism",
    "flow_candidate_scores",
    "flow_dependency_complexity",
    "flow_merge_refinement",
    "flow_ready_task_ids",
    "flow_select_candidate",
    "normalize_flow_task",
    "normalize_flow_workflow",
]
