from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_local import compose_local_research_os


_CHILD_CALLS: list[str] = []


def _child_dispatch(
    request: api.ProgramNodeRequest,
    binding: object,
) -> api.ProgramNodeResult:
    del binding
    _CHILD_CALLS.append(str(request.payload))
    return api.ProgramNodeResult(
        value={"child": "ok", "payload": request.payload},
        state_update={"called": True},
        status=api.MachineStatus.COMPLETED,
    )


CHILD_PROGRAM = (
    api.MemoryProgramBuilder.create(
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


def child_operations() -> tuple[api.ResearchHostOperation, ...]:
    return (
        api.ResearchHostOperation(
            "test.child.dispatch",
            _child_dispatch,
            api.canonical_digest(
                {
                    "operation": "test.child.dispatch",
                    "implementation_revision": 1,
                }
            ),
        ),
    )


def _invoke_child(request: api.MethodNodeRequest) -> api.MethodNodeResult:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError("declared child runtime was not injected")
    child = request.child_machines.execute(
        api.ChildResearchMachineRequest(
            host_id="test.child-memory",
            parent_machine_id=request.parent_machine_id,
            child_machine_id="memory:test-child:1",
            instance_identity={"fixture": "program-scoped-child"},
            initial_data={},
            payload={"event": "ping"},
        )
    )
    if not isinstance(child, api.ChildResearchMachineExecution):
        raise TypeError("child execution result is invalid")
    if child.status is not api.MachineStatus.COMPLETED:
        raise RuntimeError(f"child did not complete: {child.status}")
    return api.MethodNodeResult(
        value=child.result,
        child_links=(child.link,),
    )


def _return_parent(request: api.MethodNodeRequest) -> api.MethodNodeResult:
    del request
    return api.MethodNodeResult(value=None)


def build_parent_method() -> api.MethodProgram:
    identity = api.MethodProgramIdentity(
        api.MethodIdentity(
            "test.parent-method",
            "1",
            "method-runtime.v1",
            "test.parent-method.v1",
        )
    )
    return (
        api.MethodProgramBuilder(identity, entrypoint="invoke-child")
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
            required_runtime_ports=(api.MethodRuntimePort.CHILD_MACHINES,),
        )
    )


def _portfolio(*, child_revision: int) -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.method_program_factory(
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
    return api.ResearchPortfolio("child-runtime-suite", (builder.freeze(),))


def _revision(portfolio: api.ResearchPortfolio, message: str) -> api.ResearchGraphRevision:
    return api.ResearchGraphRevision(
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
            api.ResearchExecutionTarget("child-runtime", revision)
        )

        assert receipt.state == "succeeded", receipt.payload
        assert len(_CHILD_CALLS) == 1
        assert "ping" in _CHILD_CALLS[0]
    finally:
        composition.close()
