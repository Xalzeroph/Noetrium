"""Private revision-safe driver for journal-backed executable Units.

The driver is intentionally not a runtime layer. It owns no state and no
durability. MachineExecutor + MachineJournal remain authoritative; the driver
only derives revision-aware commands and drives the universal Unit ABI.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineCommand,
    MachineCommit,
    MachineCut,
    MachineExecutor,
    MachineSnapshot,
    MachineStatus,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel.universal import (
    UniversalUnitMachine,
    UNIT_STATE_KEY,
    executable_unit_digest,
    executable_unit_domain,
    validate_executable_unit,
)


_TERMINAL = frozenset({
    MachineStatus.WAITING,
    MachineStatus.INTERRUPTED,
    MachineStatus.COMPLETED,
    MachineStatus.FAILED,
})


@dataclass(frozen=True, slots=True)
class UnitRun:
    commits: tuple[MachineCommit, ...]
    status: MachineStatus
    revision: int

    @property
    def final(self) -> MachineCommit | None:
        return None if not self.commits else self.commits[-1]


@runtime_checkable
class UnitActivationRuntimePort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def execute(self, request: object) -> object: ...


@runtime_checkable
class UnitExecutionDriverPort(Protocol):
    @property
    def machine_id(self) -> str: ...

    @property
    def domain(self) -> str: ...

    @property
    def revision(self) -> int: ...

    @property
    def status(self) -> MachineStatus: ...

    @property
    def started(self) -> bool: ...

    @property
    def data(self) -> JsonObject: ...

    @property
    def previous_value(self) -> JsonValue: ...

    @property
    def visit_counts(self) -> tuple[tuple[str, int], ...]: ...

    @property
    def step_count(self) -> int: ...

    @property
    def semantic_state(self) -> JsonObject: ...

    @property
    def checkpoint_value(self) -> JsonValue: ...

    def start(self, initial_data=None, *, command_id: str) -> MachineCommit: ...

    def step(self, payload: JsonValue = None, *, command_id: str) -> MachineCommit: ...

    def resume(
        self, *, command_id: str, payload: JsonValue = None
    ) -> MachineCommit: ...



    def run_until_blocked(
        self,
        *,
        command_id_prefix: str,
        payload: JsonValue = None,
        max_steps: int | None = None,
    ) -> UnitRun: ...

    def checkpoint(self) -> MachineSnapshot: ...

    def cut(self) -> MachineCut | None: ...


class _UnitDriver:
    """Revision-safe driver over exactly one MachineExecutor + NoetriumUnit."""

    def __init__(
        self,
        machine: MachineExecutor,
        unit: NoetriumUnit,
        unit_machine: UniversalUnitMachine,
        *,
        activation_runtime: UnitActivationRuntimePort | None = None,
        activation_batch_mechanics: object | None = None,
    ) -> None:
        if not isinstance(machine, MachineExecutor):
            raise TypeError("Unit machine session requires MachineExecutor")
        validate_executable_unit(unit)
        if not isinstance(unit_machine, UniversalUnitMachine):
            raise TypeError("Unit machine session requires UniversalUnitMachine")
        if machine.unit.unit_digest != executable_unit_digest(unit):
            raise ValueError("MachineExecutor is bound to a different NoetriumUnit")
        if unit_machine.unit != unit:
            raise ValueError("Universal Unit Machine is bound to a different NoetriumUnit")
        self.machine = machine
        self.unit = unit
        self.unit_machine = unit_machine
        if activation_runtime is not None and not isinstance(
            activation_runtime,
            UnitActivationRuntimePort,
        ):
            raise TypeError(
                "Unit driver activation_runtime must implement UnitActivationRuntimePort"
            )
        self.activation_runtime = activation_runtime
        self.activation_batch_mechanics = activation_batch_mechanics
        self._snapshot = machine.open({})

    @property
    def machine_id(self) -> str:
        return self.machine.machine_id

    @property
    def domain(self) -> str:
        return executable_unit_domain(self.unit)

    @property
    def revision(self) -> int:
        return self._snapshot.revision

    @property
    def status(self) -> MachineStatus:
        return self.machine.status

    @property
    def snapshot(self) -> MachineSnapshot:
        return self._snapshot

    @property
    def started(self) -> bool:
        return UNIT_STATE_KEY in self._snapshot.state

    @property
    def unit_state(self) -> JsonObject | None:
        value = self._snapshot.state.get(UNIT_STATE_KEY)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise TypeError("machine unit state must be an object")
        return value

    @property
    def data(self) -> JsonObject:
        state = self.unit_state
        if state is None:
            return {}
        value = state.get("data", {})
        if not isinstance(value, Mapping):
            raise TypeError("machine unit data must be an object")
        return value

    @property
    def previous_value(self) -> JsonValue:
        state = self.unit_state
        return None if state is None else state.get("previous_value")

    @property
    def visit_counts(self) -> tuple[tuple[str, int], ...]:
        state = self.unit_state
        if state is None:
            return ()
        value = state.get("visits", {})
        if not isinstance(value, Mapping):
            raise TypeError("machine unit visits must be an object")
        rows = tuple(
            sorted((str(key), int(count)) for key, count in value.items())
        )
        if any(count < 0 for _key, count in rows):
            raise ValueError("machine unit visit counts cannot be negative")
        return rows

    @property
    def step_count(self) -> int:
        return sum(count for _key, count in self.visit_counts)

    @property
    def semantic_state(self) -> JsonObject:
        state = self.unit_state
        if state is None:
            return {}
        value = state.get("semantic", {})
        if not isinstance(value, Mapping):
            raise TypeError("machine unit semantic state must be an object")
        return value

    @property
    def checkpoint_value(self) -> JsonValue:
        state = self.unit_state
        return None if state is None else state.get("checkpoint_value")

    @property
    def pending_activation(self) -> JsonObject | None:
        state = self.unit_state
        if state is None:
            return None
        value = state.get("activation")
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise TypeError("unit pending activation must be an object")
        return value

    def _command(
        self,
        *,
        command_id: str,
        kind: str,
        payload: JsonValue = None,
    ) -> MachineCommand:
        if type(command_id) is not str or not command_id.strip():
            raise ValueError("Unit machine command_id is required")
        return MachineCommand(
            command_id=command_id,
            machine_id=self.machine_id,
            expected_revision=self.revision,
            kind=kind,
            payload=payload,
        )

    def _commit(self, command: MachineCommand) -> MachineCommit:
        commit = self.machine.step(command, self.unit_machine)
        self._snapshot = self.machine.current_snapshot
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
            raise ValueError("machine unit is already started")
        if initial_data is not None and not isinstance(initial_data, Mapping):
            raise TypeError("Unit machine initial_data must be an object")
        return self._commit(self._command(
            command_id=command_id,
            kind="unit.start",
            payload={"initial_data": {} if initial_data is None else dict(initial_data)},
        ))

    def step(
        self,
        payload: JsonValue = None,
        *,
        command_id: str,
    ) -> MachineCommit:
        if not self.started:
            raise ValueError("machine unit must be started before step")
        if self.status is not MachineStatus.RUNNABLE:
            raise ValueError(f"machine unit is not runnable: {self.status.value}")
        return self._commit(self._command(
            command_id=command_id,
            kind="unit.step",
            payload=payload,
        ))

    def resume(
        self,
        *,
        command_id: str,
        payload: JsonValue = None,
    ) -> MachineCommit:
        if self.status not in {MachineStatus.WAITING, MachineStatus.INTERRUPTED}:
            raise ValueError("only waiting/interrupted machine unit can resume")
        return self._commit(self._command(
            command_id=command_id,
            kind="unit.resume",
            payload=payload,
        ))

    def _drive_pending_activation(
        self,
        *,
        command_id_prefix: str,
    ) -> MachineCommit | None:
        pending = self.pending_activation
        if pending is None:
            return None
        if self.activation_runtime is None:
            return None

        from noetrium_platform.foundation.kernel.kernel.unit_activation import (
            UnitActivationRequest,
        )
        from noetrium_platform.foundation.kernel.kernel.unit_activation_batch import (
            UnitActivationBatchItem,
            UnitActivationBatchRequest,
            execute_unit_activation_batch,
        )
        from noetrium_platform.foundation.kernel.kernel.canonical import canonical_digest

        raw_requests = pending.get("requests", ())
        if not isinstance(raw_requests, tuple):
            raw_requests = tuple(raw_requests)
        requests = tuple(
            UnitActivationRequest.from_payload(row)
            for row in raw_requests
        )
        if not requests:
            raise RuntimeError("pending Unit activation has no requests")
        if any(
            request.parent_machine_id != self.machine_id
            for request in requests
        ):
            raise ValueError(
                "pending Unit activation belongs to another parent machine"
            )

        if (
            len(requests) > 1
            and self.activation_batch_mechanics is not None
        ):
            selection_digest = canonical_digest(
                tuple(request.request_digest for request in requests)
            )
            batch = UnitActivationBatchRequest(
                batch_id=(
                    f"{self.machine_id}:activation:{self.revision}"
                ),
                parent_machine_id=self.machine_id,
                selection_digest=selection_digest,
                items=tuple(
                    UnitActivationBatchItem(
                        participant_id=request.child_machine_id,
                        request=request,
                    )
                    for request in requests
                ),
            )
            batch_execution = execute_unit_activation_batch(
                self.activation_runtime,
                self.activation_batch_mechanics,
                batch,
            )
            executions = batch_execution.executions
        else:
            executions = tuple(
                self.activation_runtime.execute(request)
                for request in requests
            )

        join = str(pending.get("join", "all"))
        quorum = pending.get("quorum")
        completed = tuple(
            row for row in executions
            if row.status is MachineStatus.COMPLETED
        )
        terminal = tuple(
            row for row in executions
            if row.status in {
                MachineStatus.COMPLETED,
                MachineStatus.FAILED,
            }
        )
        if join == "all":
            ready = len(terminal) == len(executions)
        elif join == "any":
            ready = bool(completed)
        elif join == "quorum":
            if type(quorum) is not int:
                raise TypeError("pending Unit activation quorum is invalid")
            ready = len(completed) >= quorum
        else:
            raise ValueError("pending Unit activation join is invalid")
        if not ready:
            return None

        payload = {
            "value": tuple(
                {
                    "child_machine_id": row.execution.machine_id,
                    "status": row.status.value,
                    "result": row.result,
                    "link_digest": row.link.link_digest,
                }
                for row in executions
            ),
            "child_links": tuple(
                row.link.as_dict() for row in executions
            ),
        }
        return self.resume(
            command_id=(
                f"{command_id_prefix}:activate-resume:{self.revision}"
            ),
            payload=payload,
        )


    def run_until_blocked(
        self,
        *,
        command_id_prefix: str,
        payload: JsonValue = None,
        max_steps: int | None = None,
    ) -> UnitRun:
        if type(command_id_prefix) is not str or not command_id_prefix.strip():
            raise ValueError("command_id_prefix is required")
        if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
            raise ValueError("max_steps must be positive or None")
        commits: list[MachineCommit] = []
        ordinal = 0
        while max_steps is None or ordinal < max_steps:
            if self.status is MachineStatus.WAITING and self.pending_activation is not None:
                activation_commit = self._drive_pending_activation(
                    command_id_prefix=command_id_prefix,
                )
                if activation_commit is None:
                    return UnitRun(tuple(commits), self.status, self.revision)
                commits.append(activation_commit)
                if activation_commit.accepted_status in {
                    MachineStatus.COMPLETED,
                    MachineStatus.FAILED,
                }:
                    return UnitRun(
                        tuple(commits),
                        activation_commit.accepted_status,
                        activation_commit.revision,
                    )
            if self.status is not MachineStatus.RUNNABLE:
                return UnitRun(tuple(commits), self.status, self.revision)
            commit = self.step(
                payload,
                command_id=f"{command_id_prefix}:step:{self.revision}:{ordinal}",
            )
            commits.append(commit)
            if commit.accepted_status in _TERMINAL:
                if (
                    commit.accepted_status is MachineStatus.WAITING
                    and self.pending_activation is not None
                    and self.activation_runtime is not None
                ):
                    ordinal += 1
                    continue
                return UnitRun(
                    tuple(commits),
                    commit.accepted_status,
                    commit.revision,
                )
            ordinal += 1
        limit = self._commit(self._command(
            command_id=f"{command_id_prefix}:limit:{self.revision}",
            kind="unit.limit",
            payload={"max_steps": max_steps},
        ))
        commits.append(limit)
        return UnitRun(
            tuple(commits),
            limit.accepted_status,
            limit.revision,
        )

    def checkpoint(self) -> MachineSnapshot:
        self._snapshot = self.machine.checkpoint()
        return self._snapshot

    def cut(self) -> MachineCut | None:
        head = self.machine.journal.latest(self.machine_id)
        return None if head is None else MachineCut.from_commit(head)


__all__ = ["UnitRun", "UnitExecutionDriverPort", "UnitActivationRuntimePort"]
