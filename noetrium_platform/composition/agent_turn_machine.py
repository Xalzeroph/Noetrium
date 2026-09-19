from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.participant.agent.runtime.turn_facts import (
    AgentTurnFact,
    AgentTurnFactKind,
    AgentTurnFactSink,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonValue,
    MachineCommit,
)
from noetrium_platform.research.execution.machines import (
    ResearchProgramHost,
    participant_turn_initial_data,
    participant_turn_program,
)


class AgentTurnMachineFactSink(AgentTurnFactSink):
    """Agent-specific fact sink hosted by the universal Participant machine."""

    def __init__(
        self,
        host: ResearchProgramHost,
        *,
        machine_id: str,
        turn_id: str,
        session_id: str,
        goal_digest: str | None = None,
    ) -> None:
        if not isinstance(host, ResearchProgramHost):
            raise TypeError("agent turn fact sink requires ResearchProgramHost")
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("agent turn machine_id is required")
        if not turn_id.strip() or not session_id.strip():
            raise ValueError("agent turn fact sink identity is required")
        program = participant_turn_program()
        if host.program.program_digest != program.program_digest:
            raise ValueError("agent turn host is bound to a different Program")
        self._machine = host.open_session(
            machine_id=machine_id.strip(),
            instance_identity={
                "turn_id": turn_id,
                "session_id": session_id,
                "goal_digest": goal_digest,
            },
            binding=None,
        )
        self._turn_id = turn_id
        self._session_id = session_id
        self._emitted: list[AgentTurnFact] = []

        if not self._machine.started:
            self._machine.start(
                participant_turn_initial_data(
                    turn_id=turn_id,
                    session_id=session_id,
                    goal_digest=goal_digest,
                ),
                command_id=f"{turn_id}:start",
            )
            self._count = 0
            self._head: str | None = None
            self._last_kind: str | None = None
            return

        data = self._machine.data
        if data.get("status") != "active":
            raise ValueError("participant turn is not resumable from a terminal state")
        if data.get("turn_id") != turn_id or data.get("session_id") != session_id:
            raise ValueError("participant turn identity does not match requested turn")
        count = data.get("fact_count", 0)
        if type(count) is not int or count < 0:
            raise ValueError("participant turn fact_count is invalid")
        head = data.get("fact_head_digest")
        if head is not None and (not isinstance(head, str) or len(head) != 64):
            raise ValueError("participant turn fact head is invalid")
        self._count = count
        self._head = head
        self._last_kind = data.get("last_fact_kind")

    @property
    def turn_id(self) -> str:
        return self._turn_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def committed_count(self) -> int:
        return self._count

    @property
    def head_digest(self) -> str | None:
        return self._head

    @property
    def emitted_facts(self) -> tuple[AgentTurnFact, ...]:
        return tuple(self._emitted)

    def append(
        self,
        kind: AgentTurnFactKind,
        *,
        context: ExecutionContext,
        payload: Mapping[str, JsonValue] | None = None,
        artifact_refs: tuple[str, ...] = (),
    ) -> AgentTurnFact:
        fact = AgentTurnFact.from_context(
            session_id=self._session_id,
            sequence=self._count + 1,
            kind=kind,
            context=context,
            payload=payload,
            artifact_refs=artifact_refs,
            previous_fact_digest=self._head,
        )
        self._machine.step(
            {"action": "record_fact", "fact": fact.as_payload()},
            command_id=f"{self._turn_id}:fact:{fact.sequence}:{fact.fact_digest[:16]}",
        )
        self._count = fact.sequence
        self._head = fact.fact_digest
        self._last_kind = fact.kind.value
        self._emitted.append(fact)
        return fact

    def finish(
        self,
        *,
        context: ExecutionContext,
        success: bool,
        termination: str,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> MachineCommit:
        if not isinstance(success, bool) or not termination.strip():
            raise ValueError("agent turn terminal status is invalid")
        if self._last_kind != AgentTurnFactKind.TERMINATION.value:
            terminal_payload: dict[str, JsonValue] = {
                "success": success,
                "termination": termination,
            }
            if payload:
                terminal_payload.update(payload)
            self.append(
                AgentTurnFactKind.TERMINATION,
                context=context,
                payload=terminal_payload,
            )
        if self._head is None:
            raise RuntimeError("agent turn terminal fact was not committed")
        return self._machine.step(
            {
                "action": "finish",
                "success": success,
                "termination": termination,
                "fact_head_digest": self._head,
            },
            command_id=f"{self._turn_id}:finish:{self._head[:16]}",
        )


__all__ = ["AgentTurnMachineFactSink"]
