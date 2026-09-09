from __future__ import annotations

import asyncio

import pytest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectCertainty,
    EffectClass,
    EffectReceipt,
    ExecutionContext,
    OperationResult,
    OperationStatus,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeKind,
    MethodNodeResult,
    MethodNodeSpec,
    MethodProgramBuilder,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.api.adapters import (
    ResearchMethodProgramAdapter,
)
from noetrium_platform.research.execution.workflow.runtime import (
    InMemoryMethodCheckpointStore,
    KernelOperationDispatcher,
    UniversalMethodMachine,
)


def _identity() -> MethodProgramIdentity:
    return MethodProgramIdentity(MethodIdentity("test.complete.method", "1", "1", "1"))


def _context() -> ExecutionContext:
    return ExecutionContext("complete-run", "trace", "span")


def _dispatcher() -> KernelOperationDispatcher:
    from noetrium_platform.foundation.kernel.kernel import OperationExecutor
    return KernelOperationDispatcher(OperationExecutor())


class AsyncRecordingDispatcher:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch_async(self, **kwargs: object) -> OperationResult[object]:
        self.calls += 1
        handler = kwargs["handler"]
        output = handler(None)
        if hasattr(output, "__await__"):
            output = await output
        return OperationResult(
            kwargs["operation_id"],
            "async-invocation",
            OperationStatus.SUCCEEDED,
            output=output,
            effect_receipts=tuple(output.effect_receipts),
        )

    def require(self, result: OperationResult[object]) -> object:
        assert result.status is OperationStatus.SUCCEEDED
        return result.output


def test_async_nodes_use_the_async_operation_boundary() -> None:
    dispatcher = AsyncRecordingDispatcher()

    async def compute(request):
        return MethodNodeResult(value={"ok": True})

    program = (
        MethodProgramBuilder(_identity(), entrypoint="compute")
        .add(MethodNodeSpec("compute", "test.compute", (), compute, kind=MethodNodeKind.RETURN))
        .build(execution_class=MethodExecutionClass.EFFECT_RECORDED)
    )

    result = asyncio.run(
        UniversalMethodMachine().run_async(
            program,
            runtime=MethodRuntimeContext(_context(), async_dispatcher=dispatcher),
        )
    )

    assert result.value == {"ok": True}
    assert dispatcher.calls == 1


def test_async_capability_effect_is_projected_through_kernel_dispatch() -> None:
    effect = EffectReceipt(
        "effect-1",
        canonical_digest({"request": "x"}),
        EffectClass.IDEMPOTENT,
        EffectCertainty.EFFECT_CONFIRMED,
    )

    class AsyncCapabilities:
        def describe(self, capability_id):
            return CapabilityDescriptor(capability_id, "1", "json", "json", EffectClass.IDEMPOTENT)

        async def invoke(self, request: CapabilityRequest):
            return CapabilityResult(request.capability_id, {"done": True}, effect=effect)

    program = (
        MethodProgramBuilder(_identity(), entrypoint="call")
        .add(MethodNodeSpec("call", "test.capability", (), kind=MethodNodeKind.CAPABILITY,
                            capability_id="model"))
        .build(required_capabilities=("model",))
    )
    result = asyncio.run(
        UniversalMethodMachine().run_async(
            program,
            runtime=MethodRuntimeContext(
                _context(),
                capabilities=AsyncCapabilities(),
                dispatcher=_dispatcher(),
            ),
        )
    )

    assert result.status.value == "succeeded"
    assert result.value == {"done": True}


def test_resume_preserves_visit_limits_and_event_lineage() -> None:
    store = InMemoryMethodCheckpointStore()

    def loop(request):
        return MethodNodeResult(
            value=request.visit,
            state_update={"n": request.visit},
            next_node="loop",
            checkpoint=True,
        )

    program = (
        MethodProgramBuilder(_identity(), entrypoint="loop")
        .add(MethodNodeSpec("loop", "test.loop", ("loop",), loop, max_visits=2))
        .build()
    )
    machine = UniversalMethodMachine(checkpoint_store=store, max_steps=1)
    first = machine.run(program, runtime=MethodRuntimeContext(_context()))
    assert first.checkpoint is not None
    assert len(first.events) == 1

    resumed = UniversalMethodMachine(checkpoint_store=store, max_steps=3).run(
        program,
        runtime=MethodRuntimeContext(_context()),
        resume=True,
    )
    assert resumed.status.value == "limit_reached"
    assert len(resumed.events) >= 2
    assert resumed.failure == "node visit limit reached: loop"


def test_resume_rejects_binding_identity_drift() -> None:
    store = InMemoryMethodCheckpointStore()

    program = (
        MethodProgramBuilder(_identity(), entrypoint="pause")
        .add(MethodNodeSpec("pause", "test.pause", (), kind=MethodNodeKind.INTERRUPT))
        .build()
    )
    digest_a = canonical_digest({"binding": "a"})
    digest_b = canonical_digest({"binding": "b"})
    machine = UniversalMethodMachine(checkpoint_store=store)
    first = machine.run(
        program,
        runtime=MethodRuntimeContext(_context(), binding_plan_digest=digest_a),
    )
    assert first.checkpoint is not None
    with pytest.raises(ValueError, match="binding_plan_digest"):
        machine.run(
            program,
            runtime=MethodRuntimeContext(_context(), binding_plan_digest=digest_b),
            resume=True,
        )


def test_research_method_program_adapter_uses_canonical_machine() -> None:
    class ProjectMethod:
        program_identity = _identity()

        def run(self, *, task, input_value, context):
            return {"task": task, "input": input_value, "run": context.run_id}

    program = ResearchMethodProgramAdapter(ProjectMethod(), {"task": "x"}).to_method_program()
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(_context()),
        input_value={"value": 7},
    )

    assert result.status.value == "succeeded"
    assert result.value["task"] == {"task": "x"}
    assert result.value["input"] == {"value": 7}
