from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from noetrium.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium.api import (
    JsonObject,
    JsonValue,
    canonical_digest,
)
from noetrium.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import LITS_MATH500_RELEASE_FIDELITY

_POLICY_AGENT_ID = "lits.policy"
_REWARD_AGENT_ID = "lits.reward"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"LiTS {field} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"LiTS {field} must be non-empty")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"LiTS {field} must be integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"LiTS {field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"LiTS {field} must be finite")
    return result


def _rows(value: object, field: str) -> tuple[Mapping[str, JsonValue], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"LiTS {field} must be a sequence")
    if any(not isinstance(row, Mapping) for row in value):
        raise TypeError(f"LiTS {field} rows must be mappings")
    return tuple(value)


def _node_map(state: Mapping[str, JsonValue]) -> dict[str, Mapping[str, JsonValue]]:
    rows = _rows(state.get("nodes", ()), "nodes")
    result = {_text(row.get("node_id"), "node_id"): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("LiTS tree node ids must be unique")
    return result


def _replace_node(
    rows: tuple[Mapping[str, JsonValue], ...],
    node_id: str,
    update: Mapping[str, JsonValue],
) -> tuple[JsonObject, ...]:
    result: list[JsonObject] = []
    found = False
    for row in rows:
        if row.get("node_id") == node_id:
            merged = dict(row)
            merged.update(update)
            result.append(merged)
            found = True
        else:
            result.append(dict(row))
    if not found:
        raise KeyError(node_id)
    return tuple(result)


def lits_math500_initial_state(*, problem: str) -> JsonObject:
    return {
        "problem": _text(problem, "problem").strip(),
        "iteration": 0,
        "model_call_count": 0,
        "next_node_index": 1,
        "selected_node_id": "n0",
        "candidate_node_ids": (),
        "best_node_id": "n0",
        "nodes": (
            {
                "node_id": "n0",
                "parent_id": "",
                "depth": 0,
                "text": "",
                "action": "",
                "visits": 0,
                "value_sum": 0.0,
                "expanded": False,
                "terminal": False,
                "children": (),
            },
        ),
    }


def _trajectory(
    node_id: str,
    nodes: Mapping[str, Mapping[str, JsonValue]],
) -> tuple[str, ...]:
    rows: list[str] = []
    current = node_id
    while current:
        row = nodes[current]
        action = row.get("action")
        if isinstance(action, str) and action:
            rows.append(action)
        parent = row.get("parent_id")
        current = parent if isinstance(parent, str) and parent else ""
    return tuple(reversed(rows))


def _ucb(
    row: Mapping[str, JsonValue],
    nodes: Mapping[str, Mapping[str, JsonValue]],
) -> float:
    visits = _integer(row.get("visits", 0), "visits")
    mean = (
        _number(row.get("value_sum", 0.0), "value_sum") / visits
        if visits
        else 0.0
    )
    parent_id = row.get("parent_id")
    parent_visits = 1
    if isinstance(parent_id, str) and parent_id:
        parent_visits = max(
            1,
            _integer(nodes[parent_id].get("visits", 0), "parent visits"),
        )
    return mean + math.sqrt(math.log(parent_visits + 1.0) / (visits + 1.0))


def _select(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _node_map(request.state)
    candidates = tuple(
        row
        for row in nodes.values()
        if row.get("terminal") is not True
        and row.get("expanded") is not True
        and _integer(row.get("depth", 0), "depth")
        < LITS_MATH500_RELEASE_FIDELITY.max_steps
    )
    if not candidates:
        return MethodNodeResult(
            value={"search_exhausted": True},
            next_node="return",
        )
    selected = max(
        candidates,
        key=lambda row: (
            _ucb(row, nodes),
            -_integer(row.get("depth", 0), "depth"),
            _text(row.get("node_id"), "node_id"),
        ),
    )
    selected_id = _text(selected.get("node_id"), "selected node")
    return MethodNodeResult(
        value={"selected_node_id": selected_id},
        state_update={"selected_node_id": selected_id},
        next_node="policy",
    )


def _policy_view(request: MethodNodeRequest) -> JsonObject:
    nodes = _node_map(request.state)
    selected_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    selected = nodes[selected_id]
    return {
        "problem": _text(request.state.get("problem"), "problem"),
        "selected_node_id": selected_id,
        "depth": _integer(selected.get("depth", 0), "depth"),
        "partial_solution": _text(
            selected.get("text", ""),
            "partial solution",
            allow_empty=True,
        ),
        "trajectory": _trajectory(selected_id, nodes),
        "component": LITS_MATH500_RELEASE_FIDELITY.policy_component,
        "candidate_actions": LITS_MATH500_RELEASE_FIDELITY.candidate_actions,
    }


def _policy_actions(value: JsonValue) -> tuple[tuple[str, bool], ...]:
    candidate: object = value
    if isinstance(value, Mapping):
        candidate = value.get("actions", value.get("candidates"))
    if not isinstance(candidate, Sequence) or isinstance(
        candidate,
        (str, bytes, bytearray),
    ):
        raise TypeError("LiTS policy result must contain an action sequence")
    rows: list[tuple[str, bool]] = []
    for index, item in enumerate(candidate):
        if isinstance(item, str):
            action = _text(item, f"policy action {index}").strip()
            terminal = False
        elif isinstance(item, Mapping):
            action = _text(
                item.get("action", item.get("text")),
                f"policy action {index}",
            ).strip()
            terminal = item.get("terminal", False)
            if type(terminal) is not bool:
                raise TypeError("LiTS policy terminal flag must be boolean")
        else:
            raise TypeError("LiTS policy actions must be text or mappings")
        rows.append((action, terminal))
    if len(rows) != LITS_MATH500_RELEASE_FIDELITY.candidate_actions:
        raise ValueError(
            "LiTS policy result must match the released candidate-action count"
        )
    return tuple(rows)


def _expand(request: MethodNodeRequest) -> MethodNodeResult:
    actions = _policy_actions(request.previous_value)
    nodes_tuple = _rows(request.state.get("nodes", ()), "nodes")
    nodes = _node_map(request.state)
    selected_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    parent = dict(nodes[selected_id])
    if parent.get("expanded") is True:
        raise ValueError("LiTS selected node is already expanded")
    parent_text = _text(
        parent.get("text", ""),
        "parent text",
        allow_empty=True,
    )
    depth = _integer(parent.get("depth", 0), "depth") + 1
    next_index = _integer(
        request.state.get("next_node_index", 1),
        "next_node_index",
        minimum=1,
    )
    children: list[JsonObject] = []
    for offset, (action, terminal) in enumerate(actions):
        child_id = f"n{next_index + offset}"
        combined = (
            action
            if not parent_text
            else f"{parent_text}\n{action}"
        )
        children.append(
            {
                "node_id": child_id,
                "parent_id": selected_id,
                "depth": depth,
                "text": combined,
                "action": action,
                "visits": 0,
                "value_sum": 0.0,
                "expanded": False,
                "terminal": terminal
                or depth >= LITS_MATH500_RELEASE_FIDELITY.max_steps,
                "children": (),
            }
        )
    parent["expanded"] = True
    parent["children"] = tuple(row["node_id"] for row in children)
    updated = (*_replace_node(nodes_tuple, selected_id, parent), *children)
    return MethodNodeResult(
        value={
            "candidate_node_ids": tuple(row["node_id"] for row in children),
        },
        state_update={
            "nodes": updated,
            "candidate_node_ids": tuple(row["node_id"] for row in children),
            "next_node_index": next_index + len(children),
            "model_call_count": _integer(
                request.state.get("model_call_count", 0),
                "model_call_count",
            )
            + 1,
        },
        next_node="reward",
    )


def _reward_view(request: MethodNodeRequest) -> JsonObject:
    nodes = _node_map(request.state)
    candidate_ids = tuple(
        _text(row, "candidate node id")
        for row in request.state.get("candidate_node_ids", ())
    )
    return {
        "problem": _text(request.state.get("problem"), "problem"),
        "component": LITS_MATH500_RELEASE_FIDELITY.reward_component,
        "candidates": tuple(
            {
                "node_id": node_id,
                "partial_solution": nodes[node_id].get("text", ""),
                "depth": nodes[node_id].get("depth", 0),
            }
            for node_id in candidate_ids
        ),
    }


def _reward_scores(value: JsonValue, expected: int) -> tuple[float, ...]:
    candidate: object = value
    if isinstance(value, Mapping):
        candidate = value.get("scores", value.get("values"))
    if not isinstance(candidate, Sequence) or isinstance(
        candidate,
        (str, bytes, bytearray),
    ):
        raise TypeError("LiTS reward result must contain numeric scores")
    scores = tuple(_number(row, "reward score") for row in candidate)
    if len(scores) != expected:
        raise ValueError("LiTS reward score count does not match expanded candidates")
    return scores


def _backpropagate(request: MethodNodeRequest) -> MethodNodeResult:
    nodes_tuple = _rows(request.state.get("nodes", ()), "nodes")
    nodes = _node_map(request.state)
    candidate_ids = tuple(
        _text(row, "candidate node id")
        for row in request.state.get("candidate_node_ids", ())
    )
    scores = _reward_scores(request.previous_value, len(candidate_ids))
    for node_id, score in zip(candidate_ids, scores, strict=True):
        nodes_tuple = _replace_node(
            nodes_tuple,
            node_id,
            {"visits": 1, "value_sum": score},
        )

    best_index = max(range(len(candidate_ids)), key=lambda index: scores[index])
    best_id = candidate_ids[best_index]
    best_score = scores[best_index]
    current: str | None = best_id
    while current:
        current_nodes = {
            _text(row.get("node_id"), "node_id"): row for row in nodes_tuple
        }
        row = current_nodes[current]
        if current != best_id:
            visits = _integer(row.get("visits", 0), "visits")
            value_sum = _number(row.get("value_sum", 0.0), "value_sum")
            nodes_tuple = _replace_node(
                nodes_tuple,
                current,
                {
                    "visits": visits + 1,
                    "value_sum": value_sum + best_score,
                },
            )
        parent = row.get("parent_id")
        current = parent if isinstance(parent, str) and parent else None

    iteration = _integer(request.state.get("iteration", 0), "iteration") + 1
    return MethodNodeResult(
        value={
            "iteration": iteration,
            "best_node_id": best_id,
            "best_score": best_score,
        },
        state_update={
            "nodes": nodes_tuple,
            "iteration": iteration,
            "best_node_id": best_id,
            "candidate_node_ids": (),
            "model_call_count": _integer(
                request.state.get("model_call_count", 0),
                "model_call_count",
            )
            + 1,
        },
        next_node="advance",
        checkpoint=True,
        checkpoint_value={
            "iteration": iteration,
            "best_node_id": best_id,
            "best_score": best_score,
        },
    )


def _advance(request: MethodNodeRequest) -> MethodNodeResult:
    iteration = _integer(request.state.get("iteration", 0), "iteration")
    nodes = _node_map(request.state)
    best_id = _text(request.state.get("best_node_id"), "best_node_id")
    terminal = nodes[best_id].get("terminal") is True
    exhausted = iteration >= LITS_MATH500_RELEASE_FIDELITY.search_iterations
    return MethodNodeResult(
        value={
            "iteration": iteration,
            "terminal": terminal,
            "budget_exhausted": exhausted,
        },
        next_node="return" if terminal or exhausted else "select",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _node_map(request.state)
    best_id = _text(request.state.get("best_node_id"), "best_node_id")
    best = nodes[best_id]
    visits = _integer(best.get("visits", 0), "visits")
    value = (
        _number(best.get("value_sum", 0.0), "value_sum") / max(1, visits)
    )
    return MethodNodeResult(
        value={
            "answer": best.get("text", ""),
            "best_node_id": best_id,
            "best_value": value,
            "search_iterations": _integer(
                request.state.get("iteration", 0),
                "iteration",
            ),
            "model_call_count": _integer(
                request.state.get("model_call_count", 0),
                "model_call_count",
            ),
            "search_algorithm": LITS_MATH500_RELEASE_FIDELITY.search_algorithm,
            "policy_component": LITS_MATH500_RELEASE_FIDELITY.policy_component,
            "transition_component": LITS_MATH500_RELEASE_FIDELITY.transition_component,
            "reward_component": LITS_MATH500_RELEASE_FIDELITY.reward_component,
        }
    )


def build_lits_math500_method_program() -> MethodProgram:
    fidelity = LITS_MATH500_RELEASE_FIDELITY
    configuration: JsonObject = {
        "source_repository": fidelity.source.repository,
        "source_commit": fidelity.source.commit,
        "source_artifacts": fidelity.source.artifacts,
        "benchmark_dataset": fidelity.benchmark_dataset,
        "benchmark_split": fidelity.benchmark_split,
        "search_algorithm": fidelity.search_algorithm,
        "policy_component": fidelity.policy_component,
        "transition_component": fidelity.transition_component,
        "reward_component": fidelity.reward_component,
        "search_iterations": fidelity.search_iterations,
        "candidate_actions": fidelity.candidate_actions,
        "max_steps": fidelity.max_steps,
        "model_binding_semantics": fidelity.model_binding_semantics,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="lits-math500",
            implementation_version=fidelity.source.commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="lits.math500.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="select")
    builder.route(
        "select",
        "lits.mcts.select",
        _select,
        ("policy", "return"),
        max_visits=fidelity.search_iterations + 1,
    )
    builder.agent(
        "policy",
        "lits.policy.generate",
        _POLICY_AGENT_ID,
        ("expand",),
        view_handler=_policy_view,
        max_visits=fidelity.search_iterations,
    )
    builder.compute(
        "expand",
        "lits.transition.concat",
        _expand,
        ("reward",),
        max_visits=fidelity.search_iterations,
    )
    builder.agent(
        "reward",
        "lits.reward.evaluate",
        _REWARD_AGENT_ID,
        ("backpropagate",),
        view_handler=_reward_view,
        max_visits=fidelity.search_iterations,
    )
    builder.compute(
        "backpropagate",
        "lits.mcts.backpropagate",
        _backpropagate,
        ("advance",),
        max_visits=fidelity.search_iterations,
    )
    builder.route(
        "advance",
        "lits.mcts.advance",
        _advance,
        ("select", "return"),
        max_visits=fidelity.search_iterations,
    )
    builder.return_node("return", "lits.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.CHECKPOINTABLE,
        evidence_obligations=(
            "lits.search-tree",
            "lits.policy-generation",
            "lits.reward-evaluation",
            "model.invocation",
        ),
        metric_names=("search_iterations", "model_call_count"),
        artifact_kinds=("lits_search_tree", "lits_reasoning_trace"),
    )


LITS_MATH500_METHOD_PROGRAM = build_lits_math500_method_program()


__all__ = [
    "LITS_MATH500_METHOD_PROGRAM",
    "build_lits_math500_method_program",
    "lits_math500_initial_state",
]
