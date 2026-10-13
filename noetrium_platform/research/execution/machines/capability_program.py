"""Programmable capability mediation executed inside RuntimeMachine.

Capability mechanics (provider lookup, effect WAL, reconciliation) remain
outside this module. This IR owns only paper-variable execution semantics:
pre-invocation guards/approval, request transformation, post-validation and
the ordering of those steps.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import heapq
from threading import RLock
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.api import (
    CapabilityApprovalPort,
    CapabilityDescriptor,
    CapabilityGuardPort,
    CapabilityPostPolicyPort,
    CapabilityRequest,
    CapabilityResult,
    GuardVerdict,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    MachineStatus,
    canonical_digest,
    freeze_json,
    require_sha256,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel.universal import UnitStepContext, UnitTransition
from noetrium_platform.foundation.kernel.kernel.unit_host import UnitOperationBinding
from .runtime_module import runtime_module
from .domains import RuntimeConcern
from noetrium_platform.foundation.kernel.kernel.universal import unit_operation


class CapabilityMediationStage(StrEnum):
    PRE = "pre"
    POST = "post"


class CapabilityMediationVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


CAPABILITY_PROGRAM_TRAIT = "machine.capability.program"
CAPABILITY_RULE_TRAIT = "machine.capability.rule"

def capability_rule_graph(*, rule_id: str, stage: CapabilityMediationStage, mediator: str, priority: int = 0, capability_ids: tuple[str, ...] = (), effect_classes: tuple[EffectClass, ...] = (), required: bool = False, configuration: JsonObject | None = None) -> NoetriumUnit:
    if type(rule_id) is not str or not rule_id.strip(): raise ValueError("capability rule rule_id is required")
    if type(mediator) is not str or not mediator.strip(): raise ValueError("capability rule mediator is required")
    if not isinstance(stage, CapabilityMediationStage): raise TypeError("capability rule stage must be CapabilityMediationStage")
    if type(priority) is not int: raise TypeError("capability rule priority must be integer")
    if type(capability_ids) is not tuple or any(type(v) is not str or not v.strip() for v in capability_ids): raise TypeError("capability rule capability_ids must be text tuple")
    if len(capability_ids) != len(set(capability_ids)): raise ValueError("capability rule capability_ids must be unique")
    if type(effect_classes) is not tuple or any(not isinstance(v, EffectClass) for v in effect_classes): raise TypeError("capability rule effect_classes must be EffectClass tuple")
    if type(required) is not bool: raise TypeError("capability rule required must be boolean")
    return structure_unit(rule_id.strip(), traits=(CAPABILITY_RULE_TRAIT,), parameters={"stage":stage.value,"mediator":mediator.strip(),"priority":priority,"capability_ids":capability_ids,"effect_classes":tuple(v.value for v in effect_classes),"required":required,"configuration":{} if configuration is None else configuration})

def _rule_stage(rule: NoetriumUnit) -> CapabilityMediationStage: return CapabilityMediationStage(str(rule.parameters["stage"]))
def _rule_mediator(rule: NoetriumUnit) -> str: return str(rule.parameters["mediator"])
def _rule_priority(rule: NoetriumUnit) -> int: return int(rule.parameters["priority"])
def _rule_capability_ids(rule: NoetriumUnit) -> tuple[str, ...]: return tuple(str(v) for v in rule.parameters.get("capability_ids", ()))
def _rule_effect_classes(rule: NoetriumUnit) -> tuple[EffectClass, ...]: return tuple(EffectClass(str(v)) for v in rule.parameters.get("effect_classes", ()))
def _rule_matches(rule: NoetriumUnit, descriptor: CapabilityDescriptor) -> bool:
    if type(rule) is not NoetriumUnit or not rule.has_trait(CAPABILITY_RULE_TRAIT): raise TypeError("capability rule must be capability-rule NoetriumUnit")
    ids, effects = _rule_capability_ids(rule), _rule_effect_classes(rule)
    return (not ids or descriptor.capability_id in ids) and (not effects or descriptor.effect_class in effects)

def capability_program_graph(*, program_id: str, version: str, rules: tuple[NoetriumUnit, ...]) -> NoetriumUnit:
    if type(program_id) is not str or not program_id.strip(): raise ValueError("capability program program_id is required")
    if type(version) is not str or not version.strip(): raise ValueError("capability program version is required")
    if type(rules) is not tuple or any(type(r) is not NoetriumUnit or not r.has_trait(CAPABILITY_RULE_TRAIT) for r in rules): raise TypeError("capability program rules must be capability-rule NoetriumUnit values")
    ids=tuple(r.unit_id for r in rules)
    if len(ids) != len(set(ids)): raise ValueError("capability program rule ids must be unique")
    return structure_unit(program_id.strip(), traits=(CAPABILITY_PROGRAM_TRAIT,), members=rules, parameters={"version":version.strip()})

def capability_program_rules(program: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    if type(program) is not NoetriumUnit or not program.has_trait(CAPABILITY_PROGRAM_TRAIT): raise TypeError("capability program must be capability-program NoetriumUnit")
    return tuple(r for r in program.members if r.has_trait(CAPABILITY_RULE_TRAIT))

def capability_rules_for(program: NoetriumUnit, stage: CapabilityMediationStage, descriptor: CapabilityDescriptor) -> tuple[NoetriumUnit, ...]:
    return tuple(sorted((r for r in capability_program_rules(program) if _rule_stage(r) is stage and _rule_matches(r, descriptor)), key=lambda r:(-_rule_priority(r), r.unit_id)))


@dataclass(frozen=True, slots=True)
class CapabilityMediationRequest:
    rule: NoetriumUnit
    descriptor: CapabilityDescriptor
    request: CapabilityRequest
    result: CapabilityResult | None = None

    def __post_init__(self) -> None:
        if type(self.rule) is not NoetriumUnit or not self.rule.has_trait(CAPABILITY_RULE_TRAIT):
            raise TypeError("capability mediation request requires rule")
        if not isinstance(self.descriptor, CapabilityDescriptor):
            raise TypeError("capability mediation request requires descriptor")
        if not isinstance(self.request, CapabilityRequest):
            raise TypeError("capability mediation request requires CapabilityRequest")
        if self.result is not None and not isinstance(self.result, CapabilityResult):
            raise TypeError("capability mediation result must be CapabilityResult or None")


@dataclass(frozen=True, slots=True)
class CapabilityMediationResult:
    verdict: CapabilityMediationVerdict = CapabilityMediationVerdict.ALLOW
    reason_code: str = ""
    request_payload: JsonValue = None
    receipt: JsonValue = None

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, CapabilityMediationVerdict):
            raise TypeError("capability mediation verdict must be typed")
        if self.verdict is CapabilityMediationVerdict.DENY and (
            type(self.reason_code) is not str or not self.reason_code.strip()
        ):
            raise ValueError("denied capability mediation requires reason_code")
        if type(self.reason_code) is not str:
            raise TypeError("capability mediation reason_code must be text")
        object.__setattr__(self, "request_payload", freeze_json(self.request_payload))
        object.__setattr__(self, "receipt", freeze_json(self.receipt))


CapabilityMediator = Callable[[CapabilityMediationRequest], CapabilityMediationResult]


@runtime_checkable
class CapabilityMediatorRegistryPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(self, mediator: str) -> CapabilityMediator: ...

    def implementation_digest(self, mediator: str) -> str: ...


class CapabilityMediatorRegistry(CapabilityMediatorRegistryPort):
    def __init__(self) -> None:
        self._handlers: dict[str, tuple[CapabilityMediator, str]] = {}
        self._identity_digest_cache: str | None = None
        self._lock = RLock()

    def register(
        self,
        mediator: str,
        handler: CapabilityMediator,
        *,
        implementation_digest: str,
    ) -> None:
        if type(mediator) is not str or not mediator.strip():
            raise ValueError("capability mediator id is required")
        if not callable(handler):
            raise TypeError("capability mediator handler must be callable")
        mediator = mediator.strip()
        digest = require_sha256(
            implementation_digest,
            "capability mediator implementation_digest",
        )
        value = (handler, digest)
        with self._lock:
            current = self._handlers.get(mediator)
            if current is not None and current != value:
                raise ValueError(f"capability mediator already registered: {mediator}")
            self._handlers[mediator] = value
            self._identity_digest_cache = None

    def resolve(self, mediator: str) -> CapabilityMediator:
        if type(mediator) is not str or not mediator.strip():
            raise ValueError("capability mediator id is required")
        with self._lock:
            try:
                return self._handlers[mediator.strip()][0]
            except KeyError as exc:
                raise KeyError(f"unbound capability mediator: {mediator}") from exc

    def implementation_digest(self, mediator: str) -> str:
        if type(mediator) is not str or not mediator.strip():
            raise ValueError("capability mediator id is required")
        with self._lock:
            try:
                return self._handlers[mediator.strip()][1]
            except KeyError as exc:
                raise KeyError(f"unbound capability mediator: {mediator}") from exc

    def mediators(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._handlers))

    @property
    def identity_digest(self) -> str:
        with self._lock:
            cached = self._identity_digest_cache
            if cached is None:
                cached = canonical_digest(tuple(
                    (mediator, implementation_digest)
                    for mediator, (_, implementation_digest)
                    in sorted(self._handlers.items())
                ))
                self._identity_digest_cache = cached
            return cached


def capability_mediator_binding_digest(
    program: NoetriumUnit,
    mediators: CapabilityMediatorRegistryPort,
) -> str:
    """Bind a capability-program NoetriumUnit to exact mediator implementations."""

    if type(program) is not NoetriumUnit or not program.has_trait(CAPABILITY_PROGRAM_TRAIT):
        raise TypeError("capability mediator binding requires capability-program NoetriumUnit")
    if not isinstance(mediators, CapabilityMediatorRegistryPort):
        raise TypeError(
            "capability mediator binding requires CapabilityMediatorRegistryPort"
        )
    require_sha256(
        mediators.identity_digest,
        "capability mediator registry identity_digest",
    )
    mediator_ids = tuple(sorted({_rule_mediator(rule) for rule in capability_program_rules(program)}))
    implementations = tuple(
        (
            mediator,
            require_sha256(
                mediators.implementation_digest(mediator),
                "capability mediator implementation_digest",
            ),
        )
        for mediator in mediator_ids
    )
    return canonical_digest({
        "capability_program_digest": program.semantic_digest,
        "mediator_implementations": implementations,
    })


class CapabilityMediationDenied(PermissionError):
    def __init__(
        self,
        *,
        rule_id: str,
        reason_code: str,
        stage: CapabilityMediationStage,
        execution_completed: bool = False,
    ) -> None:
        self.rule_id = rule_id
        self.reason_code = reason_code
        self.stage = stage
        self.execution_completed = execution_completed
        self.retry_safe = not execution_completed
        super().__init__(
            "capability mediation denied "
            f"stage={stage.value} rule={rule_id} reason={reason_code}"
        )


@dataclass(slots=True)
class CapabilityRuntimeBinding:
    program: NoetriumUnit
    mediators: CapabilityMediatorRegistryPort
    descriptor: CapabilityDescriptor
    request: CapabilityRequest
    control: ExecutionControlPort
    execute: Callable[[CapabilityRequest, ExecutionControlPort], CapabilityResult]
    current_request: CapabilityRequest | None = None
    result: CapabilityResult | None = None

    def __post_init__(self) -> None:
        if type(self.program) is not NoetriumUnit or not self.program.has_trait(CAPABILITY_PROGRAM_TRAIT):
            raise TypeError("capability runtime binding requires capability-program NoetriumUnit")
        if not isinstance(self.mediators, CapabilityMediatorRegistryPort):
            raise TypeError("capability runtime binding requires mediator registry")
        if not isinstance(self.descriptor, CapabilityDescriptor):
            raise TypeError("capability runtime binding requires descriptor")
        if not isinstance(self.request, CapabilityRequest):
            raise TypeError("capability runtime binding requires request")
        if not isinstance(self.control, ExecutionControlPort):
            raise TypeError("capability runtime binding requires ExecutionControlPort")
        if not callable(self.execute):
            raise TypeError("capability runtime binding execute must be callable")
        capability_mediator_binding_digest(self.program, self.mediators)
        self.current_request = self.request

    @property
    def binding_digest(self) -> str:
        return canonical_digest({
            "capability_program_binding_digest": (
                capability_mediator_binding_digest(
                    self.program,
                    self.mediators,
                )
            ),
            "capability_id": self.descriptor.capability_id,
            "descriptor_digest": self.descriptor.digest(),
        })



@dataclass(frozen=True, slots=True)
class CapabilityProgramBinding:
    """Immutable binding of one mediation program to exact implementations."""

    program: NoetriumUnit
    mediators: CapabilityMediatorRegistryPort

    def __post_init__(self) -> None:
        capability_mediator_binding_digest(self.program, self.mediators)

    @property
    def binding_digest(self) -> str:
        return capability_mediator_binding_digest(self.program, self.mediators)


def capability_program_binding(
    *,
    program_id: str = "runtime.capability",
    version: str = "1",
    rules: tuple[NoetriumUnit, ...] = (),
    mediators: CapabilityMediatorRegistryPort | None = None,
) -> CapabilityProgramBinding:
    """Bind immutable capability rule Units to an exact mediator registry."""

    registry = CapabilityMediatorRegistry() if mediators is None else mediators
    if not isinstance(registry, CapabilityMediatorRegistryPort):
        raise TypeError("capability program binding requires mediator registry")
    return CapabilityProgramBinding(
        capability_program_graph(
            program_id=program_id,
            version=version,
            rules=rules,
        ),
        registry,
    )


def default_capability_program_binding() -> CapabilityProgramBinding:
    return capability_program_binding()

def _apply_stage(
    binding: CapabilityRuntimeBinding,
    stage: CapabilityMediationStage,
) -> tuple[str, ...]:
    request = binding.current_request
    if request is None:
        raise RuntimeError("capability runtime has no current request")
    receipts: list[str] = []
    for rule in capability_rules_for(binding.program, stage, binding.descriptor):
        handler = binding.mediators.resolve(_rule_mediator(rule))
        result = handler(
            CapabilityMediationRequest(
                rule,
                binding.descriptor,
                request,
                binding.result,
            )
        )
        if not isinstance(result, CapabilityMediationResult):
            raise TypeError("capability mediator must return CapabilityMediationResult")
        if result.receipt is not None:
            receipts.append(canonical_digest(result.receipt))
        if result.verdict is CapabilityMediationVerdict.DENY:
            raise CapabilityMediationDenied(
                rule_id=rule.unit_id,
                reason_code=result.reason_code,
                stage=stage,
                execution_completed=(
                    stage is CapabilityMediationStage.POST
                    and binding.result is not None
                ),
            )
        if (
            stage is CapabilityMediationStage.PRE
            and result.request_payload is not None
        ):
            request = CapabilityRequest(
                capability_id=request.capability_id,
                payload=result.request_payload,
                context=request.context,
                idempotency_key=request.idempotency_key,
            )
            binding.current_request = request
    return tuple(receipts)


def _invoke(request: UnitStepContext, binding: object) -> UnitTransition:
    if not isinstance(binding, CapabilityRuntimeBinding):
        raise TypeError("runtime capability invoke requires CapabilityRuntimeBinding")

    try:
        pre_receipts = _apply_stage(binding, CapabilityMediationStage.PRE)
    except CapabilityMediationDenied as exc:
        return UnitTransition.halt(failed=True, value={'denied': True, 'rule_id': exc.rule_id, 'reason_code': exc.reason_code, 'stage': exc.stage.value}, state_delta={'mediation_denied_rule': exc.rule_id, 'mediation_denied_reason': exc.reason_code, 'mediation_denied_stage': exc.stage.value, 'execution_completed': False}, events=({'type': 'runtime_capability_denied', 'rule_id': exc.rule_id, 'reason_code': exc.reason_code, 'stage': exc.stage.value, 'execution_completed': False},))

    current = binding.current_request
    if current is None:
        raise RuntimeError("capability runtime lost current request")
    request_digest = canonical_digest({
        "capability_id": current.capability_id,
        "payload": current.payload,
        "idempotency_key": current.idempotency_key,
        "context": current.context,
    })
    prepared_event = {
        "type": "runtime_capability_prepared",
        "capability_id": current.capability_id,
        "request_digest": request_digest,
        "rule_count": len(pre_receipts),
    }

    binding.control.checkpoint()
    result = binding.execute(current, binding.control)
    binding.control.checkpoint()
    if not isinstance(result, CapabilityResult):
        raise TypeError("capability provider execution must return CapabilityResult")
    binding.result = result
    result_digest = result.digest()
    executed_event = {
        "type": "runtime_capability_executed",
        "capability_id": result.capability_id,
        "result_digest": result_digest,
    }

    try:
        post_receipts = _apply_stage(binding, CapabilityMediationStage.POST)
    except CapabilityMediationDenied as exc:
        return UnitTransition.halt(failed=True, value={'denied': True, 'rule_id': exc.rule_id, 'reason_code': exc.reason_code, 'stage': exc.stage.value, 'result_digest': result_digest}, state_delta={'capability_id': current.capability_id, 'request_digest': request_digest, 'pre_receipt_digests': pre_receipts, 'result_digest': result_digest, 'result_artifacts': result.artifacts, 'mediation_denied_rule': exc.rule_id, 'mediation_denied_reason': exc.reason_code, 'mediation_denied_stage': exc.stage.value, 'execution_completed': True}, events=(prepared_event, executed_event, {'type': 'runtime_capability_denied', 'rule_id': exc.rule_id, 'reason_code': exc.reason_code, 'stage': exc.stage.value, 'execution_completed': True}), artifact_refs=result.artifacts)

    return UnitTransition.goto(value={'result_digest': result_digest, 'capability_id': result.capability_id, 'post_receipt_digests': post_receipts}, state_delta={'capability_id': current.capability_id, 'request_digest': request_digest, 'pre_receipt_digests': pre_receipts, 'result_digest': result_digest, 'result_artifacts': result.artifacts, 'post_receipt_digests': post_receipts}, events=(prepared_event, executed_event, {'type': 'runtime_capability_validated', 'capability_id': result.capability_id, 'result_digest': result_digest, 'rule_count': len(post_receipts)}), artifact_refs=result.artifacts)

def capability_runtime_module(
    program: NoetriumUnit,
    *,
    module_id: str = "runtime.capability",
) -> NoetriumUnit:
    if type(program) is not NoetriumUnit or not program.has_trait(CAPABILITY_PROGRAM_TRAIT):
        raise TypeError("capability runtime module requires capability-program NoetriumUnit")
    return runtime_module(
        module_id=module_id,
        concern=RuntimeConcern.CAPABILITY_MEDIATION,
        entrypoint="invoke",
        nodes=(
            unit_operation(
                "invoke",
                "runtime.capability.invoke",
                configuration={"capability_program_digest": program.semantic_digest},
            ),
        ),
    )


def capability_runtime_operations() -> tuple[UnitOperationBinding, ...]:
    return (
        UnitOperationBinding(
            "runtime.capability.invoke",
            _invoke,
            canonical_digest({
                "operation": "runtime.capability.invoke",
                "implementation_revision": 1,
            }),
        ),
    )


__all__ = [
    "CapabilityMediationDenied",
    "CAPABILITY_PROGRAM_TRAIT",
    "CAPABILITY_RULE_TRAIT",
    "capability_program_graph",
    "capability_program_rules",
    "capability_rule_graph",
    "capability_rules_for",
    "CapabilityMediationRequest",
    "CapabilityMediationResult",
    "CapabilityMediationStage",
    "CapabilityMediationVerdict",
    "CapabilityMediator",
    "CapabilityMediatorRegistry",
    "CapabilityMediatorRegistryPort",
    "CapabilityProgramBinding",
    "default_capability_program_binding",
    "capability_program_binding",
        "CapabilityRuntimeBinding",
    "capability_mediator_binding_digest",
    "capability_runtime_module",
    "capability_runtime_operations",
]
