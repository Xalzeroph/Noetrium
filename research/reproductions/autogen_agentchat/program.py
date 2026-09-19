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

from .fidelity import AUTOGEN_AGENTCHAT_FIDELITY

_MANAGER_AGENT_ID = "autogen.group-manager"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"AutoGen {field} must be text")
    return value


def _agent_ids(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) < 2:
        raise ValueError("AutoGen GroupChat requires at least two participant ids")
    if any(type(row) is not str or not row.strip() for row in value):
        raise ValueError("AutoGen participant ids must be canonical non-empty text")
    if len(value) != len(set(value)):
        raise ValueError("AutoGen participant ids must be unique")
    if _MANAGER_AGENT_ID in value:
        raise ValueError("AutoGen participant id collides with group manager")
    return value


def _transcript(value: object) -> tuple[JsonObject, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("AutoGen transcript must be a sequence")
    rows: list[JsonObject] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError("AutoGen transcript rows must be mappings")
        speaker = _text(row.get("speaker"), "transcript speaker")
        content = _text(row.get("content"), "transcript content", allow_empty=True)
        recipients = row.get("recipients", ())
        if type(recipients) is not tuple or any(
            type(item) is not str or not item.strip() for item in recipients
        ):
            raise TypeError("AutoGen transcript recipients must be text tuple")
        round_index = row.get("round")
        if type(round_index) is not int or round_index <= 0:
            raise ValueError("AutoGen transcript round must be positive")
        rows.append(
            freeze_json(
                {
                    "speaker": speaker,
                    "content": content,
                    "recipients": recipients,
                    "round": round_index,
                }
            )
        )
    return tuple(rows)


def autogen_groupchat_initial_state(
    *,
    participant_ids: tuple[str, ...],
    task_instruction: str,
) -> JsonObject:
    participants = _agent_ids(participant_ids)
    return {
        "participants": participants,
        "task_instruction": _text(task_instruction, "task instruction"),
        "transcript": (),
        "round": 0,
        "last_speaker": "",
        "current_speaker": "",
        "speaker_fallback_count": 0,
        "interrupt_count": 0,
        "terminated": False,
        "last_message": "",
    }


def _manager_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "task_instruction": _text(
            request.state.get("task_instruction"),
            "task instruction",
        ),
        "participants": _agent_ids(request.state.get("participants")),
        "transcript": _transcript(request.state.get("transcript", ())),
        "round": request.state.get("round", 0),
        "last_speaker": _text(
            request.state.get("last_speaker", ""),
            "last speaker",
            allow_empty=True,
        ),
    }


def _participant_view(request: MethodNodeRequest) -> JsonObject:
    speaker = _text(request.state.get("current_speaker"), "current speaker")
    return {
        "participant_id": speaker,
        "task_instruction": _text(
            request.state.get("task_instruction"),
            "task instruction",
        ),
        "transcript": _transcript(request.state.get("transcript", ())),
        "round": request.state.get("round", 0),
    }


def _current_speaker_target(request: MethodNodeRequest) -> str:
    return _text(request.state.get("current_speaker"), "current speaker")


def _proposal(value: JsonValue) -> str | None:
    if not isinstance(value, Mapping):
        return None
    speaker = value.get("speaker")
    return speaker if isinstance(speaker, str) and speaker.strip() else None


def _fallback_speaker(
    participants: tuple[str, ...],
    last_speaker: str,
) -> str:
    if last_speaker not in participants:
        return participants[0]
    index = participants.index(last_speaker)
    return participants[(index + 1) % len(participants)]


def _participant_output(value: JsonValue) -> tuple[str, bool, bool]:
    if isinstance(value, str):
        return value, False, False
    if not isinstance(value, Mapping):
        raise TypeError("AutoGen participant result must be text or mapping")
    content = _text(value.get("content"), "participant content", allow_empty=True)
    terminate = value.get("terminate") is True
    admin_interrupt = value.get("admin_interrupt") is True
    return content, terminate, admin_interrupt


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    transcript = _transcript(request.state.get("transcript", ()))
    round_count = request.state.get("round", 0)
    if type(round_count) is not int or round_count < 0:
        raise ValueError("AutoGen round must be non-negative")
    return MethodNodeResult(
        value={
            "terminated": request.state.get("terminated") is True,
            "round_count": round_count,
            "message_count": len(transcript),
            "speaker_fallback_count": request.state.get(
                "speaker_fallback_count",
                0,
            ),
            "interrupt_count": request.state.get("interrupt_count", 0),
            "last_speaker": request.state.get("last_speaker", ""),
            "transcript": transcript,
        }
    )


def build_autogen_groupchat_method_program(
    participant_ids: tuple[str, ...],
) -> MethodProgram:
    participants = _agent_ids(participant_ids)
    fidelity = AUTOGEN_AGENTCHAT_FIDELITY

    def validate_topology(request: MethodNodeRequest) -> MethodNodeResult:
        state_participants = _agent_ids(request.state.get("participants"))
        if state_participants != participants:
            raise ValueError(
                "AutoGen initial participant topology does not match program closure"
            )
        return MethodNodeResult(value={"participants": participants})

    def resolve_speaker(request: MethodNodeRequest) -> MethodNodeResult:
        state_participants = _agent_ids(request.state.get("participants"))
        if state_participants != participants:
            raise ValueError("AutoGen participant topology drift")
        proposed = _proposal(request.previous_value)
        last = _text(
            request.state.get("last_speaker", ""),
            "last speaker",
            allow_empty=True,
        )
        fallback = proposed not in participants
        selected = (
            _fallback_speaker(participants, last)
            if fallback
            else proposed
        )
        assert selected is not None
        fallback_count = request.state.get("speaker_fallback_count", 0)
        if type(fallback_count) is not int or fallback_count < 0:
            raise ValueError("AutoGen speaker_fallback_count must be non-negative")
        return MethodNodeResult(
            value={
                "speaker": selected,
                "fallback": fallback,
            },
            state_update={
                "current_speaker": selected,
                "speaker_fallback_count": fallback_count + (1 if fallback else 0),
            },
        )

    def record_message(request: MethodNodeRequest) -> MethodNodeResult:
        speaker = _text(request.state.get("current_speaker"), "current speaker")
        if speaker not in participants:
            raise ValueError("AutoGen current speaker escaped participant closure")
        content, terminate, admin_interrupt = _participant_output(
            request.previous_value
        )
        transcript = _transcript(request.state.get("transcript", ()))
        current_round = request.state.get("round", 0)
        if type(current_round) is not int or current_round < 0:
            raise ValueError("AutoGen round must be non-negative")
        next_round = current_round + 1
        recipients = tuple(row for row in participants if row != speaker)
        row: JsonObject = {
            "speaker": speaker,
            "content": content,
            "recipients": recipients,
            "round": next_round,
        }
        terminal = terminate or next_round >= fidelity.groupchat_default_max_round
        interrupts = request.state.get("interrupt_count", 0)
        if type(interrupts) is not int or interrupts < 0:
            raise ValueError("AutoGen interrupt_count must be non-negative")
        next_node = (
            "return"
            if terminal
            else "admin_interrupt"
            if admin_interrupt
            else "manager"
        )
        return MethodNodeResult(
            value={
                "speaker": speaker,
                "recipients": recipients,
                "round": next_round,
                "terminate": terminate,
                "admin_interrupt": admin_interrupt,
            },
            state_update={
                "transcript": (*transcript, row),
                "round": next_round,
                "last_speaker": speaker,
                "current_speaker": "",
                "last_message": content,
                "terminated": terminate,
                "interrupt_count": interrupts + (1 if admin_interrupt else 0),
            },
            next_node=next_node,
            checkpoint=True,
            checkpoint_value={
                "round": next_round,
                "last_speaker": speaker,
                "message_count": len(transcript) + 1,
            },
        )

    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "participant_ids": participants,
        "groupchat_default_max_round": fidelity.groupchat_default_max_round,
        "broadcast_excludes_speaker": fidelity.groupchat_broadcast_excludes_speaker,
        "speaker_selected_from_conversation": fidelity.next_speaker_selected_from_conversation,
        "speaker_fallback_round_robin": (
            fidelity.invalid_or_failed_speaker_selection_falls_back_round_robin
        ),
        "admin_can_take_over_on_interrupt": fidelity.admin_can_take_over_on_interrupt,
        "user_proxy_default_human_input_mode": fidelity.user_proxy_default_human_input_mode,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="autogen-paper-era-groupchat",
            implementation_version=fidelity.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="autogen-paper-era-groupchat.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    max_round = fidelity.groupchat_default_max_round
    builder = MethodProgramBuilder(identity, entrypoint="validate_topology")
    builder.compute(
        "validate_topology",
        "autogen.groupchat.topology.validate",
        validate_topology,
        ("manager",),
    )
    builder.agent(
        "manager",
        "autogen.groupchat.select-speaker",
        _MANAGER_AGENT_ID,
        ("resolve_speaker",),
        view_handler=_manager_view,
        max_visits=max_round,
    )
    builder.compute(
        "resolve_speaker",
        "autogen.groupchat.resolve-speaker",
        resolve_speaker,
        ("participant",),
        max_visits=max_round,
    )
    builder.dynamic_agent(
        "participant",
        "autogen.groupchat.participant-turn",
        participants,
        _current_speaker_target,
        ("record_message",),
        view_handler=_participant_view,
        max_visits=max_round,
    )
    builder.compute(
        "record_message",
        "autogen.groupchat.record-message",
        record_message,
        ("manager", "admin_interrupt", "return"),
        max_visits=max_round,
    )
    builder.interrupt(
        "admin_interrupt",
        ("manager",),
        max_visits=max_round,
    )
    builder.return_node("return", "autogen.groupchat.result", _return_result)
    return builder.build(
        configuration=configuration,
        execution_class=MethodExecutionClass.CHECKPOINTABLE,
        evidence_obligations=(
            "autogen.groupchat.transcript",
            "autogen.groupchat.delivery",
            "autogen.groupchat.interrupt",
        ),
        metric_names=(
            "task_success",
            "round_count",
            "message_count",
            "speaker_fallback_count",
            "interrupt_count",
        ),
        artifact_kinds=("groupchat_transcript",),
    )


AUTOGEN_REFERENCE_GROUPCHAT_PROGRAM = build_autogen_groupchat_method_program(
    ("agent1", "agent2", "user_proxy")
)


__all__ = [
    "AUTOGEN_REFERENCE_GROUPCHAT_PROGRAM",
    "autogen_groupchat_initial_state",
    "build_autogen_groupchat_method_program",
]
