"""Programmable capability mediation executed inside RuntimeMachine.

Capability mechanics (provider lookup, effect WAL, reconciliation) remain
outside this module. This IR owns only paper-variable execution semantics:
pre-invocation guards/approval, request transformation, post-validation and
the ordering of those steps.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.capabilities.participant.capability.api.policy import (
    CapabilityPolicySet,
    GuardVerdict,
)
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
from .program import ProgramNodeRequest, ProgramNodeResult
from .program_host import ResearchHostOperation
from .runtime_module import RuntimeModule, RuntimeModuleBuilder


class CapabilityMediationStage(StrEnum):
    PRE = "pre"
    POST = "post"


class CapabilityMediationVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class CapabilityRuleProgram:
    rule_id: str
    stage: CapabilityMediationStage
    mediator: str
    priority: int = 0
    capability_ids: tuple[str, ...] = ()
    effect_classes: tuple[EffectClass, ...] = ()
    required: bool = False
    configuration: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("rule_id", self.rule_id),
            ("mediator", self.mediator),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"capability rule {name} is required")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.stage, CapabilityMediationStage):
            raise TypeError("capability rule stage must be CapabilityMediationStage")
        if type(self.priority) is not int:
            raise TypeError("capability rule priority must be integer")
        if type(self.capability_ids) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.capability_ids
        ):
            raise TypeError("capability rule capability_ids must be text tuple")
        if len(self.capability_ids) != len(set(self.capability_ids)):
            raise ValueError("capability rule capability_ids must be unique")
        if type(self.effect_classes) is not tuple or any(
            not isinstance(value, EffectClass) for value in self.effect_classes
        ):
            raise TypeError("capability rule effect_classes must be EffectClass tuple")
        if type(self.required) is not bool:
            raise TypeError("capability rule required must be boolean")
        if not isinstance(self.configuration, Mapping):
            raise TypeError("capability rule configuration must be an object")
        object.__setattr__(self, "configuration", freeze_json(self.configuration))

    def matches(self, descriptor: CapabilityDescriptor) -> bool:
        if not isinstance(descriptor, CapabilityDescriptor):
            raise TypeError("capability rule matching requires CapabilityDescriptor")
        if self.capability_ids and descriptor.capability_id not in self.capability_ids:
            return False
        if self.effect_classes and descriptor.effect_class not in self.effect_classes:
            return False
        return True


@dataclass(frozen=True, slots=True)
class CapabilityProgram:
    program_id: str
    version: str
    rules: tuple[CapabilityRuleProgram, ...]
    program_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("program_id", self.program_id),
            ("version", self.version),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"capability program {name} is required")
            object.__setattr__(self, name, value.strip())
        if type(self.rules) is not tuple:
            raise TypeError("capability program rules must be a tuple")
        if any(not isinstance(rule, CapabilityRuleProgram) for rule in self.rules):
            raise TypeError("capability program rules must be CapabilityRuleProgram values")
        ids = tuple(rule.rule_id for rule in self.rules)
        if len(ids) != len(set(ids)):
            raise ValueError("capability program rule ids must be unique")
        object.__setattr__(
            self,
            "program_digest",
            canonical_digest({
                "program_id": self.program_id,
                "version": self.version,
                "rules": tuple({
                    "rule_id": rule.rule_id,
                    "stage": rule.stage.value,
                    "mediator": rule.mediator,
                    "priority": rule.priority,
                    "capability_ids": rule.capability_ids,
                    "effect_classes": tuple(value.value for value in rule.effect_classes),
                    "required": rule.required,
                    "configuration": thaw_json(rule.configuration),
                } for rule in self.rules),
            }),
        )

    def rules_for(
        self,
        stage: CapabilityMediationStage,
        descriptor: CapabilityDescriptor,
    ) -> tuple[CapabilityRuleProgram, ...]:
        if not isinstance(stage, CapabilityMediationStage):
            raise TypeError("capability stage must be CapabilityMediationStage")
        rows = tuple(
            rule
            for rule in self.rules
            if rule.stage is stage and rule.matches(descriptor)
        )
        return tuple(sorted(rows, key=lambda rule: (-rule.priority, rule.rule_id)))


@dataclass(frozen=True, slots=True)
class CapabilityMediationRequest:
    rule: CapabilityRuleProgram
    descriptor: CapabilityDescriptor
    request: CapabilityRequest
    result: CapabilityResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rule, CapabilityRuleProgram):
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
            return canonical_digest(tuple(
                (mediator, implementation_digest)
                for mediator, (_, implementation_digest)
                in sorted(self._handlers.items())
            ))


def capability_mediator_binding_digest(
    program: CapabilityProgram,
    mediators: CapabilityMediatorRegistryPort,
) -> str:
    """Bind a pure CapabilityProgram to exact mediator implementations."""

    if not isinstance(program, CapabilityProgram):
        raise TypeError("capability mediator binding requires CapabilityProgram")
    if not isinstance(mediators, CapabilityMediatorRegistryPort):
        raise TypeError(
            "capability mediator binding requires CapabilityMediatorRegistryPort"
        )
    require_sha256(
        mediators.identity_digest,
        "capability mediator registry identity_digest",
    )
    mediator_ids = tuple(sorted({rule.mediator for rule in program.rules}))
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
        "capability_program_digest": program.program_digest,
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
    program: CapabilityProgram
    mediators: CapabilityMediatorRegistryPort
    descriptor: CapabilityDescriptor
    request: CapabilityRequest
    execute: Callable[[CapabilityRequest], CapabilityResult]
    current_request: CapabilityRequest | None = None
    result: CapabilityResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.program, CapabilityProgram):
            raise TypeError("capability runtime binding requires CapabilityProgram")
        if not isinstance(self.mediators, CapabilityMediatorRegistryPort):
            raise TypeError("capability runtime binding requires mediator registry")
        if not isinstance(self.descriptor, CapabilityDescriptor):
            raise TypeError("capability runtime binding requires descriptor")
        if not isinstance(self.request, CapabilityRequest):
            raise TypeError("capability runtime binding requires request")
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



def capability_program_from_policy(
    policy: CapabilityPolicySet | None,
    *,
    program_id: str = "runtime.capability.policy",
    version: str = "1",
) -> tuple[CapabilityProgram, CapabilityMediatorRegistry]:
    """Compile the legacy policy object into RuntimeMachine program semantics."""

    selected = CapabilityPolicySet() if policy is None else policy
    if not isinstance(selected, CapabilityPolicySet):
        raise TypeError("capability policy preset must be CapabilityPolicySet")

    rules: list[CapabilityRuleProgram] = []
    registry = CapabilityMediatorRegistry()

    for index, guard in enumerate(selected.guards):
        mediator_id = f"capability.guard:{index}:{guard.guard_id}"
        rules.append(
            CapabilityRuleProgram(
                rule_id=f"guard:{index}:{guard.guard_id}",
                stage=CapabilityMediationStage.PRE,
                mediator=mediator_id,
                priority=10_000 - index,
                required=True,
            )
        )

        def guard_handler(
            request: CapabilityMediationRequest,
            *,
            _guard=guard,
        ) -> CapabilityMediationResult:
            decision = _guard.evaluate(request.descriptor, request.request)
            if decision.guard_id != _guard.guard_id:
                raise ValueError("capability guard returned mismatched guard_id")
            if decision.verdict is GuardVerdict.DENY:
                return CapabilityMediationResult(
                    verdict=CapabilityMediationVerdict.DENY,
                    reason_code=decision.reason_code,
                    receipt={
                        "guard_id": decision.guard_id,
                        "verdict": decision.verdict.value,
                        "reason_code": decision.reason_code,
                    },
                )
            return CapabilityMediationResult(
                receipt={
                    "guard_id": decision.guard_id,
                    "verdict": decision.verdict.value,
                    "reason_code": decision.reason_code,
                }
            )

        registry.register(
            mediator_id,
            guard_handler,
            implementation_digest=guard.implementation_digest,
        )

    if selected.approval is not None:
        mediator_id = (
            f"capability.approval:{selected.approval.approval_id}"
        )
        rules.append(
            CapabilityRuleProgram(
                rule_id=f"approval:{selected.approval.approval_id}",
                stage=CapabilityMediationStage.PRE,
                mediator=mediator_id,
                priority=0,
                required=True,
            )
        )

        def approval_handler(
            request: CapabilityMediationRequest,
        ) -> CapabilityMediationResult:
            if not selected.approval.approve(
                request.descriptor,
                request.request,
            ):
                return CapabilityMediationResult(
                    verdict=CapabilityMediationVerdict.DENY,
                    reason_code="approval_denied",
                    receipt={"approved": False},
                )
            return CapabilityMediationResult(
                receipt={"approved": True}
            )

        registry.register(
            mediator_id,
            approval_handler,
            implementation_digest=selected.approval.implementation_digest,
        )

    for index, post in enumerate(selected.post_policies):
        mediator_id = f"capability.post:{index}:{post.policy_id}"
        rules.append(
            CapabilityRuleProgram(
                rule_id=f"post:{index}:{post.policy_id}",
                stage=CapabilityMediationStage.POST,
                mediator=mediator_id,
                priority=10_000 - index,
                required=True,
            )
        )

        def post_handler(
            request: CapabilityMediationRequest,
            *,
            _post=post,
        ) -> CapabilityMediationResult:
            if request.result is None:
                raise RuntimeError("post-policy requires capability result")
            try:
                _post.validate(
                    request.descriptor,
                    request.request,
                    request.result,
                )
            except Exception:
                return CapabilityMediationResult(
                    verdict=CapabilityMediationVerdict.DENY,
                    reason_code=f"post_policy:{_post.policy_id}",
                    receipt={
                        "policy_id": _post.policy_id,
                        "validated": False,
                    },
                )
            return CapabilityMediationResult(
                receipt={
                    "policy_id": _post.policy_id,
                    "validated": True,
                }
            )

        registry.register(
            mediator_id,
            post_handler,
            implementation_digest=post.implementation_digest,
        )

    return (
        CapabilityProgram(
            program_id=program_id,
            version=version,
            rules=tuple(rules),
        ),
        registry,
    )

def _apply_stage(
    binding: CapabilityRuntimeBinding,
    stage: CapabilityMediationStage,
) -> tuple[str, ...]:
    request = binding.current_request
    if request is None:
        raise RuntimeError("capability runtime has no current request")
    receipts: list[str] = []
    for rule in binding.program.rules_for(stage, binding.descriptor):
        handler = binding.mediators.resolve(rule.mediator)
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
                rule_id=rule.rule_id,
                reason_code=result.reason_code,
                stage=stage,
                execution_completed=(
                    stage is CapabilityMediationStage.POST
                    and binding.result is not None
                ),
            )
        if stage is CapabilityMediationStage.PRE and result.request_payload is not None:
            request = CapabilityRequest(
                capability_id=request.capability_id,
                payload=result.request_payload,
                context=request.context,
                idempotency_key=request.idempotency_key,
            )
            binding.current_request = request
    return tuple(receipts)


def _pre(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    if not isinstance(binding, CapabilityRuntimeBinding):
        raise TypeError("runtime capability pre requires CapabilityRuntimeBinding")
    try:
        receipts = _apply_stage(binding, CapabilityMediationStage.PRE)
    except CapabilityMediationDenied as exc:
        return ProgramNodeResult(
            value={
                "denied": True,
                "rule_id": exc.rule_id,
                "reason_code": exc.reason_code,
                "stage": exc.stage.value,
            },
            state_update={
                "mediation_denied_rule": exc.rule_id,
                "mediation_denied_reason": exc.reason_code,
                "mediation_denied_stage": exc.stage.value,
                "execution_completed": False,
            },
            status=MachineStatus.FAILED,
            events=({
                "type": "runtime_capability_denied",
                "rule_id": exc.rule_id,
                "reason_code": exc.reason_code,
                "stage": exc.stage.value,
                "execution_completed": False,
            },),
        )
    current = binding.current_request
    if current is None:
        raise RuntimeError("capability runtime lost current request")
    request_digest = canonical_digest({
        "capability_id": current.capability_id,
        "payload": current.payload,
        "idempotency_key": current.idempotency_key,
        "context": current.context,
    })
    return ProgramNodeResult(
        value={"request_digest": request_digest},
        state_update={
            "capability_id": current.capability_id,
            "request_digest": request_digest,
            "pre_receipt_digests": receipts,
        },
        events=({
            "type": "runtime_capability_prepared",
            "capability_id": current.capability_id,
            "request_digest": request_digest,
            "rule_count": len(receipts),
        },),
    )


def _execute(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    if not isinstance(binding, CapabilityRuntimeBinding):
        raise TypeError("runtime capability execute requires CapabilityRuntimeBinding")
    current = binding.current_request
    if current is None:
        raise RuntimeError("capability runtime has no current request")
    result = binding.execute(current)
    if not isinstance(result, CapabilityResult):
        raise TypeError("capability provider execution must return CapabilityResult")
    binding.result = result
    return ProgramNodeResult(
        value={
            "result_digest": result.digest(),
            "capability_id": result.capability_id,
        },
        state_update={
            "result_digest": result.digest(),
            "result_artifacts": result.artifacts,
        },
        events=({
            "type": "runtime_capability_executed",
            "capability_id": result.capability_id,
            "result_digest": result.digest(),
        },),
        artifact_refs=result.artifacts,
    )


def _post(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
    if not isinstance(binding, CapabilityRuntimeBinding):
        raise TypeError("runtime capability post requires CapabilityRuntimeBinding")
    if binding.result is None:
        raise RuntimeError("capability post mediation requires provider result")
    try:
        receipts = _apply_stage(binding, CapabilityMediationStage.POST)
    except CapabilityMediationDenied as exc:
        return ProgramNodeResult(
            value={
                "denied": True,
                "rule_id": exc.rule_id,
                "reason_code": exc.reason_code,
                "stage": exc.stage.value,
            },
            state_update={
                "mediation_denied_rule": exc.rule_id,
                "mediation_denied_reason": exc.reason_code,
                "mediation_denied_stage": exc.stage.value,
                "execution_completed": True,
            },
            status=MachineStatus.FAILED,
            events=({
                "type": "runtime_capability_denied",
                "rule_id": exc.rule_id,
                "reason_code": exc.reason_code,
                "stage": exc.stage.value,
                "execution_completed": True,
            },),
            artifact_refs=binding.result.artifacts,
        )
    return ProgramNodeResult(
        value={
            "result_digest": binding.result.digest(),
            "post_receipt_digests": receipts,
        },
        state_update={"post_receipt_digests": receipts},
        events=({
            "type": "runtime_capability_validated",
            "capability_id": binding.result.capability_id,
            "result_digest": binding.result.digest(),
            "rule_count": len(receipts),
        },),
    )


def capability_runtime_module(
    program: CapabilityProgram,
    *,
    module_id: str = "runtime.capability",
) -> RuntimeModule:
    if not isinstance(program, CapabilityProgram):
        raise TypeError("capability runtime module requires CapabilityProgram")
    return (
        RuntimeModuleBuilder.capability(module_id=module_id, entrypoint="pre")
        .node(
            "pre",
            "runtime.capability.pre",
            configuration={"capability_program_digest": program.program_digest},
            next_node="execute",
        )
        .node(
            "execute",
            "runtime.capability.execute",
            configuration={"capability_program_digest": program.program_digest},
            next_node="post",
        )
        .node(
            "post",
            "runtime.capability.post",
            configuration={"capability_program_digest": program.program_digest},
        )
        .build()
    )


def capability_runtime_operations() -> tuple[ResearchHostOperation, ...]:
    return (
        ResearchHostOperation(
            "runtime.capability.pre",
            _pre,
            canonical_digest({
                "operation": "runtime.capability.pre",
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "runtime.capability.execute",
            _execute,
            canonical_digest({
                "operation": "runtime.capability.execute",
                "implementation_revision": 1,
            }),
        ),
        ResearchHostOperation(
            "runtime.capability.post",
            _post,
            canonical_digest({
                "operation": "runtime.capability.post",
                "implementation_revision": 1,
            }),
        ),
    )


__all__ = [
    "CapabilityMediationDenied",
    "CapabilityMediationRequest",
    "CapabilityMediationResult",
    "CapabilityMediationStage",
    "CapabilityMediationVerdict",
    "CapabilityMediator",
    "CapabilityMediatorRegistry",
    "CapabilityMediatorRegistryPort",
    "CapabilityProgram",
    "CapabilityRuleProgram",
    "CapabilityRuntimeBinding",
    "capability_mediator_binding_digest",
    "capability_program_from_policy",
    "capability_runtime_module",
    "capability_runtime_operations",
]
