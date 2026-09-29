"""Generic host for one journal-backed ResearchProgram instance.

The host owns no research semantics. It binds any non-Method ResearchProgram
to MachineExecutor and injects caller-owned operation handlers. Accepted state
and transitions remain exclusively in the Machine Journal.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineCut,
    MachineExecutor,
    MachineIdentity,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    ProgramLock,
    canonical_digest,
    require_sha256,
)
from .program import (
    ProgramHandlerRegistry,
    ProgramHandlerRegistryPort,
    ProgramNodeRequest,
    ProgramNodeResult,
    ProgrammableMachineInterpreter,
    ResearchProgram,
    core_program_handlers,
    program_handler_binding_digest,
)
from .session import ResearchMachineRun, ResearchMachineSession
from .program import programmable_machine_family


ResearchHostHandler = Callable[[ProgramNodeRequest, object], ProgramNodeResult]
ResearchHostBindingRestorer = Callable[[object, JsonObject, JsonValue], None]


class _BoundResearchHostHandlers(ProgramHandlerRegistryPort):
    """Immutable per-session view over one sealed host handler template."""

    def __init__(
        self,
        *,
        base: ProgramHandlerRegistry,
        operations: tuple["ResearchHostOperation", ...],
        binding: object,
        identity_digest: str,
    ) -> None:
        if not base.sealed:
            raise RuntimeError("research host base handler registry must be sealed")
        bound = {}
        for item in operations:
            def invoke(
                request: ProgramNodeRequest,
                *,
                _handler: ResearchHostHandler = item.handler,
                _binding: object = binding,
            ) -> ProgramNodeResult:
                result = _handler(request, _binding)
                if not isinstance(result, ProgramNodeResult):
                    raise TypeError(
                        "research host handler must return ProgramNodeResult"
                    )
                return result
            bound[item.operation] = (invoke, item.implementation_digest)
        self._base = base
        self._bound = MappingProxyType(bound)
        self._identity_digest = require_sha256(
            identity_digest,
            "research host handler registry identity_digest",
        )
        self._operations = tuple(sorted(set(base.operations()).union(bound)))

    def resolve(self, operation: str):
        if type(operation) is not str or not operation.strip():
            raise ValueError("program operation is required")
        row = self._bound.get(operation)
        return self._base.resolve(operation) if row is None else row[0]

    def implementation_digest(self, operation: str) -> str:
        if type(operation) is not str or not operation.strip():
            raise ValueError("program operation is required")
        row = self._bound.get(operation)
        return (
            self._base.implementation_digest(operation)
            if row is None
            else row[1]
        )

    def operations(self) -> tuple[str, ...]:
        return self._operations

    @property
    def identity_digest(self) -> str:
        return self._identity_digest


@dataclass(frozen=True, slots=True)
class ResearchHostOperation:
    operation: str
    handler: ResearchHostHandler
    implementation_digest: str

    def __post_init__(self) -> None:
        if type(self.operation) is not str or not self.operation.strip():
            raise ValueError("research host operation name is required")
        object.__setattr__(self, "operation", self.operation.strip())
        if not callable(self.handler):
            raise TypeError("research host operation handler must be callable")
        object.__setattr__(
            self,
            "implementation_digest",
            require_sha256(
                self.implementation_digest,
                "research host operation implementation_digest",
            ),
        )


@dataclass(frozen=True, slots=True)
class ResearchHostExecution:
    machine_id: str
    revision: int
    status: MachineStatus
    data: JsonObject
    previous_value: JsonValue
    visit_counts: tuple[tuple[str, int], ...]
    step_count: int
    semantic_state: JsonObject
    checkpoint_value: JsonValue
    cut: MachineCut | None
    run: ResearchMachineRun


class ResearchProgramHost:
    """Reusable execution host for arbitrary downstream ResearchPrograms."""

    def __init__(
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
    ) -> None:
        if type(host_id) is not str or not host_id.strip():
            raise ValueError("research host_id is required")
        if not isinstance(program, ResearchProgram):
            raise TypeError("research host requires ResearchProgram")
        if type(operations) is not tuple or any(
            not isinstance(item, ResearchHostOperation) for item in operations
        ):
            raise TypeError("research host operations must be ResearchHostOperation tuple")
        names = tuple(item.operation for item in operations)
        if len(names) != len(set(names)):
            raise ValueError("research host operation names must be unique")
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("research host max_steps must be positive")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("research host requires MachineJournalPort")
        if base_handlers is not None and not isinstance(
            base_handlers, ProgramHandlerRegistry
        ):
            raise TypeError(
                "research host base_handlers must be ProgramHandlerRegistry"
            )
        self.host_id = host_id.strip()
        self.program = program
        self.operations = operations
        self.base_handlers = base_handlers
        effective_base_handlers = (
            core_program_handlers()
            if base_handlers is None
            else base_handlers
        )
        effective_base_handlers.seal()
        base_operations = set(effective_base_handlers.operations())
        overlap = base_operations.intersection(names)
        if overlap:
            raise ValueError(
                "research host operations conflict with base handlers: "
                + ", ".join(sorted(overlap))
            )
        self._effective_base_handlers = effective_base_handlers
        self.journal = journal
        self.snapshot_store = snapshot_store
        self.max_steps = max_steps
        self.dependency_identity = dependency_identity
        if binding_restorer is not None and not callable(binding_restorer):
            raise TypeError("research host binding_restorer must be callable")
        self.binding_restorer = binding_restorer
        if self.base_handlers is not None:
            self.base_handlers.seal()
        self._operation_implementations = tuple(
            (item.operation, item.implementation_digest)
            for item in self.operations
        )
        self._base_handler_identity_digest = (
            None
            if self.base_handlers is None
            else self.base_handlers.identity_digest
        )
        handler_implementations = {
            operation: self._effective_base_handlers.implementation_digest(
                operation
            )
            for operation in self._effective_base_handlers.operations()
        }
        handler_implementations.update(dict(self._operation_implementations))
        self._handler_registry_identity_digest = canonical_digest(tuple(
            sorted(handler_implementations.items())
        ))
        referenced_operations = tuple(
            sorted({node.operation for node in self.program.nodes})
        )
        try:
            referenced_implementations = tuple(
                (operation, handler_implementations[operation])
                for operation in referenced_operations
            )
        except KeyError as exc:
            raise KeyError(
                f"unbound research-program operation: {exc.args[0]}"
            ) from exc
        self._handler_binding_digest = canonical_digest({
            "research_program_digest": self.program.program_digest,
            "operation_implementations": referenced_implementations,
        })
        self._schema_digest = canonical_digest({
            "state_schema": self.program.state_schema,
        })
        self._interpreter_digest = canonical_digest({
            "interpreter": "programmable-machine",
            "version": 1,
        })
        self.configuration_digest = canonical_digest({
            "host_id": self.host_id,
            "program_digest": self.program.program_digest,
            "operation_implementations": self._operation_implementations,
            "base_handler_identity_digest": self._base_handler_identity_digest,
            "max_steps": self.max_steps,
            "dependency_identity": self.dependency_identity,
        })
        self._dependency_digest = canonical_digest({
            "host_id": self.host_id,
            "operation_implementations": self._operation_implementations,
            "base_handler_identity_digest": self._base_handler_identity_digest,
            "handler_binding_digest": self._handler_binding_digest,
            "required_capabilities": self.program.required_capabilities,
            "dependency_identity": self.dependency_identity,
        })

    def _program_lock(
        self,
        *,
        instance_identity: JsonValue,
        handler_binding_digest: str,
    ) -> ProgramLock:
        handler_binding_digest = require_sha256(
            handler_binding_digest,
            "research program handler_binding_digest",
        )
        if handler_binding_digest != self._handler_binding_digest:
            raise ValueError("research host handler binding identity drifted")
        return ProgramLock(
            code_digest=self.program.program_digest,
            dependency_digest=self._dependency_digest,
            schema_digest=self._schema_digest,
            interpreter_digest=self._interpreter_digest,
            data_digest=canonical_digest(instance_identity),
            config_digest=self.configuration_digest,
        )

    def _handlers(self, binding: object) -> ProgramHandlerRegistryPort:
        return _BoundResearchHostHandlers(
            base=self._effective_base_handlers,
            operations=self.operations,
            binding=binding,
            identity_digest=self._handler_registry_identity_digest,
        )

    def terminal_replay_machine_id(
        self,
        base_machine_id: str,
        *,
        max_attempts: int = 4096,
    ) -> str:
        if type(base_machine_id) is not str or not base_machine_id.strip():
            raise ValueError("research base_machine_id is required")
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("research replay max_attempts must be positive")
        for attempt in range(max_attempts):
            machine_id = f"{base_machine_id}:attempt:{attempt}"
            latest = self.journal.latest(machine_id)
            if latest is None:
                return machine_id
            if latest.accepted_status not in {
                MachineStatus.COMPLETED,
                MachineStatus.FAILED,
            }:
                return machine_id
        raise RuntimeError(
            f"research host {self.host_id} exhausted terminal replay attempts"
        )

    def open_session(
        self,
        *,
        machine_id: str,
        instance_identity: JsonValue,
        binding: object,
    ) -> ResearchMachineSession:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("research machine_id is required")
        handlers = self._handlers(binding)
        handler_binding_digest = self._handler_binding_digest
        machine = MachineExecutor(
            identity=MachineIdentity(
                machine_id,
                self.program.kind,
                "1",
                f"program:{self.program.program_digest[:16]}",
            ),
            program=self.program.machine_program_ref(
                self._program_lock(
                    instance_identity=instance_identity,
                    handler_binding_digest=handler_binding_digest,
                )
            ),
            journal=self.journal,
            snapshot_store=self.snapshot_store,
            family=programmable_machine_family(self.program.kind),
        )
        interpreter = ProgrammableMachineInterpreter(
            self.program,
            handlers,
            handler_binding_digest=handler_binding_digest,
        )
        return ResearchMachineSession(machine, self.program, interpreter)

    @staticmethod
    def _initial_data_digest(session: ResearchMachineSession) -> str | None:
        state = session.program_state
        if state is None:
            return None
        value = state.get("initial_data_digest")
        if value is None:
            return None
        if type(value) is not str or len(value) != 64:
            raise ValueError("research program initial_data_digest is invalid")
        return value

    @staticmethod
    def _project_execution(
        session: ResearchMachineSession,
        run: ResearchMachineRun,
    ) -> ResearchHostExecution:
        snapshot = session.snapshot
        cut = (
            None
            if snapshot.revision == 0 or snapshot.parent_commit_id is None
            else MachineCut(
                machine_id=session.machine_id,
                revision=snapshot.revision,
                commit_id=snapshot.parent_commit_id,
                state_digest=snapshot.state_digest,
                program_digest=snapshot.program.program_digest,
                program_lock_digest=snapshot.program.program_lock.lock_digest,
            )
        )
        return ResearchHostExecution(
            machine_id=session.machine_id,
            revision=session.revision,
            status=run.status,
            data=session.data,
            previous_value=session.previous_value,
            visit_counts=session.visit_counts,
            step_count=session.step_count,
            semantic_state=session.semantic_state,
            checkpoint_value=session.checkpoint_value,
            cut=cut,
            run=run,
        )

    def step_once(
        self,
        *,
        machine_id: str,
        instance_identity: JsonValue,
        binding: object,
        initial_data: JsonObject,
        payload: JsonValue = None,
        command_id_prefix: str | None = None,
        resume_waiting: bool = False,
    ) -> ResearchHostExecution:
        """Commit at most one semantic Program step after start/resume.

        This is the incremental event-driven companion to execute().  It is
        intended for nested ask/tell Machines (Optimization, Evaluation,
        interactive Runtime, etc.) whose parent supplies one event at a time.
        Accepted state remains exclusively in the Machine Journal.
        """

        session = self.open_session(
            machine_id=machine_id,
            instance_identity=instance_identity,
            binding=binding,
        )
        prefix = command_id_prefix or machine_id
        expected_initial_digest = canonical_digest(initial_data)
        commits = []

        if not session.started:
            commits.append(
                session.start(
                    initial_data,
                    command_id=f"{prefix}:start",
                )
            )
        else:
            actual_initial_digest = self._initial_data_digest(session)
            if actual_initial_digest != expected_initial_digest:
                raise ValueError(
                    "ResearchProgram instance initial-data identity drifted"
                )
            if self.binding_restorer is not None:
                self.binding_restorer(
                    binding,
                    session.data,
                    session.previous_value,
                )

            if session.status in {MachineStatus.COMPLETED, MachineStatus.FAILED}:
                run = ResearchMachineRun((), session.status, session.revision)
                return self._project_execution(session, run)

            if session.status in {MachineStatus.WAITING, MachineStatus.INTERRUPTED}:
                if not resume_waiting:
                    run = ResearchMachineRun((), session.status, session.revision)
                    return self._project_execution(session, run)
                commits.append(
                    session.resume(
                        command_id=f"{prefix}:resume:{session.revision}",
                        payload=payload,
                    )
                )

        if session.status is MachineStatus.RUNNABLE:
            commits.append(
                session.step(
                    payload,
                    command_id=f"{prefix}:step:{session.revision}",
                )
            )

        session.checkpoint()
        run = ResearchMachineRun(
            tuple(commits),
            session.status,
            session.revision,
        )
        return self._project_execution(session, run)

    def execute(
        self,
        *,
        machine_id: str,
        instance_identity: JsonValue,
        binding: object,
        initial_data: JsonObject,
        payload: JsonValue = None,
        command_id_prefix: str | None = None,
        resume_waiting: bool = False,
    ) -> ResearchHostExecution:
        session = self.open_session(
            machine_id=machine_id,
            instance_identity=instance_identity,
            binding=binding,
        )
        prefix = command_id_prefix or machine_id
        expected_initial_digest = canonical_digest(initial_data)

        if not session.started:
            session.start(initial_data, command_id=f"{prefix}:start")
        else:
            actual_initial_digest = self._initial_data_digest(session)
            if actual_initial_digest != expected_initial_digest:
                raise ValueError(
                    "ResearchProgram instance initial-data identity drifted"
                )
            if self.binding_restorer is not None:
                self.binding_restorer(
                    binding,
                    session.data,
                    session.previous_value,
                )

            if session.status in {MachineStatus.COMPLETED, MachineStatus.FAILED}:
                run = ResearchMachineRun((), session.status, session.revision)
                return self._project_execution(session, run)

            if session.status in {MachineStatus.WAITING, MachineStatus.INTERRUPTED}:
                if not resume_waiting:
                    run = ResearchMachineRun((), session.status, session.revision)
                    return self._project_execution(session, run)
                session.resume(
                    command_id=f"{prefix}:resume:{session.revision}",
                    payload=payload,
                )

        run = session.run_until_blocked(
            command_id_prefix=f"{prefix}:drive",
            payload=payload,
            max_steps=self.max_steps,
        )
        session.checkpoint()
        return self._project_execution(session, run)


__all__ = [
    "ResearchHostBindingRestorer",
    "ResearchHostExecution",
    "ResearchHostHandler",
    "ResearchHostOperation",
    "ResearchProgramHost",
]
