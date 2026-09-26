from __future__ import annotations

from pathlib import Path

import pytest

from noetrium import api
import noetrium_platform.research.execution.api as execution_api
import noetrium_platform.product.research_os as product_api
import noetrium_platform.foundation.kernel.kernel as kernel_api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import StrictResearchOSControl
from noetrium_platform.composition.research_os_runtime import CanonicalResearchOSNodeRuntime
from noetrium_platform.composition.research_os_values import ResearchOSValueRouter
from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


_CALLS: list[str] = []


def _first(request: execution_api.ProgramNodeRequest, _binding: object) -> execution_api.ProgramNodeResult:
    _CALLS.append("first")
    return execution_api.ProgramNodeResult(
        value={"stage": 1},
        state_update={"stage": 1},
    )


def _second(request: execution_api.ProgramNodeRequest, _binding: object) -> execution_api.ProgramNodeResult:
    _CALLS.append("second")
    return execution_api.ProgramNodeResult(
        value={
            "stage": 2,
            "previous": request.previous_value,
        },
        state_update={"stage": 2},
    )


NATIVE_RUNTIME_PROGRAM = (
    execution_api.MachineResearchProgramBuilder(
        program_id="test.native-runtime",
        kind=kernel_api.MachineKind.RUNTIME,
        version="1",
        state_schema="json",
        entrypoint="first",
    )
    .node("first", "test.native.first", next_node="second")
    .node("second", "test.native.second")
    .build()
)


def native_runtime_operations() -> tuple[execution_api.ResearchHostOperation, ...]:
    return (
        execution_api.ResearchHostOperation(
            "test.native.first",
            _first,
            kernel_api.canonical_digest({"operation": "test.native.first", "revision": 1}),
        ),
        execution_api.ResearchHostOperation(
            "test.native.second",
            _second,
            kernel_api.canonical_digest({"operation": "test.native.second", "revision": 1}),
        ),
    )


NATIVE_ANALYSIS_PROGRAM = (
    execution_api.MachineResearchProgramBuilder(
        program_id="test.native-analysis",
        kind=kernel_api.MachineKind.ANALYSIS,
        version="1",
        state_schema="json",
        entrypoint="analyze",
    )
    .node("analyze", "test.native.analysis")
    .build()
)


def native_analysis_operations() -> tuple[execution_api.ResearchHostOperation, ...]:
    return (
        execution_api.ResearchHostOperation(
            "test.native.analysis",
            _second,
            kernel_api.canonical_digest({"operation": "test.native.analysis", "revision": 1}),
        ),
    )


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def _bound(tmp_path: Path):
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    runtime = CanonicalResearchOSNodeRuntime(tmp_path / "machine-state")
    research_os = bind_portfolio_research_os(
        revisions,
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            ResearchOSValueRouter(()),
        ),
    )
    return graph, pool, research_os


def test_native_machine_program_executes_exact_multi_operation_ir(
    tmp_path: Path,
) -> None:
    _CALLS.clear()
    builder = product_api.ResearchProgramBuilder("paper")
    builder.machine_program(
        "native",
        program_module=__name__,
        program_qualname="NATIVE_RUNTIME_PROGRAM",
        operations_module=__name__,
        operations_qualname="native_runtime_operations",
    )
    builder.node(
        "run",
        kind=product_api.ResearchNodeKind.CUSTOM,
        definitions=("native",),
    )
    portfolio = product_api.ResearchPortfolio("native-machine-suite", (builder.freeze(),))

    graph, pool, research_os = _bound(tmp_path)
    try:
        revision = research_os.commit(portfolio, message="native machine")
        target = product_api.ResearchExecutionTarget("native-machine", revision)
        receipt = research_os.run(target)

        assert receipt.state == "succeeded"
        assert _CALLS == ["first", "second"]
        active = graph.active_cut(target.execution_id)
        assert active is not None
        attempts = graph.attempts(active.cut_id, "paper::run")
        assert len(attempts) == 1
    finally:
        pool.close()


def test_native_machine_kind_mismatch_fails_before_durable_cut(
    tmp_path: Path,
) -> None:
    builder = product_api.ResearchProgramBuilder("paper")
    builder.machine_program(
        "native",
        program_module=__name__,
        program_qualname="NATIVE_ANALYSIS_PROGRAM",
        operations_module=__name__,
        operations_qualname="native_analysis_operations",
    )
    builder.node(
        "run",
        kind=product_api.ResearchNodeKind.CUSTOM,
        definitions=("native",),
    )
    portfolio = product_api.ResearchPortfolio("native-machine-mismatch", (builder.freeze(),))

    graph, pool, research_os = _bound(tmp_path)
    try:
        revision = research_os.commit(portfolio, message="kind mismatch")
        target = product_api.ResearchExecutionTarget("native-machine-mismatch", revision)
        with pytest.raises(ValueError, match="machine program kind does not match node target"):
            research_os.run(target)
        assert graph.active_cut(target.execution_id) is None
    finally:
        pool.close()
