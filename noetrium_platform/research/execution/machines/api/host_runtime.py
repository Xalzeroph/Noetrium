from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineCommit,
    MachineCut,
    MachineJournalPort,
    MachineKind,
    MachineSnapshot,
    MachineSnapshotStorePort,
    MachineStatus,
)

from ..program import ProgramHandlerRegistry, ResearchProgram
from ..program_host import (
    ResearchHostBindingRestorer,
    ResearchHostExecution,
    ResearchHostOperation,
)


@runtime_checkable
class ResearchMachineRunPort(Protocol):
    @property
    def commits(self) -> tuple[MachineCommit, ...]: ...

    @property
    def status(self) -> MachineStatus: ...

    @property
    def revision(self) -> int: ...

    @property
    def final(self) -> MachineCommit | None: ...


@runtime_checkable
class ResearchMachineSessionPort(Protocol):
    @property
    def machine_id(self) -> str: ...

    @property
    def kind(self) -> MachineKind: ...

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

    def start(
        self,
        initial_data: Mapping[str, JsonValue] | None = None,
        *,
        command_id: str,
    ) -> MachineCommit: ...

    def step(
        self,
        payload: JsonValue = None,
        *,
        command_id: str,
    ) -> MachineCommit: ...

    def resume(
        self,
        *,
        command_id: str,
        payload: JsonValue = None,
    ) -> MachineCommit: ...

    def run_until_blocked(
        self,
        *,
        command_id_prefix: str,
        payload: JsonValue = None,
        max_steps: int = 10_000,
    ) -> ResearchMachineRunPort: ...

    def checkpoint(self) -> MachineSnapshot: ...

    def cut(self) -> MachineCut | None: ...


@runtime_checkable
class ResearchProgramHostPort(Protocol):
    host_id: str
    program: ResearchProgram

    def open_session(
        self,
        *,
        machine_id: str,
        instance_identity: JsonValue,
        binding: object,
    ) -> ResearchMachineSessionPort: ...

    def execute(
        self,
        *,
        machine_id: str,
        instance_identity: JsonValue,
        binding: object,
        initial_data: JsonObject,
        payload: JsonValue = None,
        command_id_prefix: str | None = None,
    ) -> ResearchHostExecution: ...


@runtime_checkable
class ResearchProgramHostFactoryPort(Protocol):
    def build(
        self,
        *,
        host_id: str,
        program: ResearchProgram,
        operations: tuple[ResearchHostOperation, ...] = (),
        journal: MachineJournalPort,
        base_handlers: ProgramHandlerRegistry | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
        max_steps: int = 10_000,
        dependency_identity: JsonValue = None,
        binding_restorer: ResearchHostBindingRestorer | None = None,
    ) -> ResearchProgramHostPort: ...


__all__ = [
    "ResearchMachineRunPort",
    "ResearchMachineSessionPort",
    "ResearchProgramHostFactoryPort",
    "ResearchProgramHostPort",
]
