from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import RAP_FIDELITY
from .search import RAPReward, backpropagate_mean_rewards

_REASONER_AGENT_ID = "rap.reasoner"
_WORLD_MODEL_AGENT_ID = "rap.world_model"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"RAP {field} must be text")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"RAP {field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"RAP {field} must be finite numeric")
    return float(value)


def _nodes(state: Mapping[str, JsonValue]) -> tuple[Mapping[str, JsonValue], ...]:
    value = state.get("nodes")
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
    ):
        raise TypeError("RAP state requires a non-empty node sequence")
    if any(not isinstance(row, Mapping) for row in value):
        raise TypeError("RAP tree nodes must be mappings")
    return tuple(value)


def _node(nodes: tuple[Mapping[str, JsonValue], ...], node_id: str) -> Mapping[str, JsonValue]:
    for row in nodes:
        if row.get("node_id") == node_id:
            return row
    raise ValueError(f"RAP tree references unknown node: {node_id}")


def _replace_node(
    nodes: tuple[Mapping[str, JsonValue], ...],
    node_id: str,
    replacement: Mapping[str, JsonValue],
) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    found = False
    for row in nodes:
        if row.get("node_id") == node_id:
            rows.append(dict(replacement))
            found = True
        else:
            rows.append(dict(row))
    if not found:
        raise ValueError(f"RAP tree cannot replace unknown node: {node_id}")
    return tuple(rows)


def _current_id(state: Mapping[str, JsonValue]) -> str:
    return _text(state.get("current_node_id"), "current_node_id")


def _path(state: Mapping[str, JsonValue]) -> tuple[str, ...]:
    value = state.get("path")
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not value
        or any(not isinstance(row, str) or not row for row in value)
    ):
        raise TypeError("RAP state path must be a non-empty sequence of node ids")
    return tuple(value)


def _reward(r0: float, r1: float) -> float:
    return RAPReward(r0, r1, RAP_FIDELITY.alpha).combined


def _rap_world_model_view(request: MethodNodeRequest) -> JsonObject:
    nodes = _nodes(request.state)
    current_id = _current_id(request.state)
    return {
        "goal": _text(request.state.get("goal"), "goal"),
        "current_node": dict(_node(nodes, current_id)),
        "path": _path(request.state),
        "rollout": _integer(request.state.get("rollout"), "rollout"),
    }


def _rap_reasoner_view(request: MethodNodeRequest) -> JsonObject:
    nodes = _nodes(request.state)
    current_id = _current_id(request.state)
    return {
        "goal": _text(request.state.get("goal"), "goal"),
        "current_node": dict(_node(nodes, current_id)),
        "rollout": _integer(request.state.get("rollout"), "rollout"),
    }


def rap_blocksworld_initial_state(*, initial_state: str, goal: str) -> JsonObject:
    initial = _text(initial_state, "initial_state").strip()
    target = _text(goal, "goal").strip()
    root: JsonObject = {
        "node_id": "n0",
        "parent_id": "",
        "depth": 0,
        "action": "",
        "world_state": initial,
        "predicted_change": "",
        "r0": 0.0,
        "r1": RAP_FIDELITY.r1_default,
        "reward": 0.0,
        "evaluated": True,
        "expanded": False,
        "children": (),
        "q_sum": 0.0,
        "visits": 0,
        "max_return": None,
    }
    return {
        "initial_state": initial,
        "goal": target,
        "nodes": (root,),
        "current_node_id": "n0",
        "path": ("n0",),
        "rollout": 0,
        "next_node_index": 1,
        "best_node_id": "",
        "best_score": None,
    }


def _prepare_current(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _nodes(request.state)
    current = _node(nodes, _current_id(request.state))
    evaluated = current.get("evaluated") is True
    return MethodNodeResult(
        value={"node_id": current["node_id"], "evaluated": evaluated},
        next_node="terminal" if evaluated else "world_model",
    )


def _record_world_model(request: MethodNodeRequest) -> MethodNodeResult:
    if not isinstance(request.previous_value, Mapping):
        raise TypeError("RAP world-model result must be a mapping")
    predicted_change = _text(request.previous_value.get("predicted_change"), "predicted_change")
    predicted_state = _text(request.previous_value.get("predicted_state"), "predicted_state")
    r1 = _number(request.previous_value.get("world_state_reward"), "world_state_reward")

    nodes = _nodes(request.state)
    current_id = _current_id(request.state)
    current = dict(_node(nodes, current_id))
    if current.get("evaluated") is True:
        raise ValueError("RAP world model may not re-evaluate an already evaluated node")
    r0 = _number(current.get("r0"), "action prior")
    current.update(
        {
            "world_state": predicted_state,
            "predicted_change": predicted_change,
            "r1": r1,
            "reward": _reward(r0, r1),
            "evaluated": True,
        }
    )
    updated = _replace_node(nodes, current_id, current)
    return MethodNodeResult(
        value={
            "node_id": current_id,
            "predicted_change": predicted_change,
            "predicted_state": predicted_state,
            "r1": r1,
            "reward": current["reward"],
        },
        state_update={"nodes": updated},
    )


def _is_terminal(node: Mapping[str, JsonValue]) -> bool:
    depth = _integer(node.get("depth"), "node depth")
    if depth == 0:
        return False
    if node.get("evaluated") is not True:
        raise ValueError("RAP terminal decision requires evaluated world state")
    r1 = _number(node.get("r1"), "r1")
    reward = _number(node.get("reward"), "reward")
    return r1 > 50.0 or depth >= RAP_FIDELITY.max_depth or reward < -1.0


def _route_terminal(request: MethodNodeRequest) -> MethodNodeResult:
    current = _node(_nodes(request.state), _current_id(request.state))
    terminal = _is_terminal(current)
    return MethodNodeResult(
        value={"node_id": current["node_id"], "terminal": terminal},
        next_node="backpropagate" if terminal else "expansion",
    )


def _route_expansion(request: MethodNodeRequest) -> MethodNodeResult:
    current = _node(_nodes(request.state), _current_id(request.state))
    if current.get("expanded") is not True:
        next_node = "generate"
    else:
        children = current.get("children")
        if (
            not isinstance(children, Sequence)
            or isinstance(children, (str, bytes, bytearray))
        ):
            raise TypeError("RAP node children must be a sequence")
        next_node = "select" if children else "backpropagate"
    return MethodNodeResult(
        value={"node_id": current["node_id"], "expanded": current.get("expanded") is True},
        next_node=next_node,
    )


def _action_candidates(value: JsonValue) -> tuple[tuple[str, float], ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise TypeError("RAP reasoner result must be a sequence")
    rows: list[tuple[str, float]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise TypeError("RAP reasoner candidates must be mappings")
        action = _text(item.get("action"), f"candidate[{index}].action").strip()
        prior = _number(item.get("action_prior"), f"candidate[{index}].action_prior")
        if action in seen:
            raise ValueError("RAP reasoner candidates must have unique actions")
        seen.add(action)
        rows.append((action, prior))
    return tuple(rows)


def _record_expansion(request: MethodNodeRequest) -> MethodNodeResult:
    candidates = _action_candidates(request.previous_value)
    nodes = _nodes(request.state)
    current_id = _current_id(request.state)
    current = dict(_node(nodes, current_id))
    if current.get("expanded") is True:
        raise ValueError("RAP node expansion is immutable once materialized")
    depth = _integer(current.get("depth"), "node depth")
    next_index = _integer(request.state.get("next_node_index"), "next_node_index", minimum=1)

    children: list[JsonObject] = []
    for offset, (action, prior) in enumerate(candidates):
        node_id = f"n{next_index + offset}"
        children.append(
            {
                "node_id": node_id,
                "parent_id": current_id,
                "depth": depth + 1,
                "action": action,
                "world_state": "",
                "predicted_change": "",
                "r0": prior,
                "r1": RAP_FIDELITY.r1_default,
                "reward": _reward(prior, RAP_FIDELITY.r1_default),
                "evaluated": False,
                "expanded": False,
                "children": (),
                "q_sum": 0.0,
                "visits": 0,
                "max_return": None,
            }
        )
    current["expanded"] = True
    current["children"] = tuple(row["node_id"] for row in children)
    updated = (*_replace_node(nodes, current_id, current), *children)
    return MethodNodeResult(
        value={"node_id": current_id, "children": current["children"]},
        state_update={
            "nodes": updated,
            "next_node_index": next_index + len(children),
        },
    )


def _uct_score(node: Mapping[str, JsonValue], *, parent_visits: int) -> float:
    visits = _integer(node.get("visits"), "child visits")
    log_n = math.log(parent_visits) if parent_visits > 0 else 0.0
    if visits == 0:
        return _number(node.get("reward"), "child prior reward") + RAP_FIDELITY.exploration_weight * math.sqrt(log_n)
    maximum = node.get("max_return")
    if maximum is None:
        raise ValueError("visited RAP child requires max_return")
    return _number(maximum, "child max_return") + RAP_FIDELITY.exploration_weight * math.sqrt(log_n / visits)


def _select_child(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _nodes(request.state)
    current_id = _current_id(request.state)
    parent = _node(nodes, current_id)
    children = parent.get("children")
    if (
        not isinstance(children, Sequence)
        or isinstance(children, (str, bytes, bytearray))
        or not children
    ):
        raise ValueError("RAP selection requires expanded children")
    parent_visits = _integer(parent.get("visits"), "parent visits")

    best_id = children[0]
    best_score = _uct_score(_node(nodes, best_id), parent_visits=parent_visits)
    for child_id in children[1:]:
        score = _uct_score(_node(nodes, child_id), parent_visits=parent_visits)
        if score > best_score:
            best_id = child_id
            best_score = score
    return MethodNodeResult(
        value={"selected_node_id": best_id, "uct": best_score},
        state_update={
            "current_node_id": best_id,
            "path": (*_path(request.state), best_id),
        },
    )


def _path_to(nodes: tuple[Mapping[str, JsonValue], ...], node_id: str) -> tuple[str, ...]:
    reversed_ids: list[str] = []
    current_id = node_id
    while current_id:
        reversed_ids.append(current_id)
        current = _node(nodes, current_id)
        parent_id = current.get("parent_id")
        if not isinstance(parent_id, str):
            raise TypeError("RAP node parent_id must be text")
        current_id = parent_id
    return tuple(reversed(reversed_ids))


def _best_terminal(nodes: tuple[Mapping[str, JsonValue], ...]) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for node in nodes:
        if node.get("evaluated") is not True or not _is_terminal(node):
            continue
        ids = _path_to(nodes, _text(node.get("node_id"), "node_id"))
        rewards = tuple(_number(_node(nodes, node_id).get("reward"), "path reward") for node_id in ids)
        score = sum(rewards) / len(rewards)
        if best is None or score > best[1]:
            best = (_text(node.get("node_id"), "node_id"), score)
    return best


def _backpropagate(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _nodes(request.state)
    path = _path(request.state)
    leaf_to_root = tuple(
        _number(_node(nodes, node_id).get("reward"), "backprop reward")
        for node_id in reversed(path)
    )
    returns = backpropagate_mean_rewards(leaf_to_root, discount=RAP_FIDELITY.discount)

    updated = nodes
    for node_id, row in zip(reversed(path), returns):
        current = dict(_node(updated, node_id))
        visits = _integer(current.get("visits"), "node visits")
        q_sum = _number(current.get("q_sum"), "node q_sum")
        maximum = current.get("max_return")
        aggregate = row.aggregated_reward
        current.update(
            {
                "visits": visits + 1,
                "q_sum": q_sum + aggregate,
                "max_return": aggregate if maximum is None else max(_number(maximum, "node max_return"), aggregate),
            }
        )
        updated = _replace_node(updated, node_id, current)

    best = _best_terminal(updated)
    rollout = _integer(request.state.get("rollout"), "rollout") + 1
    return MethodNodeResult(
        value={
            "rollout": rollout,
            "best_node_id": "" if best is None else best[0],
            "best_score": None if best is None else best[1],
        },
        state_update={
            "nodes": updated,
            "rollout": rollout,
            "best_node_id": "" if best is None else best[0],
            "best_score": None if best is None else best[1],
            "current_node_id": "n0",
            "path": ("n0",),
        },
    )


def _route_rollout(request: MethodNodeRequest) -> MethodNodeResult:
    rollout = _integer(request.state.get("rollout"), "rollout")
    complete = rollout >= RAP_FIDELITY.rollouts
    return MethodNodeResult(
        value={"rollout": rollout, "complete": complete},
        next_node="return" if complete else "prepare",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _nodes(request.state)
    best_id = _text(request.state.get("best_node_id"), "best_node_id", allow_empty=True)
    if best_id:
        ids = _path_to(nodes, best_id)
        actions = tuple(
            _text(_node(nodes, node_id).get("action"), "node action")
            for node_id in ids[1:]
        )
    else:
        actions = ()
    return MethodNodeResult(
        value={
            "rollouts": _integer(request.state.get("rollout"), "rollout"),
            "best_node_id": best_id,
            "best_score": request.state.get("best_score"),
            "plan_actions": actions,
            "tree": tuple(dict(row) for row in nodes),
        }
    )


def build_rap_blocksworld_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "source_repository": RAP_FIDELITY.source.repository,
        "source_commit": RAP_FIDELITY.source.commit,
        "mcts_source_artifact": RAP_FIDELITY.mcts_source_artifact,
        "blocksworld_source_artifact": RAP_FIDELITY.blocksworld_source_artifact,
        "runner_source_artifact": RAP_FIDELITY.runner_source_artifact,
        "temperature": RAP_FIDELITY.temperature,
        "rollouts": RAP_FIDELITY.rollouts,
        "max_depth": RAP_FIDELITY.max_depth,
        "n_sample_confidence": RAP_FIDELITY.n_sample_confidence,
        "alpha": RAP_FIDELITY.alpha,
        "r1_default": RAP_FIDELITY.r1_default,
        "exploration_weight": RAP_FIDELITY.exploration_weight,
        "discount": RAP_FIDELITY.discount,
        "prior": RAP_FIDELITY.mcts_prior,
        "reward_aggregation": RAP_FIDELITY.mcts_reward_aggregation,
        "child_aggregation": RAP_FIDELITY.mcts_child_aggregation,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="rap-blocksworld",
            implementation_version="official-774817c2",
            abi_version="noetrium.method-machine.v1",
            schema_version="rap.blocksworld.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    search_visits = RAP_FIDELITY.rollouts * (RAP_FIDELITY.max_depth + 2)
    builder = MethodProgramBuilder(identity, entrypoint="prepare")
    builder.route("prepare", "rap.prepare-current", _prepare_current, ("terminal", "world_model"), max_visits=search_visits)
    builder.agent(
        "world_model",
        "rap.world-model",
        _WORLD_MODEL_AGENT_ID,
        ("record_world_model",),
        view_handler=_rap_world_model_view,
        max_visits=search_visits,
    )
    builder.compute("record_world_model", "rap.record-world-model", _record_world_model, ("terminal",), max_visits=search_visits)
    builder.route("terminal", "rap.terminal-route", _route_terminal, ("backpropagate", "expansion"), max_visits=search_visits)
    builder.route("expansion", "rap.expansion-route", _route_expansion, ("generate", "select", "backpropagate"), max_visits=search_visits)
    builder.agent(
        "generate",
        "rap.generate-actions",
        _REASONER_AGENT_ID,
        ("record_expansion",),
        view_handler=_rap_reasoner_view,
        max_visits=search_visits,
    )
    builder.compute("record_expansion", "rap.record-expansion", _record_expansion, ("expansion",), max_visits=search_visits)
    builder.compute("select", "rap.uct-select", _select_child, ("prepare",), max_visits=search_visits)
    builder.compute("backpropagate", "rap.mean-backpropagate", _backpropagate, ("rollout",), max_visits=RAP_FIDELITY.rollouts)
    builder.route("rollout", "rap.rollout-route", _route_rollout, ("prepare", "return"), max_visits=RAP_FIDELITY.rollouts)
    builder.return_node("return", "rap.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=("rap.search.tree", "model.invocation"),
        metric_names=("plan_valid", "rollout_count"),
        artifact_kinds=("rap_search_tree",),
    )


RAP_BLOCKSWORLD_METHOD_PROGRAM = build_rap_blocksworld_method_program()


__all__ = [
    "RAP_BLOCKSWORLD_METHOD_PROGRAM",
    "build_rap_blocksworld_method_program",
    "rap_blocksworld_initial_state",
]
