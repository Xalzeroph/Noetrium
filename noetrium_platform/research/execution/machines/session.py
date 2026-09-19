"""Universal session/driver for journal-backed ResearchProgram Machines.

The session is intentionally not a second runtime. It owns no state and no
durability. MachineExecutor + MachineJournal remain authoritative; the session
only derives revision-aware commands and drives the universal program ABI.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineCommand,
    MachineCommit,
    MachineExecutor,
    MachineSnapshot,
    MachineStatus,
    thaw_json,
)
from .program import ProgrammableMachineInterpreter, ResearchProgram


_TERMINAL = frozenset({
    MachineStatus.WAITING,
    MachineStatus.INTERRUPTED,
    MachineStatus.COMPLETED,
    MachineStatus.FAILED,
})


@dataclass(frozen=True, slots=True)
class ResearchMachineRun:
    commits: tuple[MachineCommit, ...]
    status: MachineStatus
    revision: int

    @property
    def final(self) -> MachineCommit | None:
        return None if not self.commits else self.commits[-1]


class ResearchMachineSession:
    """Revision-safe driver over exactly one MachineExecutor + ResearchProgram."""

    def __init__(
        self,
        machine: MachineExecutor,
        program: ResearchProgram,
        interpreter: ProgrammableMachineInterpreter,
    ) -> None:
        if not isinstance(machine, MachineExecutor):
            raise TypeError("research machine session requires MachineExecutor")
        if not isinstance(program, ResearchProgram):
            raise TypeError("research machine session requires ResearchProgram")
        if not isinstance(interpreter, ProgrammableMachineInterpreter):
            raise TypeError("research machine session requires ProgrammableMachineInterpreter")
        if machine.identity.kind is not program.kind:
            raise ValueError("machine kind does not match ResearchProgram kind")
        if machine.program.program_digest != program.program_digest:
            raise ValueError("MachineExecutor is bound to a different ResearchProgram")
        if interpreter.program != program:
            raise ValueError("interpreter is bound to a different ResearchProgram")
        self.machine = machine
        self.program = program
        self.interpreter = interpreter
        self._snapshot = machine.open({})

    @property
    def machine_id(self) -> str:
        return self.machine.machine_id

    @property
    def revision(self) -> int:
        return self._snapshot.revision

    @property
    def status(self) -> MachineStatus:
        latest = self.machine.journal.latest(self.machine_id)
        return MachineStatus.READY if latest is None else latest.accepted_status

    @property
    def snapshot(self) -> MachineSnapshot:
        return self._snapshot

    @property
    def started(self) -> bool:
        state = thaw_json(self._snapshot.state)
        return isinstance(state, dict) and "_program" in state

    @property
    def program_state(self) -> JsonObject | None:
        state = thaw_json(self._snapshot.state)
        if not isinstance(state, dict):
            raise TypeError("machine state must decode to an object")
        value = state.get("_program")
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("research program state must be an object")
        return value

    @property
    def data(self) -> JsonObject:
        state = self.program_state
        if state is None:
            return {}
        value = state.get("data", {})
        if not isinstance(value, dict):
            raise TypeError("research program data must be an object")
        return value

    @property
    def previous_value(self) -> JsonValue:
        state = self.program_state
        return None if state is None else state.get("previous_value")

    def _command(
        self,
        *,
        command_id: str,
        kind: str,
        payload: JsonValue = None,
    ) -> MachineCommand:
        if type(command_id) is not str or not command_id.strip():
            raise ValueError("research machine command_id is required")
        return MachineCommand(
            command_id=command_id,
            machine_id=self.machine_id,
            expected_revision=self.revision,
            kind=kind,
            payload=payload,
        )

    def _commit(self, command: MachineCommand) -> MachineCommit:
        commit = self.machine.step(command, self.interpreter)
        self._snapshot = self.machine.open()
        if self._snapshot.revision != commit.revision:
            raise RuntimeError("MachineExecutor snapshot did not advance to committed revision")
        return commit

    def start(
        self,
        initial_data: Mapping[str, JsonValue] | None = None,
        *,
        command_id: str,
    ) -> MachineCommit:
        if self.started:
            raise ValueError("research program is already started")
        if initial_data is not None and not isinstance(initial_data, Mapping):
            raise TypeError("research machine initial_data must be an object")
        return self._commit(self._command(
            command_id=command_id,
            kind="program.start",
            payload={"initial_data": {} if initial_data is None else dict(initial_data)},
        ))

    def step(
        self,
        payload: JsonValue = None,
        *,
        command_id: str,
    ) -> MachineCommit:
        if not self.started:
            raise ValueError("research program must be started before step")
        if self.status is not MachineStatus.RUNNABLE:
            raise ValueError(f"research program is not runnable: {self.status.value}")
        return self._commit(self._command(
            command_id=command_id,
            kind="program.step",
            payload=payload,
        ))

    def resume(
        self,
        *,
        command_id: str,
        payload: JsonValue = None,
    ) -> MachineCommit:
        if self.status not in {MachineStatus.WAITING, MachineStatus.INTERRUPTED}:
            raise ValueError("only waiting/interrupted research program can resume")
        return self._commit(self._command(
            command_id=command_id,
            kind="program.resume",
            payload=payload,
        ))

    def run_until_blocked(
        self,
        *,
        command_id_prefix: str,
        payload: JsonValue = None,
        max_steps: int = 10_000,
    ) -> ResearchMachineRun:
        if type(command_id_prefix) is not str or not command_id_prefix.strip():
            raise ValueError("command_id_prefix is required")
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("max_steps must be positive")
        commits: list[MachineCommit] = []
        for ordinal in range(max_steps):
            if self.status is not MachineStatus.RUNNABLE:
                return ResearchMachineRun(tuple(commits), self.status, self.revision)
            commit = self.step(
                payload,
                command_id=f"{command_id_prefix}:step:{self.revision}:{ordinal}",
            )
            commits.append(commit)
            if commit.accepted_status in _TERMINAL:
                return ResearchMachineRun(tuple(commits), commit.accepted_status, commit.revision)
        raise RuntimeError(
            f"research program exceeded run_until_blocked max_steps={max_steps}"
        )

    def checkpoint(self) -> MachineSnapshot:
        self._snapshot = self.machine.checkpoint()
        return self._snapshot


__all__ = ["ResearchMachineRun", "ResearchMachineSession"]
