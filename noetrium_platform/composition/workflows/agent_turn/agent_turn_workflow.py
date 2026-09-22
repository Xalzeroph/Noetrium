from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    MachineJournalPort,
    MachineSnapshotStorePort,
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
)
from .contracts import AgentTurnOperationPort


AGENT_TURN_TRIAL_PROGRAM = (
    RuntimeProgramBuilder.create(
        program_id="workflow.agent-turn",
        version="2",
        state_schema="workflow.agent-turn.state.v2",
        entrypoint="turn",
    )
    .semantic(
        "turn",
        RuntimeConcern.TURN,
        "workflow.agent-turn.execute",
    )
    .build()
)


def _execute_agent_turn(request, surface: object, frame: TrialProgramFrame) -> ProgramNodeResult:
    if not isinstance(surface, AgentTurnOperationPort):
        raise TypeError("agent-turn Program requires AgentTurnOperationPort")
    result, rows = surface.agent_turn(
        frame.task,
        {"input_kind": frame.input_kind, "payload": frame.input_payload},
        frame.context,
    )
    frame.operation_results.extend(rows)
    if result.agent_generation is not None:
        frame.context = frame.context.with_generation("agent", result.agent_generation)
    frame.context_text = str(result.output)
    frame.primary_result = result
    result_digest = canonical_digest({
        "output": result.output,
        "agent_generation": result.agent_generation,
    })
    return ProgramNodeResult(
        value={
            "result_digest": result_digest,
            "agent_generation": result.agent_generation,
        },
        state_update={
            "result_digest": result_digest,
            "agent_generation": result.agent_generation,
            "operation_ids": tuple(row.operation_id for row in rows),
        },
        events=({
            "type": "agent_turn_completed",
            "result_digest": result_digest,
            "operation_ids": tuple(row.operation_id for row in rows),
        },),
    )


AGENT_TURN_TRIAL_CONFIGURATION_DIGEST = canonical_digest({
    "program_digest": AGENT_TURN_TRIAL_PROGRAM.program_digest,
    "surface_id": "agent_turn.operations.v1",
    "max_steps": 8,
    "operation_implementations": ((
        "workflow.agent-turn.execute",
        canonical_digest({
            "operation": "workflow.agent-turn.execute",
            "implementation_revision": 1,
        }),
    ),),
})


def agent_turn_trial_protocol(
    *,
    journal: MachineJournalPort | None = None,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> RuntimeProgramTrialProtocol:
    return RuntimeProgramTrialProtocol(
        protocol_id="agent_turn.v2",
        surface_id="agent_turn.operations.v1",
        program=AGENT_TURN_TRIAL_PROGRAM,
        operations=(
            TrialProgramOperation(
                "workflow.agent-turn.execute",
                _execute_agent_turn,
                canonical_digest({
                    "operation": "workflow.agent-turn.execute",
                    "implementation_revision": 1,
                }),
            ),
        ),
        max_steps=8,
        journal=journal,
        snapshot_store=snapshot_store,
    )


__all__ = [
    "AGENT_TURN_TRIAL_CONFIGURATION_DIGEST",
    "AGENT_TURN_TRIAL_PROGRAM",
    "agent_turn_trial_protocol",
]
