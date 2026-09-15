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
    MachineCommand,
    MachineCommit,
    MachineRuntime,
    thaw_json,
)
from noetrium_platform.research.execution.machines import AgentTurnMachineInterpreter


class AgentTurnMachineFactSink(AgentTurnFactSink):
    """Composition adapter that makes Kernel Journal the fact commit authority.

    A candidate fact is constructed from typed Agent Turn input, committed via
    MachineRuntime, and only then reflected in the process-local cursor. On
    restart, ``MachineRuntime.open`` rebuilds the cursor from Journal-derived
    state so no parallel trajectory store is required.
    """

    def __init__(
        self,
        runtime: MachineRuntime,
        *,
        turn_id: str,
        session_id: str,
        goal_digest: str | None = None,
        interpreter: AgentTurnMachineInterpreter | None = None,
    ) -> None:
        if not isinstance(runtime, MachineRuntime):
            raise TypeError("agent turn fact sink requires MachineRuntime")
        if not turn_id.strip() or not session_id.strip():
            raise ValueError("agent turn fact sink identity is required")
        self._runtime = runtime
        self._interpreter = interpreter or AgentTurnMachineInterpreter()
        self._turn_id = turn_id
        self._session_id = session_id
        self._emitted: list[AgentTurnFact] = []

        snapshot = runtime.open({})
        state = thaw_json(snapshot.state)
        if not isinstance(state, dict):
            raise ValueError("agent turn machine state must be an object")
        if not state:
            commit = runtime.step(
                MachineCommand(
                    command_id=f"{turn_id}:begin",
                    machine_id=runtime.machine_id,
                    expected_revision=snapshot.revision,
                    kind="agent.turn.begin",
                    payload={
                        "turn_id": turn_id,
                        "session_id": session_id,
                        "goal_digest": goal_digest,
                    },
                    scope=(),
                ),
                self._interpreter,
            )
            self._revision = commit.revision
            self._count = 0
            self._head: str | None = None
            self._last_kind: str | None = None
            return

        if state.get("status") != "active":
            raise ValueError("agent turn machine is not resumable from a terminal state")
        if state.get("turn_id") != turn_id or state.get("session_id") != session_id:
            raise ValueError("agent turn machine identity does not match requested turn")
        count = state.get("fact_count", 0)
        if type(count) is not int or count < 0:
            raise ValueError("agent turn machine fact_count is invalid")
        head = state.get("fact_head_digest")
        if head is not None and (not isinstance(head, str) or len(head) != 64):
            raise ValueError("agent turn machine fact head is invalid")
        if (count == 0) != (head is None):
            raise ValueError("agent turn machine cursor is inconsistent")
        last_kind = state.get("last_fact_kind")
        if last_kind is not None and not isinstance(last_kind, str):
            raise ValueError("agent turn machine last fact kind is invalid")
        self._revision = snapshot.revision
        self._count = count
        self._head = head
        self._last_kind = last_kind

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
        commit = self._runtime.step(
            MachineCommand(
                command_id=f"{self._turn_id}:fact:{fact.sequence}:{fact.fact_digest[:16]}",
                machine_id=self._runtime.machine_id,
                expected_revision=self._revision,
                kind="agent.fact.record",
                payload={"turn_id": self._turn_id, "fact": fact.as_payload()},
                scope=(),
            ),
            self._interpreter,
        )
        self._revision = commit.revision
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
        commit = self._runtime.step(
            MachineCommand(
                command_id=f"{self._turn_id}:finish:{self._head[:16]}",
                machine_id=self._runtime.machine_id,
                expected_revision=self._revision,
                kind="agent.turn.finish",
                payload={
                    "turn_id": self._turn_id,
                    "success": success,
                    "termination": termination,
                    "fact_head_digest": self._head,
                },
                scope=(),
            ),
            self._interpreter,
        )
        self._revision = commit.revision
        return commit


__all__ = ["AgentTurnMachineFactSink"]
