"""Paper-programmable logical scheduling for RuntimeMachine.

This module selects admitted research participants for logical execution.  It
does not own physical placement, worker scheduling, resource admission, or
process lifecycle.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineStatus,
    canonical_digest,
    freeze_json,
    thaw_json,
)
from .program import ProgramNodeRequest, ProgramNodeResult
from .program_host import ResearchHostOperation
from .runtime_module import RuntimeModule, RuntimeModuleBuilder


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _digest(value: object, field_name: str) -> str:
    value = _text(value, field_name)
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class LogicalSchedulingCandidate:
    participant_id: str
    ready: bool = True
    priority: int = 0
    metadata: JsonObject = field(default_factory=dict)
    candidate_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "participant_id",
            _text(self.participant_id, "logical scheduling participant_id"),
        )
        if type(self.ready) is not bool:
            raise TypeError("logical scheduling ready must be boolean")
        if type(self.priority) is not int:
            raise TypeError("logical scheduling priority must be integer")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("logical scheduling metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        object.__setattr__(
            self, "candidate_digest",
            canonical_digest({
                "participant_id": self.participant_id,
                "ready": self.ready,
                "priority": self.priority,
                "metadata": thaw_json(self.metadata),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "participant_id": self.participant_id,
            "ready": self.ready,
            "priority": self.priority,
            "metadata": thaw_json(self.metadata),
            "candidate_digest": self.candidate_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "LogicalSchedulingCandidate":
        if not isinstance(value, Mapping):
            raise TypeError("logical scheduling candidate must be an object")
        candidate = cls(
            _text(value.get("participant_id"), "logical scheduling participant_id"),
            value.get("ready", True),
            value.get("priority", 0),
            value.get("metadata", {}),
        )
        supplied = value.get("candidate_digest")
        if supplied is not None and _digest(
            supplied, "logical scheduling candidate_digest"
        ) != candidate.candidate_digest:
            raise ValueError("logical scheduling candidate digest mismatch")
        return candidate


@dataclass(frozen=True, slots=True)
class LogicalSchedulingProgram:
    program_id: str
    version: str
    selector: str
    selector_digest: str
    batch_size: int = 1
    allow_idle: bool = False
    require_ready: bool = True
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("program_id", "version", "selector"):
            object.__setattr__(
                self, field_name,
                _text(getattr(self, field_name), f"logical scheduling {field_name}"),
            )
        object.__setattr__(
            self, "selector_digest",
            _digest(self.selector_digest, "logical scheduling selector_digest"),
        )
        if type(self.batch_size) is not int or self.batch_size < 1:
            raise ValueError("logical scheduling batch_size must be positive")
        if type(self.allow_idle) is not bool or type(self.require_ready) is not bool:
            raise TypeError("logical scheduling flags must be boolean")
        object.__setattr__(
            self, "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "selector": self.selector,
                "selector_digest": self.selector_digest,
                "batch_size": self.batch_size,
                "allow_idle": self.allow_idle,
                "require_ready": self.require_ready,
            }),
        )


@dataclass(frozen=True, slots=True)
class LogicalSchedulingRequest:
    decision_id: str
    candidates: tuple[LogicalSchedulingCandidate, ...]
    batch_size: int
    allow_idle: bool
    require_ready: bool
    prior_selected_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_id",
            _text(self.decision_id, "logical scheduling decision_id"),
        )
        if type(self.candidates) is not tuple or any(
            not isinstance(value, LogicalSchedulingCandidate)
            for value in self.candidates
        ):
            raise TypeError(
                "logical scheduling candidates must be a candidate tuple"
            )
        ids = tuple(value.participant_id for value in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("logical scheduling participant ids must be unique")
        if type(self.batch_size) is not int or self.batch_size < 1:
            raise ValueError(
                "logical scheduling request batch_size must be positive"
            )
        if type(self.allow_idle) is not bool or type(self.require_ready) is not bool:
            raise TypeError("logical scheduling request flags must be boolean")
        if type(self.prior_selected_ids) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.prior_selected_ids
        ):
            raise TypeError(
                "logical scheduling prior_selected_ids must be a text tuple"
            )


@dataclass(frozen=True, slots=True)
class LogicalSchedulingSelection:
    participant_ids: tuple[str, ...]
    receipt: JsonValue = None
    selection_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.participant_ids) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.participant_ids
        ):
            raise TypeError("logical scheduling selection ids must be a text tuple")
        if len(self.participant_ids) != len(set(self.participant_ids)):
            raise ValueError("logical scheduling selection ids must be unique")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self, "selection_digest",
            canonical_digest({
                "participant_ids": self.participant_ids,
                "receipt": thaw_json(self.receipt),
            }),
        )


LogicalSchedulingSelector = Callable[
    [LogicalSchedulingRequest], LogicalSchedulingSelection
]


@runtime_checkable
class LogicalSchedulingSelectorRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, selector: str) -> LogicalSchedulingSelector: ...

    def implementation_digest(self, selector: str) -> str: ...


class LogicalSchedulingSelectorRegistry(LogicalSchedulingSelectorRegistryPort):
    def __init__(self) -> None:
        self._selectors: dict[str, tuple[LogicalSchedulingSelector, str]] = {}
        self._lock = RLock()

    def register(
        self,
        selector: str,
        handler: LogicalSchedulingSelector,
        *,
        implementation_digest: str,
    ) -> None:
        selector = _text(selector, "logical scheduling selector")
        if not callable(handler):
            raise TypeError("logical scheduling selector must be callable")
        implementation_digest = _digest(
            implementation_digest,
            "logical scheduling selector implementation_digest",
        )
        value = (handler, implementation_digest)
        with self._lock:
            current = self._selectors.get(selector)
            if current is not None and current != value:
                raise ValueError(
                    f"logical scheduling selector already registered: {selector}"
                )
            self._selectors[selector] = value

    def resolve(self, selector: str) -> LogicalSchedulingSelector:
        selector = _text(selector, "logical scheduling selector")
        with self._lock:
            try:
                return self._selectors[selector][0]
            except KeyError as exc:
                raise KeyError(
                    f"unbound logical scheduling selector: {selector}"
                ) from exc

    def implementation_digest(self, selector: str) -> str:
        selector = _text(selector, "logical scheduling selector")
        with self._lock:
            try:
                return self._selectors[selector][1]
            except KeyError as exc:
                raise KeyError(
                    f"unbound logical scheduling selector: {selector}"
                ) from exc

    @property
    def identity_digest(self) -> str:
        with self._lock:
            return canonical_digest(tuple(
                (selector, implementation_digest)
                for selector, (_, implementation_digest)
                in sorted(self._selectors.items())
            ))


@dataclass(slots=True)
class LogicalSchedulingRuntimeBinding:
    program: LogicalSchedulingProgram
    selectors: LogicalSchedulingSelectorRegistryPort
    selection: LogicalSchedulingSelection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.program, LogicalSchedulingProgram):
            raise TypeError(
                "logical scheduling binding requires LogicalSchedulingProgram"
            )
        if not isinstance(
            self.selectors,
            LogicalSchedulingSelectorRegistryPort,
        ):
            raise TypeError(
                "logical scheduling binding requires selector registry"
            )
        _digest(
            self.selectors.identity_digest,
            "logical scheduling selector registry identity_digest",
        )
        actual = _digest(
            self.selectors.implementation_digest(self.program.selector),
            "logical scheduling selector implementation_digest",
        )
        if actual != self.program.selector_digest:
            raise ValueError(
                "logical scheduling selector implementation identity drifted"
            )

    @property
    def binding_digest(self) -> str:
        return canonical_digest({
            "logical_scheduling_program_digest": self.program.program_digest,
            "selector_registry_identity_digest": self.selectors.identity_digest,
            "selected_selector_implementation_digest": (
                self.selectors.implementation_digest(self.program.selector)
            ),
        })


def _select(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    if not isinstance(binding, LogicalSchedulingRuntimeBinding):
        raise TypeError("logical scheduling requires LogicalSchedulingRuntimeBinding")
    values = request.data.get("candidates", ())
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TypeError("logical scheduling candidates must be a sequence")
    candidates = tuple(LogicalSchedulingCandidate.from_payload(value) for value in values)
    ids = tuple(candidate.participant_id for candidate in candidates)
    if len(ids) != len(set(ids)):
        raise ValueError("logical scheduling participant ids must be unique")
    prior = request.data.get("prior_selected_ids", ())
    if isinstance(prior, (str, bytes, bytearray)) or not isinstance(prior, Sequence):
        raise TypeError("logical scheduling prior_selected_ids must be a sequence")
    decision_id = _text(request.data.get("decision_id"), "logical scheduling decision_id")
    selection = binding.selectors.resolve(binding.program.selector)(
        LogicalSchedulingRequest(
            decision_id,
            candidates,
            binding.program.batch_size,
            binding.program.allow_idle,
            binding.program.require_ready,
            tuple(_text(value, "prior participant id") for value in prior),
        )
    )
    if not isinstance(selection, LogicalSchedulingSelection):
        raise TypeError("logical scheduling selector returned invalid selection")
    by_id = {candidate.participant_id: candidate for candidate in candidates}
    unknown = tuple(value for value in selection.participant_ids if value not in by_id)
    if unknown:
        raise ValueError(f"logical scheduling selected unknown participants: {unknown}")
    if len(selection.participant_ids) > binding.program.batch_size:
        raise ValueError("logical scheduling selection exceeds batch_size")
    if not binding.program.allow_idle and not selection.participant_ids:
        raise ValueError("logical scheduling idle selection is disabled")
    if binding.program.require_ready:
        unready = tuple(
            value for value in selection.participant_ids if not by_id[value].ready
        )
        if unready:
            raise ValueError(f"logical scheduling selected unready participants: {unready}")
    binding.selection = selection
    return ProgramNodeResult(
        value={
            "decision_id": decision_id,
            "participant_ids": selection.participant_ids,
            "selection_digest": selection.selection_digest,
        },
        state_update={
            "selected_participant_ids": selection.participant_ids,
            "selection_digest": selection.selection_digest,
            "selection_receipt": thaw_json(selection.receipt),
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "runtime_logical_scheduling_selected",
            "decision_id": decision_id,
            "participant_ids": selection.participant_ids,
            "selection_digest": selection.selection_digest,
            "selector": binding.program.selector,
            "selector_digest": binding.program.selector_digest,
        },),
    )


def logical_scheduling_runtime_module(
    program: LogicalSchedulingProgram,
    *,
    module_id: str = "runtime.logical-scheduling",
) -> RuntimeModule:
    if not isinstance(program, LogicalSchedulingProgram):
        raise TypeError("logical scheduling module requires LogicalSchedulingProgram")
    return (
        RuntimeModuleBuilder.scheduling(module_id=module_id, entrypoint="select")
        .node(
            "select",
            "runtime.scheduling.select",
            configuration={
                "logical_scheduling_program_digest": program.program_digest,
                "selector": program.selector,
                "selector_digest": program.selector_digest,
            },
        )
        .build()
    )


def logical_scheduling_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "runtime.scheduling.select",
            _select,
            canonical_digest({
                "operation": "runtime.scheduling.select",
                "implementation_revision": 1,
            }),
        ),
    )


def logical_scheduling_initial_data(
    *,
    decision_id: str,
    program: LogicalSchedulingProgram,
    candidates: tuple[LogicalSchedulingCandidate, ...],
    prior_selected_ids: tuple[str, ...] = (),
) -> JsonObject:
    if not isinstance(program, LogicalSchedulingProgram):
        raise TypeError("logical scheduling initial data requires program")
    if type(candidates) is not tuple or any(
        not isinstance(value, LogicalSchedulingCandidate) for value in candidates
    ):
        raise TypeError("logical scheduling candidates must be a candidate tuple")
    return {
        "decision_id": _text(decision_id, "logical scheduling decision_id"),
        "logical_scheduling_program_digest": program.program_digest,
        "candidate_set_digest": canonical_digest(
            tuple(candidate.candidate_digest for candidate in candidates)
        ),
        "candidates": tuple(candidate.payload() for candidate in candidates),
        "prior_selected_ids": prior_selected_ids,
        "selected_participant_ids": (),
        "selection_digest": None,
        "selection_receipt": None,
    }


__all__ = [
    "LogicalSchedulingCandidate",
    "LogicalSchedulingProgram",
    "LogicalSchedulingRequest",
    "LogicalSchedulingRuntimeBinding",
    "LogicalSchedulingSelection",
    "LogicalSchedulingSelector",
    "LogicalSchedulingSelectorRegistry",
    "LogicalSchedulingSelectorRegistryPort",
    "logical_scheduling_initial_data",
    "logical_scheduling_runtime_module",
    "logical_scheduling_runtime_operations",
]
