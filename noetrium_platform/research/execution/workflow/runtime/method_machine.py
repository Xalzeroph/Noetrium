"""Reference runtime for the universal method-machine ABI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import inspect
from threading import RLock
from typing import Any

from noetrium_platform.capabilities.participant.capability.api import CapabilityRequest, CapabilityResult
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    OperationRequest,
    OperationStatus,
    canonical_digest,
    freeze_json,
)

from ..api.method_machine import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodCheckpoint,
    MethodCheckpointStorePort,
    MethodEvent,
    MethodEvidenceStatus,
    MethodEvidencePort,
    MethodGraph,
    MethodInterrupt,
    MethodNodeKind,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodRunResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from .operation_dispatch import MethodNodeOperationAdapter


METHOD_MACHINE_IDENTITY = ComponentIdentity(
    "platform.workflow_runtime",
    "universal_method_machine",
    "1",
    "1",
    "universal-method-machine-v1",
)


class InMemoryMethodCheckpointStore(MethodCheckpointStorePort):
    """Small deterministic store useful for tests and short-lived local runs."""

    durability = "process_local"

    def __init__(self) -> None:
        self._latest: dict[str, MethodCheckpoint] = {}
        self._lock = RLock()

    def save(self, checkpoint: MethodCheckpoint) -> None:
        if not isinstance(checkpoint, MethodCheckpoint):
            raise TypeError("method checkpoint store accepts MethodCheckpoint")
        with self._lock:
            current = self._latest.get(checkpoint.run_id)
            if current is not None and checkpoint.sequence < current.sequence:
                raise ValueError("method checkpoint sequence cannot move backwards")
            if current is not None and checkpoint.sequence == current.sequence and checkpoint.checkpoint_id != current.checkpoint_id:
                raise ValueError("method checkpoint conflict at the same sequence")
            self._latest[checkpoint.run_id] = checkpoint

    def load(self, run_id: str) -> MethodCheckpoint | None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("method checkpoint run_id is required")
        with self._lock:
            return self._latest.get(run_id)


@dataclass(frozen=True, slots=True)
class _ExecutionState:
    current_node: str
    sequence: int
    state: Mapping[str, object]
    previous_value: object
    events: tuple[MethodEvent, ...]
    visit_counts: Mapping[str, int]
    effect_receipts: tuple[EffectReceipt, ...]
    checkpoint_value: object


class UniversalMethodMachine:
    """Execute any bounded agent/research control graph through platform seams.

    Downstream code supplies only ``MethodProgram`` node functions.  The machine
    provides typed capability access, operation provenance, stable idempotency
    keys, interruption, checkpoint/resume, and loop limits.
    """

    def __init__(
        self,
        *,
        checkpoint_store: MethodCheckpointStorePort | None = None,
        max_steps: int = 10_000,
        checkpoint_interval: int = 1,
        target: ComponentIdentity = METHOD_MACHINE_IDENTITY,
    ) -> None:
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("method machine max_steps must be a positive integer")
        if type(checkpoint_interval) is not int or checkpoint_interval < 1:
            raise ValueError("method machine checkpoint_interval must be a positive integer")
        self._checkpoints = checkpoint_store
        self._max_steps = max_steps
        self._checkpoint_interval = checkpoint_interval
        self._target = target

    def run(
        self,
        program: MethodProgram,
        *,
        runtime: MethodRuntimeContext,
        input_value: object = None,
        initial_state: Mapping[str, object] | None = None,
        resume: bool = False,
    ) -> MethodRunResult:
        self._validate_inputs(program, runtime, input_value, initial_state)
        state = self._initial_state(program, runtime, initial_state, resume)
        graph = program.graph
        while state.sequence < self._max_steps:
            node = graph.node(state.current_node)
            visit = state.visit_counts.get(node.node_id, 0)
            if visit >= node.max_visits:
                return self._result(
                    MethodRunStatus.LIMIT_REACHED, program, runtime, state,
                    failure=f"node visit limit reached: {node.node_id}",
                    failure_code="method.node_visit_limit",
                    failure_phase=f"node:{node.node_id}:schedule",
                )
            try:
                request = self._request(program, runtime, input_value, state, node.node_id, visit)
                self._validate_node_input(program, runtime, node, request)
                node_result, operation_effects = self._invoke_sync(program, runtime, node, request, state.sequence)
                self._validate_node_output(runtime, node, node_result)
            except Exception as exc:
                return self._result(
                    MethodRunStatus.FAILED, program, runtime, state,
                    failure=f"{type(exc).__qualname__}: {exc}",
                    failure_code="method.node_execution_failed",
                    failure_phase=f"node:{node.node_id}:invoke",
                )
            if operation_effects and node_result.effect_receipts and operation_effects != node_result.effect_receipts:
                return self._result(
                    MethodRunStatus.FAILED, program, runtime, state,
                    failure="method node effect receipts changed during operation projection",
                )
            try:
                state = self._advance(state, node, node_result, operation_effects)
                self._validate_state(program, runtime, state.state, node.node_id)
            except Exception as exc:
                return self._result(
                    MethodRunStatus.FAILED, program, runtime, state,
                    failure=f"{type(exc).__qualname__}: {exc}",
                    failure_code="method.state_transition_invalid",
                    failure_phase=f"node:{node.node_id}:advance",
                )
            self._publish_events(
                runtime,
                request.context,
                (*node_result.events, MethodEvent(f"node:{node.node_id}", node_result.value)),
            )
            if node_result.interrupt is not None:
                checkpoint = self._save_checkpoint(program, runtime, state, state.current_node)
                return self._result(
                    MethodRunStatus.INTERRUPTED, program, runtime, state,
                    checkpoint=checkpoint, interrupt=node_result.interrupt,
                )
            if self._terminal(node, node_result):
                try:
                    self._validate_program_output(program, runtime, state.previous_value)
                except Exception as exc:
                    return self._result(
                        MethodRunStatus.FAILED, program, runtime, state,
                        failure=f"{type(exc).__qualname__}: {exc}",
                        failure_code="method.output_schema_invalid",
                        failure_phase=f"node:{node.node_id}:output",
                    )
                return self._result(MethodRunStatus.SUCCEEDED, program, runtime, state)
            if self._must_checkpoint(node_result, state.sequence):
                self._save_checkpoint(program, runtime, state, state.current_node)
        checkpoint = self._save_checkpoint(program, runtime, state, state.current_node)
        return self._result(
            MethodRunStatus.LIMIT_REACHED,
            program,
            runtime,
            state,
            checkpoint=checkpoint,
            failure="method step limit reached",
            failure_code="method.step_limit",
            failure_phase="scheduler",
        )

    async def run_async(
        self,
        program: MethodProgram,
        *,
        runtime: MethodRuntimeContext,
        input_value: object = None,
        initial_state: Mapping[str, object] | None = None,
        resume: bool = False,
    ) -> MethodRunResult:
        """Async sibling for model/tool loops; sync handlers remain valid here."""
        self._validate_inputs(program, runtime, input_value, initial_state)
        state = self._initial_state(program, runtime, initial_state, resume)
        while state.sequence < self._max_steps:
            node = program.graph.node(state.current_node)
            visit = state.visit_counts.get(node.node_id, 0)
            if visit >= node.max_visits:
                return self._result(MethodRunStatus.LIMIT_REACHED, program, runtime, state,
                                    failure=f"node visit limit reached: {node.node_id}",
                                    failure_code="method.node_visit_limit",
                                    failure_phase=f"node:{node.node_id}:schedule")
            try:
                request = self._request(program, runtime, input_value, state, node.node_id, visit)
                self._validate_node_input(program, runtime, node, request)
                node_result, operation_effects = await self._invoke_async(program, runtime, node, request, state.sequence)
                self._validate_node_output(runtime, node, node_result)
            except Exception as exc:
                return self._result(MethodRunStatus.FAILED, program, runtime, state,
                                    failure=f"{type(exc).__qualname__}: {exc}",
                                    failure_code="method.node_execution_failed",
                                    failure_phase=f"node:{node.node_id}:invoke")
            try:
                state = self._advance(state, node, node_result, operation_effects)
                self._validate_state(program, runtime, state.state, node.node_id)
            except Exception as exc:
                return self._result(
                    MethodRunStatus.FAILED, program, runtime, state,
                    failure=f"{type(exc).__qualname__}: {exc}",
                    failure_code="method.state_transition_invalid",
                    failure_phase=f"node:{node.node_id}:advance",
                )
            self._publish_events(
                runtime,
                request.context,
                (*node_result.events, MethodEvent(f"node:{node.node_id}", node_result.value)),
            )
            if node_result.interrupt is not None:
                checkpoint = self._save_checkpoint(program, runtime, state, state.current_node)
                return self._result(MethodRunStatus.INTERRUPTED, program, runtime, state,
                                    checkpoint=checkpoint, interrupt=node_result.interrupt)
            if self._terminal(node, node_result):
                try:
                    self._validate_program_output(program, runtime, state.previous_value)
                except Exception as exc:
                    return self._result(
                        MethodRunStatus.FAILED, program, runtime, state,
                        failure=f"{type(exc).__qualname__}: {exc}",
                        failure_code="method.output_schema_invalid",
                        failure_phase=f"node:{node.node_id}:output",
                    )
                return self._result(MethodRunStatus.SUCCEEDED, program, runtime, state)
            if self._must_checkpoint(node_result, state.sequence):
                self._save_checkpoint(program, runtime, state, state.current_node)
        checkpoint = self._save_checkpoint(program, runtime, state, state.current_node)
        return self._result(
            MethodRunStatus.LIMIT_REACHED,
            program,
            runtime,
            state,
            checkpoint=checkpoint,
            failure="method step limit reached",
            failure_code="method.step_limit",
            failure_phase="scheduler",
        )

    @staticmethod
    def _validate_inputs(program: MethodProgram, runtime: MethodRuntimeContext, input_value: object,
                         initial_state: Mapping[str, object] | None) -> None:
        if not isinstance(program, MethodProgram):
            raise TypeError("method machine requires MethodProgram")
        if not isinstance(runtime, MethodRuntimeContext):
            raise TypeError("method machine requires MethodRuntimeContext")
        freeze_json(input_value)
        if initial_state is not None and not isinstance(initial_state, Mapping):
            raise TypeError("method machine initial_state must be a mapping")
        if runtime.schemas is not None:
            runtime.schemas.validate(program.input_schema, input_value, location="method.input")
            runtime.schemas.validate(program.state_schema, initial_state or {}, location="method.initial_state")
        if program.required_capabilities:
            if runtime.capabilities is None:
                raise RuntimeError("method program requires capabilities")
            for capability_id in program.required_capabilities:
                runtime.capabilities.describe(capability_id)

    @staticmethod
    def _validate_node_input(
        program: MethodProgram,
        runtime: MethodRuntimeContext,
        node: object,
        request: MethodNodeRequest,
    ) -> None:
        if runtime.schemas is not None:
            runtime.schemas.validate(
                program.state_schema,
                request.state,
                location=f"method.node.{node.node_id}.state",
            )
            runtime.schemas.validate(
                node.input_schema,
                request.input_value,
                location=f"method.node.{node.node_id}.input",
            )

    @staticmethod
    def _validate_node_output(runtime: MethodRuntimeContext, node: object, result: MethodNodeResult) -> None:
        if runtime.schemas is not None:
            runtime.schemas.validate(
                node.output_schema,
                result.value,
                location=f"method.node.{node.node_id}.output",
            )

    @staticmethod
    def _validate_program_output(
        program: MethodProgram,
        runtime: MethodRuntimeContext,
        value: object,
    ) -> None:
        if runtime.schemas is not None:
            runtime.schemas.validate(program.output_schema, value, location="method.output")

    @staticmethod
    def _validate_state(
        program: MethodProgram,
        runtime: MethodRuntimeContext,
        state: Mapping[str, object],
        node_id: str,
    ) -> None:
        if runtime.schemas is not None:
            runtime.schemas.validate(
                program.state_schema,
                state,
                location=f"method.node.{node_id}.state_update",
            )

    def _initial_state(self, program: MethodProgram, runtime: MethodRuntimeContext,
                       initial_state: Mapping[str, object] | None, resume: bool) -> _ExecutionState:
        if resume and self._checkpoints is None:
            raise ValueError("method resume requires a checkpoint store")
        checkpoint = self._checkpoints.load(runtime.execution.run_id) if resume else None
        if resume and checkpoint is None:
            raise ValueError(f"no method checkpoint found for run: {runtime.execution.run_id}")
        if checkpoint is not None:
            if checkpoint.program_digest != program.program_digest:
                raise ValueError("method checkpoint belongs to a different program")
            for name, checkpoint_value, runtime_value in (
                ("binding_plan_digest", checkpoint.binding_plan_digest, runtime.binding_plan_digest),
                ("runtime_binding_digest", checkpoint.runtime_binding_digest, runtime.runtime_binding_digest),
                ("schema_digest", checkpoint.schema_digest, runtime.schema_digest),
            ):
                if checkpoint_value != runtime_value:
                    raise ValueError(f"method checkpoint {name} does not match runtime")
            visit_counts = dict(checkpoint.visit_counts)
            if not visit_counts:
                visit_counts = self._counts_from_events(checkpoint.events)
            return _ExecutionState(
                checkpoint.next_node or checkpoint.current_node,
                checkpoint.sequence,
                checkpoint.state,
                checkpoint.previous_value,
                checkpoint.events,
                visit_counts,
                checkpoint.effect_receipts,
                checkpoint.checkpoint_value,
            )
        return _ExecutionState(program.graph.entrypoint, 0, freeze_json(initial_state or {}), None, (), {}, (), None)

    def _request(self, program: MethodProgram, runtime: MethodRuntimeContext, input_value: object,
                 state: _ExecutionState, node_id: str, visit: int) -> MethodNodeRequest:
        operation_id = self._operation_id(runtime.execution.run_id, program, node_id, visit)
        context = runtime.execution.child(
            span_id=f"method:{node_id}:{state.sequence}",
            operation_id=operation_id,
            component_id=self._target.component_id,
        )
        return MethodNodeRequest(
            node_id=node_id,
            visit=visit,
            state=state.state,
            input_value=input_value,
            previous_value=state.previous_value,
            context=context,
            capabilities=runtime.capabilities,
            visit_counts=tuple(sorted(state.visit_counts.items())),
            checkpoint=state.checkpoint_value,
        )

    def _invoke_sync(self, program: MethodProgram, runtime: MethodRuntimeContext, node: object,
                     request: MethodNodeRequest, sequence: int) -> tuple[MethodNodeResult, tuple[object, ...]]:
        dispatcher = runtime.dispatcher
        if dispatcher is None:
            node_result = self._invoke_node_body(runtime, node, request)
            return node_result, tuple(node_result.effect_receipts)
        operation_id = self._operation_id(runtime.execution.run_id, program, request.node_id, request.visit)
        payload = {
            "program_digest": program.program_digest,
            "node_id": request.node_id,
            "visit": request.visit,
            "sequence": sequence,
            "input_digest": canonical_digest(request.input_value),
            "state_digest": canonical_digest(request.state),
            "checkpoint_digest": canonical_digest(request.checkpoint),
            "effect_class": node.effect_class.value,
        }
        operation = MethodNodeOperationAdapter(dispatcher).execute(
            root_context=runtime.execution,
            operation_id=operation_id,
            operation_type=node.operation_type,
            target=self._target,
            payload=payload,
            payload_schema="noetrium.method-machine.node.v2",
            handler=lambda _envelope: self._invoke_node_body(runtime, node, request),
            digest_output=True,
            effect_projector=lambda output: tuple(output.effect_receipts),
            idempotency_key=f"method:{program.program_digest}:{request.node_id}:{request.visit}",
        )
        node_result = dispatcher.require(operation)
        if not isinstance(node_result, MethodNodeResult):
            raise TypeError("method node operation must return MethodNodeResult")
        if operation.effect_receipts != node_result.effect_receipts:
            raise RuntimeError("method node operation receipt projection mismatch")
        return node_result, operation.effect_receipts

    async def _invoke_async(self, program: MethodProgram, runtime: MethodRuntimeContext, node: object,
                            request: MethodNodeRequest, sequence: int) -> tuple[MethodNodeResult, tuple[EffectReceipt, ...]]:
        dispatcher = runtime.async_dispatcher
        if dispatcher is None and callable(getattr(runtime.dispatcher, "dispatch_async", None)):
            dispatcher = runtime.dispatcher
        if dispatcher is None:
            if runtime.dispatcher is not None:
                raise RuntimeError("async method execution requires an async operation dispatcher")
            result = await self._invoke_node_body_async(runtime, node, request)
            if not isinstance(result, MethodNodeResult):
                raise TypeError("method node handler must return MethodNodeResult")
            return result, tuple(result.effect_receipts)
        operation_id = self._operation_id(runtime.execution.run_id, program, request.node_id, request.visit)
        payload = {
            "program_digest": program.program_digest,
            "node_id": request.node_id,
            "visit": request.visit,
            "sequence": sequence,
            "input_digest": canonical_digest(request.input_value),
            "state_digest": canonical_digest(request.state),
            "checkpoint_digest": canonical_digest(request.checkpoint),
            "effect_class": node.effect_class.value,
        }
        operation = await MethodNodeOperationAdapter(dispatcher).execute_async(
            root_context=runtime.execution,
            operation_id=operation_id,
            operation_type=node.operation_type,
            target=self._target,
            payload=payload,
            payload_schema="noetrium.method-machine.node.v2",
            handler=lambda _envelope: self._invoke_node_body_async(runtime, node, request),
            digest_output=True,
            effect_projector=lambda output: tuple(output.effect_receipts),
            idempotency_key=f"method:{program.program_digest}:{request.node_id}:{request.visit}",
        )
        require = getattr(dispatcher, "require", None)
        if not callable(require):
            raise TypeError("async operation dispatcher must provide require")
        node_result = require(operation)
        if not isinstance(node_result, MethodNodeResult):
            raise TypeError("method node operation must return MethodNodeResult")
        if operation.effect_receipts != node_result.effect_receipts:
            raise RuntimeError("method node operation receipt projection mismatch")
        return node_result, operation.effect_receipts

    async def _invoke_node_body_async(
        self,
        runtime: MethodRuntimeContext,
        node: object,
        request: MethodNodeRequest,
    ) -> MethodNodeResult:
        if node.kind is MethodNodeKind.AGENT:
            if runtime.agent_loop is None:
                raise RuntimeError("agent node requires MethodRuntimeContext.agent_loop")
            runner = getattr(runtime.agent_loop, "run_async", None)
            if callable(runner):
                result = runner(self._agent_request(node, request))
            else:
                sync_runner = getattr(runtime.agent_loop, "run", None)
                if not callable(sync_runner):
                    raise RuntimeError("async agent execution requires run_async or run")
                result = sync_runner(self._agent_request(node, request))
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, MethodAgentResult):
                raise TypeError("agent loop must return MethodAgentResult")
            return MethodNodeResult(
                value=result.value,
                state_update=result.state_update,
                events=result.events,
                effect_receipts=result.effect_receipts,
                checkpoint=result.checkpoint is not None,
                checkpoint_value=result.checkpoint,
                next_node=result.next_node,
                interrupt=result.interrupt,
            )
        result = self._invoke_node_body(runtime, node, request)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, MethodNodeResult):
            raise TypeError("method node handler must return MethodNodeResult")
        return result

    @staticmethod
    def _agent_request(node: object, request: MethodNodeRequest) -> MethodAgentRequest:
        return MethodAgentRequest(
            agent_id=node.agent_id,
            goal=request.input_value,
            state=request.state,
            input_value=request.input_value,
            previous_value=request.previous_value,
            context=request.context,
            checkpoint=request.checkpoint,
        )

    @staticmethod
    def _invoke_node_body(runtime: MethodRuntimeContext, node: object, request: MethodNodeRequest) -> Any:
        if node.kind is MethodNodeKind.AGENT:
            if runtime.agent_loop is None:
                raise RuntimeError("agent node requires MethodRuntimeContext.agent_loop")
            runner = getattr(runtime.agent_loop, "run", None)
            if not callable(runner):
                raise RuntimeError("synchronous agent execution requires MethodAgentLoopPort.run")
            result = runner(UniversalMethodMachine._agent_request(node, request))
            if inspect.isawaitable(result):
                async def await_agent() -> MethodNodeResult:
                    resolved = await result
                    if not isinstance(resolved, MethodAgentResult):
                        raise TypeError("agent loop must return MethodAgentResult")
                    return MethodNodeResult(
                        value=resolved.value,
                        state_update=resolved.state_update,
                        events=resolved.events,
                        effect_receipts=resolved.effect_receipts,
                        checkpoint=resolved.checkpoint is not None,
                        checkpoint_value=resolved.checkpoint,
                        next_node=resolved.next_node,
                        interrupt=resolved.interrupt,
                    )
                return await_agent()
            if not isinstance(result, MethodAgentResult):
                raise TypeError("agent loop must return MethodAgentResult")
            return MethodNodeResult(
                value=result.value,
                state_update=result.state_update,
                events=result.events,
                effect_receipts=result.effect_receipts,
                checkpoint=result.checkpoint is not None,
                checkpoint_value=result.checkpoint,
                next_node=result.next_node,
                interrupt=result.interrupt,
            )
        if node.kind is MethodNodeKind.CAPABILITY:
            if runtime.capabilities is None:
                raise RuntimeError("capability node requires MethodRuntimeContext.capabilities")
            descriptor = runtime.capabilities.describe(node.capability_id)
            key = f"method:{request.context.run_id}:{request.node_id}:{request.visit}"
            capability_request = CapabilityRequest(
                node.capability_id,
                request.input_value if request.input_value is not None else request.state,
                request.context,
                key if descriptor.effect_class is not EffectClass.PURE else None,
            )
            result = runtime.capabilities.invoke(capability_request)
            if inspect.isawaitable(result):
                async def await_capability() -> MethodNodeResult:
                    resolved = await result
                    if not isinstance(resolved, CapabilityResult):
                        raise TypeError("capability port must return CapabilityResult")
                    effects = () if resolved.effect is None else (resolved.effect,)
                    return MethodNodeResult(value=resolved.payload, effect_receipts=effects)
                return await_capability()
            if not isinstance(result, CapabilityResult):
                raise TypeError("capability port must return CapabilityResult")
            effects = () if result.effect is None else (result.effect,)
            return MethodNodeResult(value=result.payload, effect_receipts=effects)
        if node.kind is MethodNodeKind.CHECKPOINT:
            return MethodNodeResult(value=request.previous_value, checkpoint=True)
        if node.kind is MethodNodeKind.INTERRUPT:
            return MethodNodeResult(
                value=request.previous_value,
                interrupt=MethodInterrupt(
                    f"{request.context.run_id}:{request.node_id}:{request.visit}",
                    request.node_id,
                    request.state,
                ),
            )
        if node.handler is None:
            raise RuntimeError(f"method node has no handler: {node.node_id}")
        result = node.handler(request)
        return result

    @staticmethod
    def _advance(state: _ExecutionState, node: object, result: MethodNodeResult,
                 operation_effects: tuple[EffectReceipt, ...] = ()) -> _ExecutionState:
        merged = dict(state.state)
        merged.update(result.state_update)
        visit_counts = dict(state.visit_counts)
        visit_counts[node.node_id] = visit_counts.get(node.node_id, 0) + 1
        next_node = result.next_node
        if next_node is None and len(node.next_nodes) == 1:
            next_node = node.next_nodes[0]
        if next_node is not None and next_node not in node.next_nodes:
            raise ValueError(f"method node selected non-adjacent next node: {next_node}")
        events = (*state.events, *result.events, MethodEvent(f"node:{node.node_id}", result.value))
        return _ExecutionState(
            next_node or node.node_id,
            state.sequence + 1,
            freeze_json(merged),
            result.value,
            events,
            visit_counts,
            (*state.effect_receipts, *operation_effects),
            result.checkpoint_value if result.checkpoint_value is not None else state.checkpoint_value,
        )

    @staticmethod
    def _terminal(node: object, result: MethodNodeResult) -> bool:
        return node.kind is MethodNodeKind.RETURN or (not node.next_nodes and result.next_node is None)

    def _must_checkpoint(self, result: MethodNodeResult, sequence: int) -> bool:
        return result.checkpoint or sequence % self._checkpoint_interval == 0

    def _save_checkpoint(self, program: MethodProgram, runtime: MethodRuntimeContext,
                         state: _ExecutionState, current_node: str) -> MethodCheckpoint | None:
        if self._checkpoints is None:
            return None
        checkpoint = MethodCheckpoint(
            run_id=runtime.execution.run_id,
            program_digest=program.program_digest,
            sequence=state.sequence,
            current_node=current_node,
            state=state.state,
            previous_value=state.previous_value,
            next_node=state.current_node,
            visit_counts=tuple(sorted(state.visit_counts.items())),
            events=state.events,
            binding_plan_digest=runtime.binding_plan_digest,
            runtime_binding_digest=runtime.runtime_binding_digest,
            schema_digest=runtime.schema_digest,
            effect_receipts=state.effect_receipts,
            evidence_status=self._evidence_status(program, runtime),
            checkpoint_value=state.checkpoint_value,
        )
        self._checkpoints.save(checkpoint)
        if runtime.evidence is not None:
            runtime.evidence.record_checkpoint(checkpoint)
        return checkpoint

    @staticmethod
    def _counts_from_events(events: tuple[MethodEvent, ...]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in events:
            if event.kind.startswith("node:"):
                node_id = event.kind[5:]
                counts[node_id] = counts.get(node_id, 0) + 1
        return counts

    @staticmethod
    def _operation_id(run_id: str, program: MethodProgram, node_id: str, visit: int) -> str:
        return f"method:{run_id}:{program.program_digest[:16]}:{node_id}:{visit}"

    @staticmethod
    def _evidence_obligations(program: MethodProgram) -> tuple[str, ...]:
        obligations = list(program.evidence_obligations)
        for node in program.graph.nodes:
            obligations.extend(node.evidence_obligations)
        return tuple(dict.fromkeys(obligations))

    @staticmethod
    def _evidence_status(
        program: MethodProgram,
        runtime: MethodRuntimeContext,
        result: MethodRunResult | None = None,
    ) -> MethodEvidenceStatus:
        obligations = UniversalMethodMachine._evidence_obligations(program)
        if not obligations:
            return MethodEvidenceStatus.NOT_REQUIRED
        if runtime.evidence is None:
            return MethodEvidenceStatus.INCOMPLETE
        if result is None:
            return MethodEvidenceStatus.UNKNOWN
        validator = getattr(runtime.evidence, "validate_result", None)
        if not callable(validator):
            return MethodEvidenceStatus.UNKNOWN
        try:
            status = validator(result, obligations)
        except Exception:
            return MethodEvidenceStatus.INCOMPLETE
        return status if isinstance(status, MethodEvidenceStatus) else MethodEvidenceStatus.UNKNOWN

    def _result(self, status: MethodRunStatus, program: MethodProgram, runtime: MethodRuntimeContext,
                state: _ExecutionState, *, checkpoint: MethodCheckpoint | None = None,
                interrupt: MethodInterrupt | None = None, failure: str | None = None,
                failure_code: str | None = None, failure_phase: str | None = None) -> MethodRunResult:
        result = MethodRunResult(
            status=status,
            run_id=runtime.execution.run_id,
            program_digest=program.program_digest,
            value=state.previous_value,
            state=state.state,
            events=state.events,
            checkpoint=checkpoint,
            interrupt=interrupt,
            failure=failure,
            effect_receipts=state.effect_receipts,
            step_count=state.sequence,
            visit_counts=tuple(sorted(state.visit_counts.items())),
            evidence_status=MethodEvidenceStatus.UNKNOWN,
            binding_plan_digest=runtime.binding_plan_digest,
            runtime_binding_digest=runtime.runtime_binding_digest,
            schema_digest=runtime.schema_digest,
            failure_code=failure_code,
            failure_phase=failure_phase,
            diagnostics={
                "checkpoint_id": None if checkpoint is None else checkpoint.checkpoint_id,
                "effect_receipt_count": len(state.effect_receipts),
            },
        )
        evidence_status = self._evidence_status(program, runtime, result)
        if evidence_status is not result.evidence_status:
            result = replace(result, evidence_status=evidence_status)
        if runtime.evidence is not None:
            runtime.evidence.record_result(result)
        return result

    @staticmethod
    def _publish_events(
        runtime: MethodRuntimeContext,
        context: object,
        events: tuple[MethodEvent, ...],
    ) -> None:
        if runtime.observation is None:
            return
        for event in events:
            try:
                runtime.observation.publish(event, context)
            except Exception:
                # Observation is a side plane and cannot mutate method truth.
                continue


__all__ = ["InMemoryMethodCheckpointStore", "METHOD_MACHINE_IDENTITY", "UniversalMethodMachine"]
