from __future__ import annotations

from threading import RLock

from noetrium import api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os_graph import (
    bind_research_portfolio_scheduler,
    compile_research_portfolio_graph,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget


def _method(payload=None):
    return payload


def _search_program() -> api.research_os.ResearchProgram:
    builder = api.research_os.ResearchProgramBuilder("search-paper")
    builder.method("method", implementation=_method)
    builder.experiment(
        "explore",
        definitions=("method",),
        outputs=(
            api.research_os.ResearchOutputSpec(
                "candidates",
                api.research_os.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    builder.selection(
        "select",
        depends_on=("explore",),
        outputs=(
            api.research_os.ResearchOutputSpec(
                "best",
                api.research_os.ResearchValueKind.SELECTION,
            ),
        ),
    )
    return builder.freeze()


def _confirm_program() -> api.research_os.ResearchProgram:
    builder = api.research_os.ResearchProgramBuilder("confirm-paper")
    builder.environment(
        "environment",
        config={"family": "minecraft"},
    )
    builder.experiment(
        "confirm",
        definitions=("environment",),
    )
    return builder.freeze()


def _portfolio(input_name: str = "candidate") -> api.research_os.ResearchPortfolio:
    builder = api.research_os.ResearchPortfolioBuilder("suite")
    builder.program(_search_program())
    builder.program(_confirm_program())
    builder.depends(
        upstream_program_id="search-paper",
        upstream_node_id="select",
        downstream_program_id="confirm-paper",
        downstream_node_id="confirm",
        bindings=(
            api.research_os.ResearchInputBinding(
                input_name,
                "best",
                api.research_os.ResearchValueKind.SELECTION,
            ),
        ),
    )
    return builder.freeze()


def _revision(portfolio: api.research_os.ResearchPortfolio) -> api.research_os.ResearchGraphRevision:
    return api.research_os.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "test",
    )


class _Execution:
    def __init__(self) -> None:
        self.order: list[api.research_os.ResearchNodeRef] = []
        self._lock = RLock()

    def execute(self, context, node, *, deadline) -> None:
        del deadline
        context.checkpoint()
        with self._lock:
            self.order.append(node.ref)


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=4,
            max_cpu_workers=1,
            max_async_io_in_flight=4,
        )
    )


def test_portfolio_compiles_same_and_cross_paper_dependencies_into_one_graph() -> None:
    portfolio = _portfolio()
    compilation = compile_research_portfolio_graph(
        _revision(portfolio),
        portfolio,
    )
    by_id = {node.node_id: node for node in compilation.plan.nodes}

    assert tuple(by_id) == (
        "confirm-paper::confirm",
        "search-paper::explore",
        "search-paper::select",
    )
    assert by_id["search-paper::select"].depends_on_node_ids == (
        "search-paper::explore",
    )
    assert by_id["confirm-paper::confirm"].depends_on_node_ids == (
        "search-paper::select",
    )
    confirm = compilation.node("confirm-paper::confirm")
    assert confirm.ref == api.research_os.ResearchNodeRef("confirm-paper", "confirm")
    assert confirm.definitions[0].definition_id == "environment"
    assert confirm.definitions[0].platform_resolved

    assert len(confirm.incoming_edges) == 1
    edge = confirm.incoming_edges[0]
    assert edge.upstream == api.research_os.ResearchNodeRef("search-paper", "select")
    assert tuple(
        (binding.input_name, binding.output_name, binding.kind)
        for binding in edge.bindings
    ) == (
        ("candidate", "best", api.research_os.ResearchValueKind.SELECTION),
    )
    assert confirm.upstream_refs == (edge.upstream,)
    assert confirm.incoming_dependency_digests == (edge.dependency_digest,)


def test_typed_cross_paper_binding_changes_canonical_graph_identity() -> None:
    first = _portfolio("candidate")
    second = _portfolio("selected-candidate")
    compiled_first = compile_research_portfolio_graph(_revision(first), first)
    compiled_second = compile_research_portfolio_graph(_revision(second), second)

    assert first.portfolio_digest != second.portfolio_digest
    assert compiled_first.plan.graph_digest != compiled_second.plan.graph_digest
    assert (
        compiled_first.node("confirm-paper::confirm").semantic_digest
        != compiled_second.node("confirm-paper::confirm").semantic_digest
    )


def test_compiled_portfolio_runs_through_the_same_research_graph_scheduler() -> None:
    portfolio = _portfolio()
    compilation = compile_research_portfolio_graph(
        _revision(portfolio),
        portfolio,
    )
    execution = _Execution()
    pool = _pool()
    scheduler = bind_research_portfolio_scheduler(
        compilation,
        execution,
        execution_pool=pool,
    )
    try:
        report = scheduler.execute()
    finally:
        scheduler.close()
        pool.close()

    assert report.failed_node_ids == ()
    assert report.blocked_node_ids == ()
    assert set(report.succeeded_node_ids) == {
        "confirm-paper::confirm",
        "search-paper::explore",
        "search-paper::select",
    }
    positions = {ref: index for index, ref in enumerate(execution.order)}
    assert positions[api.research_os.ResearchNodeRef("search-paper", "explore")] < positions[
        api.research_os.ResearchNodeRef("search-paper", "select")
    ]
    assert positions[api.research_os.ResearchNodeRef("search-paper", "select")] < positions[
        api.research_os.ResearchNodeRef("confirm-paper", "confirm")
    ]
