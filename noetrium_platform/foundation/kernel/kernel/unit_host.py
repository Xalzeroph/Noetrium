"""Generic host for one journal-backed executable NoetriumUnit instance.

The host owns no research semantics. It binds any executable NoetriumUnit
to the single MachineExecutor and injects caller-owned operation handlers. Accepted state
and transitions remain exclusively in the Machine Journal.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from types import MappingProxyType
from typing import Callable, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.structure import NoetriumUnit, implementation_digest
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineCommit,
    MachineCut,
    MachineExecutor,
    MachineIdentity,
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    UnitExecutionLock,
    canonical_digest,
    require_sha256,
)
from noetrium_platform.foundation.kernel.kernel.universal import (
    UnitOperationRegistry,
    UnitOperationRegistryPort,
    UnitStepContext,
    UnitTransition,
    UniversalUnitMachine,
    _compile_unit_execution_plan,
    UNIVERSAL_UNIT_MACHINE_VERSION,
    unit_operation_binding_digest,
    unit_operation_name,
    unit_operation_implementation,
    executable_unit_digest,
    executable_unit_domain,
    executable_unit_nodes,
    executable_unit_ref,
    executable_unit_required_capabilities,
    executable_unit_state_schema,
    validate_executable_unit,
)
from noetrium_platform.foundation.kernel.kernel.unit_driver import (
    UnitActivationRuntimePort,
    UnitExecutionDriverPort,
    UnitRun,
    _UnitDriver,
)
from noetrium_platform.foundation.kernel.kernel.universal import universal_machine_family


BoundUnitStepImplementation = Callable[[UnitStepContext, object], UnitTransition]
UnitStateRestorer = Callable[[object, JsonObject, JsonValue], None]


class _BoundResearchHostHandlers(UnitOperationRegistryPort):
    """Immutable per-session view over one sealed host handler template."""

    def __init__(
        self,
        *,
        base: UnitOperationRegistry,
        operations: tuple["UnitOperationBinding", ...],
        binding: object,
        identity_digest: str,
    ) -> None:
        if not base.sealed:
            raise RuntimeError("Unit host base handler registry must be sealed")
        bound = {}
        for item in operations:
            def invoke(
                request: UnitStepContext,
                *,
                _handler: BoundUnitStepImplementation = item.handler,
                _binding: object = binding,
            ) -> UnitTransition:
                result = _handler(request, _binding)
                if not isinstance(result, UnitTransition):
                    raise TypeError(
                        "Unit host handler must return UnitTransition"
                    )
                return result
            bound[item.operation] = (invoke, item.implementation_digest)
        self._base = base
        self._bound = MappingProxyType(bound)
        self._identity_digest = require_sha256(
            identity_digest,
            "Unit host handler registry identity_digest",
        )
        self._operations = tuple(sorted(set(base.operations()).union(bound)))

    def resolve(self, operation: str):
        if type(operation) is not str or not operation.strip():
            raise ValueError("Unit operation is required")
        row = self._bound.get(operation)
        return self._base.resolve(operation) if row is None else row[0]

    def implementation_digest(self, operation: str) -> str:
        if type(operation) is not str or not operation.strip():
            raise ValueError("Unit operation is required")
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
class UnitOperationBinding:
    operation: str
    handler: BoundUnitStepImplementation
    implementation_digest: str

    def __post_init__(self) -> None:
        if type(self.operation) is not str or not self.operation.strip():
            raise ValueError("Unit host operation name is required")
        object.__setattr__(self, "operation", self.operation.strip())
        if not callable(self.handler):
            raise TypeError("Unit host operation handler must be callable")
        object.__setattr__(
            self,
            "implementation_digest",
            require_sha256(
                self.implementation_digest,
                "Unit host operation implementation_digest",
            ),
        )


@dataclass(frozen=True, slots=True)
class UnitExecution:
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
    run: UnitRun


@runtime_checkable
class BoundExecutableUnitPort(Protocol):
    host_id: str
    unit: NoetriumUnit

    def accepted_commits(self, machine_id: str) -> tuple[MachineCommit, ...]: ...

    def open_driver(
        self,
        *,
        machine_id: str,
        instance_identity: JsonValue,
        binding: object,
    ) -> UnitExecutionDriverPort: ...

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
    ) -> UnitExecution: ...


class BoundExecutableUnit:
    """Reusable execution host for arbitrary downstream executable Units."""

    def __init__(
        self,
        *,
        host_id: str,
        unit: NoetriumUnit,
        operations: tuple[UnitOperationBinding, ...] = (),
        journal: MachineJournalPort,
        base_handlers: UnitOperationRegistry | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
        max_steps: int | None = None,
        dependency_identity: JsonValue = None,
        binding_restorer: UnitStateRestorer | None = None,
        activation_runtime: UnitActivationRuntimePort | None = None,
        activation_batch_mechanics: object | None = None,
    ) -> None:
        if type(host_id) is not str or not host_id.strip():
            raise ValueError("Unit host_id is required")
        validate_executable_unit(unit)
        if type(operations) is not tuple or any(
            not isinstance(item, UnitOperationBinding) for item in operations
        ):
            raise TypeError("Unit host operations must be UnitOperationBinding tuple")
        names = tuple(item.operation for item in operations)
        if len(names) != len(set(names)):
            raise ValueError("Unit host operation names must be unique")
        if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
            raise ValueError("Unit host max_steps must be positive or None")
        if not isinstance(journal, MachineJournalPort):
            raise TypeError("Unit host requires MachineJournalPort")
        if base_handlers is not None and not isinstance(
            base_handlers, UnitOperationRegistry
        ):
            raise TypeError(
                "Unit host base_handlers must be UnitOperationRegistry"
            )
        self.host_id = host_id.strip()
        self.unit = unit
        self._execution_plan = _compile_unit_execution_plan(unit)
        self.operations = operations
        self.base_handlers = base_handlers
        effective_base_handlers = (
            UnitOperationRegistry.empty()
            if base_handlers is None
            else base_handlers
        )
        effective_base_handlers.seal()
        base_operations = set(effective_base_handlers.operations())
        overlap = base_operations.intersection(names)
        if overlap:
            raise ValueError(
                "Unit host operations conflict with base handlers: "
                + ", ".join(sorted(overlap))
            )
        self._effective_base_handlers = effective_base_handlers
        self.journal = journal
        self.snapshot_store = snapshot_store
        self.max_steps = max_steps
        self.dependency_identity = dependency_identity
        if binding_restorer is not None and not callable(binding_restorer):
            raise TypeError("Unit host binding_restorer must be callable")
        self.binding_restorer = binding_restorer
        if activation_runtime is not None and not isinstance(
            activation_runtime,
            UnitActivationRuntimePort,
        ):
            raise TypeError(
                "Unit host activation_runtime must implement UnitActivationRuntimePort"
            )
        self.activation_runtime = activation_runtime
        self.activation_batch_mechanics = activation_batch_mechanics
        self._activation_runtime_digest = (
            None
            if activation_runtime is None
            else require_sha256(
                activation_runtime.identity_digest,
                "Unit activation runtime identity_digest",
            )
        )
        mechanics_digest = (
            None
            if activation_batch_mechanics is None
            else getattr(activation_batch_mechanics, "identity_digest", None)
        )
        self._activation_batch_mechanics_digest = (
            None
            if mechanics_digest is None
            else require_sha256(
                mechanics_digest,
                "Unit activation batch mechanics identity_digest",
            )
        )
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
        referenced_implementations = []
        for node in executable_unit_nodes(self.unit):
            operation = unit_operation_name(node)
            inline = unit_operation_implementation(node)
            if inline is not None:
                digest = implementation_digest(inline)
            else:
                try:
                    digest = handler_implementations[operation]
                except KeyError as exc:
                    raise KeyError(
                        f"unbound Unit operation: {operation}"
                    ) from exc
            referenced_implementations.append(
                (node.unit_id, operation, require_sha256(
                    digest,
                    "Unit operation implementation_digest",
                ))
            )
        self._handler_binding_digest = canonical_digest({
            "executable_unit_digest": executable_unit_digest(self.unit),
            "operation_implementations": tuple(sorted(referenced_implementations)),
        })
        self._schema_digest = canonical_digest({
            "state_schema": executable_unit_state_schema(self.unit),
        })
        self._unit_machine_digest = canonical_digest({
            "unit_machine": "universal-unit-machine",
            "version": 1,
        })
        self.configuration_digest = canonical_digest({
            "host_id": self.host_id,
            "unit_digest": executable_unit_digest(self.unit),
            "operation_implementations": self._operation_implementations,
            "base_handler_identity_digest": self._base_handler_identity_digest,
            "max_steps": self.max_steps,
            "dependency_identity": self.dependency_identity,
            "activation_runtime_digest": self._activation_runtime_digest,
            "activation_batch_mechanics_digest": (
                self._activation_batch_mechanics_digest
            ),
        })
        self._dependency_digest = canonical_digest({
            "host_id": self.host_id,
            "operation_implementations": self._operation_implementations,
            "base_handler_identity_digest": self._base_handler_identity_digest,
            "handler_binding_digest": self._handler_binding_digest,
            "required_capabilities": executable_unit_required_capabilities(self.unit),
            "dependency_identity": self.dependency_identity,
            "activation_runtime_digest": self._activation_runtime_digest,
            "activation_batch_mechanics_digest": (
                self._activation_batch_mechanics_digest
            ),
        })

    def _execution_lock(
        self,
        *,
        instance_identity: JsonValue,
        handler_binding_digest: str,
    ) -> UnitExecutionLock:
        handler_binding_digest = require_sha256(
            handler_binding_digest,
            "Unit handler_binding_digest",
        )
        if handler_binding_digest != self._handler_binding_digest:
            raise ValueError("Unit host handler binding identity drifted")
        return UnitExecutionLock(
            code_digest=executable_unit_digest(self.unit),
            dependency_digest=self._dependency_digest,
            schema_digest=self._schema_digest,
            unit_machine_digest=self._unit_machine_digest,
            data_digest=canonical_digest(instance_identity),
            config_digest=self.configuration_digest,
        )

    def _handlers(self, binding: object) -> UnitOperationRegistryPort:
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
            f"Unit host {self.host_id} exhausted terminal replay attempts"
        )

    def accepted_commits(
        self,
        machine_id: str,
    ):
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("research machine_id is required")
        return self.journal.commits(machine_id)

    def open_driver(
        self,
        *,
        machine_id: str,
        instance_identity: JsonValue,
        binding: object,
    ) -> _UnitDriver:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("research machine_id is required")
        handlers = self._handlers(binding)
        handler_binding_digest = self._handler_binding_digest
        machine = MachineExecutor(
            identity=MachineIdentity(
                machine_id,
                UNIVERSAL_UNIT_MACHINE_VERSION,
                f"unit:{executable_unit_digest(self.unit)[:16]}",
            ),
            unit=executable_unit_ref(
                self.unit,
                self._execution_lock(
                    instance_identity=instance_identity,
                    handler_binding_digest=handler_binding_digest,
                ),
            ),
            journal=self.journal,
            snapshot_store=self.snapshot_store,
            family=universal_machine_family(),
        )
        unit_machine = UniversalUnitMachine(
            self.unit,
            handlers,
            handler_binding_digest=handler_binding_digest,
            execution_plan=self._execution_plan,
        )
        return _UnitDriver(
            machine,
            self.unit,
            unit_machine,
            activation_runtime=self.activation_runtime,
            activation_batch_mechanics=self.activation_batch_mechanics,
        )

    @staticmethod
    def _initial_data_digest(session: _UnitDriver) -> str | None:
        state = session.unit_state
        if state is None:
            return None
        value = state.get("initial_data_digest")
        if value is None:
            return None
        if type(value) is not str or len(value) != 64:
            raise ValueError("Unit initial_data_digest is invalid")
        return value

    @staticmethod
    def _project_execution(
        session: _UnitDriver,
        run: UnitRun,
    ) -> UnitExecution:
        snapshot = session.snapshot
        cut = (
            None
            if snapshot.revision == 0 or snapshot.parent_commit_id is None
            else MachineCut(
                machine_id=session.machine_id,
                revision=snapshot.revision,
                commit_id=snapshot.parent_commit_id,
                state_digest=snapshot.state_digest,
                unit_digest=snapshot.unit.unit_digest,
                execution_lock_digest=snapshot.unit.execution_lock.lock_digest,
            )
        )
        return UnitExecution(
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
    ) -> UnitExecution:
        """Commit at most one semantic Unit STEP after start/resume.

        This is the incremental event-driven companion to execute().  It is
        intended for nested ask/tell Machines (Optimization, Evaluation,
        interactive Runtime, etc.) whose parent supplies one event at a time.
        Accepted state remains exclusively in the Machine Journal.
        """

        session = self.open_driver(
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
                    "NoetriumUnit instance initial-data identity drifted"
                )
            if self.binding_restorer is not None:
                self.binding_restorer(
                    binding,
                    session.data,
                    session.previous_value,
                )

            if session.status in {MachineStatus.COMPLETED, MachineStatus.FAILED}:
                run = UnitRun((), session.status, session.revision)
                return self._project_execution(session, run)

            if session.status in {
                MachineStatus.WAITING,
                MachineStatus.INTERRUPTED,
            }:
                if (
                    session.status is MachineStatus.WAITING
                    and session.pending_activation is not None
                    and self.activation_runtime is not None
                ):
                    activation_commit = session._drive_pending_activation(
                        command_id_prefix=prefix,
                    )
                    if activation_commit is None:
                        run = UnitRun((), session.status, session.revision)
                        return self._project_execution(session, run)
                    commits.append(activation_commit)
                elif not resume_waiting:
                    run = UnitRun((), session.status, session.revision)
                    return self._project_execution(session, run)
                else:
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

        # Accepted transitions are already crash-durable in the Machine Journal.
        # Persisting a second full MachineSnapshot here duplicates the durability
        # barrier and is not consulted when a journal head exists. Explicit
        # checkpoint callers still use MachineExecutor.checkpoint().
        run = UnitRun(
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
    ) -> UnitExecution:
        session = self.open_driver(
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
                    "NoetriumUnit instance initial-data identity drifted"
                )
            if self.binding_restorer is not None:
                self.binding_restorer(
                    binding,
                    session.data,
                    session.previous_value,
                )

            if session.status in {MachineStatus.COMPLETED, MachineStatus.FAILED}:
                run = UnitRun((), session.status, session.revision)
                return self._project_execution(session, run)

            if session.status in {
                MachineStatus.WAITING,
                MachineStatus.INTERRUPTED,
            }:
                if (
                    session.status is MachineStatus.WAITING
                    and session.pending_activation is not None
                    and self.activation_runtime is not None
                ):
                    pass
                elif not resume_waiting:
                    run = UnitRun((), session.status, session.revision)
                    return self._project_execution(session, run)
                else:
                    session.resume(
                        command_id=f"{prefix}:resume:{session.revision}",
                        payload=payload,
                    )

        run = session.run_until_blocked(
            command_id_prefix=f"{prefix}:drive",
            payload=payload,
            max_steps=self.max_steps,
        )
        # The journal is the single recovery authority. Avoid a second full
        # snapshot write/fsync at every host execution boundary.
        return self._project_execution(session, run)


__all__ = [
    "UnitStateRestorer",
    "UnitExecution",
    "BoundUnitStepImplementation",
    "UnitOperationBinding",
    "BoundExecutableUnit",
    "BoundExecutableUnitPort",
]
