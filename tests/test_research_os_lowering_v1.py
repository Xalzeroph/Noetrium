from __future__ import annotations

import pytest

from noetrium_platform.composition.research_os_lowering import (
    ResearchImplementationResolutionError,
    ResearchOSLoweringTarget,
    compile_research_os_lowering,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.product import research_os as api


def _method(payload=None):
    return payload


def _metric(payload=None):
    return payload


def _revision(portfolio: api.ResearchPortfolio) -> api.ResearchGraphRevision:
    return api.ResearchGraphRevision(
        portfolio.portfolio_id,
        portfolio.portfolio_digest,
        (),
        "lowering test",
    )


def test_lowering_partitions_paper_implementation_from_platform_requirement() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("method", implementation=_method)
    builder.model("planner", config={"role": "planner"})
    builder.environment("world", config={"family": "minecraft"})
    builder.experiment(
        "main",
        definitions=("method", "planner", "world"),
    )
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))
    compilation = compile_research_portfolio_graph(_revision(portfolio), portfolio)

    lowering = compile_research_os_lowering(compilation)
    node = lowering.node("paper::main")

    assert node.target is ResearchOSLoweringTarget.EXPERIMENTATION
    assert tuple(row.definition_id for row in node.implementations) == ("method",)
    assert node.implementations[0].implementation is _method
    assert tuple(row.definition_id for row in node.platform_requirements) == (
        "planner",
        "world",
    )
    assert len(node.lowering_digest) == 64
    assert len(lowering.lowering_digest) == 64


def test_lowering_covers_method_evaluation_optimization_and_workbench_routes() -> None:
    builder = api.ResearchProgramBuilder("paper")
    builder.method("method", implementation=_method)
    builder.metric("metric", implementation=_metric)
    builder.node(
        "method-node",
        kind=api.ResearchNodeKind.METHOD,
        definitions=("method",),
    )
    builder.evaluation(
        "evaluation",
        definitions=("metric",),
        depends_on=("method-node",),
    )
    builder.node(
        "optimization",
        kind=api.ResearchNodeKind.OPTIMIZATION,
        definitions=("metric",),
        depends_on=("evaluation",),
    )
    builder.analysis("analysis", depends_on=("optimization",))
    builder.selection("selection", depends_on=("analysis",))
    builder.figure("figure", depends_on=("selection",))
    builder.table("table", depends_on=("figure",))
    portfolio = api.ResearchPortfolio("suite", (builder.freeze(),))

    lowering = compile_research_os_lowering(
        compile_research_portfolio_graph(_revision(portfolio), portfolio)
    )

    assert lowering.node("paper::method-node").target is (
        ResearchOSLoweringTarget.METHOD_MACHINE
    )
    assert lowering.node("paper::evaluation").target is (
        ResearchOSLoweringTarget.EVALUATION_MACHINE
    )
    assert lowering.node("paper::optimization").target is (
        ResearchOSLoweringTarget.OPTIMIZATION_MACHINE
    )
    for node_id in ("analysis", "selection", "figure", "table"):
        assert lowering.node(f"paper::{node_id}").target is (
            ResearchOSLoweringTarget.WORKBENCH
        )


def test_import_resolution_fails_closed_when_frozen_source_identity_drifted() -> None:
    declared = api.ResearchImplementation(
        implementation_id="method",
        module=__name__,
        qualname="_method",
        source_digest="0" * 64,
    )
    definition = api.ResearchDefinition(
        "method",
        api.ResearchDefinitionKind.METHOD,
        declared,
    )
    node = api.ResearchNode(
        "method-node",
        api.ResearchNodeKind.METHOD,
        ("method",),
    )
    program = api.ResearchProgram("paper", (definition,), (node,), ())
    portfolio = api.ResearchPortfolio("suite", (program,))
    compilation = compile_research_portfolio_graph(_revision(portfolio), portfolio)

    with pytest.raises(
        ResearchImplementationResolutionError,
        match="source drifted",
    ):
        compile_research_os_lowering(compilation)
