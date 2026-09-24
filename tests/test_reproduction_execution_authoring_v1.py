from __future__ import annotations

from noetrium import api
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)
from research.reproductions import (
    build_execution_research,
    execution_request,
)


def _task(task_id: str) -> TaskDefinition:
    return TaskDefinition(
        task_id,
        "mind2web.paper-cut",
        "web-navigation",
        "mind2web.task.v1",
        canonical_digest({"task_id": task_id}),
    )


def _benchmark() -> BenchmarkTaskSet:
    return BenchmarkTaskSet(
        benchmark_id="mind2web",
        revision_id="paper-cut",
        source_digest=canonical_digest(
            {"benchmark": "mind2web", "revision": "paper-cut"}
        ),
        task_schema_id="mind2web.task.v1",
        tasks=(_task("dev-task"), _task("test-task")),
        splits=(
            TaskSetSplit("dev", ("dev-task",)),
            TaskSetSplit("test", ("test-task",)),
        ),
    )


def test_top_level_execution_request_preserves_exact_benchmark_split_selection() -> None:
    benchmark = _benchmark()
    request = execution_request(
        "adaptagent_acl2025",
        "build_adaptagent_study",
        benchmark,
        benchmark_split_ids=("test",),
    )

    portfolio = build_execution_research((request,))

    assert isinstance(portfolio, api.ResearchPortfolio)
    assert portfolio.portfolio_id == "repository-reproductions.execution-research"
    assert len(portfolio.programs) == 1
    assert all(
        program.program_id.startswith("adaptagent_acl2025.")
        for program in portfolio.programs
    )
    assert len({program.program_id for program in portfolio.programs}) == 1

    revision = api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "top-level execution request",
    )
    graph = compile_research_portfolio_graph(revision, portfolio)
    assert len(graph.nodes) == 1
    assert graph.plan.research_revision_digest == revision.revision_digest
