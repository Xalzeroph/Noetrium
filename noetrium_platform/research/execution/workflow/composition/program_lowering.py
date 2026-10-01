"""Lossless MethodProgram lowering onto the single ResearchProgram Machine interpreter."""

from __future__ import annotations

from dataclasses import asdict, replace
import inspect
from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.api import CapabilityRequest, CapabilityResult
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    MachineKind,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.research.execution.policy.api import (
    ExecutionBudgetDelta,
    ExecutionBudgetExceeded,
)
from noetrium_platform.research.execution.machines import (
    ProgramNode,
    ProgramNodeRequest,
    ProgramNodeResult,
    ResearchHostOperation,
    ResearchProgram,
)
from noetrium_platform.research.execution.workflow.api.method_machine import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodEvent,
    MethodInterrupt,
    MethodNodeKind,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodRuntimeContext,
)

METHOD_PROGRAM_ADAPTER_VERSION = 3
METHOD_PROGRAM_TARGET = ComponentIdentity(
    "platform.workflow_runtime",
    "method_program_adapter",
    "1",
    "1",
    "method-program-adapter-v1",
)


def lower_method_program(program: MethodProgram) -> ResearchProgram:
    if not isinstance(program, MethodProgram):
        raise TypeError("method lowering requires MethodProgram")
    nodes = []
    for node in program.graph.nodes:
        required = ()
        if node.kind is MethodNodeKind.CAPABILITY and node.capability_id is not None:
            required = (node.capability_id,)
        nodes.append(
            ProgramNode(
                node_id=node.node_id,
                operation=f"method.node.{node.node_id}",
                configuration={
                    "method_program_digest": program.program_digest,
                    "method_operation_type": node.operation_type,
                    "method_node_kind": node.kind.value,
                    "input_schema": node.input_schema,
                    "output_schema": node.output_schema,
                    "effect_class": node.effect_class.value,
                    "evidence_obligations": node.evidence_obligations,
                    "implementation_digest": node.implementation_digest,
                },
                next_node=(node.next_nodes[0] if len(node.next_nodes) == 1 else None),
                allowed_next_nodes=node.next_nodes,
                max_visits=node.max_visits,
                required_capabilities=required,
            )
        )
    identity = program.program_identity.implementation
    return ResearchProgram(
        program_id=f"method:{identity.method_id}",
        kind=MachineKind.METHOD,
        version=identity.implementation_version,
        state_schema=program.state_schema,
        entrypoint=program.graph.entrypoint,
        nodes=tuple(nodes),
        required_capabilities=program.required_capabilities,
    )


def method_program_lowering_digest(program: MethodProgram) -> str:
    lowered = lower_method_program(program)
    return canonical_digest(
        {
            "adapter": "method-program-to-research-program",
            "version": METHOD_PROGRAM_ADAPTER_VERSION,
            "method_program_digest": program.program_digest,
            "research_program_digest": lowered.program_digest,
        }
    )


def _effect_payload(receipt: EffectReceipt) -> dict[str, object]:
    return {
        "effect_id": receipt.effect_id,
        "request_digest": receipt.request_digest,
        "effect_class": receipt.effect_class.value,
        "certainty": receipt.certainty.value,
        "provider_instance_id": receipt.provider_instance_id,
        "verification_required": receipt.verification_required,
        "before_artifact": receipt.before_artifact,
        "after_artifact": receipt.after_artifact,
        "provider_receipt": receipt.provider_receipt,
    }


def decode_effect_receipt(payload: Mapping[str, object]) -> EffectReceipt:
    return EffectReceipt(
        effect_id=str(payload["effect_id"]),
        request_digest=str(payload["request_digest"]),
        effect_class=EffectClass(str(payload["effect_class"])),
        certainty=EffectCertainty(str(payload["certainty"])),
        provider_instance_id=(
            None if payload.get("provider_instance_id") is None
            else str(payload["provider_instance_id"])
        ),
        verification_required=bool(payload.get("verification_required", False)),
        before_artifact=(
            None if payload.get("before_artifact") is None
            else str(payload["before_artifact"])
        ),
        after_artifact=(
            None if payload.get("after_artifact") is None
            else str(payload["after_artifact"])
        ),
        provider_receipt=(
            None if payload.get("provider_receipt") is None
            else str(payload["provider_receipt"])
        ),
    )


class _JournalEffectReceiptHistory(Sequence[EffectReceipt]):
    """Lazy receipt projection over accepted Method Machine commits.

    Receipt truth is the Machine Journal event stream. Nodes that never inspect
    prior effects pay O(1); the first consumer materializes the exact accepted
    history once for that node request.
    """

    __slots__ = ("_host", "_machine_id", "_rows")

    def __init__(self, host, machine_id: str) -> None:
        self._host = host
        self._machine_id = machine_id
        self._rows: tuple[EffectReceipt, ...] | None = None

    def _materialize(self) -> tuple[EffectReceipt, ...]:
        rows = self._rows
        if rows is not None:
            return rows
        projected: list[EffectReceipt] = []
        for commit in self._host.accepted_commits(self._machine_id):
            for raw_event in commit.event_payloads:
                event = thaw_json(raw_event)
                if (
                    isinstance(event, Mapping)
                    and event.get("type") == "method.effect_receipt"
                    and isinstance(event.get("receipt"), Mapping)
                ):
                    projected.append(
                        decode_effect_receipt(event["receipt"])
                    )
        rows = tuple(projected)
        self._rows = rows
        return rows

    def __len__(self) -> int:
        return len(self._materialize())

    def __getitem__(self, index):
        return self._materialize()[index]


def _effect_event_payloads(
    receipts: Sequence[EffectReceipt],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "type": "method.effect_receipt",
            "receipt": _effect_payload(receipt),
        }
        for receipt in receipts
    )


def _event_payload(event: MethodEvent) -> dict[str, object]:
    return {"kind": event.kind, "payload": event.payload}


def _capability_progress_signal(
    node,
    result: MethodNodeResult,
) -> tuple[bool | None, str | None]:
    if node.kind is not MethodNodeKind.CAPABILITY or not result.effect_receipts:
        return None, None
    certainties = tuple(receipt.certainty for receipt in result.effect_receipts)
    if any(value is EffectCertainty.EFFECT_CONFIRMED for value in certainties):
        progress = True
    elif all(
        value in {EffectCertainty.NO_EFFECT, EffectCertainty.EFFECT_REJECTED}
        for value in certainties
    ):
        progress = False
    else:
        return None, None
    fingerprint = canonical_digest({
        "method_node_id": node.node_id,
        "receipts": tuple(
            {
                "request_digest": receipt.request_digest,
                "certainty": receipt.certainty.value,
                "provider_instance_id": receipt.provider_instance_id,
                "before_artifact": receipt.before_artifact,
                "after_artifact": receipt.after_artifact,
            }
            for receipt in result.effect_receipts
        ),
    })
    return progress, fingerprint


def decode_method_event(payload: Mapping[str, object]) -> MethodEvent:
    return MethodEvent(str(payload["kind"]), payload.get("payload"))


def _interrupt_payload(interrupt: MethodInterrupt | None):
    if interrupt is None:
        return None
    return {
        "interrupt_id": interrupt.interrupt_id,
        "node_id": interrupt.node_id,
        "payload": interrupt.payload,
    }


def decode_method_interrupt(payload: object) -> MethodInterrupt | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise TypeError("method interrupt semantic payload must be an object")
    return MethodInterrupt(
        str(payload["interrupt_id"]),
        str(payload["node_id"]),
        payload.get("payload"),
    )


def _failure_payload(exc: BaseException, node_id: str) -> dict[str, object]:
    outer_description = describe_exception(exc)
    failure_id = None
    seen: set[int] = set()
    current: BaseException | None = exc
    primary: BaseException = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        primary = current
        value = getattr(current, "failure_id", None)
        if failure_id is None and isinstance(value, str) and value.strip():
            failure_id = value.strip()
        result = getattr(current, "result", None)
        value = getattr(result, "failure_id", None)
        if failure_id is None and isinstance(value, str) and value.strip():
            failure_id = value.strip()
        result_cause = getattr(result, "cause", None)
        if isinstance(result_cause, BaseException) and id(result_cause) not in seen:
            current = result_cause
            continue
        current = current.__cause__ if current.__cause__ is not None else (
            None if current.__suppress_context__ else current.__context__
        )
    primary_description = describe_exception(primary)
    return {
        "failure": (
            f"{primary_description.qualified_type}: "
            f"{primary_description.safe_message}"
        ),
        "failure_code": "method.node_execution_failed",
        "failure_phase": f"node:{node_id}:invoke",
        "failure_id": failure_id,
        "error_digest": outer_description.error_digest,
        "primary_error_digest": primary_description.error_digest,
    }


def _semantic_scope(context: ExecutionContext) -> dict[str, object]:
    return {
        "run_id": context.run_id,
        "study_id": context.study_id,
        "condition_id": context.condition_id,
        "lifetime_id": context.lifetime_id,
        "branch_id": context.branch_id,
        "task_id": context.task_id,
    }


def _operation_id(
    context: ExecutionContext,
    program: MethodProgram,
    node_id: str,
    visit: int,
) -> str:
    digest = canonical_digest(
        {
            "scope": _semantic_scope(context),
            "program_digest": program.program_digest,
            "node_id": node_id,
            "visit": visit,
        }
    )
    return f"method:{context.run_id}:{digest[:24]}"


def _node_idempotency_key(
    context: ExecutionContext,
    program: MethodProgram,
    node_id: str,
    visit: int,
) -> str:
    return "method-node:" + canonical_digest(
        {
            "scope": _semantic_scope(context),
            "program_digest": program.program_digest,
            "node_id": node_id,
            "visit": visit,
        }
    )


def _capability_idempotency_key(
    context: ExecutionContext,
    capability_id: str,
) -> str:
    if not isinstance(context.operation_id, str) or not context.operation_id.strip():
        raise RuntimeError("method capability invocation requires stable operation identity")
    return "method-capability:" + canonical_digest(
        {
            "scope": _semantic_scope(context),
            "operation_id": context.operation_id,
            "capability_id": capability_id,
        }
    )


def _budget_usage(
    request: ProgramNodeRequest,
    runtime: MethodRuntimeContext,
) -> dict[str, object]:
    if (
        runtime.execution_budget is not None
        and runtime.execution.lifetime_id is not None
        and runtime.execution.trial_budget
    ):
        snapshot = runtime.execution_budget.snapshot(
            runtime.execution.lifetime_id
        )
        usage = snapshot.usage
        return {
            "steps": usage.steps,
            "turns": usage.turns,
            "model_calls": usage.model_calls,
            "messages": usage.messages,
            "tokens": usage.tokens,
            "working_seconds": usage.working_seconds,
            "cost_usd": usage.cost_usd,
        }
    raw_usage = request.semantic_state.get("method_usage", {})
    if not isinstance(raw_usage, Mapping):
        raise TypeError("Method semantic usage must be an object")
    def usage_int(name: str) -> int:
        value = raw_usage.get(name, 0)
        if type(value) is not int or value < 0:
            raise TypeError(f"Method semantic usage {name} must be non-negative integer")
        return value
    model_calls = usage_int("model_calls")
    messages = usage_int("messages")
    input_tokens = usage_int("input_tokens")
    output_tokens = usage_int("output_tokens")
    cost_usd_value = raw_usage.get("cost_usd", 0.0)
    if (
        isinstance(cost_usd_value, bool)
        or not isinstance(cost_usd_value, (int, float))
    ):
        raise TypeError("Method semantic usage cost_usd must be numeric")
    cost_usd = float(cost_usd_value)
    cost_known = raw_usage.get("cost_known", True)
    if type(cost_known) is not bool:
        raise TypeError("Method semantic usage cost_known must be boolean")
    return {
        "turns": model_calls,
        "model_calls": model_calls,
        "messages": messages,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
        "cost_usd": cost_usd if cost_known else None,
    }


def _method_request(
    program: MethodProgram,
    runtime: MethodRuntimeContext,
    request: ProgramNodeRequest,
) -> MethodNodeRequest:
    node = program.graph.node(request.node.node_id)
    visit = request.visit - 1
    operation_id = _operation_id(runtime.execution, program, node.node_id, visit)
    context = replace(
        runtime.execution,
        operation_id=operation_id,
        component_id=METHOD_PROGRAM_TARGET.component_id,
        budget_usage=_budget_usage(request, runtime),
    )
    if runtime.program_host is None:
        raise RuntimeError("Method receipt projection requires bound ResearchProgramHost")
    effects = _JournalEffectReceiptHistory(
        runtime.program_host,
        request.snapshot.machine_id,
    )
    return MethodNodeRequest(
        node_id=node.node_id,
        visit=visit,
        state=request.data,
        input_value=request.payload,
        context=context,
        previous_value=request.previous_value,
        effect_receipts=effects,
        capabilities=runtime.capabilities,
        child_machines=runtime.child_machines,
        visit_counts=request.visit_counts,
        checkpoint=request.checkpoint_value,
        parent_machine_id=(
            request.snapshot.machine_id if runtime.child_machines is not None else None
        ),
    )


def _agent_request(node, request: MethodNodeRequest) -> MethodAgentRequest:
    projector = node.agent_view
    if not callable(projector):
        raise RuntimeError("agent node has no model-visible view projector")
    view = projector(request)
    if not isinstance(view, Mapping):
        raise TypeError("agent view projector must return a mapping")
    selector = node.agent_target
    if callable(selector):
        agent_id = selector(request)
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("dynamic agent selector must return non-empty text")
        if agent_id not in node.agent_targets:
            raise ValueError(
                f"dynamic agent selector chose undeclared participant: {agent_id!r}"
            )
    else:
        agent_id = node.agent_id
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise RuntimeError("static agent node has no valid agent_id")
    return MethodAgentRequest(
        agent_id=agent_id,
        goal=request.input_value,
        view=view,
        input_value=request.input_value,
        previous_value=request.previous_value,
        context=request.context,
        checkpoint=request.checkpoint,
    )


def _capability_id(node, request: MethodNodeRequest) -> str:
    selector = node.capability_target
    if callable(selector):
        capability_id = selector(request)
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("dynamic capability selector must return non-empty text")
        if capability_id not in node.capability_targets:
            raise ValueError(
                f"dynamic capability selector chose undeclared capability: {capability_id!r}"
            )
        return capability_id
    capability_id = node.capability_id
    if not isinstance(capability_id, str) or not capability_id.strip():
        raise RuntimeError("static capability node has no valid capability_id")
    return capability_id


def _invoke_method_node(
    runtime: MethodRuntimeContext,
    node,
    request: MethodNodeRequest,
) -> MethodNodeResult:
    if node.kind is MethodNodeKind.AGENT:
        if runtime.agent_loop is None:
            raise RuntimeError("agent node requires MethodRuntimeContext.agent_loop")
        runner = getattr(runtime.agent_loop, "run", None)
        if not callable(runner):
            raise RuntimeError(
                "Method Machine uses the single synchronous commit path; "
                "agent providers must expose run() at the Operation boundary"
            )
        result = runner(_agent_request(node, request))
        if inspect.isawaitable(result):
            raise RuntimeError(
                "async agent result cannot escape into the Machine interpreter"
            )
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
        capability_id = _capability_id(node, request)
        descriptor = runtime.capabilities.describe(capability_id)
        capability_payload = (
            request.previous_value
            if request.previous_value is not None
            else request.input_value
            if request.input_value is not None
            else request.state
        )
        result = runtime.capabilities.invoke(
            CapabilityRequest(
                capability_id,
                capability_payload,
                request.context,
                (
                    _capability_idempotency_key(request.context, capability_id)
                    if descriptor.effect_class is not EffectClass.PURE
                    else None
                ),
            )
        )
        if inspect.isawaitable(result):
            raise RuntimeError(
                "async capability result cannot escape into the Machine interpreter"
            )
        if not isinstance(result, CapabilityResult):
            raise TypeError("capability port must return CapabilityResult")
        effects = () if result.effect is None else (result.effect,)
        evidence_events = (
            ()
            if result.evidence is None
            else (
                MethodEvent(
                    "capability.evidence",
                    {
                        "capability_id": result.capability_id,
                        "request_digest": result.request_digest,
                        "generation": result.generation,
                        "artifacts": result.artifacts,
                        "evidence": result.evidence,
                    },
                ),
            )
        )
        return MethodNodeResult(
            value=result.payload,
            events=evidence_events,
            effect_receipts=effects,
        )
    if node.kind is MethodNodeKind.CHECKPOINT:
        return MethodNodeResult(
            value=request.previous_value,
            checkpoint=True,
            checkpoint_value=request.checkpoint,
        )
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
    if inspect.isawaitable(result):
        raise RuntimeError(
            "async Method handler cannot escape into the single Machine interpreter"
        )
    if not isinstance(result, MethodNodeResult):
        raise TypeError("method node handler must return MethodNodeResult")
    return result


def _semantic_update(
    request: ProgramNodeRequest,
    node_id: str,
    result: MethodNodeResult | None,
    *,
    failure: dict[str, object] | None = None,
) -> dict[str, object]:
    current = dict(request.semantic_state)
    # Method events are already authoritative Machine Journal event payloads.
    # Keeping the entire event history inside hot semantic state made every
    # node copy O(history) data. Maintain only the budget aggregate needed by
    # the fallback accounting path; final MethodRunResult.events is projected
    # once from the journal.
    raw_usage = current.get("method_usage", {})
    if not isinstance(raw_usage, Mapping):
        raise TypeError("Method semantic usage must be an object")
    usage = {
        "model_calls": int(raw_usage.get("model_calls", 0)),
        "messages": int(raw_usage.get("messages", 0)),
        "input_tokens": int(raw_usage.get("input_tokens", 0)),
        "output_tokens": int(raw_usage.get("output_tokens", 0)),
        "cost_usd": float(raw_usage.get("cost_usd", 0.0)),
        "cost_known": bool(raw_usage.get("cost_known", True)),
    }
    if result is not None:
        for event in result.events:
            if event.kind != "model.invocation":
                continue
            payload = event.payload
            if not isinstance(payload, Mapping):
                continue
            usage["model_calls"] += 1
            value = payload.get("message_count")
            if isinstance(value, int) and not isinstance(value, bool):
                usage["messages"] += value
            value = payload.get("input_tokens")
            if isinstance(value, int) and not isinstance(value, bool):
                usage["input_tokens"] += value
            value = payload.get("output_tokens")
            if isinstance(value, int) and not isinstance(value, bool):
                usage["output_tokens"] += value
            value = payload.get("cost_usd")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage["cost_usd"] += float(value)
            else:
                usage["cost_known"] = False
        current["interrupt"] = _interrupt_payload(result.interrupt)
    current.pop("method_events", None)
    current.pop("effect_receipts", None)
    current["method_usage"] = usage
    if failure is not None:
        current["failure"] = failure
    return current


def _method_operation(
    program: MethodProgram,
    node_id: str,
):
    node = program.graph.node(node_id)

    def handler(request: ProgramNodeRequest, binding: object) -> ProgramNodeResult:
        if not isinstance(binding, MethodRuntimeContext):
            raise TypeError("Method ResearchProgram host requires MethodRuntimeContext binding")
        runtime = binding
        method_request = _method_request(program, runtime, request)
        if runtime.schemas is not None:
            runtime.schemas.validate(
                program.state_schema,
                method_request.state,
                location=f"method.node.{node.node_id}.state",
            )
            runtime.schemas.validate(
                node.input_schema,
                method_request.input_value,
                location=f"method.node.{node.node_id}.input",
            )
        if runtime.dispatcher is None:
            raise RuntimeError("Method execution requires durable Operation dispatcher")
        payload = {
            "method_program_digest": program.program_digest,
            "lowered_program_digest": request.program.program_digest,
            "node_id": node.node_id,
            "visit": method_request.visit,
            "input_digest": canonical_digest(method_request.input_value),
            "state_digest": canonical_digest(method_request.state),
            "checkpoint_digest": canonical_digest(method_request.checkpoint),
            "effect_class": node.effect_class.value,
        }
        try:
            if (
                runtime.execution_budget is not None
                and method_request.context.lifetime_id is not None
            ):
                runtime.execution_budget.consume(
                    method_request.context.lifetime_id,
                    method_request.context.operation_id + ":step",
                    ExecutionBudgetDelta(steps=1),
                )
            operation = runtime.dispatcher.dispatch(
                root_context=runtime.execution,
                operation_id=_operation_id(
                    runtime.execution,
                    program,
                    node.node_id,
                    method_request.visit,
                ),
                operation_type=node.operation_type,
                target=METHOD_PROGRAM_TARGET,
                payload=payload,
                payload_schema="noetrium.method-program-node.v3",
                handler=lambda _envelope: _invoke_method_node(
                    runtime,
                    node,
                    method_request,
                ),
                digest_output=True,
                effect_projector=lambda output: tuple(output.effect_receipts),
                idempotency_key=_node_idempotency_key(
                    runtime.execution,
                    program,
                    node.node_id,
                    method_request.visit,
                ),
            )
            require = getattr(runtime.dispatcher, "require", None)
            if not callable(require):
                raise TypeError("Operation dispatcher must provide require()")
            result = require(operation)
            if not isinstance(result, MethodNodeResult):
                raise TypeError("Method operation must return MethodNodeResult")
            if operation.effect_receipts != result.effect_receipts:
                raise RuntimeError("Method effect receipt projection mismatch")
            if runtime.schemas is not None:
                runtime.schemas.validate(
                    node.output_schema,
                    result.value,
                    location=f"method.node.{node.node_id}.output",
                )
                merged = dict(method_request.state)
                merged.update(result.state_update)
                runtime.schemas.validate(
                    program.state_schema,
                    merged,
                    location=f"method.node.{node.node_id}.state_update",
                )
        except BaseException as exc:
            failure = _failure_payload(exc, node.node_id)
            return ProgramNodeResult(
                value=request.previous_value,
                status=MachineStatus.FAILED,
                semantic_state_update=_semantic_update(
                    request,
                    node.node_id,
                    None,
                    failure=failure,
                ),
                events=(
                    {
                        "type": "method_node_failed",
                        "node_id": node.node_id,
                        **failure,
                    },
                ),
            )

        method_events = (*result.events, MethodEvent(f"node:{node.node_id}", result.value))
        if runtime.observation is not None:
            for event in method_events:
                try:
                    runtime.observation.publish(event, method_request.context)
                except Exception:
                    pass

        budget_violations = tuple(
            event
            for event in result.events
            if event.kind == "budget.violation"
        )
        if budget_violations:
            violation_text = "; ".join(
                str(event.payload) for event in budget_violations
            )
            failure = _failure_payload(
                ExecutionBudgetExceeded(violation_text),
                node.node_id,
            )
            return ProgramNodeResult(
                value=result.value,
                state_update=result.state_update,
                status=MachineStatus.FAILED,
                checkpoint_requested=result.checkpoint,
                checkpoint_value=result.checkpoint_value,
                semantic_state_update=_semantic_update(
                    request,
                    node.node_id,
                    result,
                    failure=failure,
                ),
                events=(
                    tuple(
                        {
                            "type": "method.event",
                            "event": _event_payload(event),
                        }
                        for event in method_events
                    )
                    + _effect_event_payloads(result.effect_receipts)
                    + (
                        {
                            "type": "method_budget_failed",
                            "node_id": node.node_id,
                            **failure,
                        },
                    )
                ),
                effect_intent_refs=tuple(
                    receipt.effect_id for receipt in result.effect_receipts
                ),
                child_links=result.child_links,
            )

        progress, progress_fingerprint = _capability_progress_signal(node, result)
        terminal = (
            node.kind is MethodNodeKind.RETURN
            or (not node.next_nodes and result.next_node is None)
        )
        status = (
            MachineStatus.INTERRUPTED
            if result.interrupt is not None
            else MachineStatus.COMPLETED
            if terminal
            else None
        )
        return ProgramNodeResult(
            value=result.value,
            state_update=result.state_update,
            next_node=result.next_node,
            status=status,
            checkpoint_requested=result.checkpoint,
            checkpoint_value=result.checkpoint_value,
            semantic_state_update=_semantic_update(
                request,
                node.node_id,
                result,
            ),
            events=(
                tuple(
                    {
                        "type": "method.event",
                        "event": _event_payload(event),
                    }
                    for event in method_events
                )
                + _effect_event_payloads(result.effect_receipts)
                + (
                    (
                        {
                            "type": "method.interrupt",
                            "interrupt": _interrupt_payload(result.interrupt),
                        },
                    )
                    if result.interrupt is not None
                    else ()
                )
            ),
            effect_intent_refs=tuple(
                receipt.effect_id for receipt in result.effect_receipts
            ),
            child_links=result.child_links,
            progress=progress,
            progress_fingerprint=progress_fingerprint,
        )

    return handler


def method_program_operations(program: MethodProgram) -> tuple[ResearchHostOperation, ...]:
    if not isinstance(program, MethodProgram):
        raise TypeError("Method operation lowering requires MethodProgram")
    return tuple(
        ResearchHostOperation(
            operation=f"method.node.{node.node_id}",
            handler=_method_operation(program, node.node_id),
            implementation_digest=canonical_digest(
                {
                    "adapter": "method-node-operation",
                    "version": METHOD_PROGRAM_ADAPTER_VERSION,
                    "method_program_digest": program.program_digest,
                    "node_id": node.node_id,
                    "node_implementation_digest": node.implementation_digest,
                }
            ),
        )
        for node in program.graph.nodes
    )


__all__ = [
    "METHOD_PROGRAM_ADAPTER_VERSION",
    "METHOD_PROGRAM_TARGET",
    "decode_effect_receipt",
    "decode_method_event",
    "decode_method_interrupt",
    "lower_method_program",
    "method_program_lowering_digest",
    "method_program_operations",
]
