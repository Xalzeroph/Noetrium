from __future__ import annotations

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeResult,
    MethodProgramBuilder,
    MethodRuntimePortInventory,
)
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentTaskSpec

from research.reproductions.contracts import ReproductionMethodWorkloadBinding
from research.reproductions.workload_composition import (
    compose_reproduction_method_workload,
)


def _program():
    identity = MethodProgramIdentity(
        MethodIdentity("fixture.workload", "1", "1", "1")
    )

    def finish(request):
        return MethodNodeResult(
            value={
                "completion": request.state["question"],
                "task_id": request.state["task_id"],
            }
        )

    return (
        MethodProgramBuilder(identity, entrypoint="finish")
        .return_node("finish", "fixture.finish", finish)
        .build()
    )


def test_reproduction_workload_binding_drives_canonical_method_machine(tmp_path) -> None:
    workload = compose_reproduction_method_workload(
        _program(),
        ReproductionMethodWorkloadBinding(
            initial_state_fields=(
                ("task_id", "task_id"),
                ("question", "payload.question"),
            ),
            result_fields=(("completion", "value.completion"),),
        ),
        MethodRuntimePortInventory(),
        state_root=tmp_path / "state",
    )
    result = workload.execute_one(
        ExperimentTaskSpec(
            "fixture-task",
            "qa",
            "Solve",
            payload={"question": "downstream-owned-input"},
        ),
        ExecutionContext("run", "trace", "span"),
    )
    assert result.success is True
    assert result.exports == {"completion": "downstream-owned-input"}
    method_receipt = dict(result.participant_receipts)["method"]
    assert method_receipt.status == "succeeded"


def test_reproduction_workload_composition_rejects_missing_runtime_port(tmp_path) -> None:
    identity = MethodProgramIdentity(
        MethodIdentity("fixture.agent", "1", "1", "1")
    )
    program = (
        MethodProgramBuilder(identity, entrypoint="agent")
        .agent(
            "agent",
            "fixture.agent",
            "agent-a",
            ("done",),
            view_handler=lambda request: {"prompt": "downstream prompt"},
         )
        .return_node(
            "done",
            "fixture.done",
            lambda request: MethodNodeResult(value=request.previous_value),
         )
        .build()
    )
    try:
        compose_reproduction_method_workload(
            program,
            ReproductionMethodWorkloadBinding(
                initial_state_fields=(("task_id", "task_id"),)
            ),
            MethodRuntimePortInventory(),
            state_root=tmp_path / "state",
        )
    except RuntimeError as exc:
        assert "port:agent_loop" in str(exc)
    else:
        raise AssertionError("missing Method runtime port must fail closed")
