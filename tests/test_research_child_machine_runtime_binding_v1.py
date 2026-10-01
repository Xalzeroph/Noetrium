from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from noetrium import api
import noetrium_platform.research.execution.api as execution_api
import noetrium_platform.product.research_os as product_api
import noetrium_platform.foundation.kernel.kernel as kernel_api
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_local import compose_local_research_os
from noetrium_platform.research.execution.machines.child_machine import ChildResearchHostRegistry


_CHILD_CALLS: list[str] = []


def _child_dispatch(
    request: execution_api.ProgramNodeRequest,
    binding: object,
) -> execution_api.ProgramNodeResult:
    del binding
    _CHILD_CALLS.append(str(request.payload))
    return execution_api.ProgramNodeResult(
        value={"child": "ok", "payload": request.payload},
        state_update={"called": True},
        status=kernel_api.MachineStatus.COMPLETED,
    )


CHILD_PROGRAM = (
    execution_api.MemoryProgramBuilder.create(
        program_id="test.child-memory",
        version="1",
        state_schema="test.child-memory.state.v1",
        entrypoint="dispatch",
    )
    .custom(
        "dispatch",
        "test.child.dispatch",
        configuration={"kind": "runtime-fixture"},
    )
    .build()
)


def child_operations() -> tuple[execution_api.ResearchHostOperation, ...]:
    return (
        execution_api.ResearchHostOperation(
            "test.child.dispatch",
            _child_dispatch,
            kernel_api.canonical_digest(
                {
                    "operation": "test.child.dispatch",
                    "implementation_revision": 1,
                }
            ),
        ),
    )


def _invoke_child(request: execution_api.MethodNodeRequest) -> execution_api.MethodNodeResult:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError("declared child runtime was not injected")
    child = request.child_machines.execute(
        execution_api.ChildResearchMachineRequest(
            host_id="test.child-memory",
            parent_machine_id=request.parent_machine_id,
            child_machine_id="memory:test-child:1",
            instance_identity={"fixture": "program-scoped-child"},
            initial_data={},
            payload={"event": "ping"},
        )
    )
    if not isinstance(child, execution_api.ChildResearchMachineExecution):
        raise TypeError("child execution result is invalid")
    if child.status is not kernel_api.MachineStatus.COMPLETED:
        raise RuntimeError(f"child did not complete: {child.status}")
    return execution_api.MethodNodeResult(
        value=child.result,
        child_links=(child.link,),
    )


def _return_parent(request: execution_api.MethodNodeRequest) -> execution_api.MethodNodeResult:
    del request
    return execution_api.MethodNodeResult(value=None)


def build_parent_method() -> execution_api.MethodProgram:
    identity = execution_api.MethodProgramIdentity(
        execution_api.MethodIdentity(
            "test.parent-method",
            "1",
            "method-runtime.v1",
            "test.parent-method.v1",
        )
    )
    return (
        execution_api.MethodProgramBuilder(identity, entrypoint="invoke-child")
        .compute(
            "invoke-child",
            "test.parent.invoke-child",
            _invoke_child,
            ("return",),
        )
        .return_node(
            "return",
            "test.parent.return",
            _return_parent,
        )
        .build(
            required_runtime_ports=(execution_api.MethodRuntimePort.CHILD_MACHINES,),
        )
    )


def _portfolio(*, child_revision: int) -> product_api.ResearchPortfolio:
    builder = product_api.ResearchProgramBuilder("paper")
    builder.method_configurer(
        "parent-method",
        module=__name__,
        qualname="build_parent_method",
    )
    builder.child_machine_program(
        "test.child-memory",
        program_module=__name__,
        program_qualname="CHILD_PROGRAM",
        operations_module=__name__,
        operations_qualname="child_operations",
        config={"declaration_revision": child_revision},
    )
    builder.method_node(
        "run",
        definitions=("parent-method",),
    )
    return product_api.ResearchPortfolio("child-runtime-suite", (builder.freeze(),))


def _revision(portfolio: product_api.ResearchPortfolio, message: str) -> product_api.ResearchGraphRevision:
    return product_api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        message,
    )


def test_child_machine_declaration_is_part_of_program_node_semantic_identity() -> None:
    first = _portfolio(child_revision=1)
    second = _portfolio(child_revision=2)

    first_graph = compile_research_portfolio_graph(_revision(first, "first"), first)
    second_graph = compile_research_portfolio_graph(_revision(second, "second"), second)

    assert (
        first_graph.node("paper::run").semantic_digest
        != second_graph.node("paper::run").semantic_digest
    )


def test_canonical_runtime_auto_binds_program_scoped_child_machine(
    tmp_path: Path,
) -> None:
    _CHILD_CALLS.clear()
    composition = compose_local_research_os(tmp_path / "research-os")
    try:
        portfolio = _portfolio(child_revision=1)
        revision = composition.research_os.commit(
            portfolio,
            message="declared child runtime",
        )
        receipt = composition.research_os.run(
            product_api.ResearchExecutionTarget("child-runtime", revision)
        )

        assert receipt.state == "succeeded", receipt.payload
        assert len(_CHILD_CALLS) == 1
        assert "ping" in _CHILD_CALLS[0]
    finally:
        composition.close()


class _SlowMachineJournal(kernel_api.InMemoryMachineJournal):
    def append(self, commit):
        # Widen the read-head -> append race that used to let two sessions
        # propose from the same durable revision.
        time.sleep(0.02)
        return super().append(commit)


def test_child_executor_serializes_same_machine_without_throttling_machine_identity() -> None:
    journal = _SlowMachineJournal()
    program = (
        execution_api.MemoryProgramBuilder.create(
            program_id="test.concurrent-child",
            version="1",
            state_schema="test.concurrent-child.state.v1",
            entrypoint="dispatch",
        )
        .custom(
            "dispatch",
            "test.concurrent-child.dispatch",
            next_node="dispatch",
        )
        .build()
    )

    def dispatch(request, binding):
        del binding
        return execution_api.ProgramNodeResult(
            value=request.payload,
            state_update={"last": request.payload},
        )

    host = execution_api.ResearchProgramHost(
        host_id="test.concurrent-child",
        program=program,
        operations=(
            execution_api.ResearchHostOperation(
                "test.concurrent-child.dispatch",
                dispatch,
                kernel_api.canonical_digest(
                    {
                        "operation": "test.concurrent-child.dispatch",
                        "implementation_revision": 1,
                    }
                ),
            ),
        ),
        journal=journal,
    )
    registry = ChildResearchHostRegistry()
    registry.register_static(host)
    executor = registry.executor()
    child_machine_id = "memory:shared-concurrent-child"

    def invoke(index: int):
        return executor.step_once(
            execution_api.ChildResearchMachineRequest(
                host_id="test.concurrent-child",
                parent_machine_id=f"parent:{index}",
                child_machine_id=child_machine_id,
                instance_identity={"scope": "shared"},
                initial_data={},
                payload={"index": index},
                command_id_prefix=f"concurrent:{index}",
            )
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        executions = tuple(pool.map(invoke, range(8)))

    assert len(executions) == 8
    assert all(row.execution.machine_id == child_machine_id for row in executions)
    assert journal.latest(child_machine_id).revision == 9
    assert executor._machine_locks == {}
