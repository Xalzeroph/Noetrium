from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentResult,
    MethodEvidenceStatus,
    MethodNodeKind,
    MethodNodeResult,
    MethodNodeSpec,
    MethodProgramBuilder,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.providers import JsonMethodCheckpointStore
from noetrium_platform.research.execution.workflow.runtime import (
    InMemoryMethodCheckpointStore,
    KernelOperationDispatcher,
    UniversalMethodMachine,
)


def _identity() -> MethodProgramIdentity:
    return MethodProgramIdentity(MethodIdentity("test.complete.v2", "1", "1", "1"))


def _context(run_id: str = "complete-v2-run") -> ExecutionContext:
    return ExecutionContext(run_id, "trace", "span")


def _dispatcher() -> KernelOperationDispatcher:
    from noetrium_platform.foundation.kernel.kernel import OperationExecutor

    return KernelOperationDispatcher(OperationExecutor())


def _receipt() -> EffectReceipt:
    return EffectReceipt(
        "effect-v2",
        canonical_digest({"request": "v2"}),
        EffectClass.IDEMPOTENT,
        EffectCertainty.EFFECT_CONFIRMED,
    )


def test_agent_node_is_hosted_by_the_machine_and_preserves_agent_checkpoint_and_receipt() -> None:
    class AgentLoop:
        def run(self, request):
            return MethodAgentResult(
                value={"agent_id": request.agent_id, "goal": request.goal},
                state_update={"agent_done": True},
                checkpoint={"agent_step": 1},
                effect_receipts=(_receipt(),),
            )

    program = (
        MethodProgramBuilder(_identity(), entrypoint="agent")
        .agent("agent", "test.agent", "research-agent")
        .build()
    )
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(
            _context(),
            dispatcher=_dispatcher(),
            agent_loop=AgentLoop(),
        ),
        input_value={"objective": "find evidence"},
    )

    assert result.status.value == "succeeded"
    assert result.value["agent_id"] == "research-agent"
    assert result.state["agent_done"] is True
    assert result.state["__noetrium_agent_checkpoints"] == {
        "research-agent": {"agent_step": 1},
    }
    assert result.effect_receipts[0].effect_id == "effect-v2"
    assert len(result.run_digest) == 64


def test_schema_port_is_called_for_program_input_state_and_node_output() -> None:
    class Schemas:
        def __init__(self) -> None:
            self.calls = []

        def validate(self, schema_id, value, *, location):
            self.calls.append((schema_id, location))

    schemas = Schemas()

    def compute(request):
        return MethodNodeResult(value={"answer": 42})

    program = (
        MethodProgramBuilder(_identity(), entrypoint="compute")
        .add(MethodNodeSpec(
            "compute", "test.compute", (), compute, kind=MethodNodeKind.RETURN,
            input_schema="request.v1", output_schema="answer.v1",
        ))
        .build(state_schema="state.v1", input_schema="program-input.v1")
    )
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(_context(), schemas=schemas),
        input_value={"x": 1},
        initial_state={"n": 0},
    )

    assert result.status.value == "succeeded"
    assert ("program-input.v1", "method.input") in schemas.calls
    assert ("state.v1", "method.initial_state") in schemas.calls
    assert ("answer.v1", "method.node.compute.output") in schemas.calls
    assert ("request.v1", "method.node.compute.input") in schemas.calls
    assert ("json", "method.output") in schemas.calls


def test_async_agent_loop_port_is_used_by_async_machine() -> None:
    class AsyncAgentLoop:
        async def run_async(self, request):
            return MethodAgentResult(value={"async": request.agent_id})

    program = (
        MethodProgramBuilder(_identity(), entrypoint="agent")
        .agent("agent", "test.agent.async", "async-research-agent")
        .build()
    )

    import asyncio

    result = asyncio.run(UniversalMethodMachine().run_async(
        program,
        runtime=MethodRuntimeContext(_context("async-agent-v2-run"), agent_loop=AsyncAgentLoop()),
        input_value={"objective": "continue"},
    ))
    assert result.status.value == "succeeded"
    assert result.value == {"async": "async-research-agent"}


def test_multiple_agent_nodes_preserve_each_continuation_checkpoint() -> None:
    class AgentLoop:
        def run(self, request):
            return MethodAgentResult(value=request.agent_id, checkpoint={"agent": request.agent_id})

    program = (
        MethodProgramBuilder(_identity(), entrypoint="first")
        .agent("first", "test.agent.first", "first-agent", ("second",))
        .agent("second", "test.agent.second", "second-agent")
        .build()
    )
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(_context("multi-agent-v2-run"), agent_loop=AgentLoop()),
    )
    assert result.state["__noetrium_agent_checkpoints"] == {
        "first-agent": {"agent": "first-agent"},
        "second-agent": {"agent": "second-agent"},
    }


def test_checkpoint_store_is_monotonic_and_json_store_round_trips_receipts(tmp_path: Path) -> None:
    def pause(request):
        return MethodNodeResult(value={"step": request.visit}, checkpoint=True)

    program = (
        MethodProgramBuilder(_identity(), entrypoint="pause")
        .add(MethodNodeSpec("pause", "test.pause", (), pause, kind=MethodNodeKind.RETURN))
        .build()
    )
    store = InMemoryMethodCheckpointStore()
    result = UniversalMethodMachine(checkpoint_store=store).run(
        program,
        runtime=MethodRuntimeContext(_context()),
    )
    checkpoint = result.checkpoint
    assert checkpoint is None

    # A terminating RETURN does not need a persisted checkpoint; use a loop to
    # exercise the provider without changing the method's terminal semantics.
    loop_program = (
        MethodProgramBuilder(_identity(), entrypoint="loop")
        .add(MethodNodeSpec("loop", "test.loop", ("loop",), pause, max_visits=2))
        .build()
    )
    loop_result = UniversalMethodMachine(checkpoint_store=store, max_steps=1).run(
        loop_program,
        runtime=MethodRuntimeContext(_context("checkpoint-v2-run")),
    )
    assert loop_result.checkpoint is not None

    json_store = JsonMethodCheckpointStore(tmp_path)
    json_store.save(loop_result.checkpoint)
    restored = json_store.load("checkpoint-v2-run")
    assert restored is not None
    assert restored.checkpoint_id == loop_result.checkpoint.checkpoint_id
    assert restored.effect_receipts == loop_result.checkpoint.effect_receipts


def test_evidence_obligations_are_not_reported_complete_without_authoritative_sink() -> None:
    program = (
        MethodProgramBuilder(_identity(), entrypoint="return")
        .return_node("return", "test.return", lambda request: MethodNodeResult(value={"ok": True}))
        .build(evidence_obligations=("claim_has_source",))
    )
    result = UniversalMethodMachine().run(program, runtime=MethodRuntimeContext(_context()))
    assert result.status.value == "succeeded"
    assert result.evidence_status is MethodEvidenceStatus.INCOMPLETE


def test_platform_facade_hosts_the_universal_machine_without_runtime_imports() -> None:
    from noetrium.platform import bind_method_checkpoint_store, bind_universal_method_machine, run_method_program

    program = (
        MethodProgramBuilder(_identity(), entrypoint="return")
        .return_node("return", "test.facade", lambda request: MethodNodeResult(value={"ok": True}))
        .build()
    )
    machine = bind_universal_method_machine()
    result = run_method_program(
        program,
        runtime=MethodRuntimeContext(_context("platform-facade-v2-run")),
        machine=machine,
    )
    assert result.status.value == "succeeded"
    assert result.value == {"ok": True}


def test_platform_facade_binds_durable_method_checkpoints(tmp_path: Path) -> None:
    from noetrium.platform import bind_method_checkpoint_store

    store = bind_method_checkpoint_store(tmp_path / "method-checkpoints")
    assert isinstance(store, JsonMethodCheckpointStore)


def test_platform_facade_exposes_async_execution() -> None:
    import asyncio

    from noetrium.platform import run_method_program_async

    program = (
        MethodProgramBuilder(_identity(), entrypoint="return")
        .return_node("return", "test.async-facade", lambda request: MethodNodeResult(value={"async": True}))
        .build()
    )

    async def execute():
        return await run_method_program_async(
            program,
            runtime=MethodRuntimeContext(_context("platform-async-facade-v2-run")),
        )

    result = asyncio.run(execute())
    assert result.status.value == "succeeded"
    assert result.value == {"async": True}
