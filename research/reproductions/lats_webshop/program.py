from __future__ import annotations

from collections.abc import Mapping, Sequence
import math

from noetrium_platform.capabilities.environment.composition import (
    environment_fork_action_payload,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import LATS_WEBSHOP_FIDELITY
from .reflection import should_refresh_reflections
from .tree import uct_score

_POLICY_AGENT_ID = "lats.policy"
_VALUE_AGENT_ID = "lats.value"
_REFLECTION_AGENT_ID = "lats.reflection"
_RESET_CAPABILITY = "environment.reset"
_BRANCH_CAPABILITY = "environment.branch-state"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"LATS {field} must be text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"LATS {field} must be a non-negative integer")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"LATS {field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"LATS {field} must be finite")
    return result


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"LATS {field} must be a sequence")
    return tuple(freeze_json(item) for item in value)


def lats_webshop_initial_state(
    *,
    task_id: str,
    source_cut_id: str,
    root_branch_id: str = "root",
) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "source_cut_id": _text(source_cut_id, "source_cut_id"),
        "root_branch_id": _text(root_branch_id, "root_branch_id"),
        "root_observation": "",
        "nodes": (),
        "selected_node_id": "",
        "iteration": 0,
        "phase": "expansion",
        "rollout_depth": 0,
        "sampled_actions": (),
        "candidate_index": 0,
        "current_candidates": (),
        "failed_trajectories": (),
        "reflections": (),
        "terminal_rollout_ids": (),
        "search_exhausted": False,
    }


def _node_id(row: Mapping[str, JsonValue]) -> str:
    return _text(row.get("node_id"), "node_id")


def _nodes(state: Mapping[str, JsonValue]) -> tuple[JsonObject, ...]:
    raw = _sequence(state.get("nodes", ()), "nodes")
    rows: list[JsonObject] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("LATS node rows must be mappings")
        rows.append(freeze_json(dict(item)))
    return tuple(rows)


def _node_map(state: Mapping[str, JsonValue]) -> dict[str, JsonObject]:
    rows = _nodes(state)
    result = {_node_id(row): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("LATS node ids must be unique")
    return result


def _replace_node(
    nodes: tuple[JsonObject, ...],
    node_id: str,
    update: Mapping[str, JsonValue],
) -> tuple[JsonObject, ...]:
    found = False
    rows: list[JsonObject] = []
    for row in nodes:
        if _node_id(row) != node_id:
            rows.append(row)
            continue
        found = True
        merged = dict(row)
        merged.update(update)
        rows.append(freeze_json(merged))
    if not found:
        raise KeyError(node_id)
    return tuple(rows)


def _trajectory(
    node_id: str,
    nodes: Mapping[str, JsonObject],
) -> tuple[JsonObject, ...]:
    rows: list[JsonObject] = []
    current: str | None = node_id
    while current is not None:
        row = nodes[current]
        rows.append(
            {
                "node_id": current,
                "depth": row["depth"],
                "action": row["action"],
                "observation": row["observation"],
            }
        )
        parent = row.get("parent_id")
        current = parent if isinstance(parent, str) and parent else None
    rows.reverse()
    return tuple(rows)


def _prepare_reset(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "task_id": _text(request.state.get("task_id"), "task_id"),
            "source_cut_id": _text(
                request.state.get("source_cut_id"),
                "source_cut_id",
            ),
        }
    )


def _reset_observation(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("observation", "text", "content"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
        observation = value.get("observation")
        if isinstance(observation, Mapping):
            payload = observation.get("payload")
            if isinstance(payload, str):
                return payload
            if isinstance(payload, Mapping):
                for key in ("text", "observation", "content"):
                    candidate = payload.get(key)
                    if isinstance(candidate, str):
                        return candidate
    return str(value)


def _record_root(request: MethodNodeRequest) -> MethodNodeResult:
    observation = _reset_observation(request.previous_value)
    root: JsonObject = {
        "node_id": "root",
        "parent_id": None,
        "depth": 0,
        "branch_id": _text(request.state.get("root_branch_id"), "root_branch_id"),
        "source_cut_id": _text(request.state.get("source_cut_id"), "source_cut_id"),
        "action": "",
        "observation": observation,
        "visits": 0,
        "value": 0.0,
        "reward": 0.0,
        "terminal": False,
        "exhausted": False,
        "tree_visible": True,
    }
    return MethodNodeResult(
        value={"root": "root"},
        state_update={
            "root_observation": observation,
            "nodes": (root,),
            "selected_node_id": "root",
            "iteration": 0,
            "phase": "expansion",
            "rollout_depth": 0,
            "failed_trajectories": (),
            "reflections": (),
            "terminal_rollout_ids": (),
            "search_exhausted": False,
        },
        next_node="select",
    )


def _visible_children(
    parent_id: str,
    nodes: Mapping[str, JsonObject],
) -> list[JsonObject]:
    return [
        row
        for row in nodes.values()
        if row.get("parent_id") == parent_id and row.get("tree_visible") is True
    ]


def _select_node(request: MethodNodeRequest) -> MethodNodeResult:
    nodes_tuple = _nodes(request.state)
    nodes = {_node_id(row): row for row in nodes_tuple}
    current_id: str | None = "root"
    mutable = nodes_tuple

    while current_id is not None:
        current = {_node_id(row): row for row in mutable}[current_id]
        children = _visible_children(current_id, {_node_id(row): row for row in mutable})
        active = [
            row
            for row in children
            if row.get("terminal") is not True and row.get("exhausted") is not True
        ]
        successful = next(
            (
                row
                for row in children
                if row.get("terminal") is True
                and _number(row.get("reward", 0.0), "reward") == LATS_WEBSHOP_FIDELITY.success_reward
            ),
            None,
        )
        if successful is not None:
            return MethodNodeResult(
                value={"success_node_id": _node_id(successful)},
                state_update={"selected_node_id": _node_id(successful)},
                next_node="return",
            )
        if not children:
            return MethodNodeResult(
                value={"selected_node_id": current_id},
                state_update={
                    "nodes": mutable,
                    "selected_node_id": current_id,
                    "phase": "expansion",
                    "rollout_depth": 0,
                },
                next_node="maybe_reflect",
            )
        if not active:
            if current_id == "root":
                return MethodNodeResult(
                    value={"search_exhausted": True},
                    state_update={"nodes": mutable, "search_exhausted": True},
                    next_node="return",
                )
            mutable = _replace_node(
                mutable,
                current_id,
                {"exhausted": True},
            )
            parent = current.get("parent_id")
            current_id = parent if isinstance(parent, str) and parent else None
            continue

        parent_visits = _integer(current.get("visits", 0), "parent visits")
        def score(row: JsonObject) -> float:
            visits = _integer(row.get("visits", 0), "visits")
            value = _number(row.get("value", 0.0), "value")
            return uct_score(
                value=value,
                visits=visits,
                parent_visits=max(parent_visits, 1),
            )
        selected = max(active, key=score)
        current_id = _node_id(selected)

    return MethodNodeResult(
        value={"search_exhausted": True},
        state_update={"nodes": mutable, "search_exhausted": True},
        next_node="return",
    )


def _maybe_reflect(request: MethodNodeRequest) -> MethodNodeResult:
    failed = _sequence(
        request.state.get("failed_trajectories", ()),
        "failed_trajectories",
    )
    reflections = _sequence(
        request.state.get("reflections", ()),
        "reflections",
    )
    refresh = should_refresh_reflections(
        failed_count=len(failed),
        reflection_count=len(reflections),
    )
    return MethodNodeResult(
        value={"refresh_reflections": refresh},
        next_node="reflection" if refresh else "policy",
    )


def _reflection_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task": _text(
            request.state.get("root_observation", ""),
            "root observation",
            allow_empty=True,
        ),
        "failed_trajectories": _sequence(
            request.state.get("failed_trajectories", ()),
            "failed_trajectories",
        ),
        "existing_reflections": _sequence(
            request.state.get("reflections", ()),
            "reflections",
        ),
    }


def _record_reflection(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    candidate: object = value
    if isinstance(value, Mapping):
        candidate = value.get("reflections", value.get("reflection"))
    if isinstance(candidate, str):
        rows = (candidate,)
    elif isinstance(candidate, Sequence) and not isinstance(
        candidate, (str, bytes, bytearray)
    ):
        rows = tuple(_text(row, "reflection") for row in candidate)
    else:
        raise TypeError("LATS reflection result must contain reflection text")
    return MethodNodeResult(
        value={"reflection_count": len(rows)},
        state_update={"reflections": rows},
        next_node="policy",
    )


def _policy_view(request: MethodNodeRequest) -> JsonObject:
    node_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    nodes = _node_map(request.state)
    node = nodes[node_id]
    sample_count = (
        LATS_WEBSHOP_FIDELITY.rollout_candidate_count
        * LATS_WEBSHOP_FIDELITY.root_expansion_multiplier
        if _integer(node.get("depth", 0), "depth") == 0
        and request.state.get("phase") == "expansion"
        else LATS_WEBSHOP_FIDELITY.rollout_candidate_count
    )
    return {
        "task": request.state.get("root_observation", ""),
        "trajectory": _trajectory(node_id, nodes),
        "reflections": _sequence(
            request.state.get("reflections", ()),
            "reflections",
        ),
        "sample_count": sample_count,
        "temperature": LATS_WEBSHOP_FIDELITY.temperature,
        "phase": request.state.get("phase"),
    }


def _sampled_actions(
    value: JsonValue,
    expected: int,
) -> tuple[str, ...]:
    candidate: object = value
    if isinstance(value, Mapping):
        candidate = value.get("actions", value.get("samples"))
    if not isinstance(candidate, Sequence) or isinstance(
        candidate, (str, bytes, bytearray)
    ):
        raise TypeError("LATS policy result must contain action sequence")
    actions = tuple(_text(row, "sampled action") for row in candidate)
    if len(actions) != expected:
        raise ValueError("LATS policy sample count drifted from method configuration")

    # The released code keeps the last node for a duplicate action key while
    # preserving the key's first insertion position.
    positions: list[str] = []
    latest: dict[str, str] = {}
    for action in actions:
        if action not in latest:
            positions.append(action)
        latest[action] = action
    return tuple(latest[action] for action in positions)


def _record_samples(request: MethodNodeRequest) -> MethodNodeResult:
    node_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    node = _node_map(request.state)[node_id]
    expected = (
        LATS_WEBSHOP_FIDELITY.rollout_candidate_count
        * LATS_WEBSHOP_FIDELITY.root_expansion_multiplier
        if _integer(node.get("depth", 0), "depth") == 0
        and request.state.get("phase") == "expansion"
        else LATS_WEBSHOP_FIDELITY.rollout_candidate_count
    )
    actions = _sampled_actions(request.previous_value, expected)
    if not actions:
        raise RuntimeError("LATS policy produced no unique candidate actions")
    return MethodNodeResult(
        value={"candidate_count": len(actions)},
        state_update={
            "sampled_actions": actions,
            "candidate_index": 0,
            "current_candidates": (),
        },
        next_node="prepare_candidate",
    )


def _prepare_candidate(request: MethodNodeRequest) -> MethodNodeResult:
    actions = _sequence(
        request.state.get("sampled_actions", ()),
        "sampled_actions",
    )
    index = _integer(request.state.get("candidate_index", 0), "candidate_index")
    if index >= len(actions):
        raise IndexError("LATS candidate index outside sampled actions")
    parent_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    parent = _node_map(request.state)[parent_id]
    iteration = _integer(request.state.get("iteration", 0), "iteration")
    phase = _text(request.state.get("phase"), "phase")
    child_id = f"{phase}:{iteration}:{parent_id}:{index}"
    return MethodNodeResult(
        value=environment_fork_action_payload(
            parent_branch_id=_text(parent.get("branch_id"), "parent branch_id"),
            child_branch_id=child_id,
            source_cut_id=_text(
                parent.get("source_cut_id"),
                "parent source_cut_id",
            ),
            action_type="command",
            action_payload={"text": _text(actions[index], "candidate action")},
        )
    )


def _branch_result(
    value: JsonValue,
    *,
    fallback_action: str,
    child_id: str,
    parent_id: str,
    depth: int,
    tree_visible: bool,
) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("LATS branch result must be a mapping")
    action = value.get("action", fallback_action)
    action_payload = value.get("action_payload")
    if isinstance(action_payload, Mapping):
        candidate_text = action_payload.get("text")
        if isinstance(candidate_text, str) and candidate_text.strip():
            action = candidate_text

    raw_observation = value.get("observation", "")
    observation_payload: object = raw_observation
    if isinstance(raw_observation, Mapping) and "payload" in raw_observation:
        observation_payload = raw_observation.get("payload")

    reward: object = value.get("reward", 0.0)
    terminal: object = value.get("terminal", value.get("done", False))
    observation: object = observation_payload
    if isinstance(observation_payload, Mapping):
        reward = observation_payload.get("reward", reward)
        terminal = observation_payload.get(
            "terminal",
            observation_payload.get("done", terminal),
        )
        for key in ("text", "observation", "content"):
            candidate_text = observation_payload.get(key)
            if isinstance(candidate_text, str):
                observation = candidate_text
                break

    branch_id = value.get("branch_id", child_id)
    source_cut_id = value.get("source_cut_id", value.get("branch_state_digest"))
    if not isinstance(action, str) or not action.strip():
        raise ValueError("LATS branch result action is required")
    if not isinstance(observation, str):
        observation = str(observation)
    if type(terminal) is not bool:
        raise TypeError("LATS branch result terminal must be boolean")
    reward_value = _number(reward, "branch reward")
    if source_cut_id is None:
        raise ValueError("LATS branch result requires source_cut_id/branch_state_digest")
    return {
        "node_id": child_id,
        "parent_id": parent_id,
        "depth": depth,
        "branch_id": _text(branch_id, "branch_id"),
        "source_cut_id": _text(source_cut_id, "source_cut_id"),
        "action": action,
        "observation": observation,
        "visits": 0,
        "value": reward_value,
        "reward": reward_value,
        "terminal": terminal or reward_value > 0.0,
        "exhausted": False,
        "tree_visible": tree_visible,
    }


def _trajectory_text(
    node: JsonObject,
    nodes: Mapping[str, JsonObject],
) -> str:
    rows = _trajectory(_node_id(node), nodes)
    parts = [str(rows[0].get("observation", ""))]
    for row in rows[1:]:
        parts.append(f"Action: {row.get('action', '')}")
        parts.append(f"Observation: {row.get('observation', '')}")
    return "\n".join(parts)


def _record_candidate(request: MethodNodeRequest) -> MethodNodeResult:
    actions = _sequence(
        request.state.get("sampled_actions", ()),
        "sampled_actions",
    )
    index = _integer(request.state.get("candidate_index", 0), "candidate_index")
    parent_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    parent = _node_map(request.state)[parent_id]
    phase = _text(request.state.get("phase"), "phase")
    iteration = _integer(request.state.get("iteration", 0), "iteration")
    child_id = f"{phase}:{iteration}:{parent_id}:{index}"
    child = _branch_result(
        request.previous_value,
        fallback_action=_text(actions[index], "candidate action"),
        child_id=child_id,
        parent_id=parent_id,
        depth=_integer(parent.get("depth", 0), "parent depth") + 1,
        tree_visible=phase == "expansion",
    )

    nodes = (*_nodes(request.state), child)
    candidates = (
        *_sequence(
            request.state.get("current_candidates", ()),
            "current_candidates",
        ),
        child_id,
    )
    failed = list(
        _sequence(
            request.state.get("failed_trajectories", ()),
            "failed_trajectories",
        )
    )
    reward = _number(child.get("reward", 0.0), "reward")
    if (
        child.get("terminal") is True
        and 0.0 < reward < LATS_WEBSHOP_FIDELITY.success_reward
        and len(failed) < LATS_WEBSHOP_FIDELITY.unique_failed_trajectory_limit
    ):
        known = {
            row.get("final_answer")
            for row in failed
            if isinstance(row, Mapping)
        }
        if child["action"] not in known:
            failed.append(
                {
                    "final_answer": child["action"],
                    "trajectory": _trajectory_text(
                        child,
                        {_node_id(row): row for row in nodes},
                    ),
                    "reward": reward,
                }
            )

    next_index = index + 1
    if next_index < len(actions):
        next_node = "prepare_candidate"
    else:
        next_node = "value"
    return MethodNodeResult(
        value={"child_node_id": child_id, "reward": reward},
        state_update={
            "nodes": nodes,
            "current_candidates": candidates,
            "candidate_index": next_index,
            "failed_trajectories": tuple(failed),
        },
        next_node=next_node,
    )


def _value_view(request: MethodNodeRequest) -> JsonObject:
    nodes = _node_map(request.state)
    ids = _sequence(
        request.state.get("current_candidates", ()),
        "current_candidates",
    )
    nonterminal = [
        _text(node_id, "candidate node id")
        for node_id in ids
        if nodes[_text(node_id, "candidate node id")].get("terminal") is not True
    ]
    return {
        "task": request.state.get("root_observation", ""),
        "candidates": tuple(
            {
                "node_id": node_id,
                "trajectory": _trajectory(node_id, nodes),
            }
            for node_id in nonterminal
        ),
        "sample_count": LATS_WEBSHOP_FIDELITY.value_evaluation_sample_count,
        "failed_trajectories": request.state.get("failed_trajectories", ()),
        "reflections": request.state.get("reflections", ()),
    }


def _value_scores(value: JsonValue, expected: int) -> tuple[float, ...]:
    candidate: object = value
    if isinstance(value, Mapping):
        candidate = value.get("values", value.get("scores"))
    if expected == 0:
        return ()
    if not isinstance(candidate, Sequence) or isinstance(
        candidate, (str, bytes, bytearray)
    ):
        raise TypeError("LATS value result must contain numeric sequence")
    scores = tuple(_number(row, "value score") for row in candidate)
    if len(scores) != expected:
        raise ValueError("LATS value score count mismatch")
    return scores


def _assign_values(request: MethodNodeRequest) -> MethodNodeResult:
    nodes_tuple = _nodes(request.state)
    nodes = {_node_id(row): row for row in nodes_tuple}
    ids = tuple(
        _text(row, "candidate node id")
        for row in _sequence(
            request.state.get("current_candidates", ()),
            "current_candidates",
        )
    )
    nonterminal = [node_id for node_id in ids if nodes[node_id].get("terminal") is not True]
    raw_scores = _value_scores(request.previous_value, len(nonterminal))
    score_iter = iter(raw_scores)
    votes: list[float] = []
    for node_id in ids:
        if nodes[node_id].get("terminal") is True:
            votes.append(0.0)
        else:
            votes.append(next(score_iter))
    max_vote = max(votes) if votes else 1.0
    if max_vote == 0.0:
        max_vote = 1.0
    for index, node_id in enumerate(ids):
        row = nodes[node_id]
        vote = votes[index]
        if row.get("terminal") is True:
            vote = max_vote + 1.0
        nodes_tuple = _replace_node(
            nodes_tuple,
            node_id,
            {"value": vote / max_vote},
        )
    return MethodNodeResult(
        value={"evaluated_candidates": len(ids)},
        state_update={"nodes": nodes_tuple},
        next_node="advance",
    )


def _advance(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _node_map(request.state)
    ids = tuple(
        _text(row, "candidate node id")
        for row in _sequence(
            request.state.get("current_candidates", ()),
            "current_candidates",
        )
    )
    if not ids:
        raise RuntimeError("LATS advance requires candidate nodes")
    best_id = max(ids, key=lambda node_id: _number(nodes[node_id].get("value", 0.0), "value"))
    best = nodes[best_id]
    reward = _number(best.get("reward", 0.0), "reward")
    if best.get("terminal") is True:
        terminals = list(
            _sequence(
                request.state.get("terminal_rollout_ids", ()),
                "terminal_rollout_ids",
            )
        )
        if request.state.get("phase") == "rollout":
            terminals.append(best_id)
        return MethodNodeResult(
            value={"terminal_node_id": best_id, "reward": reward},
            state_update={
                "selected_node_id": best_id,
                "terminal_rollout_ids": tuple(terminals),
            },
            next_node="return" if reward == LATS_WEBSHOP_FIDELITY.success_reward else "backprop",
        )

    if request.state.get("phase") == "expansion":
        return MethodNodeResult(
            value={"rollout_start": best_id},
            state_update={
                "selected_node_id": best_id,
                "phase": "rollout",
                "rollout_depth": 0,
            },
            next_node="maybe_reflect",
        )

    depth = _integer(request.state.get("rollout_depth", 0), "rollout_depth") + 1
    if depth >= LATS_WEBSHOP_FIDELITY.max_tree_depth:
        nodes_tuple = _replace_node(
            _nodes(request.state),
            best_id,
            {"reward": -0.5, "terminal": True},
        )
        terminals = (
            *_sequence(
                request.state.get("terminal_rollout_ids", ()),
                "terminal_rollout_ids",
            ),
            best_id,
        )
        return MethodNodeResult(
            value={"depth_limit": True, "node_id": best_id},
            state_update={
                "nodes": nodes_tuple,
                "selected_node_id": best_id,
                "rollout_depth": depth,
                "terminal_rollout_ids": terminals,
            },
            next_node="backprop",
        )
    return MethodNodeResult(
        value={"rollout_node_id": best_id, "rollout_depth": depth},
        state_update={
            "selected_node_id": best_id,
            "rollout_depth": depth,
        },
        next_node="maybe_reflect",
    )


def _backprop(request: MethodNodeRequest) -> MethodNodeResult:
    node_id = _text(request.state.get("selected_node_id"), "selected_node_id")
    nodes_tuple = _nodes(request.state)
    nodes = {_node_id(row): row for row in nodes_tuple}
    reward = _number(nodes[node_id].get("reward", 0.0), "reward")
    current: str | None = node_id
    while current is not None:
        row = {_node_id(item): item for item in nodes_tuple}[current]
        visits = _integer(row.get("visits", 0), "visits")
        value = _number(row.get("value", 0.0), "value")
        next_visits = visits + 1
        next_value = (value * visits + reward) / next_visits
        nodes_tuple = _replace_node(
            nodes_tuple,
            current,
            {"visits": next_visits, "value": next_value},
        )
        parent = row.get("parent_id")
        current = parent if isinstance(parent, str) and parent else None

    iteration = _integer(request.state.get("iteration", 0), "iteration") + 1
    return MethodNodeResult(
        value={"iteration": iteration, "backpropagated_reward": reward},
        state_update={
            "nodes": nodes_tuple,
            "iteration": iteration,
            "phase": "expansion",
            "rollout_depth": 0,
            "sampled_actions": (),
            "candidate_index": 0,
            "current_candidates": (),
        },
        next_node=(
            "return"
            if iteration >= LATS_WEBSHOP_FIDELITY.max_iterations
            else "select"
        ),
        checkpoint=True,
        checkpoint_value={
            "iteration": iteration,
            "reward": reward,
            "node_id": node_id,
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    nodes = _node_map(request.state)
    candidates = list(nodes.values())
    terminal_ids = {
        _text(row, "terminal rollout id")
        for row in _sequence(
            request.state.get("terminal_rollout_ids", ()),
            "terminal_rollout_ids",
        )
    }
    candidates.extend(
        nodes[node_id]
        for node_id in terminal_ids
        if node_id in nodes and nodes[node_id] not in candidates
    )
    if not candidates:
        raise RuntimeError("LATS result requires at least root node")
    best = max(
        candidates,
        key=lambda row: _number(row.get("reward", 0.0), "reward"),
    )
    reward = _number(best.get("reward", 0.0), "reward")
    return MethodNodeResult(
        value={
            "reward": reward,
            "task_success": reward == LATS_WEBSHOP_FIDELITY.success_reward,
            "iteration_count": _integer(
                request.state.get("iteration", 0),
                "iteration",
            ),
            "best_node_id": _node_id(best),
            "best_action": best.get("action", ""),
            "best_observation": best.get("observation", ""),
            "failed_trajectory_count": len(
                _sequence(
                    request.state.get("failed_trajectories", ()),
                    "failed_trajectories",
                )
            ),
            "reflection_count": len(
                _sequence(
                    request.state.get("reflections", ()),
                    "reflections",
                )
            ),
            "search_exhausted": request.state.get("search_exhausted") is True,
        }
    )


def build_lats_webshop_method_program() -> MethodProgram:
    fidelity = LATS_WEBSHOP_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.source.commit,
        "max_iterations": fidelity.max_iterations,
        "max_tree_depth": fidelity.max_tree_depth,
        "root_expansion_multiplier": fidelity.root_expansion_multiplier,
        "rollout_candidate_count": fidelity.rollout_candidate_count,
        "value_evaluation_sample_count": fidelity.value_evaluation_sample_count,
        "uct_exploration_constant": fidelity.uct_exploration_constant,
        "reflection_failed_trajectory_limit_exclusive": fidelity.reflection_failed_trajectory_limit_exclusive,
        "unique_failed_trajectory_limit": fidelity.unique_failed_trajectory_limit,
        "child_environment_semantics": fidelity.child_environment_semantics,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="lats",
            implementation_version=fidelity.source.commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="lats.webshop.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    # Host guards bound the graph while preserving the paper's 30-iteration and
    # depth-15 method semantics.
    max_candidate_evaluations = (
        fidelity.max_iterations
        * fidelity.max_tree_depth
        * fidelity.rollout_candidate_count
        * fidelity.root_expansion_multiplier
    )
    max_model_calls = fidelity.max_iterations * fidelity.max_tree_depth * 4

    builder = MethodProgramBuilder(identity, entrypoint="prepare_reset")
    builder.compute("prepare_reset", "lats.environment.reset.prepare", _prepare_reset, ("reset",))
    builder.capability("reset", "lats.environment.reset", _RESET_CAPABILITY, ("record_root",), effect_class=EffectClass.IDEMPOTENT)
    builder.compute("record_root", "lats.root.record", _record_root, ("select",))
    builder.route("select", "lats.uct.select", _select_node, ("maybe_reflect", "return"), max_visits=fidelity.max_iterations + 1)
    builder.route("maybe_reflect", "lats.reflection.route", _maybe_reflect, ("reflection", "policy"), max_visits=max_model_calls)
    builder.agent("reflection", "lats.reflection.generate", _REFLECTION_AGENT_ID, ("record_reflection",), view_handler=_reflection_view, max_visits=fidelity.unique_failed_trajectory_limit)
    builder.compute("record_reflection", "lats.reflection.record", _record_reflection, ("policy",), max_visits=fidelity.unique_failed_trajectory_limit)
    builder.agent("policy", "lats.policy.sample", _POLICY_AGENT_ID, ("record_samples",), view_handler=_policy_view, max_visits=max_model_calls)
    builder.compute("record_samples", "lats.samples.record", _record_samples, ("prepare_candidate",), max_visits=max_model_calls)
    builder.compute("prepare_candidate", "lats.branch.prepare", _prepare_candidate, ("branch",), max_visits=max_candidate_evaluations)
    builder.capability("branch", "lats.branch.evaluate", _BRANCH_CAPABILITY, ("record_candidate",), effect_class=EffectClass.IDEMPOTENT, max_visits=max_candidate_evaluations, evidence_obligations=("environment.branch.receipt",))
    builder.route("record_candidate", "lats.branch.record", _record_candidate, ("prepare_candidate", "value"), max_visits=max_candidate_evaluations)
    builder.agent("value", "lats.value.evaluate", _VALUE_AGENT_ID, ("assign_values",), view_handler=_value_view, max_visits=max_model_calls)
    builder.compute("assign_values", "lats.value.assign", _assign_values, ("advance",), max_visits=max_model_calls)
    builder.route("advance", "lats.rollout.advance", _advance, ("maybe_reflect", "backprop", "return"), max_visits=max_model_calls)
    builder.route("backprop", "lats.reward.backpropagate", _backprop, ("select", "return"), max_visits=fidelity.max_iterations)
    builder.return_node("return", "lats.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_RESET_CAPABILITY, _BRANCH_CAPABILITY),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "lats.search-tree",
            "lats.failed-trajectories",
            "lats.reflections",
            "environment.branch.receipt",
        ),
        metric_names=("reward", "task_success", "iteration_count"),
        artifact_kinds=("lats_search_tree", "lats_trajectory"),
    )


LATS_WEBSHOP_METHOD_PROGRAM = build_lats_webshop_method_program()

__all__ = [
    "LATS_WEBSHOP_METHOD_PROGRAM",
    "build_lats_webshop_method_program",
    "lats_webshop_initial_state",
]
