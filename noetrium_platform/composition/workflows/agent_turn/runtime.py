"""Canonical agent-turn runtime composition.

The ordinary agent-turn path is one runtime layer: operation dispatch, capability
routing, surface binding and trial-program execution. Crash-safe external-effect
state remains isolated in capability_effects because it is a distinct WAL-backed
recovery semantics, not an ordinary routing layer.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.universal import UnitTransition


from noetrium_platform.capabilities.participant.agent.api import AgentTurnResult
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonValue,
    OperationResult,
    ComponentIdentity,
    EffectClass,
    canonical_digest,
    MachineJournalPort,
    MachineSnapshotStorePort,
    canonical_text,
)
from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort
from collections.abc import Callable
from dataclasses import dataclass
from noetrium_platform.capabilities.participant.capability.api import CapabilityDescriptor, CapabilityProviderSession, CapabilityRequest, CapabilityResult, capability_effect_request_id, capability_request_digest
from noetrium_platform.research.execution.operation.api import OperationEffectProfile
from noetrium_platform.research.execution.workflow.api import (
    OperationDispatchPort,
    OperationEffectBinding,
    EffectIntentOperationPort,
    WorkflowParticipantRequirementError,
    WorkflowSurfaceBindingContext,
)
from threading import RLock
from noetrium_platform.capabilities.participant.capability.api import CapabilityDescriptor, CapabilityPort, CapabilityRequest, CapabilityResult
from noetrium_platform.research.execution.capability.api import CapabilityInvocationPipelinePort, CapabilityLifetime, CapabilityRegistration, RegistrationKey, RegistrationScopePort
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from noetrium_platform.capabilities.participant.agent.api import AgentTurnRequest, AgentTurnResult
from noetrium_platform.capabilities.participant.capability.api import CapabilityExportSession
from noetrium_platform.research.execution.capability.api import CapabilityInvocationPipelineFactoryPort, RegistrationScopeFactory
from noetrium_platform.capabilities.participant.core.api import ParticipantSessionBinding
from noetrium_platform.research.execution.capability.runtime import CapabilityInvocationPipelineFactory
from noetrium_platform.research.execution.machines.api import RuntimeConcern, unit_operation, executable_unit
from noetrium_platform.research.execution.workflow.runtime.program_trial import RuntimeProgramTrialProtocol, TrialProgramFrame, TrialProgramOperation, runtime_program_trial_configuration_digest


@runtime_checkable
class AgentTurnOperationPort(Protocol):

    def agent_turn(self, task: object, input_payload: object, context: ExecutionContext, control: ExecutionControlPort) -> tuple[AgentTurnResult, tuple[OperationResult[JsonValue], ...]]:
        ...


@dataclass(frozen=True, slots=True)
class CapabilityInvocationExecution:
    result: CapabilityResult
    operation: OperationResult[JsonValue]


class CapabilityOperationAdapter:
    """Encodes one already-routed capability invocation as a Kernel operation."""

    def __init__(self, dispatcher: OperationDispatchPort) -> None:
        self._dispatcher = dispatcher

    @staticmethod
    def operation_id(request: CapabilityRequest, *, invocation_ordinal: int=0) -> str:
        dc = request.context.decision_cycle_id or request.context.span_id
        if isinstance(request.idempotency_key, str) and request.idempotency_key.strip():
            slot = canonical_digest(request.idempotency_key)[:16]
            return f'{dc}:capability.invoke:{request.capability_id}:key:{slot}'
        if invocation_ordinal <= 0:
            return f'{dc}:capability.invoke:{request.capability_id}'
        return f'{dc}:capability.invoke:{request.capability_id}:call:{invocation_ordinal}'

    def invoke(self, *, target: ComponentIdentity, session: CapabilityProviderSession, descriptor: CapabilityDescriptor, request: CapabilityRequest, control: ExecutionControlPort, invocation_ordinal: int=0, handler: Callable[[CapabilityRequest, ExecutionControlPort], CapabilityResult] | None=None) -> CapabilityInvocationExecution:
        if not isinstance(control, ExecutionControlPort):
            raise TypeError('capability operation requires ExecutionControlPort')
        effect_binding = None
        if descriptor.effect_class is EffectClass.IDEMPOTENT:
            request_id = capability_effect_request_id(request)
            effect_binding = OperationEffectBinding(OperationEffectProfile(descriptor.effect_class.value), request_id, request_id, capability_request_digest(request))

        def invoke_provider(envelope) -> CapabilityResult:
            rebound = CapabilityRequest(envelope.payload.capability_id, envelope.payload.payload, envelope.context, envelope.payload.idempotency_key)
            control.checkpoint()
            result = handler(rebound, control) if handler is not None else session.invoke(rebound, control)
            control.checkpoint()
            if not isinstance(result, CapabilityResult):
                raise TypeError('CapabilityProviderSession invocation must return CapabilityResult')
            if result.capability_id != request.capability_id:
                raise ValueError('capability provider returned mismatched capability_id')
            if descriptor.effect_class is EffectClass.PURE and result.effect is not None:
                raise ValueError('PURE capability returned an external-effect receipt')
            return result
        operation = self._dispatcher.dispatch(root_context=request.context, operation_id=self.operation_id(request, invocation_ordinal=invocation_ordinal), operation_type='capability.invoke', target=target, payload=request, payload_schema=descriptor.request_schema, idempotency_key=request.idempotency_key, effect_binding=effect_binding, effect_projector=lambda output: () if output.effect is None else (output.effect,), handler=invoke_provider)
        result = self._dispatcher.require(operation)
        if not isinstance(result, CapabilityResult):
            raise TypeError('CapabilityProviderSession invocation must return CapabilityResult')
        if result.capability_id != request.capability_id:
            raise ValueError('capability provider returned mismatched capability_id')
        return CapabilityInvocationExecution(result, operation)


class CapabilityNotAvailable(LookupError):
    pass


class CapabilityAmbiguous(RuntimeError):
    pass


class UnsafeGenericCapability(RuntimeError):
    pass


@runtime_checkable
class ContextualCapabilitySessionPort(Protocol):

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        ...

    def session_for(self, context) -> object:
        ...


@dataclass(frozen=True, slots=True)
class CapabilitySessionBinding:
    """Provider-kind-independent exported capability binding."""
    component: ComponentIdentity
    session: object
    source_role: str
    participant: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.component, ComponentIdentity):
            raise TypeError('CapabilitySessionBinding.component must be ComponentIdentity')
        if not self.source_role.strip():
            raise ValueError('CapabilitySessionBinding.source_role must be non-empty')


@dataclass(frozen=True, slots=True)
class CapabilityRoute:
    binding: CapabilitySessionBinding
    descriptor: CapabilityDescriptor


class StudyCapabilityRouter(CapabilityPort):
    """Routes Agent calls by capability identity without exposing provider objects/kinds."""

    def __init__(self, operations: CapabilityOperationAdapter, bindings: tuple[CapabilitySessionBinding, ...], *, effect_executor: CapabilityEffectExecutor | None=None, consumer_component: ComponentIdentity | None=None, pipeline: CapabilityInvocationPipelinePort, scope: RegistrationScopePort) -> None:
        self._operations_adapter = operations
        self._effect_executor = effect_executor
        self._consumer_component = consumer_component
        self._operations: list[OperationResult[JsonValue]] = []
        self._scope = scope
        self._route_contracts: dict[str, CapabilityRegistration[CapabilityRoute]] = {}
        self._register_routes(bindings)
        self._identity_digest = canonical_digest({'router': 'study-capability-router.v1', 'routes': tuple(sorted(((descriptor.capability_id, binding.component, descriptor) for binding in bindings for descriptor in tuple(getattr(binding.session, 'capabilities')))))})
        self._pipeline = pipeline
        self._invocation_counts: dict[str, int] = {}
        self._state_lock = RLock()

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def _register_routes(self, bindings: tuple[CapabilitySessionBinding, ...]) -> None:
        seen: set[str] = set()
        for binding in bindings:
            descriptors = tuple(getattr(binding.session, 'capabilities'))
            for descriptor in descriptors:
                if not isinstance(descriptor, CapabilityDescriptor):
                    raise TypeError('CapabilityExportSession.capabilities must contain CapabilityDescriptor')
                if descriptor.capability_id in seen:
                    raise CapabilityAmbiguous(f'capability is exported by multiple participants: {descriptor.capability_id}')
                seen.add(descriptor.capability_id)
                route = CapabilityRoute(binding, descriptor)
                contract = CapabilityRegistration(RegistrationKey('capability', descriptor.capability_id), CapabilityRoute, owner_id=binding.component.component_id, lifetime=CapabilityLifetime.EXECUTION_SCOPE)
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

    def invoke(self, request: CapabilityRequest, control: ExecutionControlPort) -> CapabilityResult:
        if not isinstance(control, ExecutionControlPort):
            raise TypeError('capability router requires ExecutionControlPort')
        control.checkpoint()
        contract = self._route_contract(request.capability_id)
        try:
            lease = self._scope.acquire_typed(contract)
            with lease as route:
                ordinal = self._ordinal(request.capability_id)
                invocation_id = f'{request.context.decision_cycle_id or request.context.span_id}:{request.capability_id}:{ordinal}'
                if (
                    route.descriptor.effect_class
                    in {EffectClass.RECONCILABLE, EffectClass.NON_IDEMPOTENT}
                    and self._effect_executor is not None
                    and self._consumer_component is not None
                ):
                    self._effect_executor.preflight_new_execution(
                        target=route.binding.component,
                        descriptor=route.descriptor,
                        request=request,
                        control=control,
                        invocation_ordinal=ordinal,
                    )
                return self._pipeline.invoke(invocation_id=invocation_id, descriptor=route.descriptor, request=request, control=control, execute=lambda mediated_request, mediated_control: self._invoke_routed(route.binding, route.descriptor, mediated_request, mediated_control, ordinal))
        except KeyError as exc:
            raise CapabilityNotAvailable(request.capability_id) from exc

    def _invoke_routed(self, binding: CapabilitySessionBinding, descriptor: CapabilityDescriptor, request: CapabilityRequest, control: ExecutionControlPort, ordinal: int) -> CapabilityResult:
        session = binding.session.session_for(request.context) if isinstance(binding.session, ContextualCapabilitySessionPort) else binding.session
        if descriptor.effect_class in (EffectClass.PURE, EffectClass.IDEMPOTENT):
            execution = self._operations_adapter.invoke(target=binding.component, session=session, descriptor=descriptor, request=request, control=control, invocation_ordinal=ordinal)
            with self._state_lock:
                self._operations.append(execution.operation)
            return execution.result
        if self._effect_executor is None or self._consumer_component is None:
            raise UnsafeGenericCapability(f'generic capability {descriptor.capability_id} has {descriptor.effect_class.value} effects; a generic EffectIntentJournal and consumer identity are required')
        execution = self._effect_executor.invoke(target=binding.component, session=session, descriptor=descriptor, request=request, control=control, consumer_component=self._consumer_component, invocation_ordinal=ordinal)
        with self._state_lock:
            self._operations.extend(execution.operation_results)
        return execution.result

    def drain_operations(self) -> tuple[OperationResult[JsonValue], ...]:
        with self._state_lock:
            rows = tuple(self._operations)
            self._operations.clear()
            return rows

    def close(self) -> None:
        """Dispose only the registration scope owned by this routing view.

        Dispatcher, capability sessions and the effect executor are injected shared
        authorities. Their lifecycle belongs to the composition that created them,
        never to a per-turn router.
        """
        self._scope.dispose()


if TYPE_CHECKING:
    from .capability_effects import CapabilityEffectExecutor

    from noetrium_platform.research.execution.machines.capability_program import CapabilityProgramBinding


class AgentTurnTrialOperations:
    """Agent+Capability operation surface only; no Method/Environment action dependencies."""

    def __init__(self, dispatcher: OperationDispatchPort, participant_sessions: tuple[ParticipantSessionBinding, ...], *, effect_dispatcher: OperationDispatchPort | None=None, effect_intents: EffectIntentOperationPort | None=None, capability_pipeline_factory: CapabilityInvocationPipelineFactoryPort, registration_scope_factory: RegistrationScopeFactory, capability_program: 'CapabilityProgramBinding | None'=None) -> None:
        from .capability_effects import CapabilityEffectExecutor
        self._dispatcher = dispatcher
        agent = next((row for row in participant_sessions if row.participant.role == 'agent'), None)
        if agent is None:
            raise WorkflowParticipantRequirementError('agent_turn workflow requires participant role: agent')
        self._agent = agent
        self._capability_sessions = tuple((CapabilitySessionBinding(row.participant.component, row.session, source_role=row.participant.role, participant=row.participant) for row in participant_sessions if isinstance(row.session, CapabilityExportSession)))
        effect_operation_dispatcher = effect_dispatcher or dispatcher
        self._capability_operations = CapabilityOperationAdapter(effect_operation_dispatcher)
        self._capability_pipeline_factory = capability_pipeline_factory
        self._registration_scope_factory = registration_scope_factory
        self._capability_program = capability_program
        self._capability_effects = CapabilityEffectExecutor(dispatcher, effect_intents, self._capability_operations) if effect_intents is not None else None

    @staticmethod
    def _dc(context: ExecutionContext) -> str:
        return context.decision_cycle_id or context.span_id

    def agent_turn(self, task: object, input_payload: object, context: ExecutionContext, control: ExecutionControlPort) -> tuple[AgentTurnResult, tuple[OperationResult[JsonValue], ...]]:
        if not isinstance(control, ExecutionControlPort):
            raise TypeError('agent turn requires ExecutionControlPort')
        control.checkpoint()
        router = StudyCapabilityRouter(self._capability_operations, self._capability_sessions, effect_executor=self._capability_effects, consumer_component=self._agent.participant.component, pipeline=self._capability_pipeline_factory.create(self._capability_program), scope=self._registration_scope_factory(f'decision-cycle:{self._dc(context)}:capabilities'))
        dc = self._dc(context)
        request = AgentTurnRequest(task, context, input_payload)
        try:
            operation = self._dispatcher.dispatch(root_context=context, operation_id=f'{dc}:agent.run_turn', operation_type='agent.run_turn', target=self._agent.participant.component, payload=request, payload_schema='agent.turn.request.v1', handler=lambda envelope: self._agent.session.run_turn(AgentTurnRequest(envelope.payload.task, envelope.context, envelope.payload.input_payload), router, control))
            result = self._dispatcher.require(operation)
            if not isinstance(result, AgentTurnResult):
                raise TypeError('AgentSession.run_turn must return AgentTurnResult')
            return (result, router.drain_operations() + (operation,))
        finally:
            router.close()


class AgentTurnSurfaceFactory:
    surface_id = 'agent_turn.operations.v1'
    reuse_scope = 'run'

    def __init__(self, registration_scope_factory: RegistrationScopeFactory) -> None:
        self._registration_scope_factory = registration_scope_factory

    def bind(self, context: WorkflowSurfaceBindingContext) -> AgentTurnTrialOperations:
        if context.machine_journal is None:
            raise RuntimeError('agent-turn surface requires shared MachineJournal authority')
        capability_pipeline_factory = CapabilityInvocationPipelineFactory(context.machine_journal, snapshot_store=context.machine_snapshot_store)
        return AgentTurnTrialOperations(context.dispatcher, context.participant_sessions, effect_dispatcher=context.effect_dispatcher, effect_intents=context.effect_intents, capability_pipeline_factory=capability_pipeline_factory, registration_scope_factory=self._registration_scope_factory)


AGENT_TURN_TRIAL_PROGRAM = executable_unit(
    "workflow.agent-turn",
    domain="runtime",
    version="2",
    state_schema="workflow.agent-turn.state.v2",
    entrypoint="turn",
    members=(unit_operation(
        "turn",
        "workflow.agent-turn.execute",
        configuration={"runtime_concern": RuntimeConcern.TURN.value},
    ),),
)


def _execute_agent_turn(request, surface: object, frame: TrialProgramFrame) -> UnitTransition:
    if not isinstance(surface, AgentTurnOperationPort):
        raise TypeError('agent-turn Program requires AgentTurnOperationPort')
    result, rows = surface.agent_turn(frame.task, {'input_kind': frame.input_kind, 'payload': frame.input_payload}, frame.context, frame.control)
    frame.operation_results.extend(rows)
    if result.agent_generation is not None:
        frame.context = frame.context.with_generation('agent', result.agent_generation)
    frame.context_text = canonical_text(result.output)
    frame.primary_result = result
    result_digest = canonical_digest({'output': result.output, 'agent_generation': result.agent_generation})
    return UnitTransition.goto(value={'result_digest': result_digest, 'agent_generation': result.agent_generation}, state_delta={'result_digest': result_digest, 'agent_generation': result.agent_generation, 'operation_ids': tuple((row.operation_id for row in rows))}, events=({'type': 'agent_turn_completed', 'result_digest': result_digest, 'operation_ids': tuple((row.operation_id for row in rows))},))


_AGENT_TURN_OPERATIONS = (TrialProgramOperation('workflow.agent-turn.execute', _execute_agent_turn, canonical_digest({'operation': 'workflow.agent-turn.execute', 'implementation_revision': 2})),)


AGENT_TURN_TRIAL_CONFIGURATION_DIGEST = runtime_program_trial_configuration_digest(program=AGENT_TURN_TRIAL_PROGRAM, surface_id='agent_turn.operations.v1', max_steps=None, operations=_AGENT_TURN_OPERATIONS)


def agent_turn_trial_protocol(*, journal: MachineJournalPort, snapshot_store: MachineSnapshotStorePort | None=None) -> RuntimeProgramTrialProtocol:
    return RuntimeProgramTrialProtocol(protocol_id='agent_turn.v2', surface_id='agent_turn.operations.v1', program=AGENT_TURN_TRIAL_PROGRAM, operations=_AGENT_TURN_OPERATIONS, max_steps=None, journal=journal, snapshot_store=snapshot_store)


__all__ = [
    "AgentTurnOperationPort",
    "CapabilityInvocationExecution",
    "CapabilityOperationAdapter",
    "CapabilityNotAvailable",
    "CapabilityAmbiguous",
    "UnsafeGenericCapability",
    "ContextualCapabilitySessionPort",
    "CapabilitySessionBinding",
    "CapabilityRoute",
    "StudyCapabilityRouter",
    "AgentTurnTrialOperations",
    "AgentTurnSurfaceFactory",
    "AGENT_TURN_TRIAL_CONFIGURATION_DIGEST",
    "AGENT_TURN_TRIAL_PROGRAM",
    "agent_turn_trial_protocol",
]
