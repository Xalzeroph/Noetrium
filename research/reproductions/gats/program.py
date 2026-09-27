from __future__ import annotations

from research.reproductions._support import (
    JsonObject,
    JsonValue,
    MethodCall,
    canonical_digest,
    freeze_json,
    method_event,
    require_sha256,
    thaw_json,
)
from research.reproductions._support import JsonObject, JsonValue, canonical_digest, freeze_json

from collections.abc import Mapping, Sequence
import math




from .fidelity import GATS_REPRODUCIBILITY_FIDELITY


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"GATS {field} must be non-empty text")
    return value.strip()


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"GATS {field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"GATS {field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"GATS {field} must be finite")
    return result


def _rows(value: object, field: str) -> tuple[JsonObject, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"GATS {field} must be a sequence")
    result: list[JsonObject] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError(f"GATS {field} rows must be mappings")
        result.append(freeze_json(dict(row)))
    return tuple(result)


def _mapping(value: object, field: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"GATS {field} must be a mapping")
    return value


def gats_stress_initial_state(
    *,
    start_state: str,
    goal_state: str,
    transitions: Mapping[str, JsonValue],
    state_values: Mapping[str, JsonValue] | None = None,
) -> JsonObject:
    """Build the deterministic stress-lane planning state.

    The frozen benchmark owns task generation.  The MethodProgram owns only the
    source-faithful stress-planner semantics: direct transitions plus UCB over
    state values.  Layered world-model behavior is deliberately not invented.
    """

    start = _text(start_state, "start_state")
    goal = _text(goal_state, "goal_state")
    frozen_transitions = freeze_json(dict(transitions))
    frozen_values = freeze_json({} if state_values is None else dict(state_values))
    if not isinstance(frozen_transitions, Mapping) or not isinstance(frozen_values, Mapping):
        raise TypeError("GATS initial transition/value tables must be mappings")
    return {
        "start_state": start,
        "goal_state": goal,
        "transitions": frozen_transitions,
        "state_values": frozen_values,
        "iteration": 0,
        "selected_node_id": "root",
        "expanded_child_id": "",
        "best_node_id": "root",
        "search_exhausted": False,
        "nodes": (
            {
                "node_id": "root",
                "parent_id": None,
                "state": start,
                "action": "",
                "depth": 0,
                "visits": 0,
                "value": 0.0,
                "terminal": start == goal,
            },
        ),
    }


def _nodes(state: Mapping[str, JsonValue]) -> tuple[JsonObject, ...]:
    return _rows(state.get("nodes", ()), "nodes")


def _node_map(state: Mapping[str, JsonValue]) -> dict[str, JsonObject]:
    rows = _nodes(state)
    result = {_text(row.get("node_id"), "node_id"): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("GATS node ids must be unique")
    return result


def _replace_node(
    nodes: tuple[JsonObject, ...],
    node_id: str,
    update: Mapping[str, JsonValue],
) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    found = False
    for row in nodes:
        if row.get("node_id") != node_id:
            rows.append(row)
            continue
        found = True
        merged = dict(row)
        merged.update(update)
        rows.append(freeze_json(merged))
    if not found:
        raise KeyError(node_id)
    return tuple(rows)


def _actions_for(state: Mapping[str, JsonValue], world_state: str) -> tuple[JsonObject, ...]:
    transitions = _mapping(state.get("transitions"), "transitions")
    raw = transitions.get(world_state, ())
    return _rows(raw, f"transitions[{world_state}]")


def _expanded_actions(node_id: str, nodes: Mapping[str, JsonObject]) -> set[str]:
    return {
        _text(row.get("action"), "child action")
        for row in nodes.values()
        if row.get("parent_id") == node_id and row.get("action")
    }


def _select_node(request: MethodCall) -> MethodNodeResult:
    nodes = _node_map(request.state)
    goal = _text(request.state.get("goal_state"), "goal_state")
    expandable: list[JsonObject] = []
    for row in nodes.values():
        if row.get("terminal") is True:
            continue
        depth = _integer(row.get("depth", 0), "depth")
        if depth >= GATS_REPRODUCIBILITY_FIDELITY.stress_max_steps:
            continue
        world_state = _text(row.get("state"), "world state")
        actions = _actions_for(request.state, world_state)
        if len(_expanded_actions(_text(row.get("node_id"), "node_id"), nodes)) < len(actions):
            expandable.append(row)

    if not expandable:
        return dict(
            value={"search_exhausted": True},
            state_update={"search_exhausted": True},
            next_node="return",
        )

    def score(row: JsonObject) -> tuple[float, str]:
        node_id = _text(row.get("node_id"), "node_id")
        visits = _integer(row.get("visits", 0), "visits")
        value = _number(row.get("value", 0.0), "value")
        parent_id = row.get("parent_id")
        parent_visits = 1
        if isinstance(parent_id, str) and parent_id:
            parent_visits = max(
                1,
                _integer(nodes[parent_id].get("visits", 0), "parent visits"),
            )
        bonus = GATS_REPRODUCIBILITY_FIDELITY.stress_c_puct * math.sqrt(
            math.log(parent_visits + 1.0) / (visits + 1.0)
        )
        return (value + bonus, node_id)

    selected = max(expandable, key=score)
    selected_id = _text(selected.get("node_id"), "selected node")
    if _text(selected.get("state"), "selected state") == goal:
        return dict(
            value={"goal_node_id": selected_id},
            state_update={"best_node_id": selected_id},
            next_node="return",
        )
    return dict(
        value={"selected_node_id": selected_id},
        state_update={"selected_node_id": selected_id},
        next_node="expand",
    )


def _expand(request: MethodCall) -> MethodNodeResult:
    nodes_tuple = _nodes(request.state)
    nodes = _node_map(request.state)
    selected_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    parent = nodes[selected_id]
    world_state = _text(parent.get("state"), "world state")
    actions = _actions_for(request.state, world_state)
    expanded = _expanded_actions(selected_id, nodes)
    candidate = next(
        (
            row
            for row in actions
            if _text(row.get("action"), "action") not in expanded
        ),
        None,
    )
    if candidate is None:
        raise RuntimeError("GATS selected node has no unexpanded direct transition")

    action = _text(candidate.get("action"), "action")
    next_state = _text(candidate.get("next_state"), "next_state")
    reward = _number(candidate.get("reward", 0.0), "reward")
    state_values = _mapping(request.state.get("state_values", {}), "state_values")
    heuristic = _number(state_values.get(next_state, 0.0), "state value")
    depth = _integer(parent.get("depth", 0), "depth") + 1
    iteration = _integer(request.state.get("iteration", 0), "iteration")
    child_id = f"n{iteration:03d}:{selected_id}:{len(expanded):02d}"
    goal = _text(request.state.get("goal_state"), "goal_state")
    terminal = (
        candidate.get("terminal") is True
        or next_state == goal
        or depth >= GATS_REPRODUCIBILITY_FIDELITY.stress_max_steps
    )
    child: JsonObject = {
        "node_id": child_id,
        "parent_id": selected_id,
        "state": next_state,
        "action": action,
        "depth": depth,
        "visits": 0,
        "value": reward + heuristic,
        "reward": reward,
        "terminal": terminal,
    }
    return dict(
        value={
            "node_id": child_id,
            "state": next_state,
            "action": action,
            "value": reward + heuristic,
            "terminal": terminal,
        },
        state_update={
            "nodes": (*nodes_tuple, child),
            "expanded_child_id": child_id,
            "best_node_id": (
                child_id
                if reward + heuristic
                >= _number(nodes[_text(request.state.get("best_node_id"), "best_node_id")].get("value", 0.0), "best value")
                else request.state.get("best_node_id")
            ),
        },
        next_node="backprop",
    )


def _backprop(request: MethodCall) -> MethodNodeResult:
    child_id = _text(request.state.get("expanded_child_id"), "expanded_child_id")
    nodes_tuple = _nodes(request.state)
    nodes = {_text(row.get("node_id"), "node_id"): row for row in nodes_tuple}
    child = nodes[child_id]
    backed_value = _number(child.get("value", 0.0), "child value")
    current: str | None = child_id
    while current is not None:
        row = {_text(item.get("node_id"), "node_id"): item for item in nodes_tuple}[current]
        visits = _integer(row.get("visits", 0), "visits")
        old_value = _number(row.get("value", 0.0), "value")
        new_visits = visits + 1
        new_value = (old_value * visits + backed_value) / new_visits
        nodes_tuple = _replace_node(
            nodes_tuple,
            current,
            {"visits": new_visits, "value": new_value},
        )
        parent = row.get("parent_id")
        current = parent if isinstance(parent, str) and parent else None

    iteration = _integer(request.state.get("iteration", 0), "iteration") + 1
    terminal = child.get("terminal") is True
    budget_exhausted = iteration >= 20
    return dict(
        value={
            "iteration": iteration,
            "terminal": terminal,
            "budget_exhausted": budget_exhausted,
        },
        state_update={
            "nodes": nodes_tuple,
            "iteration": iteration,
        },
        next_node="return" if terminal or budget_exhausted else "select",
        checkpoint=True,
        checkpoint_value={
            "iteration": iteration,
            "expanded_child_id": child_id,
            "value": backed_value,
        },
    )


def _plan_for(node_id: str, nodes: Mapping[str, JsonObject]) -> tuple[str, ...]:
    actions: list[str] = []
    current: str | None = node_id
    while current is not None:
        row = nodes[current]
        action = row.get("action")
        if isinstance(action, str) and action:
            actions.append(action)
        parent = row.get("parent_id")
        current = parent if isinstance(parent, str) and parent else None
    actions.reverse()
    return tuple(actions)


def _return_result(request: MethodCall) -> MethodNodeResult:
    nodes = _node_map(request.state)
    goal = _text(request.state.get("goal_state"), "goal_state")
    goal_nodes = [
        row for row in nodes.values() if row.get("state") == goal
    ]
    if goal_nodes:
        best = max(
            goal_nodes,
            key=lambda row: _number(row.get("value", 0.0), "goal value"),
        )
        success = True
    else:
        best = nodes[_text(request.state.get("best_node_id"), "best_node_id")]
        success = False
    best_id = _text(best.get("node_id"), "best node")
    return dict(
        value={
            "task_success": success,
            "plan": _plan_for(best_id, nodes),
            "best_node_id": best_id,
            "best_state": best.get("state"),
            "search_nodes": len(nodes),
            "search_iterations": _integer(
                request.state.get("iteration", 0),
                "iteration",
            ),
            "plan_cost": float(len(_plan_for(best_id, nodes))),
            "search_exhausted": request.state.get("search_exhausted") is True,
        }
    )


def build_gats_stress_b20_method_program(method, ) -> None:
    fidelity = GATS_REPRODUCIBILITY_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.source.commit,
        "stress_search_budget": 20,
        "stress_max_steps": fidelity.stress_max_steps,
        "stress_c_puct": fidelity.stress_c_puct,
        "transition_semantics": fidelity.stress_transition_semantics,
        "uses_layered_world_model": fidelity.stress_uses_layered_world_model,
        "stress_categories": fidelity.stress_categories,
        "stress_tasks_per_category": fidelity.stress_tasks_per_category,
    }

    visits = 21
    builder = method
    builder.route(
        "select",
        "gats.ucb.select",
        _select_node,
        ("expand", "return"),
        max_visits=visits,
    )
    builder.compute(
        "expand",
        "gats.direct-transition.expand",
        _expand,
        ("backprop",),
        max_visits=20,
    )
    builder.route(
        "backprop",
        "gats.state-value.backpropagate",
        _backprop,
        ("select", "return"),
        max_visits=20,
    )
    builder.return_node("return", "gats.result", _return_result)
    builder.configure(configuration)
    builder.policy(
        execution='checkpointable',
        evidence=("gats.search-tree", "gats.direct-transition"),
        metrics=("task_success", "search_nodes", "plan_cost"),
        artifacts=("gats_search_tree",),
    )
    return builder


METHOD_CONFIGURER = build_gats_stress_b20_method_program
METHOD_ENTRYPOINT = "select"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}


__all__ = [
    'build_gats_stress_b20_method_program',
    'gats_stress_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]

METHOD_SPEC = {"method_id": 'gats', "version": "paper-protocol", "semantic_contract": 'gats' + ".method.v2", "entrypoint": METHOD_ENTRYPOINT}

__all__ = tuple(dict.fromkeys((*__all__, 'METHOD_SPEC')))
