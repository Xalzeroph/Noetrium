from __future__ import annotations

import asyncio
import multiprocessing

import pytest

from noetrium import platform as noetrium_platform
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodCheckpoint,
    MethodAgentResult,
    MethodEvidenceStatus,
    MethodNodeResult,
    MethodProgramBuilder,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition import (
    bind_machine_method_runtime,
)
from noetrium_platform.research.execution.workflow.runtime import (
    InMemoryMethodCheckpointStore,
    UniversalMethodMachine,
)
from noetrium_platform.research.execution.workflow.providers import (
    JsonMethodCheckpointStore,
    MethodCheckpointCorruptionError,
)


def identity() -> MethodProgramIdentity:
    return MethodProgramIdentity(MethodIdentity("test.abi.v2", "1", "1", "1"))


def context() -> ExecutionContext:
    return ExecutionContext("abi-v2-run", "trace", "span")


def _empty_agent_view(request):
    return {}


def _public_agent_view(request):
    return {"public": request.state.get("public")}


def _checkpoint_receipt(run_id: str, *, marker: str) -> MethodCheckpoint:
    return MethodCheckpoint(
        run_id=run_id,
        program_digest=canonical_digest({"program": run_id}),
        sequence=1,
        current_node="finish",
        machine_id=f"method:{run_id}",
        machine_revision=1,
        machine_commit_id=canonical_digest({"commit": run_id, "marker": marker}),
        state_digest=canonical_digest({"state": run_id, "marker": marker}),
        checkpoint_value={"marker": marker},
    )


def _checkpoint_competitor(root, gate, result_queue, worker):
    store = JsonMethodCheckpointStore(root)
    checkpoint = _checkpoint_receipt("competing-run", marker=worker)
    gate.wait(10)
    try:
        store.save(checkpoint)
    except Exception as exc:  # the loser must report a deterministic conflict
        result_queue.put(type(exc).__name__)
    else:
        result_queue.put("ok")


def test_durable_checkpoint_store_serializes_process_competition(tmp_path) -> None:
    context_factory = multiprocessing.get_context("spawn")
    gate = context_factory.Event()
    result_queue = context_factory.Queue()
    processes = [
        context_factory.Process(
            target=_checkpoint_competitor,
            args=(str(tmp_path / "checkpoints"), gate, result_queue, worker),
        )
        for worker in ("one", "two")
    ]
    for process in processes:
        process.start()
    gate.set()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    statuses = [result_queue.get(timeout=2) for _ in processes]
    assert sorted(statuses) == ["ValueError", "ok"]
    final = JsonMethodCheckpointStore(tmp_path / "checkpoints").load("competing-run")
    assert final is not None
    assert final.sequence == 1
    assert final.machine_revision == 1


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
        .agent(
            "agent",
            "test.agent",
            "agent-1",
            next_nodes=("finish",),
            view_handler=_empty_agent_view,
        )
        .return_node("finish", "test.finish", finish)
        .build()
    )
    runtime = bind_machine_method_runtime(
        program, MethodRuntimeContext(context(), agent_loop=Agent())
    )
    first = UniversalMethodMachine(checkpoint_store=store, max_steps=1).run(
        program,
        runtime=runtime,
    )
    assert first.checkpoint is not None
    assert first.checkpoint.checkpoint_value == {"cursor": 1}
    assert seen == [None]
    resumed = UniversalMethodMachine(checkpoint_store=store).run(
        program,
        runtime=runtime,
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
        .agent(
            "agent",
            "test.agent",
            "async-agent",
            view_handler=_empty_agent_view,
        )
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
        "program.state.v1",
        "node.input.v1",
        "node.output.v1",
        "program.state.v1",
        "json",
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


def test_async_agent_receives_agent_abi_and_can_route():
    seen = []

    class Agent:
        async def run_async(self, request):
            assert isinstance(request, MethodAgentRequest)
            seen.append(request)
            return MethodAgentResult(value={"agent": True}, next_node="finish")

    program = (
        MethodProgramBuilder(identity(), entrypoint="agent")
        .agent(
            "agent",
            "test.agent",
            "agent-1",
            next_nodes=("finish",),
            view_handler=_empty_agent_view,
        )
        .return_node("finish", "test.finish", lambda request: MethodNodeResult(value={"done": True}))
        .build()
    )
    result = asyncio.run(UniversalMethodMachine().run_async(
        program, runtime=MethodRuntimeContext(context(), agent_loop=Agent())
    ))
    assert result.value == {"done": True}
    assert seen[0].agent_id == "agent-1"


def test_agent_request_exposes_only_explicit_model_view():
    seen = []

    class Agent:
        def run(self, request):
            seen.append(request)
            assert request.view == {"public": "visible"}
            assert not hasattr(request, "state")
            return MethodAgentResult(value={"done": True})

    program = (
        MethodProgramBuilder(identity(), entrypoint="agent")
        .agent(
            "agent",
            "test.agent-view",
            "agent-view",
            view_handler=_public_agent_view,
        )
        .build()
    )
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(context(), agent_loop=Agent()),
        initial_state={"public": "visible", "secret": "host-only"},
    )

    assert result.status.value == "succeeded"
    assert result.value == {"done": True}
    assert seen[0].view == {"public": "visible"}


def test_resume_is_explicit_when_checkpoint_is_unavailable():
    program = MethodProgramBuilder(identity(), entrypoint="answer").return_node(
        "answer", "test.answer", lambda request: MethodNodeResult(value=42)
    ).build()
    with pytest.raises(ValueError, match="checkpoint"):
        UniversalMethodMachine().run(
            program, runtime=MethodRuntimeContext(context()), resume=True
        )


def test_public_facade_binds_durable_checkpoint_store(tmp_path) -> None:
    store = noetrium_platform.bind_method_checkpoint_store(tmp_path / "checkpoints")
    checkpoint = _checkpoint_receipt("durable-run", marker="durable")
    store.save(checkpoint)
    restored = noetrium_platform.bind_method_checkpoint_store(tmp_path / "checkpoints")
    assert restored.load("durable-run") == checkpoint


def test_durable_checkpoint_corruption_fails_closed(tmp_path) -> None:
    root = tmp_path / "checkpoints"
    store = noetrium_platform.bind_method_checkpoint_store(root)
    checkpoint = _checkpoint_receipt("corrupt-run", marker="corrupt")
    store.save(checkpoint)
    (root / "corrupt-run.json").write_text("{", encoding="utf-8")
    with pytest.raises(MethodCheckpointCorruptionError):
        store.load("corrupt-run")


def test_public_facade_preserves_method_wall_clock_budget():
    ticks = iter((0.0, 2.0))
    program = MethodProgramBuilder(identity(), entrypoint="answer").return_node(
        "answer", "test.answer", lambda request: MethodNodeResult(value=42)
    ).build()
    result = noetrium_platform.bind_universal_method_machine(
        max_seconds=1, clock=lambda: next(ticks)
    ).run(program, runtime=MethodRuntimeContext(context()))
    assert result.status.value == "limit_reached"
    assert result.failure_code == "METHOD_TIMEOUT"
