from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.environment.composition import (
    environment_branch_action_spec,
    environment_replay_action_payload,
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

from .fidelity import QLASS_ALFWORLD_RELEASED_FIDELITY

_POLICY_AGENT_ID = "qlass.sft-policy"
_Q_VALUE_AGENT_ID = "qlass.q-net"
_RESET_CAPABILITY = "environment.reset"
_BRANCH_CAPABILITY = "environment.branch-state"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"QLASS {field} must be text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"QLASS {field} must be a non-negative integer")
    return value


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"QLASS {field} must be a sequence")
    return tuple(freeze_json(item) for item in value)


def qlass_alfworld_initial_state(
    *,
    task_id: str,
    source_cut_id: str,
) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "source_cut_id": _text(source_cut_id, "source_cut_id"),
        "trajectory_index": 0,
        "turn": 0,
        "committed_actions": (),
        "committed_history": (),
        "candidate_index": 0,
        "candidate_actions": (),
        "candidate_results": (),
        "trajectory_results": (),
        "selected_action": "",
        "selected_reward": 0.0,
        "selected_finished": False,
    }


def _prepare_reset(request: MethodNodeRequest) -> MethodNodeResult:
    trajectory = _integer(
        request.state.get("trajectory_index", 0),
        "trajectory_index",
    )
    if trajectory >= QLASS_ALFWORLD_RELEASED_FIDELITY.trajectories_per_task:
        return MethodNodeResult(value={"all_trajectories_complete": True}, next_node="return")
    return MethodNodeResult(
        value={
            "task_id": _text(request.state.get("task_id"), "task_id"),
            "trajectory_index": trajectory,
            "num_icl_examples": QLASS_ALFWORLD_RELEASED_FIDELITY.num_icl_examples,
            "force_first_icl": QLASS_ALFWORLD_RELEASED_FIDELITY.force_first_icl,
        },
        next_node="reset",
    )


def _history_from_reset(value: JsonValue) -> tuple[JsonValue, ...]:
    if not isinstance(value, Mapping):
        return ()
    source: object = value
    observation = value.get("observation")
    if isinstance(observation, Mapping) and "payload" in observation:
        source = observation.get("payload")
    if not isinstance(source, Mapping):
        return ()
    candidate = source.get("history", source.get("conversations", ()))
    if isinstance(candidate, Sequence) and not isinstance(
        candidate, (str, bytes, bytearray)
    ):
        return tuple(freeze_json(row) for row in candidate)
    return ()


def _record_reset(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={"trajectory_started": True},
        state_update={
            "turn": 0,
            "committed_actions": (),
            "committed_history": _history_from_reset(request.previous_value),
            "candidate_index": 0,
            "candidate_actions": (),
            "candidate_results": (),
            "selected_action": "",
            "selected_reward": 0.0,
            "selected_finished": False,
        },
        next_node="policy",
    )


def _policy_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task_id": _text(request.state.get("task_id"), "task_id"),
        "trajectory_index": _integer(
            request.state.get("trajectory_index", 0),
            "trajectory_index",
        ),
        "turn": _integer(request.state.get("turn", 0), "turn"),
        "candidate_index": _integer(
            request.state.get("candidate_index", 0),
            "candidate_index",
        ),
        "history": _sequence(
            request.state.get("committed_history", ()),
            "committed_history",
        ),
        "num_icl_examples": QLASS_ALFWORLD_RELEASED_FIDELITY.num_icl_examples,
        "force_first_icl": QLASS_ALFWORLD_RELEASED_FIDELITY.force_first_icl,
        "disable_perturbation": QLASS_ALFWORLD_RELEASED_FIDELITY.disable_perturbation,
    }


def _action(value: JsonValue) -> str:
    if isinstance(value, str):
        return _text(value, "action")
    if isinstance(value, Mapping):
        candidate = value.get("action", value.get("text"))
        if isinstance(candidate, str):
            return _text(candidate, "action")
    raise TypeError("QLASS policy result must contain action text")


def _record_candidate(request: MethodNodeRequest) -> MethodNodeResult:
    actions = list(
        _sequence(request.state.get("candidate_actions", ()), "candidate_actions")
    )
    action = _action(request.previous_value)
    actions.append(action)
    return MethodNodeResult(
        value={"action": action},
        state_update={"candidate_actions": tuple(actions)},
        next_node="prepare_branch",
    )


def _prepare_branch(request: MethodNodeRequest) -> MethodNodeResult:
    candidate_index = _integer(
        request.state.get("candidate_index", 0),
        "candidate_index",
    )
    actions = _sequence(
        request.state.get("candidate_actions", ()),
        "candidate_actions",
    )
    if candidate_index >= len(actions):
        raise IndexError("QLASS candidate_index does not reference a sampled action")
    trajectory = _integer(
        request.state.get("trajectory_index", 0),
        "trajectory_index",
    )
    turn = _integer(request.state.get("turn", 0), "turn")
    return MethodNodeResult(
        value=environment_replay_action_payload(
            branch_id=f"trajectory:{trajectory}:turn:{turn}:candidate:{candidate_index}",
            source_cut_id=_text(
                request.state.get("source_cut_id"),
                "source_cut_id",
            ),
            committed_actions=tuple(
                row
                for row in _sequence(
                    request.state.get("committed_actions", ()),
                    "committed_actions",
                )
                if isinstance(row, Mapping)
            ),
            action_type="command",
            action_payload={
                "text": _text(actions[candidate_index], "candidate action")
            },
            retain_branch=False,
        )
    )


def _candidate_result(value: JsonValue) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError("QLASS branch capability result must be a mapping")
    action: object = value.get("action")
    action_payload = value.get("action_payload")
    if isinstance(action_payload, Mapping):
        candidate_text = action_payload.get("text")
        if isinstance(candidate_text, str):
            action = candidate_text

    raw_observation = value.get("observation", "")
    observation_payload: object = raw_observation
    if isinstance(raw_observation, Mapping) and "payload" in raw_observation:
        observation_payload = raw_observation.get("payload")

    history: object = value.get("history", value.get("conversations", ()))
    reward: object = value.get("reward", 0.0)
    finished: object = value.get("finished", value.get("done", False))
    observation: object = observation_payload
    if isinstance(observation_payload, Mapping):
        history = observation_payload.get(
            "history",
            observation_payload.get("conversations", history),
        )
        reward = observation_payload.get("reward", reward)
        finished = observation_payload.get(
            "finished",
            observation_payload.get("done", finished),
        )
        observation = observation_payload.get(
            "text",
            observation_payload.get("observation", observation_payload),
        )
    if not isinstance(action, str) or not action.strip():
        raise ValueError("QLASS branch result requires action")
    if not isinstance(history, Sequence) or isinstance(
        history, (str, bytes, bytearray)
    ):
        raise TypeError("QLASS branch result history must be a sequence")
    if isinstance(reward, bool) or not isinstance(reward, (int, float)):
        raise TypeError("QLASS branch result reward must be numeric")
    if type(finished) is not bool:
        raise TypeError("QLASS branch result finished must be boolean")
    return {
        "action": action,
        "history": tuple(freeze_json(row) for row in history),
        "reward": float(reward),
        "finished": finished,
        "observation": freeze_json(observation),
    }


def _record_branch(request: MethodNodeRequest) -> MethodNodeResult:
    results = list(
        _sequence(
            request.state.get("candidate_results", ()),
            "candidate_results",
        )
    )
    result = _candidate_result(request.previous_value)
    results.append(result)
    next_index = _integer(
        request.state.get("candidate_index", 0),
        "candidate_index",
    ) + 1
    if next_index < QLASS_ALFWORLD_RELEASED_FIDELITY.best_of_n:
        return MethodNodeResult(
            value={"candidate_complete": next_index},
            state_update={
                "candidate_index": next_index,
                "candidate_results": tuple(results),
            },
            next_node="policy",
        )
    return MethodNodeResult(
        value={"all_candidates_complete": True},
        state_update={
            "candidate_index": next_index,
            "candidate_results": tuple(results),
        },
        next_node="q_value",
    )


def _q_value_view(request: MethodNodeRequest) -> JsonObject:
    candidates = _sequence(
        request.state.get("candidate_results", ()),
        "candidate_results",
    )
    return {
        "task_id": _text(request.state.get("task_id"), "task_id"),
        "trajectory_index": _integer(
            request.state.get("trajectory_index", 0),
            "trajectory_index",
        ),
        "turn": _integer(request.state.get("turn", 0), "turn"),
        "candidates": tuple(
            {
                "index": index,
                "history": row.get("history", ()),
                "terminal": row.get("finished") is True,
                "terminal_reward": row.get("reward", 0.0),
            }
            for index, row in enumerate(candidates)
            if isinstance(row, Mapping)
        ),
        "model_max_length": QLASS_ALFWORLD_RELEASED_FIDELITY.qnet_model_max_length,
    }


def _scores(value: JsonValue, count: int) -> tuple[float, ...]:
    candidate: object = value
    if isinstance(value, Mapping):
        candidate = value.get("scores", value.get("q_values"))
    if not isinstance(candidate, Sequence) or isinstance(
        candidate, (str, bytes, bytearray)
    ):
        raise TypeError("QLASS Q-Net result must contain score sequence")
    rows: list[float] = []
    for item in candidate:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise TypeError("QLASS Q-Net scores must be numeric")
        rows.append(float(item))
    if len(rows) != count:
        raise ValueError("QLASS Q-Net score count must equal best-of-N candidates")
    return tuple(rows)


def _select_candidate(request: MethodNodeRequest) -> MethodNodeResult:
    candidates = _sequence(
        request.state.get("candidate_results", ()),
        "candidate_results",
    )
    if len(candidates) != QLASS_ALFWORLD_RELEASED_FIDELITY.best_of_n:
        raise ValueError("QLASS candidate set does not match best-of-N")
    q_values = _scores(request.previous_value, len(candidates))
    selection_values = []
    for candidate, q_value in zip(candidates, q_values, strict=True):
        if not isinstance(candidate, Mapping):
            raise TypeError("QLASS candidate result must be a mapping")
        selection_values.append(
            float(candidate.get("reward", 0.0))
            if candidate.get("finished") is True
            else q_value
        )
    selected_index = max(range(len(candidates)), key=selection_values.__getitem__)
    selected = candidates[selected_index]
    assert isinstance(selected, Mapping)
    action = _text(selected.get("action"), "selected action")
    committed_actions = (
        *_sequence(
            request.state.get("committed_actions", ()),
            "committed_actions",
        ),
        environment_branch_action_spec("command", {"text": action}),
    )
    turn = _integer(request.state.get("turn", 0), "turn") + 1
    finished = selected.get("finished") is True
    reward = selected.get("reward", 0.0)
    if isinstance(reward, bool) or not isinstance(reward, (int, float)):
        raise TypeError("QLASS selected reward must be numeric")
    exhausted = turn >= QLASS_ALFWORLD_RELEASED_FIDELITY.max_turns_per_trajectory
    return MethodNodeResult(
        value={
            "selected_index": selected_index,
            "selected_action": action,
            "selection_value": selection_values[selected_index],
        },
        state_update={
            "turn": turn,
            "committed_actions": committed_actions,
            "committed_history": selected.get("history", ()),
            "selected_action": action,
            "selected_reward": float(reward),
            "selected_finished": finished,
            "candidate_index": 0,
            "candidate_actions": (),
            "candidate_results": (),
        },
        next_node="finish_trajectory" if finished or exhausted else "policy",
        checkpoint=True,
        checkpoint_value={
            "turn": turn,
            "selected_action": action,
            "selection_value": selection_values[selected_index],
        },
    )


def _finish_trajectory(request: MethodNodeRequest) -> MethodNodeResult:
    trajectory = _integer(
        request.state.get("trajectory_index", 0),
        "trajectory_index",
    )
    reward = request.state.get("selected_reward", 0.0)
    if isinstance(reward, bool) or not isinstance(reward, (int, float)):
        raise TypeError("QLASS trajectory reward must be numeric")
    success = float(reward) == 1.0
    results = list(
        _sequence(
            request.state.get("trajectory_results", ()),
            "trajectory_results",
        )
    )
    results.append(
        {
            "trajectory_index": trajectory,
            "reward": float(reward),
            "success": success,
            "turns": _integer(request.state.get("turn", 0), "turn"),
            "actions": _sequence(
                request.state.get("committed_actions", ()),
                "committed_actions",
            ),
        }
    )
    next_trajectory = trajectory + 1
    return MethodNodeResult(
        value={"trajectory_complete": trajectory, "success": success},
        state_update={
            "trajectory_results": tuple(results),
            "trajectory_index": next_trajectory,
        },
        next_node=(
            "return"
            if next_trajectory >= QLASS_ALFWORLD_RELEASED_FIDELITY.trajectories_per_task
            else "prepare_reset"
        ),
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    results = _sequence(
        request.state.get("trajectory_results", ()),
        "trajectory_results",
    )
    rewards = [
        float(row.get("reward", 0.0))
        for row in results
        if isinstance(row, Mapping)
    ]
    successes = [
        bool(row.get("success"))
        for row in results
        if isinstance(row, Mapping)
    ]
    turns = [
        _integer(row.get("turns", 0), "trajectory turns")
        for row in results
        if isinstance(row, Mapping)
    ]
    return MethodNodeResult(
        value={
            "trajectory_count": len(results),
            "trajectory_rewards": tuple(rewards),
            "trajectory_successes": tuple(successes),
            "task_success": any(successes),
            "first_trajectory_success": bool(successes and successes[0]),
            "mean_reward": (sum(rewards) / len(rewards)) if rewards else 0.0,
            "committed_turns": sum(turns),
        }
    )


def build_qlass_alfworld_method_program() -> MethodProgram:
    fidelity = QLASS_ALFWORLD_RELEASED_FIDELITY
    configuration: JsonObject = {
        "paper_source_commit": fidelity.paper_source.commit,
        "executable_source_commit": fidelity.executable_source.commit,
        "best_of_n": fidelity.best_of_n,
        "trajectories_per_task": fidelity.trajectories_per_task,
        "max_turns_per_trajectory": fidelity.max_turns_per_trajectory,
        "sampling_mode": fidelity.sampling_mode,
        "random_seed": fidelity.random_seed,
        "force_first_icl": fidelity.force_first_icl,
        "disable_perturbation": fidelity.disable_perturbation,
        "branch_strategy": fidelity.branch_strategy,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="qlass",
            implementation_version=fidelity.executable_source.commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="qlass.alfworld.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    turns = fidelity.committed_turn_budget
    candidates = turns * fidelity.best_of_n
    builder = MethodProgramBuilder(identity, entrypoint="prepare_reset")
    builder.route("prepare_reset", "qlass.trajectory.prepare", _prepare_reset, ("reset", "return"), max_visits=fidelity.trajectories_per_task + 1)
    builder.capability("reset", "qlass.environment.reset", _RESET_CAPABILITY, ("record_reset",), effect_class=EffectClass.IDEMPOTENT, max_visits=fidelity.trajectories_per_task)
    builder.compute("record_reset", "qlass.trajectory.start", _record_reset, ("policy",), max_visits=fidelity.trajectories_per_task)
    builder.agent("policy", "qlass.policy.sample", _POLICY_AGENT_ID, ("record_candidate",), view_handler=_policy_view, max_visits=candidates)
    builder.compute("record_candidate", "qlass.candidate.record", _record_candidate, ("prepare_branch",), max_visits=candidates)
    builder.compute("prepare_branch", "qlass.branch.prepare", _prepare_branch, ("branch",), max_visits=candidates)
    builder.capability("branch", "qlass.branch.evaluate", _BRANCH_CAPABILITY, ("record_branch",), effect_class=EffectClass.IDEMPOTENT, max_visits=candidates, evidence_obligations=("environment.branch.receipt",))
    builder.route("record_branch", "qlass.branch.record", _record_branch, ("policy", "q_value"), max_visits=candidates)
    builder.agent("q_value", "qlass.qnet.score", _Q_VALUE_AGENT_ID, ("select_candidate",), view_handler=_q_value_view, max_visits=turns)
    builder.route("select_candidate", "qlass.candidate.select", _select_candidate, ("policy", "finish_trajectory"), max_visits=turns)
    builder.route("finish_trajectory", "qlass.trajectory.finish", _finish_trajectory, ("prepare_reset", "return"), max_visits=fidelity.trajectories_per_task)
    builder.return_node("return", "qlass.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_RESET_CAPABILITY, _BRANCH_CAPABILITY),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "qlass.trajectory",
            "qlass.candidate-values",
            "environment.branch.receipt",
        ),
        metric_names=(
            "trajectory_reward",
            "trajectory_success",
            "first_trajectory_success",
            "committed_turns",
        ),
        artifact_kinds=("qlass_trajectory", "qlass_candidate_tree"),
    )


QLASS_ALFWORLD_METHOD_PROGRAM = build_qlass_alfworld_method_program()

__all__ = [
    "QLASS_ALFWORLD_METHOD_PROGRAM",
    "build_qlass_alfworld_method_program",
    "qlass_alfworld_initial_state",
]
