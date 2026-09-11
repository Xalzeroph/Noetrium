"""Coarse-grained adapter that hosts the existing Method VM in MachineRuntime.

UniversalMethodMachine keeps node-level semantics and checkpoint rules.  This
adapter makes its run boundary a normal Machine transition, so Run/Method
composition gets the same identity, journal, idempotency and delivery rules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    MachineCommand,
    MachineSnapshot,
    TransitionProposal,
    thaw_json,
)

from ..api.method_machine import (
    MethodMachinePort,
    MethodProgram,
    MethodRunStatus,
    MethodRuntimeContext,
)


class MethodMachineInterpreter:
    """Translate one Machine command into one bounded Method VM execution."""

    def __init__(
        self,
        *,
        machine: MethodMachinePort,
        program: MethodProgram,
        runtime: MethodRuntimeContext,
        resume: bool = False,
    ) -> None:
        self.machine = machine
        self.program = program
        self.runtime = runtime
        self.resume = resume

    def propose(
        self,
        command: MachineCommand,
        state: MachineSnapshot,
    ) -> TransitionProposal:
        payload = thaw_json(command.payload)
        if not isinstance(payload, Mapping):
            raise TypeError("method machine command payload must be an object")
        result = self.machine.run(
            self.program,
            runtime=self.runtime,
            input_value=payload.get("input"),
            initial_state=cast(Mapping[str, JsonObject], thaw_json(state.state)),
            resume=self.resume,
        )
        method_state: JsonObject = {
            "status": result.status.value,
            "run_id": result.run_id,
            "program_digest": result.program_digest,
            "value": thaw_json(result.value),
            "state": thaw_json(result.state),
            "run_digest": result.run_digest,
            "step_count": result.step_count,
            "evidence_status": result.evidence_status.value,
            "failure": result.failure,
            "failure_code": result.failure_code,
            "failure_phase": result.failure_phase,
            "diagnostics": thaw_json(result.diagnostics),
        }
        events = tuple(
            {
                "kind": event.kind,
                "payload": thaw_json(event.payload),
            }
            for event in result.events
        )
        events += ({
            "kind": "method.run",
            "payload": {
                "status": result.status.value,
                "run_id": result.run_id,
                "run_digest": result.run_digest,
            },
        },)
        return TransitionProposal(
            machine_id=state.machine_id,
            command_id=command.command_id,
            base_revision=state.revision,
            state_delta={"method": method_state},
            event_payloads=events,
            effect_intent_refs=tuple(receipt.effect_id for receipt in result.effect_receipts),
            wait_reason=(
                None
                if result.status is not MethodRunStatus.INTERRUPTED
                else "method.interrupt"
            ),
        )


__all__ = ["MethodMachineInterpreter"]
