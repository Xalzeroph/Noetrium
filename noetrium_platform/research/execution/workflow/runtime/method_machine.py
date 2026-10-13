"""Method authoring facade over the single programmable Research Machine kernel."""
from __future__ import annotations


from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel.universal import UNIT_STATE_KEY
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    MachineStatus,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodCheckpoint,
    MethodEvidenceStatus,
    MethodEvent,
    NoetriumUnit,
    MethodRunResult,
    MethodRunStatus,
    MethodRuntimeContext,
    method_program_digest,
    method_program_evidence_obligations,
    method_program_input_schema,
    method_program_nodes,
    method_program_output_schema,
    method_program_state_schema,
    method_node_evidence_obligations,
)
from .program_lowering import (
    decode_effect_receipt,
    decode_method_event,
    decode_method_interrupt,
)


METHOD_EXECUTION_IDENTITY = ComponentIdentity(
    "platform.workflow_runtime",
    "method_executable_unit_execution",
    "4",
    "1",
    "universal-unit-method-execution-v1",
)


def _evidence_obligations(program: NoetriumUnit) -> tuple[str, ...]:
    rows = list(method_program_evidence_obligations(program))
    for node in method_program_nodes(program):
        rows.extend(method_node_evidence_obligations(node))
    return tuple(dict.fromkeys(rows))


def _evidence_status(
    program: NoetriumUnit,
    runtime: MethodRuntimeContext,
    result: MethodRunResult | None,
) -> MethodEvidenceStatus:
    obligations = _evidence_obligations(program)
    if not obligations:
        return MethodEvidenceStatus.NOT_REQUIRED
    if result is not None:
        # Only the executed conditional branches incur their node obligations.
        # Global obligations without an owning node remain mandatory. Root
        # declarations of an unvisited optional node are not fabricated as
        # missing physical effects.
        executed = {
            event.kind.removeprefix("node:")
            for event in result.events
            if event.kind.startswith("node:")
        }
        node_requirements = {
            node.unit_id: method_node_evidence_obligations(node)
            for node in method_program_nodes(program)
        }
        owned = {
            item for obligations_for_node in node_requirements.values()
            for item in obligations_for_node
        }
        required = set(obligations) - owned
        for node_id in executed:
            required.update(node_requirements.get(node_id, ()))
        obligations = tuple(item for item in obligations if item in required)
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
    return (
        status
        if isinstance(status, MethodEvidenceStatus)
        else MethodEvidenceStatus.UNKNOWN
    )


def _program_state(commit) -> dict[str, object]:
    root = thaw_json(commit.state)
    if not isinstance(root, dict):
        raise TypeError("Method Machine commit state must be an object")
    value = root.get(UNIT_STATE_KEY)
    if not isinstance(value, dict):
        raise TypeError("Method Machine commit has no NoetriumUnit state")
    return value


def _checkpoint_from_execution(
    program: NoetriumUnit,
    runtime: MethodRuntimeContext,
    execution,
) -> MethodCheckpoint | None:
    selected = None
    selected_node = None
    for commit in reversed(execution.run.commits):
        for event in commit.event_payloads:
            event_value = thaw_json(event)
            if (
                isinstance(event_value, dict)
                and event_value.get("type") == "executable_unit_node_executed"
                and event_value.get("checkpoint_requested") is True
            ):
                selected = commit
                selected_node = event_value.get("node_id")
                break
        if selected is not None:
            break

    interrupt = decode_method_interrupt(
        execution.semantic_state.get("interrupt")
    )
    if selected is None and interrupt is not None and execution.cut is not None:
        cut = execution.cut
        return MethodCheckpoint(
            run_id=runtime.execution.run_id,
            program_digest=method_program_digest(program),
            sequence=execution.step_count,
            current_node=interrupt.node_id,
            machine_id=cut.machine_id,
            machine_revision=cut.revision,
            machine_commit_id=cut.commit_id,
            state_digest=cut.state_digest,
            checkpoint_value=execution.checkpoint_value,
        )
    if selected is None:
        return None

    state = _program_state(selected)
    visits = state.get("visits", {})
    if not isinstance(visits, dict):
        raise TypeError("Method checkpoint visits must be an object")
    sequence = sum(int(value) for value in visits.values())
    if type(selected_node) is not str or not selected_node.strip():
        raise ValueError("Method checkpoint node identity is missing")
    return MethodCheckpoint(
        run_id=runtime.execution.run_id,
        program_digest=method_program_digest(program),
        sequence=sequence,
        current_node=selected_node,
        machine_id=selected.machine_id,
        machine_revision=selected.revision,
        machine_commit_id=selected.commit_id,
        state_digest=selected.state_digest,
        checkpoint_value=state.get("checkpoint_value"),
    )


def _method_status(execution) -> MethodRunStatus:
    semantic = execution.semantic_state
    unit_failure = semantic.get("unit_failure")
    if isinstance(unit_failure, Mapping):
        code = unit_failure.get("code")
        if code in {
            "unit.step_limit",
            "unit.node_visit_limit",
            "unit.no_progress_livelock",
        }:
            return MethodRunStatus.LIMIT_REACHED
    if execution.status is MachineStatus.COMPLETED:
        return MethodRunStatus.SUCCEEDED
    if execution.status in {MachineStatus.WAITING, MachineStatus.INTERRUPTED}:
        return MethodRunStatus.INTERRUPTED
    if execution.status is MachineStatus.FAILED:
        return MethodRunStatus.FAILED
    raise RuntimeError(
        "generic Method Machine stopped in non-terminal state: "
        + execution.status.value
    )


def project_method_accepted_evidence(
    program_binding: object,
    machine_id: str,
) -> tuple[tuple[MethodEvent, ...], tuple[object, ...]]:
    """Decode only crash-durable Method evidence from accepted commits.

    This performs no Machine transition and is safe at cancellation/deadline
    boundaries where a full MethodRunResult may not exist. The same decoder is
    used by normal terminal projection, so censored accounting cannot invent a
    second event interpretation.
    """
    accepted = getattr(program_binding, "accepted_commits", None)
    if not callable(accepted):
        raise TypeError("Method accepted-evidence projection requires program binding")
    if type(machine_id) is not str or not machine_id.strip():
        raise ValueError("Method accepted-evidence projection requires machine id")
    event_rows = []
    effects_list = []
    for commit in accepted(machine_id):
        for raw_event in commit.event_payloads:
            event_value = thaw_json(raw_event)
            if not isinstance(event_value, Mapping):
                continue
            if (
                event_value.get("type") == "method.event"
                and isinstance(event_value.get("event"), Mapping)
            ):
                event_rows.append(event_value["event"])
            elif (
                event_value.get("type") == "method.effect_receipt"
                and isinstance(event_value.get("receipt"), Mapping)
            ):
                effects_list.append(
                    decode_effect_receipt(event_value["receipt"])
                )
    return (
        tuple(decode_method_event(row) for row in event_rows),
        tuple(effects_list),
    )


def project_method_host_execution(
    program: NoetriumUnit,
    runtime: MethodRuntimeContext,
    execution,
) -> MethodRunResult:
    """Project one authoritative generic NoetriumUnit execution into Method semantics.

    This function performs no Machine transition. It is the single typed projection
    used by both direct Method invocation and participant-child execution.
    """
    if not isinstance(program, NoetriumUnit):
        raise TypeError("Method execution projection requires NoetriumUnit")
    if not isinstance(runtime, MethodRuntimeContext):
        raise TypeError("Method execution projection requires MethodRuntimeContext")
    status = _method_status(execution)
    semantic = execution.semantic_state
    if runtime.program_binding is None:
        raise RuntimeError("Method event projection requires bound BoundExecutableUnit")
    event_rows = []
    effects_list = []
    for commit in runtime.program_binding.accepted_commits(execution.machine_id):
        for raw_event in commit.event_payloads:
            event_value = thaw_json(raw_event)
            if not isinstance(event_value, Mapping):
                continue
            if (
                event_value.get("type") == "method.event"
                and isinstance(event_value.get("event"), Mapping)
            ):
                event_rows.append(event_value["event"])
            elif (
                event_value.get("type") == "method.effect_receipt"
                and isinstance(event_value.get("receipt"), Mapping)
            ):
                effects_list.append(
                    decode_effect_receipt(event_value["receipt"])
                )
    events = tuple(decode_method_event(row) for row in event_rows)
    effects = tuple(effects_list)
    # This is a disposable, best-effort projection of accepted journal events,
    # never an independent execution fact. On observer failure the authoritative
    # events remain replayable from the Machine Journal.
    if runtime.observation is not None:
        for event in events:
            try:
                runtime.observation.publish(event, runtime.execution)
            except Exception:
                pass
    interrupt = decode_method_interrupt(semantic.get("interrupt"))
    checkpoint = _checkpoint_from_execution(
        program,
        runtime,
        execution,
    )

    method_failure = semantic.get("failure")
    unit_failure = semantic.get("unit_failure")
    failure = None
    failure_code = None
    failure_phase = None
    failure_id = None
    if isinstance(method_failure, Mapping):
        failure = (
            None
            if method_failure.get("failure") is None
            else str(method_failure["failure"])
        )
        failure_code = (
            None
            if method_failure.get("failure_code") is None
            else str(method_failure["failure_code"])
        )
        failure_phase = (
            None
            if method_failure.get("failure_phase") is None
            else str(method_failure["failure_phase"])
        )
        failure_id = (
            None
            if method_failure.get("failure_id") is None
            else str(method_failure["failure_id"])
        )
    elif isinstance(unit_failure, Mapping):
        failure = (
            None
            if unit_failure.get("message") is None
            else str(unit_failure["message"])
        )
        failure_code = (
            None
            if unit_failure.get("code") is None
            else str(unit_failure["code"])
        )
        cursor = unit_failure.get("cursor")
        failure_phase = None if cursor is None else f"node:{cursor}:unit"

    if status is MethodRunStatus.SUCCEEDED and runtime.schemas is not None:
        runtime.schemas.validate(
            method_program_output_schema(program),
            execution.previous_value,
            location="method.output",
        )

    result = MethodRunResult(
        status=status,
        run_id=runtime.execution.run_id,
        program_digest=method_program_digest(program),
        value=execution.previous_value,
        state=execution.data,
        events=events,
        checkpoint=checkpoint,
        interrupt=interrupt,
        failure=failure,
        effect_receipts=effects,
        step_count=execution.step_count,
        visit_counts=execution.visit_counts,
        evidence_status=MethodEvidenceStatus.UNKNOWN,
        binding_plan_digest=runtime.binding_plan_digest,
        runtime_binding_digest=runtime.effective_runtime_binding_digest,
        schema_digest=runtime.schema_digest,
        failure_code=failure_code,
        failure_phase=failure_phase,
        failure_id=failure_id,
        diagnostics={
            "generic_machine_id": execution.machine_id,
            "generic_machine_revision": execution.revision,
            "machine_cut_digest": (
                None if execution.cut is None else execution.cut.cut_digest
            ),
            "execution_unit_digest": program.unit_digest,
            "effect_receipt_count": len(effects),
            "checkpoint_id": (
                None if checkpoint is None else checkpoint.checkpoint_id
            ),
        },
    )
    evidence_status = _evidence_status(program, runtime, result)
    if evidence_status is not result.evidence_status:
        from dataclasses import replace
        result = replace(result, evidence_status=evidence_status)
    if runtime.evidence is not None:
        if checkpoint is not None:
            runtime.evidence.record_checkpoint(checkpoint)
        evidence_reference = runtime.evidence.record_result(result)
        if evidence_reference is not None:
            from dataclasses import replace
            result = replace(result, evidence_reference=evidence_reference)
    return result


def execute_bound_method_program(
    program: NoetriumUnit,
    *,
    runtime: MethodRuntimeContext,
    input_value=None,
    initial_state: Mapping[str, object] | None = None,
    resume: bool = False,
) -> MethodRunResult:
    """Execute typed Method semantics on the already-bound universal NoetriumUnit host."""
    if not isinstance(program, NoetriumUnit):
        raise TypeError("Method execution requires NoetriumUnit")
    if not isinstance(runtime, MethodRuntimeContext):
        raise TypeError("Method execution requires MethodRuntimeContext")
    if runtime.program_binding is None or runtime.machine_id is None:
        raise RuntimeError(
            "Method execution requires the generic BoundExecutableUnit binding"
        )
    if runtime.dispatcher is None:
        raise RuntimeError(
            "Method execution requires the durable Operation dispatcher"
        )
    if runtime.program_binding.unit.unit_digest != program.unit_digest:
        raise RuntimeError("Method Universal Unit host identity drifted")
    initial = {} if initial_state is None else dict(initial_state)

    if runtime.schemas is not None:
        runtime.schemas.validate(
            method_program_state_schema(program),
            initial,
            location="method.initial_state",
        )
        runtime.schemas.validate(
            method_program_input_schema(program),
            input_value,
            location="method.input",
        )

    instance_identity = {
        "schema": "noetrium.method-unit-instance.v5",
        "run_id": runtime.execution.run_id,
        "method_program_digest": method_program_digest(program),
        "binding_plan_digest": runtime.binding_plan_digest,
        "runtime_binding_digest": runtime.effective_runtime_binding_digest,
        "schema_digest": runtime.schema_digest,
        "study_id": runtime.execution.study_id,
        "condition_id": runtime.execution.condition_id,
        "lifetime_id": runtime.execution.lifetime_id,
        "branch_id": runtime.execution.branch_id,
        "task_id": runtime.execution.task_id,
    }
    execution = runtime.program_binding.execute(
        machine_id=runtime.machine_id,
        instance_identity=instance_identity,
        binding=runtime,
        initial_data=initial,
        payload=input_value,
        command_id_prefix=(
            "method:"
            + runtime.execution.run_id
            + ":"
            + method_program_digest(program)[:16]
        ),
        resume_waiting=resume,
    )
    return project_method_host_execution(program, runtime, execution)


__all__ = ["METHOD_EXECUTION_IDENTITY", "execute_bound_method_program", "project_method_host_execution"]
