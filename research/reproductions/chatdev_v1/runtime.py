from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
    ResearchProgramHost,
    RuntimeConcern,
    RuntimeProgramBuilder,
)

from .chain import ChatDevV1SimplePhaseSpec
from .fidelity import CHATDEV_V1_AUDITED_COMMIT


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


@dataclass(frozen=True, slots=True)
class ChatDevV1RolePlayExchangeRequest:
    phase_name: str
    assistant_role: str
    user_role: str
    assistant_role_prompt: str
    user_role_prompt: str
    task_prompt: str
    phase_prompt: str
    placeholders: JsonObject
    transcript: tuple[JsonObject, ...]
    turn_index: int
    reflection: bool = False

    def __post_init__(self) -> None:
        for name in (
            "phase_name",
            "assistant_role",
            "user_role",
            "assistant_role_prompt",
            "user_role_prompt",
            "task_prompt",
            "phase_prompt",
        ):
            object.__setattr__(
                self,
                name,
                _text(
                    getattr(self, name),
                    f"ChatDev v1 exchange {name}",
                ),
            )
        if not isinstance(self.placeholders, Mapping):
            raise TypeError("ChatDev v1 exchange placeholders must be an object")
        if type(self.transcript) is not tuple or any(
            not isinstance(row, Mapping) for row in self.transcript
        ):
            raise TypeError("ChatDev v1 exchange transcript must be an object tuple")
        if type(self.turn_index) is not int or self.turn_index < 0:
            raise ValueError("ChatDev v1 exchange turn_index must be non-negative")
        if type(self.reflection) is not bool:
            raise TypeError("ChatDev v1 exchange reflection must be boolean")
        object.__setattr__(self, "placeholders", freeze_json(self.placeholders))
        object.__setattr__(
            self,
            "transcript",
            tuple(freeze_json(row) for row in self.transcript),
        )


@dataclass(frozen=True, slots=True)
class ChatDevV1RolePlayExchange:
    assistant_message: str | None
    user_message: str | None
    assistant_info: bool = False
    user_info: bool = False
    assistant_terminated: bool = False
    user_terminated: bool = False
    provider_receipt: JsonValue = None
    exchange_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("assistant_message", "user_message"):
            value = getattr(self, name)
            if value is not None and type(value) is not str:
                raise TypeError(f"ChatDev v1 {name} must be text or None")
        for name in (
            "assistant_info",
            "user_info",
            "assistant_terminated",
            "user_terminated",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"ChatDev v1 {name} must be boolean")
        object.__setattr__(
            self,
            "provider_receipt",
            freeze_json(self.provider_receipt),
        )
        object.__setattr__(
            self,
            "exchange_digest",
            canonical_digest({
                "assistant_message": self.assistant_message,
                "user_message": self.user_message,
                "assistant_info": self.assistant_info,
                "user_info": self.user_info,
                "assistant_terminated": self.assistant_terminated,
                "user_terminated": self.user_terminated,
                "provider_receipt": self.provider_receipt,
            }),
        )


@runtime_checkable
class ChatDevV1RolePlayPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def exchange(
        self,
        request: ChatDevV1RolePlayExchangeRequest,
    ) -> ChatDevV1RolePlayExchange: ...


@dataclass(frozen=True, slots=True)
class ChatDevV1PhaseRuntimeBinding:
    role_play: ChatDevV1RolePlayPort
    role_prompts: JsonObject
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.role_play, ChatDevV1RolePlayPort):
            raise TypeError(
                "ChatDev v1 phase runtime requires ChatDevV1RolePlayPort"
            )
        require_sha256(
            self.role_play.identity_digest,
            "ChatDev v1 role-play identity_digest",
        )
        if not isinstance(self.role_prompts, Mapping):
            raise TypeError("ChatDev v1 role prompts must be an object")
        prompts = {
            _text(role, "ChatDev v1 role name"):
            _text(prompt, f"ChatDev v1 role prompt {role}")
            for role, prompt in self.role_prompts.items()
        }
        object.__setattr__(self, "role_prompts", freeze_json(prompts))
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "role_play_identity_digest": self.role_play.identity_digest,
                "role_prompts": prompts,
            }),
        )

    def role_prompt(self, role: str) -> str:
        value = self.role_prompts.get(role)
        return _text(value, f"ChatDev v1 role prompt {role}")


def _transcript(value: object) -> tuple[JsonObject, ...]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError("ChatDev v1 transcript must be a sequence")
    rows: list[JsonObject] = []
    for row in decoded:
        if not isinstance(row, dict):
            raise TypeError("ChatDev v1 transcript row must be an object")
        rows.append(row)
    return tuple(rows)


def chatdev_v1_phase_initial_data(
    *,
    phase: ChatDevV1SimplePhaseSpec,
    task_prompt: str,
    phase_prompt: str,
    placeholders: JsonObject | None = None,
) -> JsonObject:
    if not isinstance(phase, ChatDevV1SimplePhaseSpec):
        raise TypeError(
            "ChatDev v1 phase initial data requires ChatDevV1SimplePhaseSpec"
        )
    return {
        "source_commit": CHATDEV_V1_AUDITED_COMMIT,
        "phase_name": phase.name,
        "assistant_role": phase.assistant_role,
        "user_role": phase.user_role,
        "max_turns": phase.max_turns,
        "reflect": phase.reflect,
        "task_prompt": _text(task_prompt, "ChatDev v1 task_prompt"),
        "phase_prompt": _text(phase_prompt, "ChatDev v1 phase_prompt"),
        "placeholders": {} if placeholders is None else placeholders,
        "turn_index": 0,
        "transcript": (),
        "last_assistant_content": None,
        "seminar_conclusion": None,
        "reflection_content": None,
        "reflection_transcript": (),
        "stop_reason": None,
        "result": None,
    }


def _exchange(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ChatDevV1PhaseRuntimeBinding):
        raise TypeError(
            "ChatDev v1 phase exchange requires ChatDevV1PhaseRuntimeBinding"
        )
    data = thaw_json(request.data)
    if not isinstance(data, dict):
        raise TypeError("ChatDev v1 phase runtime data must be an object")
    if data.get("source_commit") != CHATDEV_V1_AUDITED_COMMIT:
        raise ValueError("ChatDev v1 source identity drifted")

    phase_name = _text(data.get("phase_name"), "ChatDev v1 phase_name")
    assistant_role = _text(
        data.get("assistant_role"),
        "ChatDev v1 assistant_role",
    )
    user_role = _text(data.get("user_role"), "ChatDev v1 user_role")
    max_turns = data.get("max_turns")
    turn_index = data.get("turn_index")
    reflect = data.get("reflect")
    if type(max_turns) is not int or not 1 <= max_turns <= 100:
        raise ValueError("ChatDev v1 max_turns must be in [1, 100]")
    if type(turn_index) is not int or not 0 <= turn_index < max_turns:
        raise ValueError("ChatDev v1 turn_index is outside phase budget")
    if type(reflect) is not bool:
        raise TypeError("ChatDev v1 reflect must be boolean")

    transcript = _transcript(data.get("transcript", ()))
    exchange = binding.role_play.exchange(
        ChatDevV1RolePlayExchangeRequest(
            phase_name=phase_name,
            assistant_role=assistant_role,
            user_role=user_role,
            assistant_role_prompt=binding.role_prompt(assistant_role),
            user_role_prompt=binding.role_prompt(user_role),
            task_prompt=_text(data.get("task_prompt"), "ChatDev v1 task_prompt"),
            phase_prompt=_text(
                data.get("phase_prompt"),
                "ChatDev v1 phase_prompt",
            ),
            placeholders=data.get("placeholders", {}),
            transcript=transcript,
            turn_index=turn_index,
            reflection=False,
        )
    )
    if not isinstance(exchange, ChatDevV1RolePlayExchange):
        raise TypeError(
            "ChatDev v1 role-play port must return ChatDevV1RolePlayExchange"
        )

    rows = list(transcript)
    if exchange.assistant_message is not None:
        rows.append({
            "turn": turn_index,
            "side": "assistant",
            "role": assistant_role,
            "content": exchange.assistant_message,
            "info": exchange.assistant_info,
            "terminated": exchange.assistant_terminated,
            "exchange_digest": exchange.exchange_digest,
        })
    if exchange.user_message is not None:
        rows.append({
            "turn": turn_index,
            "side": "user",
            "role": user_role,
            "content": exchange.user_message,
            "info": exchange.user_info,
            "terminated": exchange.user_terminated,
            "exchange_digest": exchange.exchange_digest,
        })

    seminar = data.get("seminar_conclusion")
    stop_reason: str | None = None
    if exchange.assistant_info:
        seminar = _optional_text(
            exchange.assistant_message,
            "ChatDev v1 assistant INFO message",
        )
        stop_reason = "assistant_info"
    elif exchange.assistant_terminated:
        stop_reason = "assistant_terminated"
    elif exchange.user_info:
        seminar = _optional_text(
            exchange.user_message,
            "ChatDev v1 user INFO message",
        )
        stop_reason = "user_info"
    elif exchange.user_terminated:
        stop_reason = "user_terminated"

    next_turn = turn_index + 1
    if stop_reason is None and next_turn >= max_turns:
        stop_reason = "turn_limit"

    state_update: JsonObject = {
        "turn_index": next_turn,
        "transcript": tuple(rows),
        "seminar_conclusion": seminar,
        "last_assistant_content": (
            exchange.assistant_message
            if exchange.assistant_message is not None
            else data.get("last_assistant_content")
        ),
        "stop_reason": stop_reason,
    }
    if stop_reason is None:
        next_node = "exchange"
    elif reflect and seminar in (None, ""):
        next_node = "reflect"
    else:
        next_node = "finalize"

    return ProgramNodeResult(
        value={
            "phase_name": phase_name,
            "turn": next_turn,
            "exchange_digest": exchange.exchange_digest,
            "stop_reason": stop_reason,
        },
        state_update=state_update,
        next_node=next_node,
        events=({
            "type": "chatdev_v1_roleplay_exchange",
            "phase_name": phase_name,
            "turn": turn_index,
            "assistant_role": assistant_role,
            "user_role": user_role,
            "assistant_info": exchange.assistant_info,
            "user_info": exchange.user_info,
            "assistant_terminated": exchange.assistant_terminated,
            "user_terminated": exchange.user_terminated,
            "exchange_digest": exchange.exchange_digest,
            "stop_reason": stop_reason,
        },),
    )


def _reflection_question(phase_name: str) -> str:
    if phase_name == "DemandAnalysis":
        return (
            "Answer their final product modality in the discussion without any "
            "other words, e.g., \"PowerPoint\""
        )
    if phase_name == "LanguageChoose":
        return (
            "Conclude the programming language being discussed for software "
            "development, in the format: \"*\" where '*' represents a "
            "programming language."
        )
    if phase_name == "EnvironmentDoc":
        return (
            "According to the codes and file format listed above, write a "
            "requirements.txt file to specify the dependencies or packages "
            "required for the project to run properly."
        )
    raise ValueError(
        f"ChatDev v1 reflection is not assigned for phase {phase_name}"
    )


def _format_transcript(rows: tuple[JsonObject, ...]) -> str:
    return "\n\n".join(
        f"{row.get('role')}: {str(row.get('content', '')).replace(chr(10) + chr(10), chr(10))}"
        for row in rows
    )


def _reflect(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ChatDevV1PhaseRuntimeBinding):
        raise TypeError(
            "ChatDev v1 phase reflection requires ChatDevV1PhaseRuntimeBinding"
        )
    data = thaw_json(request.data)
    if not isinstance(data, dict):
        raise TypeError("ChatDev v1 phase runtime data must be an object")
    phase_name = _text(data.get("phase_name"), "ChatDev v1 phase_name")
    transcript = _transcript(data.get("transcript", ()))
    exchange = binding.role_play.exchange(
        ChatDevV1RolePlayExchangeRequest(
            phase_name="Reflection",
            assistant_role="Chief Executive Officer",
            user_role="Counselor",
            assistant_role_prompt=binding.role_prompt(
                "Chief Executive Officer"
            ),
            user_role_prompt=binding.role_prompt("Counselor"),
            task_prompt=_text(data.get("task_prompt"), "ChatDev v1 task_prompt"),
            phase_prompt=(
                "Here is a conversation between two roles: "
                "{conversations} {question}"
            ),
            placeholders={
                "conversations": _format_transcript(transcript),
                "question": _reflection_question(phase_name),
            },
            transcript=(),
            turn_index=0,
            reflection=True,
        )
    )
    if not isinstance(exchange, ChatDevV1RolePlayExchange):
        raise TypeError(
            "ChatDev v1 role-play port must return ChatDevV1RolePlayExchange"
        )
    assistant = _optional_text(
        exchange.assistant_message,
        "ChatDev v1 reflection assistant message",
    )
    if assistant is None:
        raise RuntimeError(
            "ChatDev v1 reflection requires an assistant response"
        )
    reflection_rows: list[JsonObject] = [{
        "turn": 0,
        "side": "assistant",
        "role": "Chief Executive Officer",
        "content": assistant,
        "info": exchange.assistant_info,
        "terminated": exchange.assistant_terminated,
        "exchange_digest": exchange.exchange_digest,
    }]
    if exchange.user_message is not None:
        reflection_rows.append({
            "turn": 0,
            "side": "user",
            "role": "Counselor",
            "content": exchange.user_message,
            "info": exchange.user_info,
            "terminated": exchange.user_terminated,
            "exchange_digest": exchange.exchange_digest,
        })
    return ProgramNodeResult(
        value={
            "phase_name": phase_name,
            "reflection_exchange_digest": exchange.exchange_digest,
        },
        state_update={
            "reflection_content": assistant,
            "reflection_transcript": tuple(reflection_rows),
        },
        next_node="finalize",
        events=({
            "type": "chatdev_v1_phase_reflection",
            "phase_name": phase_name,
            "exchange_digest": exchange.exchange_digest,
        },),
    )


def _finalize(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, ChatDevV1PhaseRuntimeBinding):
        raise TypeError(
            "ChatDev v1 phase finalize requires ChatDevV1PhaseRuntimeBinding"
        )
    data = thaw_json(request.data)
    if not isinstance(data, dict):
        raise TypeError("ChatDev v1 phase runtime data must be an object")
    reflect = data.get("reflect")
    if type(reflect) is not bool:
        raise TypeError("ChatDev v1 reflect must be boolean")

    if reflect:
        raw = data.get("seminar_conclusion")
        if raw in (None, ""):
            raw = data.get("reflection_content")
    else:
        # This intentionally preserves v1.0.0 Phase.chatting semantics:
        # non-reflection phases overwrite any captured user-side INFO result
        # with the last assistant response after the turn loop.
        raw = data.get("last_assistant_content")

    raw_text = _optional_text(raw, "ChatDev v1 seminar conclusion")
    if raw_text is None:
        raise RuntimeError("ChatDev v1 phase produced no seminar conclusion")
    conclusion = raw_text.split("<INFO>")[-1]
    transcript = _transcript(data.get("transcript", ()))
    reflection_transcript = _transcript(
        data.get("reflection_transcript", ())
    )
    result = {
        "phase_name": _text(data.get("phase_name"), "ChatDev v1 phase_name"),
        "assistant_role": _text(
            data.get("assistant_role"),
            "ChatDev v1 assistant_role",
        ),
        "user_role": _text(data.get("user_role"), "ChatDev v1 user_role"),
        "turn_count": data.get("turn_index"),
        "stop_reason": data.get("stop_reason"),
        "reflected": bool(reflection_transcript),
        "conclusion": conclusion,
        "transcript": transcript,
        "reflection_transcript": reflection_transcript,
    }
    return ProgramNodeResult(
        value=result,
        state_update={"result": result},
        status=MachineStatus.COMPLETED,
        events=({
            "type": "chatdev_v1_phase_completed",
            "phase_name": result["phase_name"],
            "turn_count": result["turn_count"],
            "stop_reason": result["stop_reason"],
            "reflected": result["reflected"],
            "conclusion_digest": canonical_digest(conclusion),
        },),
    )


def build_chatdev_v1_phase_runtime_program() -> ResearchProgram:
    return (
        RuntimeProgramBuilder.create(
            program_id="chatdev.v1.phase-runtime",
            version=CHATDEV_V1_AUDITED_COMMIT[:12],
            state_schema="chatdev.v1.phase-runtime.state.v1",
            entrypoint="exchange",
        )
        .semantic(
            "exchange",
            RuntimeConcern.COMMUNICATION,
            "chatdev.v1.phase.exchange",
        )
        .semantic(
            "reflect",
            RuntimeConcern.TURN,
            "chatdev.v1.phase.reflect",
        )
        .semantic(
            "finalize",
            RuntimeConcern.EVENT,
            "chatdev.v1.phase.finalize",
        )
        .build()
    )


CHATDEV_V1_PHASE_RUNTIME_PROGRAM = (
    build_chatdev_v1_phase_runtime_program()
)


def chatdev_v1_phase_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "chatdev.v1.phase.exchange",
            _exchange,
            canonical_digest({
                "operation": "chatdev.v1.phase.exchange",
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "chatdev.v1.phase.reflect",
            _reflect,
            canonical_digest({
                "operation": "chatdev.v1.phase.reflect",
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "chatdev.v1.phase.finalize",
            _finalize,
            canonical_digest({
                "operation": "chatdev.v1.phase.finalize",
                "source_commit": CHATDEV_V1_AUDITED_COMMIT,
                "implementation_revision": 1,
            }),
        ),
    )


def chatdev_v1_phase_runtime_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    return ResearchProgramHost(
        host_id="chatdev.v1.phase-runtime",
        program=CHATDEV_V1_PHASE_RUNTIME_PROGRAM,
        operations=chatdev_v1_phase_runtime_operations(),
        journal=journal,
        snapshot_store=snapshot_store,
        max_steps=104,
        dependency_identity={
            "source_commit": CHATDEV_V1_AUDITED_COMMIT,
        },
    )


__all__ = [
    "CHATDEV_V1_PHASE_RUNTIME_PROGRAM",
    "ChatDevV1PhaseRuntimeBinding",
    "ChatDevV1RolePlayExchange",
    "ChatDevV1RolePlayExchangeRequest",
    "ChatDevV1RolePlayPort",
    "build_chatdev_v1_phase_runtime_program",
    "chatdev_v1_phase_initial_data",
    "chatdev_v1_phase_runtime_host",
    "chatdev_v1_phase_runtime_operations",
]
