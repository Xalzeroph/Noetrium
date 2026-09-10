from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    MachineCommand,
    MachineProgramRef,
    MachineSnapshot,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api.method_machine import (
    MethodEvidenceStatus,
    MethodRunResult,
    MethodRunStatus,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime.machine_adapter import (
    MethodMachineInterpreter,
)


class FakeMethodMachine:
    def run(self, program, *, runtime, input_value=None, initial_state=None, resume=False):
        assert input_value == {"question": "q"}
        assert initial_state == {"counter": 0}
        return MethodRunResult(
            status=MethodRunStatus.SUCCEEDED,
            run_id="method-run-1",
            program_digest=canonical_digest({"program": "fake"}),
            value={"answer": 42},
            state={"counter": 1},
            evidence_status=MethodEvidenceStatus.COMPLETE,
            step_count=1,
        )


def test_method_machine_adapter_projects_result_into_transition() -> None:
    program = object()
    runtime = MethodRuntimeContext(
        execution=ExecutionContext(
            run_id="run-1",
            trace_id="trace-1",
            span_id="span-1",
        ),
    )
    interpreter = MethodMachineInterpreter(
        machine=FakeMethodMachine(),
        program=program,
        runtime=runtime,
    )
    snapshot = MachineSnapshot(
        machine_id="method-1",
        revision=0,
        program=MachineProgramRef(
            program_digest=canonical_digest({"program": "machine"}),
            schema_id="method.v1",
            program_kind="method",
            program_version="1",
        ),
        state={"counter": 0},
        parent_commit_id=None,
    )
    proposal = interpreter.propose(
        MachineCommand(
            command_id="command-1",
            machine_id="method-1",
            expected_revision=0,
            kind="method.run",
            payload={"input": {"question": "q"}},
            scope=("run:run-1", "method:method-1"),
        ),
        snapshot,
    )
    assert proposal.state_delta["method"]["status"] == "succeeded"
    assert proposal.state_delta["method"]["value"]["answer"] == 42
