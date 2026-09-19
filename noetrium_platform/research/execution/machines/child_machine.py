"""Generic nested Research Machine execution.

This module does not own child state or a parallel lifecycle ledger. It executes
one child through ResearchProgramHost, then projects the authoritative child
MachineCut into a ChildMachineLink that the parent transition can commit.

Failure policy is recorded in the link but intentionally not interpreted here:
the parent Program owns the scientific semantics of fail/collect/continue.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    ChildMachineLink,
    JsonObject,
    JsonValue,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from .program_host import ResearchHostExecution, ResearchProgramHost


class ChildFailurePolicy(StrEnum):
    FAIL_PARENT = "fail_parent"
    COLLECT = "collect"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class ChildResearchMachineRequest:
    host_id: str
    parent_machine_id: str
    child_machine_id: str
    instance_identity: JsonValue
    initial_data: JsonObject
    failure_policy: ChildFailurePolicy = ChildFailurePolicy.FAIL_PARENT
    payload: JsonValue = None
    command_id_prefix: str | None = None
    resume_waiting: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("host_id", self.host_id),
            ("parent_machine_id", self.parent_machine_id),
            ("child_machine_id", self.child_machine_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"child request {name} is required")
        if self.parent_machine_id == self.child_machine_id:
            raise ValueError("parent and child machine ids must differ")
        if not isinstance(self.initial_data, Mapping):
            raise TypeError("child request initial_data must be an object")
        if not isinstance(self.failure_policy, ChildFailurePolicy):
            raise TypeError("child request failure_policy must be ChildFailurePolicy")
        if self.command_id_prefix is not None and (
            type(self.command_id_prefix) is not str
            or not self.command_id_prefix.strip()
        ):
            raise ValueError(
                "child request command_id_prefix must be non-empty when provided"
            )
        if type(self.resume_waiting) is not bool:
            raise TypeError("child request resume_waiting must be boolean")
        object.__setattr__(
            self,
            "instance_identity",
            freeze_json(self.instance_identity),
        )
        object.__setattr__(self, "initial_data", freeze_json(self.initial_data))
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def as_payload(self) -> JsonObject:
        return {
            "host_id": self.host_id,
            "parent_machine_id": self.parent_machine_id,
            "child_machine_id": self.child_machine_id,
            "instance_identity": self.instance_identity,
            "initial_data": self.initial_data,
            "failure_policy": self.failure_policy.value,
            "payload": self.payload,
            "command_id_prefix": self.command_id_prefix,
            "resume_waiting": self.resume_waiting,
        }

    @classmethod
    def from_payload(cls, value: object) -> "ChildResearchMachineRequest":
        if not isinstance(value, Mapping):
            raise TypeError("child request payload must be an object")
        decoded = thaw_json(value)
        if not isinstance(decoded, dict):
            raise TypeError("child request payload must decode to an object")
        initial_data = decoded.get("initial_data")
        if not isinstance(initial_data, dict):
            raise TypeError("child request initial_data payload must be an object")
        return cls(
            host_id=decoded.get("host_id"),
            parent_machine_id=decoded.get("parent_machine_id"),
            child_machine_id=decoded.get("child_machine_id"),
            instance_identity=decoded.get("instance_identity"),
            initial_data=initial_data,
            failure_policy=ChildFailurePolicy(
                decoded.get("failure_policy", ChildFailurePolicy.FAIL_PARENT.value)
            ),
            payload=decoded.get("payload"),
            command_id_prefix=decoded.get("command_id_prefix"),
            resume_waiting=decoded.get("resume_waiting", False),
        )


ChildResearchBindingFactory = Callable[[ChildResearchMachineRequest], object]


@dataclass(frozen=True, slots=True)
class RegisteredChildResearchHost:
    host: ResearchProgramHost
    binding_factory: ChildResearchBindingFactory
    binding_factory_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.host, ResearchProgramHost):
            raise TypeError("registered child host requires ResearchProgramHost")
        if not callable(self.binding_factory):
            raise TypeError("registered child host binding_factory must be callable")
        object.__setattr__(
            self,
            "binding_factory_digest",
            require_sha256(
                self.binding_factory_digest,
                "registered child binding_factory_digest",
            ),
        )

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "host_id": self.host.host_id,
            "program_digest": self.host.program.program_digest,
            "host_configuration_digest": self.host.configuration_digest,
            "binding_factory_digest": self.binding_factory_digest,
        })


@runtime_checkable
class ChildResearchHostRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, host_id: str) -> RegisteredChildResearchHost: ...


class ChildResearchHostRegistry(ChildResearchHostRegistryPort):
    """Process-local host directory; it owns declarations, never Machine truth."""

    def __init__(self) -> None:
        self._hosts: dict[str, RegisteredChildResearchHost] = {}
        self._lock = RLock()

    def register(
        self,
        host: ResearchProgramHost,
        binding_factory: ChildResearchBindingFactory,
        *,
        binding_factory_digest: str,
    ) -> None:
        registered = RegisteredChildResearchHost(
            host,
            binding_factory,
            binding_factory_digest,
        )
        with self._lock:
            current = self._hosts.get(host.host_id)
            if current is not None:
                if (
                    current.host.configuration_digest
                    != host.configuration_digest
                    or current.host.program.program_digest
                    != host.program.program_digest
                ):
                    raise ValueError(
                        f"child host identity already registered differently: {host.host_id}"
                    )
                if (
                    current.binding_factory_digest
                    != registered.binding_factory_digest
                ):
                    raise ValueError(
                        f"child host binding factory identity drifted: {host.host_id}"
                    )
                return
            self._hosts[host.host_id] = registered

    def register_static(
        self,
        host: ResearchProgramHost,
        binding: object = None,
        *,
        binding_identity_digest: str | None = None,
    ) -> None:
        """Register one host backed by a stable process-local binding.

        This is the common downstream authoring path for paper-owned nested
        Machines whose mechanics binding is fixed for the run. Dynamic
        per-child factories remain available through register().
        """

        if binding_identity_digest is None:
            if binding is None:
                binding_identity_digest = canonical_digest({
                    "kind": "static-child-binding",
                    "binding": None,
                })
            else:
                candidate = getattr(binding, "binding_digest", None)
                if candidate is None:
                    candidate = getattr(binding, "identity_digest", None)
                if type(candidate) is not str:
                    raise TypeError(
                        "static child binding requires binding_digest or "
                        "identity_digest; otherwise provide "
                        "binding_identity_digest explicitly"
                    )
                binding_identity_digest = require_sha256(
                    candidate,
                    "static child binding identity",
                )
        else:
            binding_identity_digest = require_sha256(
                binding_identity_digest,
                "static child binding identity",
            )

        self.register(
            host,
            lambda request, value=binding: value,
            binding_factory_digest=canonical_digest({
                "factory": "static-child-binding",
                "binding_identity_digest": binding_identity_digest,
            }),
        )

    def executor(self) -> "RegisteredChildResearchMachineExecutor":
        """Build the standard executor for the currently registered hosts."""

        return RegisteredChildResearchMachineExecutor(self)

    def resolve(self, host_id: str) -> RegisteredChildResearchHost:
        if type(host_id) is not str or not host_id.strip():
            raise ValueError("child host_id is required")
        with self._lock:
            try:
                return self._hosts[host_id]
            except KeyError as exc:
                raise KeyError(f"unknown child research host: {host_id}") from exc

    def host_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._hosts))

    @property
    def identity_digest(self) -> str:
        with self._lock:
            return canonical_digest(tuple(
                (host_id, registered.identity_digest)
                for host_id, registered in sorted(self._hosts.items())
            ))


class RegisteredChildResearchMachineExecutor:
    """Resolve a named child host and execute it without parent-specific wiring."""

    def __init__(self, registry: ChildResearchHostRegistryPort) -> None:
        if not isinstance(registry, ChildResearchHostRegistryPort):
            raise TypeError(
                "registered child executor requires ChildResearchHostRegistryPort"
            )
        self.registry = registry
        require_sha256(
            registry.identity_digest,
            "child research host registry identity_digest",
        )

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "executor": "registered-child-research-machine",
            "registry_identity_digest": self.registry.identity_digest,
        })

    def step_once(
        self,
        request: ChildResearchMachineRequest,
    ) -> ChildResearchMachineExecution:
        if not isinstance(request, ChildResearchMachineRequest):
            raise TypeError(
                "registered child executor requires ChildResearchMachineRequest"
            )
        registered = self.registry.resolve(request.host_id)
        binding = registered.binding_factory(request)
        return ChildResearchMachineExecutor(registered.host).step_once(
            parent_machine_id=request.parent_machine_id,
            child_machine_id=request.child_machine_id,
            instance_identity=request.instance_identity,
            binding=binding,
            initial_data=request.initial_data,
            failure_policy=request.failure_policy,
            payload=request.payload,
            command_id_prefix=request.command_id_prefix,
            resume_waiting=request.resume_waiting,
        )

    def execute(
        self,
        request: ChildResearchMachineRequest,
    ) -> ChildResearchMachineExecution:
        if not isinstance(request, ChildResearchMachineRequest):
            raise TypeError(
                "registered child executor requires ChildResearchMachineRequest"
            )
        registered = self.registry.resolve(request.host_id)
        binding = registered.binding_factory(request)
        return ChildResearchMachineExecutor(registered.host).execute(
            parent_machine_id=request.parent_machine_id,
            child_machine_id=request.child_machine_id,
            instance_identity=request.instance_identity,
            binding=binding,
            initial_data=request.initial_data,
            failure_policy=request.failure_policy,
            payload=request.payload,
            command_id_prefix=request.command_id_prefix,
            resume_waiting=request.resume_waiting,
        )


@dataclass(frozen=True, slots=True)
class ChildResearchMachineExecution:
    execution: ResearchHostExecution
    link: ChildMachineLink

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ResearchHostExecution):
            raise TypeError("child execution requires ResearchHostExecution")
        if not isinstance(self.link, ChildMachineLink):
            raise TypeError("child execution requires ChildMachineLink")
        if self.execution.machine_id != self.link.child_machine_id:
            raise ValueError("child execution/link machine identity mismatch")
        if self.execution.cut is None:
            raise ValueError("child execution must have an authoritative MachineCut")
        if self.execution.cut.program_digest != self.link.child_program_digest:
            raise ValueError("child execution/link program identity mismatch")

    @property
    def status(self) -> MachineStatus:
        return self.execution.status

    @property
    def result(self) -> JsonValue:
        return self.execution.previous_value


class ChildResearchMachineExecutor:
    """Stateless executor/projector for one nested ResearchProgram."""

    def __init__(self, host: ResearchProgramHost) -> None:
        if not isinstance(host, ResearchProgramHost):
            raise TypeError("child machine executor requires ResearchProgramHost")
        self.host = host

    @staticmethod
    def _project_execution(
        *,
        execution: ResearchHostExecution,
        parent_machine_id: str,
        child_machine_id: str,
        child_program_digest: str,
        failure_policy: ChildFailurePolicy,
        transition_start: int,
    ) -> ChildResearchMachineExecution:
        cut = execution.cut
        if cut is None:
            raise RuntimeError(
                "child ResearchProgram produced no authoritative MachineCut"
            )
        if cut.machine_id != child_machine_id:
            raise RuntimeError("child MachineCut belongs to another machine")
        if cut.program_digest != child_program_digest:
            raise RuntimeError(
                "child MachineCut belongs to another ResearchProgram"
            )
        if type(transition_start) is not int or transition_start < 0:
            raise ValueError("child transition_start must be non-negative")
        if transition_start > cut.revision:
            raise ValueError("child transition_start exceeds child cut")

        result_ref = None
        if execution.status is MachineStatus.COMPLETED:
            result_ref = (
                f"machine:{child_machine_id}:result:"
                f"{canonical_digest(execution.previous_value)}"
            )
        snapshot_ref = (
            f"machine:{child_machine_id}:cut:{cut.revision}:{cut.cut_digest}"
        )
        link = ChildMachineLink(
            parent_machine_id=parent_machine_id,
            child_machine_id=child_machine_id,
            child_program_digest=cut.program_digest,
            child_snapshot_ref=snapshot_ref,
            child_transition_start=transition_start,
            child_transition_end=cut.revision,
            child_result_ref=result_ref,
            failure_policy=failure_policy.value,
        )
        return ChildResearchMachineExecution(execution, link)

    def step_once(
        self,
        *,
        parent_machine_id: str,
        child_machine_id: str,
        instance_identity: JsonValue,
        binding: object,
        initial_data: JsonObject,
        failure_policy: ChildFailurePolicy = ChildFailurePolicy.FAIL_PARENT,
        payload: JsonValue = None,
        command_id_prefix: str | None = None,
        resume_waiting: bool = False,
    ) -> ChildResearchMachineExecution:
        """Commit one incremental child Program step and project its exact cut."""

        if type(parent_machine_id) is not str or not parent_machine_id.strip():
            raise ValueError("parent_machine_id is required")
        if type(child_machine_id) is not str or not child_machine_id.strip():
            raise ValueError("child_machine_id is required")
        if parent_machine_id == child_machine_id:
            raise ValueError("parent and child machine ids must differ")
        if not isinstance(failure_policy, ChildFailurePolicy):
            raise TypeError("failure_policy must be ChildFailurePolicy")

        execution = self.host.step_once(
            machine_id=child_machine_id,
            instance_identity=instance_identity,
            binding=binding,
            initial_data=initial_data,
            payload=payload,
            command_id_prefix=command_id_prefix,
            resume_waiting=resume_waiting,
        )
        if execution.run.commits:
            transition_start = execution.run.commits[0].revision
        else:
            transition_start = execution.revision
        return self._project_execution(
            execution=execution,
            parent_machine_id=parent_machine_id,
            child_machine_id=child_machine_id,
            child_program_digest=self.host.program.program_digest,
            failure_policy=failure_policy,
            transition_start=transition_start,
        )

    def execute(
        self,
        *,
        parent_machine_id: str,
        child_machine_id: str,
        instance_identity: JsonValue,
        binding: object,
        initial_data: JsonObject,
        failure_policy: ChildFailurePolicy = ChildFailurePolicy.FAIL_PARENT,
        payload: JsonValue = None,
        command_id_prefix: str | None = None,
        resume_waiting: bool = False,
    ) -> ChildResearchMachineExecution:
        if type(parent_machine_id) is not str or not parent_machine_id.strip():
            raise ValueError("parent_machine_id is required")
        if type(child_machine_id) is not str or not child_machine_id.strip():
            raise ValueError("child_machine_id is required")
        if parent_machine_id == child_machine_id:
            raise ValueError("parent and child machine ids must differ")
        if not isinstance(failure_policy, ChildFailurePolicy):
            raise TypeError("failure_policy must be ChildFailurePolicy")

        execution = self.host.execute(
            machine_id=child_machine_id,
            instance_identity=instance_identity,
            binding=binding,
            initial_data=initial_data,
            payload=payload,
            command_id_prefix=command_id_prefix,
            resume_waiting=resume_waiting,
        )
        return self._project_execution(
            execution=execution,
            parent_machine_id=parent_machine_id,
            child_machine_id=child_machine_id,
            child_program_digest=self.host.program.program_digest,
            failure_policy=failure_policy,
            transition_start=1,
        )


__all__ = [
    "ChildFailurePolicy",
    "ChildResearchBindingFactory",
    "ChildResearchHostRegistry",
    "ChildResearchHostRegistryPort",
    "ChildResearchMachineExecution",
    "ChildResearchMachineExecutor",
    "ChildResearchMachineRequest",
    "RegisteredChildResearchHost",
    "RegisteredChildResearchMachineExecutor",
]
