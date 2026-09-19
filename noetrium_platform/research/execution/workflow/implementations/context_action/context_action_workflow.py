from __future__ import annotations

from dataclasses import replace

from noetrium_platform.capabilities.environment.api import (
    action_result_from_payload,
    action_result_payload,
    observation_from_payload,
    observation_payload,
)
from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    MachineSnapshotStorePort,
    MachineStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import (
    ProgramNodeResult,
    RuntimeConcern,
    RuntimeProgramBuilder,
)
from noetrium_platform.research.execution.workflow.runtime.program_trial import (
    RuntimeProgramTrialProtocol,
    TrialProgramFrame,
    TrialProgramOperation,
    TrialProgramRestorer,
)
from .action_contracts import ActionPreflightProof
from .contracts import ContextActionOperationPort


CONTEXT_ACTION_TRIAL_PROGRAM = (
    RuntimeProgramBuilder.create(
        program_id="workflow.context-action",
        version="5",
        state_schema="workflow.context-action.state.v5",
        entrypoint="preflight",
    )
    .semantic(
        "preflight",
        RuntimeConcern.CAPABILITY_MEDIATION,
        "workflow.context-action.preflight",
        next_node="recover",
    )
    .semantic(
        "recover",
        RuntimeConcern.RECOVERY,
        "workflow.context-action.recover",
        next_node="observe",
    )
    .semantic(
        "observe",
        RuntimeConcern.EVENT,
        "workflow.context-action.observe",
        next_node="ingest",
    )
    .semantic(
        "ingest",
        RuntimeConcern.CONTEXT,
        "workflow.context-action.ingest",
        next_node="recall",
    )
    .semantic(
        "recall",
        RuntimeConcern.CONTEXT,
        "workflow.context-action.recall",
        next_node="act",
    )
    .semantic(
        "act",
        RuntimeConcern.TURN,
        "workflow.context-action.act",
        next_node="complete",
    )
    .semantic(
        "complete",
        RuntimeConcern.EVENT,
        "workflow.context-action.complete",
    )
    .build()
)


def _surface(surface: object) -> ContextActionOperationPort:
    if not isinstance(surface, ContextActionOperationPort):
        raise TypeError("context-action Program requires ContextActionOperationPort")
    return surface


def _preflight(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    operations = _surface(surface)
    proof, rows = operations.preflight_action(
        frame.input_kind,
        frame.input_payload,
        frame.context,
    )
    frame.operation_results.extend(rows)
    operation_ids = tuple(row.operation_id for row in rows)
    return ProgramNodeResult(
        value={"operation_ids": operation_ids, "preflight": proof.as_payload()},
        state_update={
            "preflight_operation_ids": operation_ids,
            "action_preflight": proof.as_payload(),
        },
        events=({
            "type": "context_action_preflight_completed",
            "operation_ids": operation_ids,
        },),
    )


def _recover(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    operations = _surface(surface)
    proof = ActionPreflightProof.from_payload(request.data.get("action_preflight"))
    recovered = operations.try_recover_committed_cycle(
        frame.input_kind,
        frame.input_payload,
        frame.context,
        proof,
    )
    if recovered is None:
        return ProgramNodeResult(
            value={"recovered": False},
            state_update={"recovered": False},
            events=({"type": "context_action_recovery_checked", "recovered": False},),
        )

    frame.primary_result = recovered.action_result
    frame.context = recovered.final_context
    frame.operation_results.extend(recovered.operation_results)
    operation_ids = tuple(row.operation_id for row in recovered.operation_results)
    result_digest = canonical_digest(recovered.action_result)
    return ProgramNodeResult(
        value={"recovered": True, "result_digest": result_digest},
        state_update={
            "recovered": True,
            "recovered_result_digest": result_digest,
            "recovered_action_result": action_result_payload(recovered.action_result),
            "recovery_operation_ids": operation_ids,
            "participant_generations": frame.context.participant_generations,
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "context_action_cycle_recovered",
            "result_digest": result_digest,
            "operation_ids": operation_ids,
        },),
    )


def _observe(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    operations = _surface(surface)
    observation, operation = operations.observe(frame.context)
    frame.operation_results.append(operation)
    frame.context = frame.context.with_generation("environment", observation.generation)
    observation_digest = canonical_digest(observation)
    return ProgramNodeResult(
        value={
            "observation_digest": observation_digest,
            "observation": observation_payload(observation),
            "environment_generation": observation.generation,
        },
        state_update={
            "observation_digest": observation_digest,
            "environment_generation": observation.generation,
            "observe_operation_id": operation.operation_id,
            "participant_generations": frame.context.participant_generations,
        },
        events=({
            "type": "context_action_observed",
            "observation_digest": observation_digest,
            "operation_id": operation.operation_id,
        },),
    )


def _ingest(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    operations = _surface(surface)
    observation_value = request.data.get("observation")
    if observation_value is None:
        raise RuntimeError("context-action ingest requires prior observation")
    observation = observation_from_payload(observation_value)
    operation = operations.ingest(observation, frame.context)
    frame.operation_results.append(operation)
    return ProgramNodeResult(
        value={"operation_id": operation.operation_id},
        state_update={"ingest_operation_id": operation.operation_id},
        events=({
            "type": "context_action_observation_ingested",
            "operation_id": operation.operation_id,
        },),
    )


def _recall(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    operations = _surface(surface)
    recall, operation = operations.recall(str(frame.task), frame.context)
    frame.operation_results.append(operation)
    frame.context = frame.context.with_generation("method", recall.method_generation)
    frame.context_text = recall.context_text
    context_digest = canonical_digest(recall.context_text)
    return ProgramNodeResult(
        value={
            "context_digest": context_digest,
            "context_text": recall.context_text,
            "method_generation": recall.method_generation,
        },
        state_update={
            "context_digest": context_digest,
            "method_generation": recall.method_generation,
            "recall_operation_id": operation.operation_id,
            "participant_generations": frame.context.participant_generations,
        },
        events=({
            "type": "context_action_recalled",
            "context_digest": context_digest,
            "operation_id": operation.operation_id,
        },),
    )


def _act(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    operations = _surface(surface)
    proof = ActionPreflightProof.from_payload(request.data.get("action_preflight"))
    action_result, rows = operations.act(
        frame.input_kind,
        frame.input_payload,
        frame.context,
        proof,
    )
    frame.operation_results.extend(rows)
    frame.primary_result = action_result
    if action_result.observation is not None:
        frame.context = frame.context.with_generation(
            "environment",
            action_result.observation.generation,
        )
    result_digest = canonical_digest(action_result)
    operation_ids = tuple(row.operation_id for row in rows)
    return ProgramNodeResult(
        value={"result_digest": result_digest},
        state_update={
            "action_result_digest": result_digest,
            "action_result": action_result_payload(action_result),
            "action_operation_ids": operation_ids,
            "participant_generations": frame.context.participant_generations,
        },
        events=({
            "type": "context_action_executed",
            "result_digest": result_digest,
            "operation_ids": operation_ids,
        },),
    )


def _complete(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    operations = _surface(surface)
    action_result_value = request.data.get("action_result")
    if action_result_value is None:
        raise RuntimeError("context-action completion requires prior action result")
    action_result = action_result_from_payload(action_result_value)
    proof = ActionPreflightProof.from_payload(request.data.get("action_preflight"))
    completion = operations.task_completed(
        action_result,
        frame.context,
        action_type=frame.input_kind,
        action_payload=frame.input_payload,
        preflight=proof,
    )
    frame.operation_results.extend(completion.operation_results)
    if (
        completion.receipt is not None
        and completion.receipt.method_generation is not None
    ):
        frame.context = frame.context.with_generation(
            "method",
            completion.receipt.method_generation,
        )
    operation_ids = tuple(row.operation_id for row in completion.operation_results)
    receipt_digest = (
        None
        if completion.receipt is None
        else canonical_digest(completion.receipt)
    )
    return ProgramNodeResult(
        value={"completion_receipt_digest": receipt_digest},
        state_update={
            "completion_receipt_digest": receipt_digest,
            "completion_operation_ids": operation_ids,
            "participant_generations": frame.context.participant_generations,
        },
        status=MachineStatus.COMPLETED,
        events=({
            "type": "context_action_completed",
            "completion_receipt_digest": receipt_digest,
            "operation_ids": operation_ids,
        },),
    )



def _restore_context_action(
    surface: object,
    frame: TrialProgramFrame,
    data: dict[str, object],
    previous_value: object,
) -> None:
    del surface, previous_value
    generations = data.get("participant_generations")
    if generations is not None:
        if not isinstance(generations, (tuple, list)):
            raise TypeError("context-action participant_generations must be a sequence")
        frame.context = replace(
            frame.context,
            participant_generations=tuple(tuple(row) for row in generations),
        )
    context_text = data.get("context_text")
    if context_text is not None:
        if type(context_text) is not str:
            raise TypeError("context-action context_text must be text")
        frame.context_text = context_text

    result_value = data.get("action_result")
    if result_value is None:
        result_value = data.get("recovered_action_result")
    if result_value is not None:
        frame.primary_result = action_result_from_payload(result_value)


def _operation_identity(operation: str) -> str:
    return canonical_digest({
        "operation": operation,
        "implementation_revision": 1,
    })


_CONTEXT_ACTION_OPERATIONS = (
    TrialProgramOperation(
        "workflow.context-action.preflight",
        _preflight,
        _operation_identity("workflow.context-action.preflight"),
    ),
    TrialProgramOperation(
        "workflow.context-action.recover",
        _recover,
        _operation_identity("workflow.context-action.recover"),
    ),
    TrialProgramOperation(
        "workflow.context-action.observe",
        _observe,
        _operation_identity("workflow.context-action.observe"),
    ),
    TrialProgramOperation(
        "workflow.context-action.ingest",
        _ingest,
        _operation_identity("workflow.context-action.ingest"),
    ),
    TrialProgramOperation(
        "workflow.context-action.recall",
        _recall,
        _operation_identity("workflow.context-action.recall"),
    ),
    TrialProgramOperation(
        "workflow.context-action.act",
        _act,
        _operation_identity("workflow.context-action.act"),
    ),
    TrialProgramOperation(
        "workflow.context-action.complete",
        _complete,
        _operation_identity("workflow.context-action.complete"),
    ),
)

CONTEXT_ACTION_TRIAL_CONFIGURATION_DIGEST = canonical_digest({
    "program_digest": CONTEXT_ACTION_TRIAL_PROGRAM.program_digest,
    "surface_id": "context_action.operations.v1",
    "max_steps": 32,
    "operation_implementations": tuple(
        (item.operation, item.implementation_digest)
        for item in _CONTEXT_ACTION_OPERATIONS
    ),
    "restorer_implementation_digest": canonical_digest({
        "restorer": "workflow.context-action.restore",
        "implementation_revision": 1,
    }),
})


def context_action_trial_protocol(
    *,
    journal: MachineJournalPort | None = None,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> RuntimeProgramTrialProtocol:
    return RuntimeProgramTrialProtocol(
        protocol_id="context_action.v5",
        surface_id="context_action.operations.v1",
        program=CONTEXT_ACTION_TRIAL_PROGRAM,
        operations=_CONTEXT_ACTION_OPERATIONS,
        max_steps=32,
        journal=journal,
        snapshot_store=snapshot_store,
        restorer=_restore_context_action,
        restorer_implementation_digest=canonical_digest({
            "restorer": "workflow.context-action.restore",
            "implementation_revision": 1,
        }),
    )


__all__ = [
    "CONTEXT_ACTION_TRIAL_CONFIGURATION_DIGEST",
    "CONTEXT_ACTION_TRIAL_PROGRAM",
    "context_action_trial_protocol",
]
