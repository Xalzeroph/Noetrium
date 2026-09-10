from __future__ import annotations

import asyncio

from noetrium import platform as noetrium_platform
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentResult,
    MethodEvidenceStatus,
    MethodNodeResult,
    MethodProgramBuilder,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import (
    InMemoryMethodCheckpointStore,
    UniversalMethodMachine,
)


def identity() -> MethodProgramIdentity:
    return MethodProgramIdentity(MethodIdentity("test.abi.v2", "1", "1", "1"))


def context() -> ExecutionContext:
    return ExecutionContext("abi-v2-run", "trace", "span")


def test_agent_checkpoint_payload_survives_limit_and_resume() -> None:
    store = InMemoryMethodCheckpointStore()
    seen = []

    class Agent:
        def run(self, request):
            seen.append(request.checkpoint)
            return MethodAgentResult(value={"step": 1}, checkpoint={"cursor": 1})

    def finish(request):
        return MethodNodeResult(value=request.checkpoint if hasattr(request, "checkpoint") else request.previous_value)

    program = (
        MethodProgramBuilder(identity(), entrypoint="agent")
        .agent("agent", "test.agent", "agent-1", next_nodes=("finish",))
        .return_node("finish", "test.finish", finish)
        .build()
    )
    first = UniversalMethodMachine(checkpoint_store=store, max_steps=1).run(
        program,
        runtime=MethodRuntimeContext(context(), agent_loop=Agent()),
    )
    assert first.checkpoint is not None
    assert first.checkpoint.checkpoint_value == {"cursor": 1}
    assert seen == [None]
    resumed = UniversalMethodMachine(checkpoint_store=store).run(
        program,
        runtime=MethodRuntimeContext(context(), agent_loop=Agent()),
        resume=True,
    )
    assert resumed.status.value == "succeeded"
    assert resumed.value == {"cursor": 1}


def test_async_only_agent_loop_is_supported() -> None:
    class AsyncOnlyAgent:
        async def run_async(self, request):
            return MethodAgentResult(value={"async": True})

    program = (
        MethodProgramBuilder(identity(), entrypoint="agent")
        .agent("agent", "test.agent", "async-agent")
        .build()
    )
    result = asyncio.run(
        UniversalMethodMachine().run_async(
            program,
            runtime=MethodRuntimeContext(context(), agent_loop=AsyncOnlyAgent()),
        )
    )
    assert result.value == {"async": True}


def test_node_schema_port_validates_program_and_node_boundaries() -> None:
    calls = []

    class Schemas:
        def validate(self, schema_id, value, *, location):
            calls.append((schema_id, value, location))

    def compute(request):
        return MethodNodeResult(value={"ok": True})

    program = (
        MethodProgramBuilder(identity(), entrypoint="compute")
        .compute(
            "compute",
            "test.compute",
            compute,
            input_schema="node.input.v1",
            output_schema="node.output.v1",
        )
        .build(input_schema="program.input.v1", state_schema="program.state.v1")
    )
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(context(), schemas=Schemas()),
        input_value={"x": 1},
    )
    assert result.value == {"ok": True}
    assert [item[0] for item in calls] == [
        "program.input.v1",
        "program.state.v1",
        "node.input.v1",
        "node.output.v1",
    ]


def test_evidence_validator_receives_the_real_run_result() -> None:
    seen = []

    class Evidence:
        def record_checkpoint(self, checkpoint):
            pass

        def record_result(self, result):
            seen.append(("record", result))

        def validate_result(self, result, obligations):
            seen.append(("validate", result, obligations))
            assert result.run_id == "abi-v2-run"
            assert result.value == {"answer": 42}
            return MethodEvidenceStatus.COMPLETE

    program = (
        MethodProgramBuilder(identity(), entrypoint="answer")
        .return_node(
            "answer",
            "test.answer",
            lambda request: MethodNodeResult(value={"answer": 42}),
        )
        .build(evidence_obligations=("answer.present",))
    )
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(context(), evidence=Evidence()),
    )
    assert result.evidence_status is MethodEvidenceStatus.COMPLETE
    assert seen[0][0] == "validate"
    assert seen[0][1] is not None
    assert seen[-1] == ("record", result)


def test_public_platform_facade_binds_universal_method_machine():
    machine = noetrium_platform.bind_universal_method_machine(max_steps=3)
    assert isinstance(machine, UniversalMethodMachine)
