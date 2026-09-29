"""Method authoring facade over the single programmable Research Machine kernel."""

from __future__ import annotations

from collections.abc import Mapping

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
    MethodProgram,
    MethodRunResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition.program_lowering import (
    decode_effect_receipt,
    decode_method_event,
    decode_method_interrupt,
    lower_method_program,
    method_program_lowering_digest,
)


METHOD_EXECUTION_IDENTITY = ComponentIdentity(
    "platform.workflow_runtime",
    "method_research_program_execution",
    "3",
    "1",
    "method-research-program-execution-v4",
)


def _evidence_obligations(program: MethodProgram) -> tuple[str, ...]:
    rows = list(program.evidence_obligations)
    for node in program.graph.nodes:
        rows.extend(node.evidence_obligations)
    return tuple(dict.fromkeys(rows))


def _evidence_status(
    program: MethodProgram,
    runtime: MethodRuntimeContext,
    result: MethodRunResult | None,
) -> MethodEvidenceStatus:
    obligations = _evidence_obligations(program)
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
    value = root.get("_program")
    if not isinstance(value, dict):
        raise TypeError("Method Machine commit has no ResearchProgram state")
    return value


def _checkpoint_from_execution(
    program: MethodProgram,
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
                and event_value.get("type") == "research_program_node_executed"
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
            program_digest=program.program_digest,
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
        program_digest=program.program_digest,
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
    program_failure = semantic.get("program_failure")
    if isinstance(program_failure, Mapping):
        code = program_failure.get("code")
        if code in {"program.step_limit", "program.node_visit_limit"}:
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


def project_method_host_execution(
    program: MethodProgram,
    runtime: MethodRuntimeContext,
    execution,
) -> MethodRunResult:
    """Project one authoritative generic ResearchProgram execution into Method semantics.

    This function performs no Machine transition. It is the single typed projection
    used by both direct Method invocation and participant-child execution.
    """
    if not isinstance(program, MethodProgram):
        raise TypeError("Method execution projection requires MethodProgram")
    if not isinstance(runtime, MethodRuntimeContext):
        raise TypeError("Method execution projection requires MethodRuntimeContext")
    lowered = lower_method_program(program)
    status = _method_status(execution)
    semantic = execution.semantic_state
    raw_events = semantic.get("method_events", ())
    if not isinstance(raw_events, (tuple, list)):
        raise TypeError("Method semantic events must be a sequence")
    events = tuple(
        decode_method_event(row)
        for row in raw_events
        if isinstance(row, Mapping)
    )
    raw_effects = semantic.get("effect_receipts", ())
    if not isinstance(raw_effects, (tuple, list)):
        raise TypeError("Method semantic effect receipts must be a sequence")
    effects = tuple(
        decode_effect_receipt(row)
        for row in raw_effects
        if isinstance(row, Mapping)
    )
    interrupt = decode_method_interrupt(semantic.get("interrupt"))
    checkpoint = _checkpoint_from_execution(
        program,
        runtime,
        execution,
    )

    method_failure = semantic.get("failure")
    program_failure = semantic.get("program_failure")
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
    elif isinstance(program_failure, Mapping):
        failure = (
            None
            if program_failure.get("message") is None
            else str(program_failure["message"])
        )
        failure_code = (
            None
            if program_failure.get("code") is None
            else str(program_failure["code"])
        )
        cursor = program_failure.get("cursor")
        failure_phase = (
            None if cursor is None else f"node:{cursor}:program"
        )

    if status is MethodRunStatus.SUCCEEDED and runtime.schemas is not None:
        runtime.schemas.validate(
            program.output_schema,
            execution.previous_value,
            location="method.output",
        )

    result = MethodRunResult(
        status=status,
        run_id=runtime.execution.run_id,
        program_digest=program.program_digest,
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
            "lowered_program_digest": lowered.program_digest,
            "lowering_digest": method_program_lowering_digest(program),
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
    program: MethodProgram,
    *,
    runtime: MethodRuntimeContext,
    input_value=None,
    initial_state: Mapping[str, object] | None = None,
    resume: bool = False,
) -> MethodRunResult:
    """Execute typed Method semantics on the already-bound universal ResearchProgram host."""
    if not isinstance(program, MethodProgram):
        raise TypeError("Method execution requires MethodProgram")
    if not isinstance(runtime, MethodRuntimeContext):
        raise TypeError("Method execution requires MethodRuntimeContext")
    if runtime.program_host is None or runtime.machine_id is None:
        raise RuntimeError(
            "Method execution requires the generic ResearchProgramHost binding"
        )
    if runtime.dispatcher is None:
        raise RuntimeError(
            "Method execution requires the durable Operation dispatcher"
        )
    lowered = lower_method_program(program)
    if runtime.program_host.program.program_digest != lowered.program_digest:
        raise RuntimeError("Method generic Machine host program identity drifted")
    initial = {} if initial_state is None else dict(initial_state)

    if runtime.schemas is not None:
        runtime.schemas.validate(
            program.state_schema,
            initial,
            location="method.initial_state",
        )
        runtime.schemas.validate(
            program.input_schema,
            input_value,
            location="method.input",
        )

    instance_identity = {
        "schema": "noetrium.method-program-instance.v4",
        "run_id": runtime.execution.run_id,
        "method_program_digest": program.program_digest,
        "lowered_program_digest": lowered.program_digest,
        "lowering_digest": method_program_lowering_digest(program),
        "binding_plan_digest": runtime.binding_plan_digest,
        "runtime_binding_digest": runtime.effective_runtime_binding_digest,
        "schema_digest": runtime.schema_digest,
        "study_id": runtime.execution.study_id,
        "condition_id": runtime.execution.condition_id,
        "lifetime_id": runtime.execution.lifetime_id,
        "branch_id": runtime.execution.branch_id,
        "task_id": runtime.execution.task_id,
    }
    execution = runtime.program_host.execute(
        machine_id=runtime.machine_id,
        instance_identity=instance_identity,
        binding=runtime,
        initial_data=initial,
        payload=input_value,
        command_id_prefix=(
            "method:"
            + runtime.execution.run_id
            + ":"
            + program.program_digest[:16]
        ),
        resume_waiting=resume,
    )
    return project_method_host_execution(program, runtime, execution)


__all__ = ["METHOD_EXECUTION_IDENTITY", "execute_bound_method_program", "project_method_host_execution"]
