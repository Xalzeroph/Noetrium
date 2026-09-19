from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
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

from .fidelity import CAMEL_ROLE_PLAYING_FIDELITY

_TASK_SPECIFIER = "camel.task-specifier"
_TASK_PLANNER = "camel.task-planner"
_ASSISTANT_AGENT = "camel.assistant-agent"
_USER_AGENT = "camel.user-agent"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"CAMEL {field} must be text")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"CAMEL {field} must be a non-negative integer")
    return value


def _sequence(value: object, field: str) -> tuple[JsonValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"CAMEL {field} must be a sequence")
    return tuple(freeze_json(row) for row in value)


def camel_ai_society_initial_state(
    *,
    task_id: str,
    assistant_role: str,
    user_role: str,
    original_task: str,
) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "assistant_role": _text(assistant_role, "assistant_role"),
        "user_role": _text(user_role, "user_role"),
        "original_task": _text(original_task, "original_task"),
        "specified_task": "",
        "planned_task": "",
        "final_task": "",
        "assistant_history": (),
        "user_history": (),
        "transcript": (),
        "message_count": 0,
        "user_no_instruction_count": 0,
        "assistant_instruction_count": 0,
        "repeat_word_count": 0,
        "repeat_threshold_hits": 0,
        "pending_user": None,
        "pending_assistant": None,
        "termination_reason": "",
        "task_done": False,
    }


def _model_message(value: JsonValue, field: str) -> JsonObject:
    if isinstance(value, str):
        return {
            "content": _text(value, field),
            "terminated": False,
            "finish_reason": "stop",
        }
    if not isinstance(value, Mapping):
        raise TypeError(f"CAMEL {field} model result must be text or mapping")
    content = value.get("content", "")
    terminated = value.get("terminated", False)
    finish_reason = value.get("finish_reason", "stop")
    if type(terminated) is not bool:
        raise TypeError(f"CAMEL {field} terminated must be boolean")
    if not isinstance(finish_reason, str) or not finish_reason:
        raise ValueError(f"CAMEL {field} finish_reason must be non-empty")
    if terminated:
        content_text = "" if content is None else str(content)
    else:
        content_text = _text(content, f"{field} content")
    return {
        "content": content_text,
        "terminated": terminated,
        "finish_reason": finish_reason,
    }


def _task_specify_view(request: MethodNodeRequest) -> JsonObject:
    f = CAMEL_ROLE_PLAYING_FIDELITY
    return {
        "phase": "task_specification",
        "original_task": request.state["original_task"],
        "assistant_role": request.state["assistant_role"],
        "user_role": request.state["user_role"],
        "prompt_blob": f.task_specify_prompt_blob,
        "word_limit": f.task_specifier_word_limit,
        "temperature": f.task_specifier_temperature,
    }


def _record_specified_task(request: MethodNodeRequest) -> MethodNodeResult:
    row = _model_message(request.previous_value, "task specification")
    if row["terminated"] is True:
        raise RuntimeError("CAMEL task specification terminated")
    task = _text(row["content"], "specified task")
    return MethodNodeResult(
        value={"specified_task": task},
        state_update={"specified_task": task},
        next_node="plan_task",
    )


def _task_plan_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "phase": "task_planning",
        "specified_task": _text(request.state.get("specified_task"), "specified task"),
        "prompt": "Divide this task into subtasks: <TASK>. Be concise.",
        "temperature": CAMEL_ROLE_PLAYING_FIDELITY.default_chat_temperature,
    }


def _record_planned_task(request: MethodNodeRequest) -> MethodNodeResult:
    row = _model_message(request.previous_value, "task planning")
    if row["terminated"] is True:
        raise RuntimeError("CAMEL task planning terminated")
    planned = _text(row["content"], "planned task")
    specified = _text(request.state.get("specified_task"), "specified task")
    final_task = f"{specified}\n{planned}"
    return MethodNodeResult(
        value={"planned_task": planned, "final_task": final_task},
        state_update={
            "planned_task": planned,
            "final_task": final_task,
        },
        next_node="bootstrap_assistant",
    )


def _system_identity(state: Mapping[str, JsonValue], *, role: str) -> JsonObject:
    f = CAMEL_ROLE_PLAYING_FIDELITY
    if role == "assistant":
        prompt_blob = f.assistant_prompt_blob
        role_name = _text(state.get("assistant_role"), "assistant role")
        counterpart = _text(state.get("user_role"), "user role")
    elif role == "user":
        prompt_blob = f.user_prompt_blob
        role_name = _text(state.get("user_role"), "user role")
        counterpart = _text(state.get("assistant_role"), "assistant role")
    else:
        raise ValueError(role)
    return {
        "kind": "system",
        "role": role,
        "role_name": role_name,
        "counterpart_role": counterpart,
        "task": _text(state.get("final_task"), "final task"),
        "prompt_blob": prompt_blob,
    }


def _bootstrap_view(request: MethodNodeRequest) -> JsonObject:
    assistant_system = _system_identity(request.state, role="assistant")
    return {
        "phase": "hidden_assistant_bootstrap",
        "system": assistant_system,
        "input": {
            "kind": "assistant_system_message_echo_as_user_message",
            "content_identity": canonical_digest(assistant_system),
        },
        "temperature": CAMEL_ROLE_PLAYING_FIDELITY.default_chat_temperature,
    }


def _record_bootstrap(request: MethodNodeRequest) -> MethodNodeResult:
    row = _model_message(request.previous_value, "assistant bootstrap")
    if row["terminated"] is True:
        raise RuntimeError("CAMEL hidden assistant bootstrap terminated")
    assistant_system = _system_identity(request.state, role="assistant")
    user_system = _system_identity(request.state, role="user")
    assistant_history = (
        assistant_system,
        {
            "kind": "input",
            "source": "assistant_system_message_echo_as_user_message",
            "content_identity": canonical_digest(assistant_system),
        },
        {
            "kind": "hidden_output",
            "content": row["content"],
        },
    )
    user_history = (user_system,)
    return MethodNodeResult(
        value={"bootstrap": True},
        state_update={
            "assistant_history": assistant_history,
            "user_history": user_history,
        },
        next_node="user_turn",
    )


def _user_turn_view(request: MethodNodeRequest) -> JsonObject:
    message_count = _integer(request.state.get("message_count", 0), "message_count")
    if message_count == 0:
        incoming: JsonObject = {
            "kind": "initial_instruction_seed",
            "source": "user_system_message_reframed_as_assistant_input",
            "system_identity": canonical_digest(
                _system_identity(request.state, role="user")
            ),
            "constraint": "Now start to give me introductions one by one. Only reply with Instruction and Input.",
        }
    else:
        transcript = _sequence(request.state.get("transcript", ()), "transcript")
        last = transcript[-1]
        if not isinstance(last, Mapping) or last.get("speaker") != "assistant":
            raise ValueError("CAMEL user turn requires previous assistant transcript message")
        incoming = {
            "kind": "assistant_message",
            "content": _text(last.get("content"), "assistant message"),
        }
    return {
        "phase": "user_agent",
        "system": _system_identity(request.state, role="user"),
        "history": request.state.get("user_history", ()),
        "incoming": incoming,
        "temperature": CAMEL_ROLE_PLAYING_FIDELITY.default_chat_temperature,
    }


def _record_user_turn(request: MethodNodeRequest) -> MethodNodeResult:
    row = _model_message(request.previous_value, "user agent")
    if row["terminated"] is True:
        return MethodNodeResult(
            value={"terminated": True},
            state_update={
                "pending_user": row,
                "termination_reason": f"user:{row['finish_reason']}",
            },
            next_node="return",
        )
    history = (
        *_sequence(request.state.get("user_history", ()), "user_history"),
        {"kind": "output", "content": row["content"]},
    )
    return MethodNodeResult(
        value={"content": row["content"]},
        state_update={
            "pending_user": row,
            "user_history": history,
        },
        next_node="assistant_turn",
    )


def _assistant_turn_view(request: MethodNodeRequest) -> JsonObject:
    user = request.state.get("pending_user")
    if not isinstance(user, Mapping):
        raise TypeError("CAMEL assistant turn requires pending user message")
    content = _text(user.get("content"), "pending user content")
    return {
        "phase": "assistant_agent",
        "system": _system_identity(request.state, role="assistant"),
        "history": request.state.get("assistant_history", ()),
        "incoming": {
            "kind": "user_instruction",
            "content": content,
        },
        "temperature": CAMEL_ROLE_PLAYING_FIDELITY.default_chat_temperature,
    }


def _record_assistant_turn(request: MethodNodeRequest) -> MethodNodeResult:
    row = _model_message(request.previous_value, "assistant agent")
    if row["terminated"] is True:
        return MethodNodeResult(
            value={"terminated": True},
            state_update={
                "pending_assistant": row,
                "termination_reason": f"assistant:{row['finish_reason']}",
            },
            next_node="return",
        )
    user = request.state.get("pending_user")
    assert isinstance(user, Mapping)
    history = (
        *_sequence(request.state.get("assistant_history", ()), "assistant_history"),
        {"kind": "input", "content": user["content"]},
        {"kind": "output", "content": row["content"]},
    )
    return MethodNodeResult(
        value={"content": row["content"]},
        state_update={
            "pending_assistant": row,
            "assistant_history": history,
        },
        next_node="evaluate_pair",
    )


def _repeat_counter(
    current: int,
    user_content: str,
    assistant_content: str,
) -> tuple[int, bool]:
    counter = current
    hit = False
    combined = f"{user_content}\n{assistant_content}".lower()
    for word in CAMEL_ROLE_PLAYING_FIDELITY.repeated_words:
        if word in combined:
            counter += 1
            if counter == CAMEL_ROLE_PLAYING_FIDELITY.repeated_word_threshold:
                hit = True
                # Preserve released bug: only the inner repeat-word loop exits.
                break
        else:
            counter = 0
    return counter, hit


def _evaluate_pair(request: MethodNodeRequest) -> MethodNodeResult:
    f = CAMEL_ROLE_PLAYING_FIDELITY
    user = request.state.get("pending_user")
    assistant = request.state.get("pending_assistant")
    if not isinstance(user, Mapping) or not isinstance(assistant, Mapping):
        raise TypeError("CAMEL pair evaluation requires both pending messages")
    user_content = _text(user.get("content"), "user content")
    assistant_content = _text(assistant.get("content"), "assistant content")

    user_no_instruction = _integer(
        request.state.get("user_no_instruction_count", 0),
        "user_no_instruction_count",
    )
    if f.instruction_marker not in user_content:
        user_no_instruction += 1
        if user_no_instruction == f.user_no_instruction_threshold:
            return MethodNodeResult(
                value={"termination_reason": "user_no_instruct_threshold"},
                state_update={
                    "user_no_instruction_count": user_no_instruction,
                    "termination_reason": "user_no_instruct_threshold",
                },
                next_node="return",
            )
    else:
        user_no_instruction = 0

    assistant_instruction = _integer(
        request.state.get("assistant_instruction_count", 0),
        "assistant_instruction_count",
    )
    if f.instruction_marker in assistant_content:
        assistant_instruction += 1
        if assistant_instruction == f.assistant_instruction_threshold:
            return MethodNodeResult(
                value={"termination_reason": "assistant_instruct_threshold"},
                state_update={
                    "user_no_instruction_count": user_no_instruction,
                    "assistant_instruction_count": assistant_instruction,
                    "termination_reason": "assistant_instruct_threshold",
                },
                next_node="return",
            )
    else:
        assistant_instruction = 0

    repeat_count, repeat_hit = _repeat_counter(
        _integer(request.state.get("repeat_word_count", 0), "repeat_word_count"),
        user_content,
        assistant_content,
    )
    repeat_hits = _integer(
        request.state.get("repeat_threshold_hits", 0),
        "repeat_threshold_hits",
    ) + (1 if repeat_hit else 0)

    transcript = list(_sequence(request.state.get("transcript", ()), "transcript"))
    transcript.append({"speaker": "user", "content": user_content})
    message_count = _integer(request.state.get("message_count", 0), "message_count") + 1

    task_done = f.task_done_token in user_content
    if task_done:
        return MethodNodeResult(
            value={"termination_reason": f.task_done_token},
            state_update={
                "transcript": tuple(transcript),
                "message_count": message_count,
                "user_no_instruction_count": user_no_instruction,
                "assistant_instruction_count": assistant_instruction,
                "repeat_word_count": repeat_count,
                "repeat_threshold_hits": repeat_hits,
                "termination_reason": f.task_done_token,
                "task_done": True,
            },
            next_node="return",
            checkpoint=True,
            checkpoint_value={"message_count": message_count, "task_done": True},
        )

    transcript.append({"speaker": "assistant", "content": assistant_content})
    message_count += 1
    maxed = message_count >= f.max_saved_messages
    return MethodNodeResult(
        value={"message_count": message_count, "maxed": maxed},
        state_update={
            "transcript": tuple(transcript),
            "message_count": message_count,
            "user_no_instruction_count": user_no_instruction,
            "assistant_instruction_count": assistant_instruction,
            "repeat_word_count": repeat_count,
            "repeat_threshold_hits": repeat_hits,
            "pending_user": None,
            "pending_assistant": None,
            "termination_reason": "max_num_messages" if maxed else (
                "repeat_word_threshold" if repeat_hit else ""
            ),
        },
        next_node="return" if maxed else "user_turn",
        checkpoint=True,
        checkpoint_value={
            "message_count": message_count,
            "repeat_threshold_hit": repeat_hit,
        },
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    transcript = _sequence(request.state.get("transcript", ()), "transcript")
    return MethodNodeResult(
        value={
            "task_id": request.state["task_id"],
            "assistant_role": request.state["assistant_role"],
            "user_role": request.state["user_role"],
            "original_task": request.state["original_task"],
            "specified_task": request.state.get("specified_task", ""),
            "planned_task": request.state.get("planned_task", ""),
            "final_task": request.state.get("final_task", ""),
            "num_messages": _integer(
                request.state.get("message_count", 0),
                "message_count",
            ),
            "task_done": request.state.get("task_done") is True,
            "termination_reason": request.state.get("termination_reason", ""),
            "repeat_threshold_hits": _integer(
                request.state.get("repeat_threshold_hits", 0),
                "repeat_threshold_hits",
            ),
            "transcript": transcript,
        }
    )


def build_camel_ai_society_method_program() -> MethodProgram:
    f = CAMEL_ROLE_PLAYING_FIDELITY
    configuration: JsonObject = {
        "source_commit": f.audited_commit,
        "paper_task_specification": f.paper_task_specification,
        "paper_task_planning": f.paper_task_planning,
        "task_specifier_temperature": f.task_specifier_temperature,
        "default_chat_temperature": f.default_chat_temperature,
        "max_saved_messages": f.max_saved_messages,
        "user_no_instruction_threshold": f.user_no_instruction_threshold,
        "assistant_instruction_threshold": f.assistant_instruction_threshold,
        "repeated_word_threshold": f.repeated_word_threshold,
        "repeated_words": f.repeated_words,
        "task_done_token": f.task_done_token,
        "repeat_threshold_breaks_inner_loop_only": (
            f.repeat_threshold_breaks_inner_loop_only
        ),
        "prompt_blobs": (
            f.assistant_prompt_blob,
            f.user_prompt_blob,
            f.task_specify_prompt_blob,
        ),
        "role_blobs": (f.assistant_roles_blob, f.user_roles_blob),
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="camel",
            implementation_version=f.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="camel.ai-society.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    turns = f.max_saved_messages // 2 + 1
    builder = MethodProgramBuilder(identity, entrypoint="specify_task")
    builder.agent(
        "specify_task",
        "camel.task.specify",
        _TASK_SPECIFIER,
        ("record_specified_task",),
        view_handler=_task_specify_view,
    )
    builder.compute(
        "record_specified_task",
        "camel.task.specified.record",
        _record_specified_task,
        ("plan_task",),
    )
    builder.agent(
        "plan_task",
        "camel.task.plan",
        _TASK_PLANNER,
        ("record_planned_task",),
        view_handler=_task_plan_view,
    )
    builder.compute(
        "record_planned_task",
        "camel.task.plan.record",
        _record_planned_task,
        ("bootstrap_assistant",),
    )
    builder.agent(
        "bootstrap_assistant",
        "camel.assistant.bootstrap",
        _ASSISTANT_AGENT,
        ("record_bootstrap",),
        view_handler=_bootstrap_view,
    )
    builder.compute(
        "record_bootstrap",
        "camel.assistant.bootstrap.record",
        _record_bootstrap,
        ("user_turn",),
    )
    builder.agent(
        "user_turn",
        "camel.user.turn",
        _USER_AGENT,
        ("record_user_turn",),
        view_handler=_user_turn_view,
        max_visits=turns,
    )
    builder.route(
        "record_user_turn",
        "camel.user.turn.record",
        _record_user_turn,
        ("assistant_turn", "return"),
        max_visits=turns,
    )
    builder.agent(
        "assistant_turn",
        "camel.assistant.turn",
        _ASSISTANT_AGENT,
        ("record_assistant_turn",),
        view_handler=_assistant_turn_view,
        max_visits=turns,
    )
    builder.route(
        "record_assistant_turn",
        "camel.assistant.turn.record",
        _record_assistant_turn,
        ("evaluate_pair", "return"),
        max_visits=turns,
    )
    builder.route(
        "evaluate_pair",
        "camel.dialogue.evaluate",
        _evaluate_pair,
        ("user_turn", "return"),
        max_visits=turns,
    )
    builder.return_node("return", "camel.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "camel.task-inception",
            "camel.independent-agent-histories",
            "camel.public-transcript",
            "model.invocation",
        ),
        metric_names=(
            "num_messages",
            "task_done",
            "repeat_threshold_hits",
        ),
        artifact_kinds=("camel_transcript", "camel_task_inception"),
    )


CAMEL_AI_SOCIETY_METHOD_PROGRAM = build_camel_ai_society_method_program()


__all__ = [
    "CAMEL_AI_SOCIETY_METHOD_PROGRAM",
    "build_camel_ai_society_method_program",
    "camel_ai_society_initial_state",
]
