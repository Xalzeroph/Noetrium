from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityPort,
    CapabilityPolicySet,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.research.execution.capability.api import (
    CapabilityInvocationPipelinePort,
    CapabilityLifetime,
    CapabilityRegistration,
    RegistrationKey,
    RegistrationScopePort,
)
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, EffectClass, JsonValue, OperationResult

from .capability_effects import CapabilityEffectExecutor
from .capability_operations import CapabilityOperationAdapter


class CapabilityNotAvailable(LookupError):
    pass


class CapabilityAmbiguous(RuntimeError):
    pass


class UnsafeGenericCapability(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilitySessionBinding:
    """Provider-kind-independent exported capability binding."""

    component: ComponentIdentity
    session: object
    source_role: str
    participant: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, ComponentIdentity):
            raise TypeError("CapabilitySessionBinding.component must be ComponentIdentity")
        if not self.source_role.strip():
            raise ValueError("CapabilitySessionBinding.source_role must be non-empty")


@dataclass(frozen=True, slots=True)
class CapabilityRoute:
    binding: CapabilitySessionBinding
    descriptor: CapabilityDescriptor


class StudyCapabilityRouter(CapabilityPort):
    """Routes Agent calls by capability identity without exposing provider objects/kinds."""

    def __init__(
        self,
        operations: CapabilityOperationAdapter,
        bindings: tuple[CapabilitySessionBinding, ...],
        *,
        effect_executor: CapabilityEffectExecutor | None = None,
        consumer_component: ComponentIdentity | None = None,
        pipeline: CapabilityInvocationPipelinePort,
        scope: RegistrationScopePort,
    ) -> None:
        self._operations_adapter = operations
        self._effect_executor = effect_executor
        self._consumer_component = consumer_component
        self._operations: list[OperationResult[JsonValue]] = []
        self._scope = scope
        self._route_contracts: dict[str, CapabilityRegistration[CapabilityRoute]] = {}
        self._register_routes(bindings)
        self._pipeline = pipeline
        self._invocation_counts: dict[str, int] = {}
        self._state_lock = RLock()

    def _register_routes(self, bindings: tuple[CapabilitySessionBinding, ...]) -> None:
        seen: set[str] = set()
        for binding in bindings:
            descriptors = tuple(getattr(binding.session, "capabilities"))
            for descriptor in descriptors:
                if not isinstance(descriptor, CapabilityDescriptor):
                    raise TypeError("CapabilityExportSession.capabilities must contain CapabilityDescriptor")
                if descriptor.capability_id in seen:
                    raise CapabilityAmbiguous(
                        f"capability is exported by multiple participants: {descriptor.capability_id}"
                    )
                seen.add(descriptor.capability_id)
                route = CapabilityRoute(binding, descriptor)
                contract = CapabilityRegistration(
                    RegistrationKey("capability", descriptor.capability_id),
                    CapabilityRoute,
                    owner_id=binding.component.component_id,
                    lifetime=CapabilityLifetime.EXECUTION_SCOPE,
                )
                self._route_contracts[descriptor.capability_id] = contract
                self._scope.register_typed(contract, route)

    def _route_contract(self, capability_id: str) -> CapabilityRegistration[CapabilityRoute]:
        contract = self._route_contracts.get(capability_id)
        if contract is None:
            raise CapabilityNotAvailable(capability_id)
        return contract

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        contract = self._route_contract(capability_id)
        try:
            with self._scope.acquire_typed(contract) as route:
                return route.descriptor
        except KeyError as exc:
            raise CapabilityNotAvailable(capability_id) from exc

    def _ordinal(self, capability_id: str) -> int:
        with self._state_lock:
            current = self._invocation_counts.get(capability_id, 0)
            self._invocation_counts[capability_id] = current + 1
            return current

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        contract = self._route_contract(request.capability_id)
        try:
            lease = self._scope.acquire_typed(contract)
            with lease as route:
                ordinal = self._ordinal(request.capability_id)
                invocation_id = (
                    f"{request.context.decision_cycle_id or request.context.span_id}:"
                    f"{request.capability_id}:{ordinal}"
                )
                return self._pipeline.invoke(
                    invocation_id=invocation_id,
                    descriptor=route.descriptor,
                    request=request,
                    execute=lambda mediated_request: self._invoke_routed(
                        route.binding,
                        route.descriptor,
                        mediated_request,
                        ordinal,
                    ),
                )
        except KeyError as exc:
            raise CapabilityNotAvailable(request.capability_id) from exc

    def _invoke_routed(
        self,
        binding: CapabilitySessionBinding,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        ordinal: int,
    ) -> CapabilityResult:
        if descriptor.effect_class in (EffectClass.PURE, EffectClass.IDEMPOTENT):
            execution = self._operations_adapter.invoke(
                target=binding.component,
                session=binding.session,
                descriptor=descriptor,
                request=request,
                invocation_ordinal=ordinal,
            )
            with self._state_lock:
                self._operations.append(execution.operation)
            return execution.result
        if self._effect_executor is None or self._consumer_component is None:
            raise UnsafeGenericCapability(
                f"generic capability {descriptor.capability_id} has {descriptor.effect_class.value} effects; "
                "a generic EffectIntentJournal and consumer identity are required"
            )
        execution = self._effect_executor.invoke(
            target=binding.component,
            session=binding.session,
            descriptor=descriptor,
            request=request,
            consumer_component=self._consumer_component,
            invocation_ordinal=ordinal,
        )
        with self._state_lock:
            self._operations.extend(execution.operation_results)
        return execution.result

    def drain_operations(self) -> tuple[OperationResult[JsonValue], ...]:
        with self._state_lock:
            rows = tuple(self._operations)
            self._operations.clear()
            return rows

    def close(self) -> None:
        self._scope.dispose()


__all__ = [
    "CapabilityAmbiguous",
    "CapabilityNotAvailable",
    "CapabilityRoute",
    "CapabilitySessionBinding",
    "StudyCapabilityRouter",
    "UnsafeGenericCapability",
]
