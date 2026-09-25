"""Paper-programmable human/participant intervention for RuntimeMachine.

InterventionProgram decides whether execution should suspend for external
input. RuntimeMachine journals the request, enters WAITING, and records the
resume response digest. UI, human transport, notification and identity
authentication remain provider mechanics.
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


class InterventionKind(StrEnum):
    INPUT = "input"
    APPROVAL = "approval"
    RANKING = "ranking"
    EDIT = "edit"
    FEEDBACK = "feedback"
    TAKEOVER = "takeover"
    YIELD_CONTROL = "yield_control"


@dataclass(frozen=True, slots=True)
class InterventionTrigger:
    trigger_id: str
    trigger_kind: str
    context_digest: str
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("trigger_id", self.trigger_id),
            ("trigger_kind", self.trigger_kind),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"intervention {name} is required")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(
            self,
            "context_digest",
            require_sha256(
                self.context_digest,
                "intervention context_digest",
            ),
        )
        if not isinstance(self.metadata, Mapping):
            raise TypeError("intervention metadata must be an object")
        object.__setattr__(self, "metadata", freeze_json(self.metadata))

    @property
    def trigger_digest(self) -> str:
        return canonical_digest({
            "trigger_id": self.trigger_id,
            "trigger_kind": self.trigger_kind,
            "context_digest": self.context_digest,
            "metadata": thaw_json(self.metadata),
        })


@dataclass(frozen=True, slots=True)
class InterventionDecision:
    required: bool
    kind: InterventionKind | None = None
    target_participant_id: str | None = None
    request_payload: JsonObject = field(default_factory=dict)
    reason_code: str = "policy"
    receipt: JsonValue = None
    decision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.required) is not bool:
            raise TypeError("intervention required must be boolean")
        if self.required and not isinstance(self.kind, InterventionKind):
            raise ValueError("required intervention must declare kind")
        if not self.required and self.kind is not None:
            raise ValueError("non-required intervention must not declare kind")
        if self.target_participant_id is not None and (
            type(self.target_participant_id) is not str
            or not self.target_participant_id.strip()
        ):
            raise ValueError(
                "intervention target_participant_id must be non-empty"
            )
        if not isinstance(self.request_payload, Mapping):
            raise TypeError("intervention request_payload must be an object")
        object.__setattr__(
            self,
            "request_payload",
            freeze_json(self.request_payload),
        )
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise ValueError("intervention reason_code is required")
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "decision_digest",
            canonical_digest({
                "required": self.required,
                "kind": None if self.kind is None else self.kind.value,
                "target_participant_id": self.target_participant_id,
                "request_payload": thaw_json(self.request_payload),
                "reason_code": self.reason_code,
                "receipt": thaw_json(self.receipt),
            }),
        )


@dataclass(frozen=True, slots=True)
class InterventionPolicyRequest:
    trigger: InterventionTrigger
    allowed_kinds: tuple[InterventionKind, ...]
    prior_intervention_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, InterventionTrigger):
            raise TypeError(
                "intervention policy request requires InterventionTrigger"
            )
        if type(self.allowed_kinds) is not tuple or any(
            not isinstance(kind, InterventionKind)
            for kind in self.allowed_kinds
        ):
            raise TypeError(
                "intervention allowed_kinds must be InterventionKind tuple"
            )
        if len(self.allowed_kinds) != len(set(self.allowed_kinds)):
            raise ValueError("intervention allowed_kinds must be unique")
        if (
            type(self.prior_intervention_count) is not int
            or self.prior_intervention_count < 0
        ):
            raise ValueError(
                "intervention prior_intervention_count must be non-negative"
            )


InterventionDecider = Callable[
    [InterventionPolicyRequest],
    InterventionDecision,
]


@runtime_checkable
class InterventionDeciderRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, decider: str) -> InterventionDecider: ...

    def implementation_digest(self, decider: str) -> str: ...


class InterventionDeciderRegistry(InterventionDeciderRegistryPort):
    def __init__(self) -> None:
        self._deciders: dict[str, tuple[InterventionDecider, str]] = {}
        self._lock = RLock()

    def register(
        self,
        decider: str,
        handler: InterventionDecider,
        *,
        implementation_digest: str,
    ) -> None:
        if type(decider) is not str or not decider.strip():
            raise ValueError("intervention decider id is required")
        if not callable(handler):
            raise TypeError("intervention decider must be callable")
        digest = require_sha256(
            implementation_digest,
            "intervention decider implementation_digest",
        )
        decider = decider.strip()
        value = (handler, digest)
        with self._lock:
            current = self._deciders.get(decider)
            if current is not None and current != value:
                raise ValueError(
                    f"intervention decider already registered: {decider}"
                )
            self._deciders[decider] = value

    def resolve(self, decider: str) -> InterventionDecider:
        if type(decider) is not str or not decider.strip():
            raise ValueError("intervention decider id is required")
        with self._lock:
            try:
                return self._deciders[decider.strip()][0]
            except KeyError as exc:
                raise KeyError(
                    f"unbound intervention decider: {decider}"
                ) from exc

    def implementation_digest(self, decider: str) -> str:
        if type(decider) is not str or not decider.strip():
            raise ValueError("intervention decider id is required")
        with self._lock:
            try:
                return self._deciders[decider.strip()][1]
            except KeyError as exc:
                raise KeyError(
                    f"unbound intervention decider: {decider}"
                ) from exc

    @property
    def identity_digest(self) -> str:
        with self._lock:
            return canonical_digest(tuple(
                (name, digest)
                for name, (_, digest)
                in sorted(self._deciders.items())
            ))


@dataclass(frozen=True, slots=True)
class InterventionProgram:
    program_id: str
    version: str
    decider: str
    decider_digest: str
    allowed_kinds: tuple[InterventionKind, ...]
    max_interventions: int | None = None
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("program_id", self.program_id),
            ("version", self.version),
            ("decider", self.decider),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"intervention program {name} is required")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(
            self,
            "decider_digest",
            require_sha256(
                self.decider_digest,
                "intervention program decider_digest",
            ),
        )
        if type(self.allowed_kinds) is not tuple or any(
            not isinstance(kind, InterventionKind)
            for kind in self.allowed_kinds
        ):
            raise TypeError(
                "intervention program allowed_kinds must be typed tuple"
            )
        if len(self.allowed_kinds) != len(set(self.allowed_kinds)):
            raise ValueError("intervention program allowed_kinds must be unique")
        if self.max_interventions is not None and (
            type(self.max_interventions) is not int
            or self.max_interventions < 0
        ):
            raise ValueError(
                "intervention max_interventions must be non-negative or None"
            )
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "decider": self.decider,
                "decider_digest": self.decider_digest,
                "allowed_kinds": tuple(
                    kind.value for kind in self.allowed_kinds
                ),
                "max_interventions": self.max_interventions,
            }),
        )


@dataclass(frozen=True, slots=True)
class InterventionResponse:
    request_digest: str
    response_id: str
    actor_participant_id: str
    payload: JsonValue
    receipt: JsonValue = None
    response_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_digest",
            require_sha256(
                self.request_digest,
                "intervention response request_digest",
            ),
        )
        for name, value in (
            ("response_id", self.response_id),
            ("actor_participant_id", self.actor_participant_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"intervention response {name} is required")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "response_digest",
            canonical_digest({
                "request_digest": self.request_digest,
                "response_id": self.response_id,
                "actor_participant_id": self.actor_participant_id,
                "payload": thaw_json(self.payload),
                "receipt": thaw_json(self.receipt),
            }),
        )


@dataclass(slots=True)
class InterventionRuntimeBinding:
    program: InterventionProgram
    deciders: InterventionDeciderRegistryPort
    decision: InterventionDecision | None = None
    response: InterventionResponse | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.program, InterventionProgram):
            raise TypeError(
                "intervention binding requires InterventionProgram"
            )
        if not isinstance(
            self.deciders,
            InterventionDeciderRegistryPort,
        ):
            raise TypeError(
                "intervention binding requires decider registry"
            )
        require_sha256(
            self.deciders.identity_digest,
            "intervention registry identity_digest",
        )
        actual = self.deciders.implementation_digest(self.program.decider)
        if actual != self.program.decider_digest:
            raise ValueError(
                "intervention decider implementation identity drifted"
            )

    @property
    def binding_digest(self) -> str:
        return canonical_digest({
            "intervention_program_digest": self.program.program_digest,
            "registry_identity_digest": self.deciders.identity_digest,
            "decider_implementation_digest": (
                self.deciders.implementation_digest(self.program.decider)
            ),
        })


def intervention_initial_data(
    trigger: InterventionTrigger,
    program: InterventionProgram,
    *,
    prior_intervention_count: int = 0,
) -> JsonObject:
    if not isinstance(trigger, InterventionTrigger):
        raise TypeError(
            "intervention initial data requires InterventionTrigger"
        )
    if not isinstance(program, InterventionProgram):
        raise TypeError(
            "intervention initial data requires InterventionProgram"
        )
    if (
        type(prior_intervention_count) is not int
        or prior_intervention_count < 0
    ):
        raise ValueError(
            "intervention prior_intervention_count must be non-negative"
        )
    return {
        "intervention_program_digest": program.program_digest,
        "trigger": {
            "trigger_id": trigger.trigger_id,
            "trigger_kind": trigger.trigger_kind,
            "context_digest": trigger.context_digest,
            "metadata": thaw_json(trigger.metadata),
            "trigger_digest": trigger.trigger_digest,
        },
        "prior_intervention_count": prior_intervention_count,
        "request": None,
        "response_digest": None,
    }


def _trigger(value: object) -> InterventionTrigger:
    if not isinstance(value, Mapping):
        raise TypeError("intervention trigger state must be an object")
    trigger = InterventionTrigger(
        trigger_id=value.get("trigger_id"),
        trigger_kind=value.get("trigger_kind"),
        context_digest=value.get("context_digest"),
        metadata=value.get("metadata", {}),
    )
    supplied = value.get("trigger_digest")
    if supplied is not None and supplied != trigger.trigger_digest:
        raise ValueError("intervention trigger digest mismatch")
    return trigger


def _decide(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, InterventionRuntimeBinding):
        raise TypeError(
            "runtime intervention requires InterventionRuntimeBinding"
        )
    if (
        request.data.get("intervention_program_digest")
        != binding.program.program_digest
    ):
        raise ValueError("Runtime InterventionProgram identity drifted")
    trigger = _trigger(request.data.get("trigger"))
    count = request.data.get("prior_intervention_count", 0)
    if type(count) is not int or count < 0:
        raise ValueError("intervention count is invalid")

    if (
        binding.program.max_interventions is not None
        and count >= binding.program.max_interventions
    ):
        decision = InterventionDecision(
            False,
            reason_code="intervention-budget-exhausted",
        )
    else:
        decision = binding.deciders.resolve(binding.program.decider)(
            InterventionPolicyRequest(
                trigger,
                binding.program.allowed_kinds,
                count,
            )
        )
    if not isinstance(decision, InterventionDecision):
        raise TypeError(
            "intervention decider must return InterventionDecision"
        )
    if decision.required:
        if decision.kind not in binding.program.allowed_kinds:
            raise ValueError(
                "intervention decider selected disallowed kind"
            )
        request_payload: JsonObject = {
            "trigger_digest": trigger.trigger_digest,
            "kind": decision.kind.value,
            "target_participant_id": decision.target_participant_id,
            "request_payload": thaw_json(decision.request_payload),
            "reason_code": decision.reason_code,
            "decision_digest": decision.decision_digest,
        }
        request_digest = canonical_digest(request_payload)
        request_payload["request_digest"] = request_digest
        binding.decision = decision
        return ProgramNodeResult(
            value={
                "required": True,
                "request_digest": request_digest,
            },
            state_update={
                "request": request_payload,
                "request_digest": request_digest,
            },
            next_node="consume",
            status=MachineStatus.WAITING,
            wait_reason=f"intervention:{request_digest}",
            events=({
                "type": "runtime_intervention_requested",
                "request_digest": request_digest,
                "trigger_digest": trigger.trigger_digest,
                "kind": decision.kind.value,
                "target_participant_id": (
                    decision.target_participant_id
                ),
                "reason_code": decision.reason_code,
                "decider": binding.program.decider,
                "decider_digest": binding.program.decider_digest,
            },),
        )

    binding.decision = decision
    return ProgramNodeResult(
        value={
            "required": False,
            "decision_digest": decision.decision_digest,
        },
        state_update={
            "request": None,
            "decision_digest": decision.decision_digest,
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "runtime_intervention_skipped",
            "trigger_digest": trigger.trigger_digest,
            "reason_code": decision.reason_code,
            "decision_digest": decision.decision_digest,
        },),
    )


def _consume(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, InterventionRuntimeBinding):
        raise TypeError(
            "runtime intervention requires InterventionRuntimeBinding"
        )
    request_state = request.data.get("request")
    if not isinstance(request_state, Mapping):
        raise RuntimeError(
            "intervention response requires pending request"
        )
    expected_digest = request_state.get("request_digest")
    if type(expected_digest) is not str:
        raise RuntimeError(
            "pending intervention request has no digest"
        )
    if not isinstance(request.payload, Mapping):
        raise TypeError(
            "resumed intervention requires response payload"
        )
    payload = thaw_json(request.payload)
    if not isinstance(payload, dict):
        raise TypeError(
            "intervention response payload must decode to object"
        )
    response_value = payload.get("intervention_response")
    if not isinstance(response_value, Mapping):
        raise TypeError(
            "resume payload requires intervention_response object"
        )
    response = InterventionResponse(
        request_digest=response_value.get("request_digest"),
        response_id=response_value.get("response_id"),
        actor_participant_id=response_value.get(
            "actor_participant_id"
        ),
        payload=response_value.get("payload"),
        receipt=response_value.get("receipt"),
    )
    if response.request_digest != expected_digest:
        raise ValueError(
            "intervention response request identity drifted"
        )
    binding.response = response
    return ProgramNodeResult(
        value={
            "response_digest": response.response_digest,
            "actor_participant_id": response.actor_participant_id,
        },
        state_update={
            "response_digest": response.response_digest,
            "response_actor_participant_id": (
                response.actor_participant_id
            ),
            "prior_intervention_count": (
                request.data.get("prior_intervention_count", 0) + 1
            ),
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "runtime_intervention_resumed",
            "request_digest": response.request_digest,
            "response_digest": response.response_digest,
            "actor_participant_id": response.actor_participant_id,
        },),
    )


def intervention_runtime_module(
    program: InterventionProgram,
    *,
    module_id: str = "runtime.intervention",
) -> RuntimeModule:
    if not isinstance(program, InterventionProgram):
        raise TypeError(
            "intervention runtime module requires InterventionProgram"
        )
    return (
        RuntimeModuleBuilder.intervention(
            module_id=module_id,
            entrypoint="decide",
        )
        .node(
            "decide",
            "runtime.intervention.decide",
            configuration={
                "intervention_program_digest": program.program_digest,
                "decider": program.decider,
                "decider_digest": program.decider_digest,
            },
        )
        .node(
            "consume",
            "runtime.intervention.consume",
            configuration={
                "intervention_program_digest": program.program_digest,
            },
        )
        .build()
    )


def intervention_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "runtime.intervention.decide",
            _decide,
            canonical_digest({
                "operation": "runtime.intervention.decide",
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "runtime.intervention.consume",
            _consume,
            canonical_digest({
                "operation": "runtime.intervention.consume",
                "implementation_revision": 1,
            }),
        ),
    )


__all__ = [
    "InterventionDecision",
    "InterventionDecider",
    "InterventionDeciderRegistry",
    "InterventionDeciderRegistryPort",
    "InterventionKind",
    "InterventionPolicyRequest",
    "InterventionProgram",
    "InterventionResponse",
    "InterventionRuntimeBinding",
    "InterventionTrigger",
    "intervention_initial_data",
    "intervention_runtime_module",
    "intervention_runtime_operations",
]
