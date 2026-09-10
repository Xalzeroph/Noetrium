from __future__ import annotations

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext, OperationExecutor
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeKind,
    MethodNodeResult,
    MethodNodeSpec,
    MethodProgramBuilder,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import (
    InMemoryMethodCheckpointStore,
    KernelOperationDispatcher,
    UniversalMethodMachine,
)


def _identity() -> MethodProgramIdentity:
    return MethodProgramIdentity(MethodIdentity("test.method", "1", "1", "1"))


def _context() -> ExecutionContext:
    return ExecutionContext("run-1", "trace-1", "span-1")


def test_program_runs_through_kernel_dispatch_and_checkpointing() -> None:
    def compute(request):
        return MethodNodeResult(
            value={"answer": 42},
            state_update={"done": True},
            events=(),
        )

    def finish(request):
        return MethodNodeResult(value=request.state["done"])

    program = (
        MethodProgramBuilder(_identity(), entrypoint="compute")
        .add(MethodNodeSpec("compute", "method.compute", ("finish",), compute))
        .add(MethodNodeSpec("finish", "method.finish", (), finish, kind=MethodNodeKind.RETURN))
        .build()
    )
    machine = UniversalMethodMachine(checkpoint_store=InMemoryMethodCheckpointStore())
    result = machine.run(
        program,
        runtime=MethodRuntimeContext(_context(), dispatcher=KernelOperationDispatcher(OperationExecutor())),
        input_value={},
    )
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value is True
    assert result.state["done"] is True


def test_loop_is_explicitly_bounded_and_capability_is_typed() -> None:
    class Capabilities:
        def describe(self, capability_id):
            return CapabilityDescriptor(capability_id, "1", "json", "json", EffectClass.PURE)

        def invoke(self, request: CapabilityRequest):
            return CapabilityResult(request.capability_id, {"ok": True})

    def route(request):
        count = int(request.state.get("count", 0)) + 1
        return MethodNodeResult(
            value=count,
            state_update={"count": count},
            next_node="route" if count < 2 else "observe",
        )

    program = (
        MethodProgramBuilder(_identity(), entrypoint="route")
        .add(MethodNodeSpec("route", "method.route", ("route", "observe"), route, kind=MethodNodeKind.ROUTE, max_visits=3))
        .add(MethodNodeSpec("observe", "method.observe", (), kind=MethodNodeKind.CAPABILITY, capability_id="observe"))
        .build()
    )
    result = UniversalMethodMachine().run(
        program,
        runtime=MethodRuntimeContext(_context(), capabilities=Capabilities()),
        input_value={"query": "x"},
    )
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value == {"ok": True}


def test_interrupt_checkpoint_can_resume_at_next_node() -> None:
    store = InMemoryMethodCheckpointStore()

    def finish(request):
        return MethodNodeResult(value="resumed")

    program = (
        MethodProgramBuilder(_identity(), entrypoint="pause")
        .add(MethodNodeSpec("pause", "method.pause", ("finish",), kind=MethodNodeKind.INTERRUPT))
        .add(MethodNodeSpec("finish", "method.finish", (), finish, kind=MethodNodeKind.RETURN))
        .build()
    )
    machine = UniversalMethodMachine(checkpoint_store=store)
    first = machine.run(program, runtime=MethodRuntimeContext(_context()))
    assert first.status is MethodRunStatus.INTERRUPTED
    resumed = machine.run(program, runtime=MethodRuntimeContext(_context()), resume=True)
    assert resumed.status is MethodRunStatus.SUCCEEDED
    assert resumed.value == "resumed"
