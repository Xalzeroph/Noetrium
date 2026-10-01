"""Paper-programmable synchronization semantics for RuntimeMachine.

Synchronization is the scientific rule deciding when logically admitted
participants may cross a coordination point together.  It does not own worker
threads, process scheduling, resource admission, placement, leases, clocks, or
transport.  Those remain infrastructure/provider mechanics.

A synchronization point can WAIT and later resume on the same RuntimeMachine
node with additional participant arrivals supplied in the resume payload.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, (tuple, list)
    ):
        raise TypeError(f"{field_name} must be a sequence")
    values = tuple(_text(item, field_name) for item in value)
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")
    return values


class SynchronizationAction(StrEnum):
    WAIT = "wait"
    RELEASE = "release"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class SynchronizationPoint:
    point_id: str
    epoch: int
    expected_participant_ids: tuple[str, ...]
    arrived_participant_ids: tuple[str, ...] = ()
    metadata: JsonObject = field(default_factory=dict)
    point_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "point_id",
            _text(self.point_id, "synchronization point_id"),
        )
        if type(self.epoch) is not int or self.epoch < 0:
            raise ValueError("synchronization epoch must be non-negative")
        expected = _text_tuple(
            self.expected_participant_ids,
            "synchronization expected participant ids",
        )
        if not expected:
            raise ValueError("synchronization point requires expected participants")
        arrived = _text_tuple(
            self.arrived_participant_ids,
            "synchronization arrived participant ids",
        )
        unknown = tuple(value for value in arrived if value not in expected)
        if unknown:
            raise ValueError(
                f"synchronization arrivals include unknown participants: {unknown}"
            )
        if not isinstance(self.metadata, Mapping):
            raise TypeError("synchronization metadata must be an object")
        object.__setattr__(self, "expected_participant_ids", expected)
        object.__setattr__(self, "arrived_participant_ids", arrived)
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        object.__setattr__(
            self,
            "point_digest",
            canonical_digest({
                "point_id": self.point_id,
                "epoch": self.epoch,
                "expected_participant_ids": self.expected_participant_ids,
                "arrived_participant_ids": self.arrived_participant_ids,
                "metadata": thaw_json(self.metadata),
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "point_id": self.point_id,
            "epoch": self.epoch,
            "expected_participant_ids": self.expected_participant_ids,
            "arrived_participant_ids": self.arrived_participant_ids,
            "metadata": thaw_json(self.metadata),
            "point_digest": self.point_digest,
        }

    @classmethod
    def from_payload(cls, value: object) -> "SynchronizationPoint":
        if not isinstance(value, Mapping):
            raise TypeError("synchronization point payload must be an object")
        point = cls(
            point_id=value.get("point_id"),
            epoch=value.get("epoch"),
            expected_participant_ids=_text_tuple(
                value.get("expected_participant_ids", ()),
                "synchronization expected participant ids",
            ),
            arrived_participant_ids=_text_tuple(
                value.get("arrived_participant_ids", ()),
                "synchronization arrived participant ids",
            ),
            metadata=value.get("metadata", {}),
        )
        supplied = value.get("point_digest")
        if supplied is not None and require_sha256(
            supplied,
            "synchronization point_digest",
        ) != point.point_digest:
            raise ValueError("synchronization point digest mismatch")
        return point


@dataclass(frozen=True, slots=True)
class SynchronizationRequest:
    decision_id: str
    point: SynchronizationPoint
    prior_decision_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision_id",
            _text(self.decision_id, "synchronization decision_id"),
        )
        if not isinstance(self.point, SynchronizationPoint):
            raise TypeError(
                "synchronization request requires SynchronizationPoint"
            )
        if type(self.prior_decision_digests) is not tuple:
            raise TypeError(
                "synchronization prior_decision_digests must be a tuple"
            )
        for value in self.prior_decision_digests:
            require_sha256(value, "synchronization prior decision digest")


@dataclass(frozen=True, slots=True)
class SynchronizationDecision:
    action: SynchronizationAction
    released_participant_ids: tuple[str, ...] = ()
    reason_code: str = "policy"
    receipt: JsonValue = None
    decision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.action, SynchronizationAction):
            raise TypeError(
                "synchronization action must be SynchronizationAction"
            )
        released = _text_tuple(
            self.released_participant_ids,
            "synchronization released participant ids",
        )
        if self.action is SynchronizationAction.RELEASE and not released:
            raise ValueError(
                "synchronization RELEASE requires released participants"
            )
        if self.action is not SynchronizationAction.RELEASE and released:
            raise ValueError(
                "only synchronization RELEASE may carry participants"
            )
        object.__setattr__(
            self,
            "reason_code",
            _text(self.reason_code, "synchronization reason_code"),
        )
        object.__setattr__(self, "released_participant_ids", released)
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "decision_digest",
            canonical_digest({
                "action": self.action.value,
                "released_participant_ids": self.released_participant_ids,
                "reason_code": self.reason_code,
                "receipt": thaw_json(self.receipt),
            }),
        )


SynchronizationDecider = Callable[
    [SynchronizationRequest], SynchronizationDecision
]


@runtime_checkable
class SynchronizationDeciderRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, decider: str) -> SynchronizationDecider: ...

    def implementation_digest(self, decider: str) -> str: ...


class SynchronizationDeciderRegistry(SynchronizationDeciderRegistryPort):
    def __init__(self) -> None:
        self._deciders: dict[str, tuple[SynchronizationDecider, str]] = {}
        self._identity_digest_cache: str | None = None
        self._lock = RLock()

    def register(
        self,
        decider: str,
        handler: SynchronizationDecider,
        *,
        implementation_digest: str,
    ) -> None:
        decider = _text(decider, "synchronization decider")
        if not callable(handler):
            raise TypeError("synchronization decider must be callable")
        digest = require_sha256(
            implementation_digest,
            "synchronization decider implementation_digest",
        )
        value = (handler, digest)
        with self._lock:
            current = self._deciders.get(decider)
            if current is not None and current != value:
                raise ValueError(
                    f"synchronization decider already registered: {decider}"
                )
            self._deciders[decider] = value
            self._identity_digest_cache = None

    def resolve(self, decider: str) -> SynchronizationDecider:
        decider = _text(decider, "synchronization decider")
        with self._lock:
            try:
                return self._deciders[decider][0]
            except KeyError as exc:
                raise KeyError(
                    f"unbound synchronization decider: {decider}"
                ) from exc

    def implementation_digest(self, decider: str) -> str:
        decider = _text(decider, "synchronization decider")
        with self._lock:
            try:
                return self._deciders[decider][1]
            except KeyError as exc:
                raise KeyError(
                    f"unbound synchronization decider: {decider}"
                ) from exc

    @property
    def identity_digest(self) -> str:
        with self._lock:
            cached = self._identity_digest_cache
            if cached is None:
                cached = canonical_digest(tuple(
                    (name, implementation_digest)
                    for name, (_, implementation_digest)
                    in sorted(self._deciders.items())
                ))
                self._identity_digest_cache = cached
            return cached


@dataclass(frozen=True, slots=True)
class SynchronizationProgram:
    program_id: str
    version: str
    decider: str
    decider_digest: str
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("program_id", "version", "decider"):
            object.__setattr__(
                self,
                name,
                _text(
                    getattr(self, name),
                    f"synchronization program {name}",
                ),
            )
        object.__setattr__(
            self,
            "decider_digest",
            require_sha256(
                self.decider_digest,
                "synchronization program decider_digest",
            ),
        )
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "decider": self.decider,
                "decider_digest": self.decider_digest,
            }),
        )


@dataclass(frozen=True, slots=True)
class SynchronizationThresholdSpec:
    minimum_arrivals: int = 1
    minimum_fraction_numerator: int = 0
    minimum_fraction_denominator: int = 1
    spec_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.minimum_arrivals) is not int or self.minimum_arrivals < 1:
            raise ValueError(
                "synchronization minimum_arrivals must be a positive integer"
            )
        if (
            type(self.minimum_fraction_numerator) is not int
            or self.minimum_fraction_numerator < 0
        ):
            raise ValueError(
                "synchronization minimum_fraction_numerator must be non-negative"
            )
        if (
            type(self.minimum_fraction_denominator) is not int
            or self.minimum_fraction_denominator < 1
        ):
            raise ValueError(
                "synchronization minimum_fraction_denominator must be positive"
            )
        if self.minimum_fraction_numerator > self.minimum_fraction_denominator:
            raise ValueError("synchronization minimum fraction cannot exceed one")
        object.__setattr__(
            self,
            "spec_digest",
            canonical_digest({
                "schema": "runtime.synchronization.threshold.v1",
                "minimum_arrivals": self.minimum_arrivals,
                "minimum_fraction_numerator": self.minimum_fraction_numerator,
                "minimum_fraction_denominator": self.minimum_fraction_denominator,
            }),
        )

    def required_arrivals(self, expected_count: int) -> int:
        if type(expected_count) is not int or expected_count < 1:
            raise ValueError(
                "synchronization expected participant count must be positive"
            )
        fractional = (
            expected_count * self.minimum_fraction_numerator
            + self.minimum_fraction_denominator
            - 1
        ) // self.minimum_fraction_denominator
        required = max(self.minimum_arrivals, fractional)
        if required > expected_count:
            raise ValueError(
                "synchronization threshold exceeds expected participant count"
            )
        return required

    @property
    def decider_id(self) -> str:
        return f"runtime.synchronization.threshold:{self.spec_digest[:24]}"

    @property
    def implementation_digest(self) -> str:
        return canonical_digest({
            "handler_family": "runtime.synchronization.threshold",
            "spec_digest": self.spec_digest,
            "implementation_revision": 1,
        })


def threshold_synchronization_decider(
    spec: SynchronizationThresholdSpec,
) -> SynchronizationDecider:
    if not isinstance(spec, SynchronizationThresholdSpec):
        raise TypeError(
            "threshold synchronization decider requires SynchronizationThresholdSpec"
        )

    def decide(request: SynchronizationRequest) -> SynchronizationDecision:
        point = request.point
        expected = point.expected_participant_ids
        arrived_set = set(point.arrived_participant_ids)
        arrived = tuple(
            participant_id
            for participant_id in expected
            if participant_id in arrived_set
        )
        required = spec.required_arrivals(len(expected))
        receipt = {
            "required_arrivals": required,
            "minimum_arrivals": spec.minimum_arrivals,
            "minimum_fraction_numerator": spec.minimum_fraction_numerator,
            "minimum_fraction_denominator": spec.minimum_fraction_denominator,
            "arrived_count": len(arrived),
            "expected_count": len(expected),
            "spec_digest": spec.spec_digest,
        }
        if len(arrived) < required:
            return SynchronizationDecision(
                SynchronizationAction.WAIT,
                reason_code="await-arrival-threshold",
                receipt=receipt,
            )
        return SynchronizationDecision(
            SynchronizationAction.RELEASE,
            arrived,
            reason_code="arrival-threshold-reached",
            receipt=receipt,
        )

    return decide


def synchronization_program_from_threshold(
    spec: SynchronizationThresholdSpec,
    *,
    program_id: str = "runtime.synchronization.standard",
    version: str = "1",
) -> tuple[SynchronizationProgram, SynchronizationDeciderRegistry]:
    if not isinstance(spec, SynchronizationThresholdSpec):
        raise TypeError(
            "synchronization threshold compiler requires SynchronizationThresholdSpec"
        )
    program = SynchronizationProgram(
        program_id=program_id,
        version=version,
        decider=spec.decider_id,
        decider_digest=spec.implementation_digest,
    )
    registry = SynchronizationDeciderRegistry()
    registry.register(
        spec.decider_id,
        threshold_synchronization_decider(spec),
        implementation_digest=spec.implementation_digest,
    )
    return program, registry


@dataclass(slots=True)
class SynchronizationRuntimeBinding:
    program: SynchronizationProgram
    deciders: SynchronizationDeciderRegistryPort
    decision: SynchronizationDecision | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.program, SynchronizationProgram):
            raise TypeError(
                "synchronization binding requires SynchronizationProgram"
            )
        if not isinstance(
            self.deciders,
            SynchronizationDeciderRegistryPort,
        ):
            raise TypeError(
                "synchronization binding requires decider registry"
            )
        require_sha256(
            self.deciders.identity_digest,
            "synchronization decider registry identity_digest",
        )
        actual = require_sha256(
            self.deciders.implementation_digest(self.program.decider),
            "synchronization decider implementation_digest",
        )
        if actual != self.program.decider_digest:
            raise ValueError(
                "synchronization decider implementation identity drifted"
            )

    @property
    def binding_digest(self) -> str:
        return canonical_digest({
            "synchronization_program_digest": self.program.program_digest,
            "registry_identity_digest": self.deciders.identity_digest,
            "decider_implementation_digest": (
                self.deciders.implementation_digest(self.program.decider)
            ),
        })


def synchronization_initial_data(
    *,
    decision_id: str,
    program: SynchronizationProgram,
    point: SynchronizationPoint,
    prior_decision_digests: tuple[str, ...] = (),
) -> JsonObject:
    if not isinstance(program, SynchronizationProgram):
        raise TypeError(
            "synchronization initial data requires SynchronizationProgram"
        )
    if not isinstance(point, SynchronizationPoint):
        raise TypeError(
            "synchronization initial data requires SynchronizationPoint"
        )
    for value in prior_decision_digests:
        require_sha256(value, "synchronization prior decision digest")
    return {
        "decision_id": _text(
            decision_id,
            "synchronization decision_id",
        ),
        "synchronization_program_digest": program.program_digest,
        "point": point.payload(),
        "prior_decision_digests": prior_decision_digests,
        "decision": None,
        "decision_digest": None,
    }


def _arrival_payload(payload: JsonValue) -> tuple[str, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, Mapping):
        raise TypeError(
            "synchronization resume payload must be an object"
        )
    value = payload.get("arrival_participant_ids", ())
    return _text_tuple(
        value,
        "synchronization arrival participant ids",
    )


def _decide(
    request: ProgramNodeRequest,
    binding: object,
) -> ProgramNodeResult:
    if not isinstance(binding, SynchronizationRuntimeBinding):
        raise TypeError(
            "runtime synchronization requires SynchronizationRuntimeBinding"
        )
    if (
        request.data.get("synchronization_program_digest")
        != binding.program.program_digest
    ):
        raise ValueError("Runtime SynchronizationProgram identity drifted")

    point = SynchronizationPoint.from_payload(request.data.get("point"))
    new_arrivals = _arrival_payload(request.payload)
    expected = point.expected_participant_ids
    unknown = tuple(value for value in new_arrivals if value not in expected)
    if unknown:
        raise ValueError(
            f"synchronization resume includes unknown participants: {unknown}"
        )
    arrived_set = set(point.arrived_participant_ids)
    arrived_set.update(new_arrivals)
    arrived = tuple(
        participant_id
        for participant_id in expected
        if participant_id in arrived_set
    )
    current_point = SynchronizationPoint(
        point_id=point.point_id,
        epoch=point.epoch,
        expected_participant_ids=expected,
        arrived_participant_ids=arrived,
        metadata=point.metadata,
    )

    prior_value = request.data.get("prior_decision_digests", ())
    if isinstance(prior_value, (str, bytes, bytearray)) or not isinstance(
        prior_value, Sequence
    ):
        raise TypeError(
            "synchronization prior_decision_digests must be a sequence"
        )
    prior = tuple(
        require_sha256(value, "synchronization prior decision digest")
        for value in prior_value
    )
    decision_id = _text(
        request.data.get("decision_id"),
        "synchronization decision_id",
    )
    decision = binding.deciders.resolve(binding.program.decider)(
        SynchronizationRequest(
            decision_id=decision_id,
            point=current_point,
            prior_decision_digests=prior,
        )
    )
    if not isinstance(decision, SynchronizationDecision):
        raise TypeError(
            "synchronization decider must return SynchronizationDecision"
        )

    released = decision.released_participant_ids
    unknown_release = tuple(value for value in released if value not in expected)
    if unknown_release:
        raise ValueError(
            "synchronization decider released unknown participants: "
            f"{unknown_release}"
        )
    unarrived_release = tuple(value for value in released if value not in arrived)
    if unarrived_release:
        raise ValueError(
            "synchronization decider released participants before arrival: "
            f"{unarrived_release}"
        )

    binding.decision = decision
    payload = {
        "action": decision.action.value,
        "released_participant_ids": released,
        "reason_code": decision.reason_code,
        "receipt": thaw_json(decision.receipt),
        "decision_digest": decision.decision_digest,
    }
    state_update = {
        "point": current_point.payload(),
        "decision": payload,
        "decision_digest": decision.decision_digest,
        "prior_decision_digests": (*prior, decision.decision_digest),
    }
    event = {
        "type": "runtime_synchronization_decided",
        "decision_id": decision_id,
        "point_id": current_point.point_id,
        "point_digest": current_point.point_digest,
        "epoch": current_point.epoch,
        "arrived_participant_ids": arrived,
        "action": decision.action.value,
        "released_participant_ids": released,
        "reason_code": decision.reason_code,
        "decision_digest": decision.decision_digest,
        "decider": binding.program.decider,
        "decider_digest": binding.program.decider_digest,
    }
    if decision.action is SynchronizationAction.WAIT:
        return ProgramNodeResult(
            value=payload,
            state_update=state_update,
            status=MachineStatus.WAITING,
            wait_reason=(
                "synchronization waiting at "
                f"{current_point.point_id}:{current_point.epoch}"
            ),
            events=(event,),
        )
    if decision.action is SynchronizationAction.ABORT:
        return ProgramNodeResult(
            value=payload,
            state_update=state_update,
            status=MachineStatus.FAILED,
            events=(event,),
        )
    return ProgramNodeResult(
        value=payload,
        state_update=state_update,
        status=MachineStatus.COMPLETED,
        events=(event,),
    )


def synchronization_runtime_module(
    program: SynchronizationProgram,
    *,
    module_id: str = "runtime.synchronization",
) -> RuntimeModule:
    if not isinstance(program, SynchronizationProgram):
        raise TypeError(
            "synchronization runtime module requires SynchronizationProgram"
        )
    return (
        RuntimeModuleBuilder.synchronization(
            module_id=module_id,
            entrypoint="decide",
        )
        .node(
            "decide",
            "runtime.synchronization.decide",
            configuration={
                "synchronization_program_digest": program.program_digest,
                "decider": program.decider,
                "decider_digest": program.decider_digest,
            },
        )
        .build()
    )


def synchronization_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "runtime.synchronization.decide",
            _decide,
            canonical_digest({
                "operation": "runtime.synchronization.decide",
                "implementation_revision": 1,
            }),
        ),
    )


__all__ = [
    "SynchronizationAction",
    "SynchronizationDecision",
    "SynchronizationDecider",
    "SynchronizationDeciderRegistry",
    "SynchronizationDeciderRegistryPort",
    "SynchronizationPoint",
    "SynchronizationThresholdSpec",
    "SynchronizationProgram",
    "SynchronizationRequest",
    "SynchronizationRuntimeBinding",
    "threshold_synchronization_decider",
    "synchronization_initial_data",
    "synchronization_program_from_threshold",
    "synchronization_runtime_module",
    "synchronization_runtime_operations",
]
