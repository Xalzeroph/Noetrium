from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium.api import (
    EffectClass,
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

from .fidelity import AGENT_Q_SURROGATE_FIDELITY

_ACTOR_AGENT_ID = "agent-q.surrogate.actor"
_CRITIC_AGENT_ID = "agent-q.surrogate.critic"
_JUDGE_AGENT_ID = "agent-q.surrogate.vision-judge"
_ENVIRONMENT_CAPABILITY_ID = "environment.act"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Agent Q surrogate {field} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"Agent Q surrogate {field} must be non-empty")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"Agent Q surrogate {field} must be integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Agent Q surrogate {field} must be numeric")
    return float(value)


def _rows(value: object, field: str) -> tuple[Mapping[str, JsonValue], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"Agent Q surrogate {field} must be a sequence")
    if any(not isinstance(row, Mapping) for row in value):
        raise TypeError(f"Agent Q surrogate {field} rows must be mappings")
    return tuple(value)


def agent_q_surrogate_initial_state(
    *,
    task: str,
    start_url: str,
) -> JsonObject:
    return {
        "task": _text(task, "task").strip(),
        "start_url": _text(start_url, "start_url").strip(),
        "iteration": 0,
        "depth": 0,
        "observation": "",
        "pending_action": "",
        "pending_siblings": (),
        "trajectory": (),
        "search_history": (),
        "best_reward": AGENT_Q_SURROGATE_FIDELITY.nonterminal_reward,
        "best_trajectory": (),
        "terminal_success": False,
        "generated_dpo_pairs": (),
    }


def _prepare_iteration(request: MethodNodeRequest) -> MethodNodeResult:
    iteration = _integer(request.state.get("iteration", 0), "iteration")
    if iteration >= AGENT_Q_SURROGATE_FIDELITY.browser_invocation_iterations:
        raise ValueError("Agent Q surrogate cannot start an iteration beyond its MCTS budget")
    return MethodNodeResult(
        value={
            "action": "navigate",
            "url": _text(request.state.get("start_url"), "start_url"),
            "reason": "paper-declared-home-reset-before-mcts-iteration",
        },
        state_update={
            "depth": 0,
            "observation": "",
            "pending_action": "",
            "pending_siblings": (),
            "trajectory": (),
        },
    )


def _record_iteration_reset(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value=request.previous_value,
        state_update={"observation": request.previous_value},
    )


def _actor_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task": _text(request.state.get("task"), "task"),
        "start_url": _text(request.state.get("start_url"), "start_url"),
        "iteration": _integer(request.state.get("iteration", 0), "iteration"),
        "depth": _integer(request.state.get("depth", 0), "depth"),
        "observation": request.state.get("observation"),
        "trajectory": request.state.get("trajectory", ()),
        "candidate_count_semantics": "actor proposes one chosen action plus sibling candidates",
    }


def _prepare_action(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, str):
        action = _text(value, "actor action").strip()
        siblings: tuple[str, ...] = ()
    elif isinstance(value, Mapping):
        action = _text(value.get("action"), "actor action").strip()
        raw_siblings = value.get("siblings", ())
        if not isinstance(raw_siblings, Sequence) or isinstance(
            raw_siblings, (str, bytes, bytearray)
        ):
            raise TypeError("Agent Q surrogate actor siblings must be a sequence")
        siblings = tuple(
            _text(row, "actor sibling").strip()
            for row in raw_siblings
            if isinstance(row, str) and row.strip() and row.strip() != action
        )
    else:
        raise TypeError("Agent Q surrogate actor result must be text or mapping")
    return MethodNodeResult(
        value={"action": action},
        state_update={
            "pending_action": action,
            "pending_siblings": siblings,
        },
    )


def _record_environment(request: MethodNodeRequest) -> MethodNodeResult:
    action = _text(request.state.get("pending_action"), "pending_action")
    depth = _integer(request.state.get("depth", 0), "depth") + 1
    trajectory = list(_rows(request.state.get("trajectory", ()), "trajectory"))
    trajectory.append(
        {
            "depth": depth,
            "action": action,
            "observation": request.previous_value,
            "siblings": request.state.get("pending_siblings", ()),
        }
    )
    return MethodNodeResult(
        value={"depth": depth, "observation": request.previous_value},
        state_update={
            "depth": depth,
            "observation": request.previous_value,
            "trajectory": tuple(trajectory),
        },
    )


def _critic_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task": _text(request.state.get("task"), "task"),
        "iteration": _integer(request.state.get("iteration", 0), "iteration"),
        "depth": _integer(request.state.get("depth", 0), "depth"),
        "trajectory": request.state.get("trajectory", ()),
        "reward_semantics": {
            "terminal": AGENT_Q_SURROGATE_FIDELITY.terminal_reward,
            "nonterminal": AGENT_Q_SURROGATE_FIDELITY.nonterminal_reward,
        },
    }


def _record_critic(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, Mapping):
        raw_score = value.get("score", value.get("value"))
    else:
        raw_score = value
    score = _number(raw_score, "critic score")
    history = list(_rows(request.state.get("search_history", ()), "search_history"))
    history.append(
        {
            "iteration": _integer(request.state.get("iteration", 0), "iteration"),
            "depth": _integer(request.state.get("depth", 0), "depth"),
            "score": score,
            "trajectory": request.state.get("trajectory", ()),
        }
    )
    best_reward = _number(request.state.get("best_reward"), "best_reward")
    best_trajectory = request.state.get("best_trajectory", ())
    if score > best_reward:
        best_reward = score
        best_trajectory = request.state.get("trajectory", ())
    return MethodNodeResult(
        value={"score": score},
        state_update={
            "search_history": tuple(history),
            "best_reward": best_reward,
            "best_trajectory": best_trajectory,
        },
    )


def _judge_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task": _text(request.state.get("task"), "task"),
        "trajectory": request.state.get("trajectory", ()),
        "observation": request.state.get("observation"),
        "judge_model_identity": AGENT_Q_SURROGATE_FIDELITY.terminal_judge_model,
    }


def _route_after_judge(request: MethodNodeRequest) -> MethodNodeResult:
    value = request.previous_value
    if isinstance(value, Mapping):
        success = value.get("success", value.get("terminal", False))
    else:
        success = value
    if type(success) is not bool:
        raise TypeError("Agent Q surrogate terminal judge must return boolean success")

    depth = _integer(request.state.get("depth", 0), "depth")
    iteration = _integer(request.state.get("iteration", 0), "iteration")
    if success:
        return MethodNodeResult(
            value={"success": True, "iteration": iteration, "depth": depth},
            state_update={
                "terminal_success": True,
                "best_reward": AGENT_Q_SURROGATE_FIDELITY.terminal_reward,
                "best_trajectory": request.state.get("trajectory", ()),
            },
            next_node="extract_preferences",
        )
    if depth < AGENT_Q_SURROGATE_FIDELITY.browser_invocation_depth:
        return MethodNodeResult(
            value={"success": False, "continue_depth": True},
            next_node="actor",
        )

    next_iteration = iteration + 1
    if next_iteration < AGENT_Q_SURROGATE_FIDELITY.browser_invocation_iterations:
        return MethodNodeResult(
            value={"success": False, "next_iteration": next_iteration},
            state_update={"iteration": next_iteration},
            next_node="prepare_iteration",
            checkpoint=True,
            checkpoint_value={
                "iteration": next_iteration,
                "best_reward": request.state.get("best_reward"),
            },
        )
    return MethodNodeResult(
        value={"success": False, "search_exhausted": True},
        next_node="extract_preferences",
    )


def _extract_preferences(request: MethodNodeRequest) -> MethodNodeResult:
    trajectory = _rows(
        request.state.get("best_trajectory", request.state.get("trajectory", ())),
        "best_trajectory",
    )
    pairs: list[JsonObject] = []
    for row in trajectory:
        chosen = row.get("action")
        siblings = row.get("siblings", ())
        if not isinstance(chosen, str) or not chosen:
            continue
        if not isinstance(siblings, Sequence) or isinstance(
            siblings, (str, bytes, bytearray)
        ):
            continue
        state_text = str(row.get("observation", ""))[
            : AGENT_Q_SURROGATE_FIDELITY.dpo_state_dom_character_limit
        ]
        for rejected in siblings:
            if isinstance(rejected, str) and rejected and rejected != chosen:
                pairs.append(
                    {
                        "state": state_text,
                        "chosen": chosen,
                        "rejected": rejected,
                    }
                )
    return MethodNodeResult(
        value={"generated_dpo_pairs": tuple(pairs)},
        state_update={"generated_dpo_pairs": tuple(pairs)},
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "terminal_judge_success": request.state.get("terminal_success") is True,
            "mcts_iterations": _integer(request.state.get("iteration", 0), "iteration") + 1,
            "generated_dpo_pairs": len(
                tuple(request.state.get("generated_dpo_pairs", ()))
            ),
            "best_reward": _number(request.state.get("best_reward"), "best_reward"),
            "best_trajectory": request.state.get("best_trajectory", ()),
            "surrogate_relation": AGENT_Q_SURROGATE_FIDELITY.relation_to_paper,
        }
    )


def build_agent_q_surrogate_method_program() -> MethodProgram:
    fidelity = AGENT_Q_SURROGATE_FIDELITY
    configuration: JsonObject = {
        "source_repository": fidelity.source.repository,
        "source_commit": fidelity.source.commit,
        "source_artifacts": fidelity.source.artifacts,
        "relation_to_paper": fidelity.relation_to_paper,
        "official_source_resolved": fidelity.official_source_resolved,
        "mcts_iterations": fidelity.browser_invocation_iterations,
        "mcts_depth": fidelity.browser_invocation_depth,
        "exploration": fidelity.browser_invocation_exploration,
        "simulation": fidelity.browser_invocation_simulation,
        "output": fidelity.browser_invocation_output,
        "terminal_reward": fidelity.terminal_reward,
        "nonterminal_reward": fidelity.nonterminal_reward,
        "terminal_judge_model": fidelity.terminal_judge_model,
        "environment_iteration_policy": fidelity.iteration_environment_policy,
        "dpo_pair_policy": fidelity.dpo_pair_policy,
        "dpo_state_dom_character_limit": fidelity.dpo_state_dom_character_limit,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="agent-q-surrogate",
            implementation_version=fidelity.source.commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="agent-q.surrogate.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    max_steps = (
        fidelity.browser_invocation_iterations
        * fidelity.browser_invocation_depth
    )
    builder = MethodProgramBuilder(identity, entrypoint="prepare_iteration")
    builder.compute(
        "prepare_iteration",
        "agent-q.iteration.prepare",
        _prepare_iteration,
        ("reset_home",),
        max_visits=fidelity.browser_invocation_iterations,
    )
    builder.capability(
        "reset_home",
        "agent-q.environment.home",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_reset",),
        effect_class=EffectClass.IDEMPOTENT,
        max_visits=fidelity.browser_invocation_iterations,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_reset",
        "agent-q.iteration.reset-record",
        _record_iteration_reset,
        ("actor",),
        max_visits=fidelity.browser_invocation_iterations,
    )
    builder.agent(
        "actor",
        "agent-q.actor.propose",
        _ACTOR_AGENT_ID,
        ("prepare_action",),
        view_handler=_actor_view,
        max_visits=max_steps,
    )
    builder.compute(
        "prepare_action",
        "agent-q.action.prepare",
        _prepare_action,
        ("environment",),
        max_visits=max_steps,
    )
    builder.capability(
        "environment",
        "agent-q.environment.act",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_environment",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=max_steps,
        evidence_obligations=("environment.effect",),
    )
    builder.compute(
        "record_environment",
        "agent-q.environment.record",
        _record_environment,
        ("critic",),
        max_visits=max_steps,
    )
    builder.agent(
        "critic",
        "agent-q.critic.evaluate",
        _CRITIC_AGENT_ID,
        ("record_critic",),
        view_handler=_critic_view,
        max_visits=max_steps,
    )
    builder.compute(
        "record_critic",
        "agent-q.critic.record",
        _record_critic,
        ("judge",),
        max_visits=max_steps,
    )
    builder.agent(
        "judge",
        "agent-q.terminal-judge",
        _JUDGE_AGENT_ID,
        ("route",),
        view_handler=_judge_view,
        max_visits=max_steps,
    )
    builder.route(
        "route",
        "agent-q.search.route",
        _route_after_judge,
        ("actor", "prepare_iteration", "extract_preferences"),
        max_visits=max_steps,
    )
    builder.compute(
        "extract_preferences",
        "agent-q.dpo.extract",
        _extract_preferences,
        ("return",),
    )
    builder.return_node("return", "agent-q.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "agent-q.search-history",
            "agent-q.preference-pairs",
            "environment.effect",
            "model.invocation",
        ),
        metric_names=(
            "terminal_judge_success",
            "mcts_iterations",
            "generated_dpo_pairs",
        ),
        artifact_kinds=("agent_q_search_trace", "agent_q_dpo_pairs"),
    )


AGENT_Q_SURROGATE_METHOD_PROGRAM = build_agent_q_surrogate_method_program()


__all__ = [
    "AGENT_Q_SURROGATE_METHOD_PROGRAM",
    "agent_q_surrogate_initial_state",
    "build_agent_q_surrogate_method_program",
]
