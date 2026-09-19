"""Paper-programmable recovery policy for RuntimeMachine.

RecoveryProgram decides the next semantic action after a typed failure or
suspension. It never performs effect reconciliation, rollback I/O, participant
restart, environment restore, or human transport itself. Those remain
mechanics exposed through host/provider operations. RuntimeMachine journals
the decision and its exact policy identity.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from .program import ProgramNodeRequest, ProgramNodeResult
from .program_host import ResearchHostOperation
from .runtime_module import RuntimeModule, RuntimeModuleBuilder


class RecoveryAction(StrEnum):
    RETRY = "retry"
    RESUME = "resume"
    ROLLBACK = "rollback"
    BRANCH = "branch"
    RESTART_PARTICIPANT = "restart_participant"
    RESTART_EPISODE = "restart_episode"
    ESCALATE = "escalate"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class RecoverySignal:
    signal_id: str
    failure_kind: str
    failure_digest: str
    attempt: int
    recoverable: bool = True
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("signal_id", self.signal_id),
            ("failure_kind", self.failure_kind),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"recovery {name} is required")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(
            self,
            "failure_digest",
            require_sha256(self.failure_digest, "recovery failure_digest"),
        )
        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("recovery attempt must be non-negative")
        if type(self.recoverable) is not bool:
            raise TypeError("recovery recoverable must be boolean")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("recovery metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @property
    def signal_digest(self) -> str:
        return canonical_digest({
            "signal_id": self.signal_id,
            "failure_kind": self.failure_kind,
            "failure_digest": self.failure_digest,
            "attempt": self.attempt,
            "recoverable": self.recoverable,
            "metadata": thaw_json(self.metadata),
        })


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    action: RecoveryAction
    target: str | None = None
    reason_code: str = "policy"
    receipt: JsonValue = None
    decision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.action, RecoveryAction):
            raise TypeError("recovery action must be RecoveryAction")
        if self.target is not None and (
            type(self.target) is not str or not self.target.strip()
        ):
            raise ValueError("recovery target must be non-empty when provided")
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise ValueError("recovery reason_code is required")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "decision_digest",
            canonical_digest({
                "action": self.action.value,
                "target": self.target,
                "reason_code": self.reason_code,
                "receipt": thaw_json(self.receipt),
            }),
        )


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    signal: RecoverySignal
    allowed_actions: tuple[RecoveryAction, ...]
    max_attempts: int
    prior_decision_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.signal, RecoverySignal):
            raise TypeError("recovery request requires RecoverySignal")
        if type(self.allowed_actions) is not tuple or not self.allowed_actions:
            raise ValueError("recovery request requires allowed_actions")
        if any(
            not isinstance(action, RecoveryAction)
            for action in self.allowed_actions
        ):
            raise TypeError("recovery allowed_actions must be RecoveryAction values")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("recovery allowed_actions must be unique")
        if type(self.max_attempts) is not int or self.max_attempts < 0:
            raise ValueError("recovery max_attempts must be non-negative")
        if type(self.prior_decision_digests) is not tuple:
            raise TypeError("recovery prior_decision_digests must be tuple")
        for digest in self.prior_decision_digests:
            require_sha256(digest, "recovery prior decision digest")


RecoveryDecider = Callable[[RecoveryRequest], RecoveryDecision]


@runtime_checkable
class RecoveryDeciderRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, decider: str) -> RecoveryDecider: ...

    def implementation_digest(self, decider: str) -> str: ...


class RecoveryDeciderRegistry(RecoveryDeciderRegistryPort):
    def __init__(self) -> None:
        self._deciders: dict[str, tuple[RecoveryDecider, str]] = {}
        self._lock = RLock()

    def register(
        self,
        decider: str,
        handler: RecoveryDecider,
        *,
        implementation_digest: str,
    ) -> None:
        if type(decider) is not str or not decider.strip():
            raise ValueError("recovery decider id is required")
        if not callable(handler):
            raise TypeError("recovery decider must be callable")
        digest = require_sha256(
            implementation_digest,
            "recovery decider implementation_digest",
        )
        decider = decider.strip()
        value = (handler, digest)
        with self._lock:
            current = self._deciders.get(decider)
            if current is not None and current != value:
                raise ValueError(f"recovery decider already registered: {decider}")
            self._deciders[decider] = value

    def resolve(self, decider: str) -> RecoveryDecider:
        if type(decider) is not str or not decider.strip():
            raise ValueError("recovery decider id is required")
        with self._lock:
            try:
                return self._deciders[decider.strip()][0]
            except KeyError as exc:
                raise KeyError(f"unbound recovery decider: {decider}") from exc

    def implementation_digest(self, decider: str) -> str:
        if type(decider) is not str or not decider.strip():
            raise ValueError("recovery decider id is required")
        with self._lock:
            try:
                return self._deciders[decider.strip()][1]
            except KeyError as exc:
                raise KeyError(f"unbound recovery decider: {decider}") from exc

    @property
    def identity_digest(self) -> str:
        with self._lock:
            return canonical_digest(tuple(
                (name, digest)
                for name, (_, digest) in sorted(self._deciders.items())
            ))


@dataclass(frozen=True, slots=True)
class RecoveryProgram:
    program_id: str
    version: str
    decider: str
    decider_digest: str
    allowed_actions: tuple[RecoveryAction, ...]
    max_attempts: int = 3
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("program_id", self.program_id),
            ("version", self.version),
            ("decider", self.decider),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"recovery program {name} is required")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(
            self,
            "decider_digest",
            require_sha256(
                self.decider_digest,
                "recovery program decider_digest",
            ),
        )
        if type(self.allowed_actions) is not tuple or not self.allowed_actions:
            raise ValueError("recovery program requires allowed_actions")
        if any(
            not isinstance(action, RecoveryAction)
            for action in self.allowed_actions
        ):
            raise TypeError("recovery program actions must be RecoveryAction")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("recovery program actions must be unique")
        if type(self.max_attempts) is not int or self.max_attempts < 0:
            raise ValueError("recovery program max_attempts must be non-negative")
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "decider": self.decider,
                "decider_digest": self.decider_digest,
                "allowed_actions": tuple(
                    action.value for action in self.allowed_actions
                ),
                "max_attempts": self.max_attempts,
            }),
        )


@dataclass(slots=True)
class RecoveryRuntimeBinding:
    program: RecoveryProgram
    deciders: RecoveryDeciderRegistryPort
    decision: RecoveryDecision | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.program, RecoveryProgram):
            raise TypeError("recovery binding requires RecoveryProgram")
        if not isinstance(self.deciders, RecoveryDeciderRegistryPort):
            raise TypeError("recovery binding requires decider registry")
        require_sha256(
            self.deciders.identity_digest,
            "recovery decider registry identity_digest",
        )
        actual = self.deciders.implementation_digest(self.program.decider)
        if actual != self.program.decider_digest:
            raise ValueError("recovery decider implementation identity drifted")

    @property
    def binding_digest(self) -> str:
        return canonical_digest({
            "recovery_program_digest": self.program.program_digest,
            "registry_identity_digest": self.deciders.identity_digest,
            "decider_implementation_digest": (
                self.deciders.implementation_digest(self.program.decider)
            ),
        })


def recovery_initial_data(
    signal: RecoverySignal,
    program: RecoveryProgram,
    *,
    prior_decision_digests: tuple[str, ...] = (),
) -> JsonObject:
    if not isinstance(signal, RecoverySignal):
        raise TypeError("recovery initial data requires RecoverySignal")
    if not isinstance(program, RecoveryProgram):
        raise TypeError("recovery initial data requires RecoveryProgram")
    return {
        "recovery_program_digest": program.program_digest,
        "signal": {
            "signal_id": signal.signal_id,
            "failure_kind": signal.failure_kind,
            "failure_digest": signal.failure_digest,
            "attempt": signal.attempt,
            "recoverable": signal.recoverable,
            "metadata": thaw_json(signal.metadata),
            "signal_digest": signal.signal_digest,
        },
        "prior_decision_digests": prior_decision_digests,
        "decision": None,
    }


def _signal(value: object) -> RecoverySignal:
    if not isinstance(value, Mapping):
        raise TypeError("recovery signal state must be an object")
    signal = RecoverySignal(
        signal_id=value.get("signal_id"),
        failure_kind=value.get("failure_kind"),
        failure_digest=value.get("failure_digest"),
        attempt=value.get("attempt"),
        recoverable=value.get("recoverable", True),
        metadata=value.get("metadata", {}),
    )
    supplied = value.get("signal_digest")
    if supplied is not None and supplied != signal.signal_digest:
        raise ValueError("recovery signal digest mismatch")
    return signal


def _decide(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    if not isinstance(binding, RecoveryRuntimeBinding):
        raise TypeError("runtime recovery requires RecoveryRuntimeBinding")
    if request.data.get("recovery_program_digest") != binding.program.program_digest:
        raise ValueError("Runtime RecoveryProgram identity drifted")
    signal = _signal(request.data.get("signal"))
    prior = request.data.get("prior_decision_digests", ())
    if not isinstance(prior, (tuple, list)):
        raise TypeError("recovery prior_decision_digests must be a sequence")
    prior_digests = tuple(
        require_sha256(value, "recovery prior decision digest")
        for value in prior
    )

    if not signal.recoverable:
        decision = RecoveryDecision(
            RecoveryAction.ABORT,
            reason_code="signal-not-recoverable",
        )
    elif signal.attempt >= binding.program.max_attempts:
        terminal = (
            RecoveryAction.ESCALATE
            if RecoveryAction.ESCALATE in binding.program.allowed_actions
            else RecoveryAction.ABORT
        )
        decision = RecoveryDecision(
            terminal,
            reason_code="recovery-attempt-budget-exhausted",
        )
    else:
        decision = binding.deciders.resolve(binding.program.decider)(
            RecoveryRequest(
                signal,
                binding.program.allowed_actions,
                binding.program.max_attempts,
                prior_digests,
            )
        )
    if not isinstance(decision, RecoveryDecision):
        raise TypeError("recovery decider must return RecoveryDecision")
    if decision.action not in binding.program.allowed_actions:
        raise ValueError(
            f"recovery decider selected disallowed action: {decision.action.value}"
        )
    binding.decision = decision
    payload = {
        "action": decision.action.value,
        "target": decision.target,
        "reason_code": decision.reason_code,
        "receipt": thaw_json(decision.receipt),
        "decision_digest": decision.decision_digest,
    }
    return ProgramNodeResult(
        value=payload,
        state_update={
            "decision": payload,
            "decision_digest": decision.decision_digest,
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "runtime_recovery_decided",
            "signal_id": signal.signal_id,
            "signal_digest": signal.signal_digest,
            "action": decision.action.value,
            "target": decision.target,
            "reason_code": decision.reason_code,
            "decision_digest": decision.decision_digest,
            "decider": binding.program.decider,
            "decider_digest": binding.program.decider_digest,
        },),
    )


def recovery_runtime_module(
    program: RecoveryProgram,
    *,
    module_id: str = "runtime.recovery",
) -> RuntimeModule:
    if not isinstance(program, RecoveryProgram):
        raise TypeError("recovery runtime module requires RecoveryProgram")
    return (
        RuntimeModuleBuilder.recovery(
            module_id=module_id,
            entrypoint="decide",
        )
        .node(
            "decide",
            "runtime.recovery.decide",
            configuration={
                "recovery_program_digest": program.program_digest,
                "decider": program.decider,
                "decider_digest": program.decider_digest,
            },
        )
        .build()
    )


def recovery_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (ResearchHostOperation(
            "runtime.recovery.decide",
            _decide,
            canonical_digest({
                "operation": "runtime.recovery.decide",
                "implementation_revision": 1,
            }),
        ),)


__all__ = [
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryDecider",
    "RecoveryDeciderRegistry",
    "RecoveryDeciderRegistryPort",
    "RecoveryProgram",
    "RecoveryRequest",
    "RecoveryRuntimeBinding",
    "RecoverySignal",
    "recovery_initial_data",
    "recovery_runtime_module",
    "recovery_runtime_operations",
]
