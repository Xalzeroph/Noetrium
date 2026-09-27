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
from research.reproductions._support import JsonObject, canonical_digest

from collections.abc import Mapping




from .fidelity import MULTIAGENT_DEBATE_FIDELITY


_AGENT_IDS = (
    "multiagent-debate.agent-0",
    "multiagent-debate.agent-1",
    "multiagent-debate.agent-2",
)


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"multi-agent debate {field} must be non-empty text")
    return value.strip()


def _model_text(value: object) -> str:
    if isinstance(value, str):
        return _text(value, "model response")
    if not isinstance(value, Mapping):
        raise TypeError("multi-agent debate model response must be text or mapping")
    for key in ("content", "text", "response", "answer"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    raise ValueError("multi-agent debate model response has no textual content")


def multiagent_debate_initial_state(question: str) -> JsonObject:
    return {
        "question": _text(question, "question"),
        "round1_agent_0": "",
        "round1_agent_1": "",
        "round1_agent_2": "",
        "round2_agent_0": "",
        "round2_agent_1": "",
        "round2_agent_2": "",
        "model_call_count": 0,
    }


def _response_key(round_index: int, agent_index: int) -> str:
    return f"round{round_index}_agent_{agent_index}"


def _agent_view(agent_index: int, round_index: int):
    if agent_index not in range(3) or round_index not in {1, 2}:
        raise ValueError("multi-agent debate view identity is invalid")

    def view(request: MethodCall) -> JsonObject:
        question = _text(request.state.get("question"), "question")
        if round_index == 1:
            peer_snapshot: tuple[str, ...] = ()
            own_history: tuple[str, ...] = ()
        else:
            peer_snapshot = tuple(
                _text(
                    request.state.get(_response_key(1, peer)),
                    f"round-1 agent-{peer} response",
                )
                for peer in range(3)
                if peer != agent_index
            )
            own_history = (
                _text(
                    request.state.get(_response_key(1, agent_index)),
                    f"round-1 agent-{agent_index} response",
                ),
            )
        return {
            "phase": "multiagent_debate",
            "question": question,
            "agent_index": agent_index,
            "round_index": round_index,
            "own_previous_responses": own_history,
            "peer_previous_round_responses": peer_snapshot,
            "peer_injection_role": "user_information",
            "response_contract": MULTIAGENT_DEBATE_FIDELITY.final_answer_format,
        }

    return view


def _record_response(agent_index: int, round_index: int):
    key = _response_key(round_index, agent_index)

    def record(request: MethodCall) -> MethodNodeResult:
        count = request.state.get("model_call_count", 0)
        if type(count) is not int or count < 0:
            raise ValueError("multi-agent debate model_call_count must be non-negative")
        return dict(
            value={
                "agent_index": agent_index,
                "round_index": round_index,
                "response": _model_text(request.previous_value),
            },
            state_update={
                key: _model_text(request.previous_value),
                "model_call_count": count + 1,
            },
            checkpoint=True,
            checkpoint_value={
                "agent_index": agent_index,
                "round_index": round_index,
                "completed_model_calls": count + 1,
            },
        )

    return record


def _return_result(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "question": _text(request.state.get("question"), "question"),
            "rounds": (
                tuple(
                    _text(
                        request.state.get(_response_key(1, agent)),
                        f"round-1 agent-{agent} response",
                    )
                    for agent in range(3)
                ),
                tuple(
                    _text(
                        request.state.get(_response_key(2, agent)),
                        f"round-2 agent-{agent} response",
                    )
                    for agent in range(3)
                ),
            ),
            "final_responses": tuple(
                _text(
                    request.state.get(_response_key(2, agent)),
                    f"round-2 agent-{agent} response",
                )
                for agent in range(3)
            ),
            "model_call_count": request.state.get("model_call_count", 0),
        }
    )


def build_multiagent_debate_method_program(method, ) -> None:
    f = MULTIAGENT_DEBATE_FIDELITY
    configuration: JsonObject = {
        "paper": "Improving Factuality and Reasoning in Language Models through Multiagent Debate",
        "source_repository": f.source_repository,
        "source_commit": f.audited_commit,
        "source_artifact": f.source_artifact,
        "agent_count": f.default_agent_count,
        "round_count": f.default_round_count,
        "independent_agent_contexts": f.independent_agent_contexts,
        "first_round_independent": f.first_round_independent,
        "round_information_semantics": f.round_information_semantics,
        "self_previous_response_remains_in_local_context": (
            f.self_previous_response_remains_in_local_context
        ),
        "peer_responses_are_injected_as_user_information": (
            f.peer_responses_are_injected_as_user_information
        ),
        "reference_model": f.model_at_audited_gsm_script,
        "final_answer_format": f.final_answer_format,
    }


    builder = method
    sequence: list[tuple[int, int]] = [
        (1, 0),
        (1, 1),
        (1, 2),
        (2, 0),
        (2, 1),
        (2, 2),
    ]
    for index, (round_index, agent_index) in enumerate(sequence):
        agent_node = f"round{round_index}_agent_{agent_index}"
        record_node = f"record_round{round_index}_agent_{agent_index}"
        next_node = (
            "return"
            if index == len(sequence) - 1
            else f"round{sequence[index + 1][0]}_agent_{sequence[index + 1][1]}"
        )
        builder.agent(
            agent_node,
            f"multiagent-debate.round{round_index}.agent{agent_index}",
            _AGENT_IDS[agent_index],
            (record_node,),
            view=_agent_view(agent_index, round_index),
            max_visits=1,
        )
        builder.compute(
            record_node,
            f"multiagent-debate.round{round_index}.agent{agent_index}.record",
            _record_response(agent_index, round_index),
            (next_node,),
            max_visits=1,
        )
    builder.return_node("return", "multiagent-debate.result", _return_result)
    builder.configure(configuration)
    builder.policy(
        execution='effect_recorded',
        evidence=(
            "multiagent-debate.independent-contexts",
            "multiagent-debate.previous-round-peer-snapshot",
            "multiagent-debate.transcript",
            "model.invocation",
        ),
        metrics=(
            "task_success",
            "model_call_count",
            "debate_round_count",
        ),
        artifacts=("multiagent_debate_transcript",),
    )
    return builder


METHOD_CONFIGURER = build_multiagent_debate_method_program
METHOD_ENTRYPOINT = "round1_agent_0"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}


__all__ = [
    'build_multiagent_debate_method_program',
    'multiagent_debate_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]

METHOD_SPEC = {"method_id": 'multiagent-debate', "version": "paper-protocol", "semantic_contract": 'multiagent-debate' + ".method.v2", "entrypoint": METHOD_ENTRYPOINT}

__all__ = tuple(dict.fromkeys((*__all__, 'METHOD_SPEC')))
