from __future__ import annotations

from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.research_os import (
    PortfolioBackedResearchOSPort,
    bind_portfolio_research_os,
)
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.portfolio.api import PortfolioRevisionConflict
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.product.research_os import bind_research_os


def _method_v1(payload=None):
    return payload


def _method_v2(payload=None):
    return {"v": 2, "payload": payload}


def _other_method(payload=None):
    return payload


def _benchmark():
    return ("task",)


def _metric(value):
    return 1.0 if value else 0.0


class _Control:
    def __init__(self) -> None:
        self.calls = []

    def control(self, request, portfolio):
        self.calls.append((request, portfolio))
        return api.ResearchControlReceipt(
            request.action,
            request.target,
            "accepted",
            "f" * 64,
            request.payload,
        )


def _paper_a(method) -> api.ResearchProgram:
    builder = api.ResearchProgramBuilder("paper-a")
    builder.method("method", implementation=method)
    builder.benchmark("benchmark", implementation=_benchmark)
    builder.metric("metric", implementation=_metric)
    builder.experiment(
        "main",
        definitions=("method", "benchmark"),
        outputs=(
            api.ResearchOutputSpec(
                "trajectory",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    builder.evaluation(
        "evaluate",
        definitions=("metric",),
        depends_on=("main",),
        outputs=(
            api.ResearchOutputSpec(
                "score",
                api.ResearchValueKind.METRIC,
            ),
        ),
    )
    builder.analysis("analysis", depends_on=("evaluate",))
    return builder.freeze()


def _paper_b() -> api.ResearchProgram:
    builder = api.ResearchProgramBuilder("paper-b")
    builder.method("method", implementation=_other_method)
    builder.experiment("main", definitions=("method",))
    return builder.freeze()


def _portfolio(method) -> api.ResearchPortfolio:
    return api.ResearchPortfolio(
        "suite",
        (_paper_a(method), _paper_b()),
    )


def _binding(root: Path):
    revisions = SQLitePortfolioRevisionStore(root / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(root / "blobs")
    control = _Control()
    return revisions, blobs, control, bind_portfolio_research_os(
        revisions,
        blobs,
        control=control,
    )


def test_durable_research_os_reopens_revision_graph_and_minimally_invalidates(
    tmp_path: Path,
) -> None:
    revisions, _, _, _, _, research_os = _binding(tmp_path)
    first_portfolio = _portfolio(_method_v1)
    first = research_os.commit(first_portfolio, message="first")
    branch = research_os.branch("main", first)
    assert branch.generation == 1

    second_portfolio = _portfolio(_method_v2)
    second = research_os.commit(
        second_portfolio,
        parents=(first,),
        message="method update",
    )
    advanced = research_os.branch("main", second, expected=first)
    assert advanced.generation == 2
    research_os.tag("baseline", first)

    stored = revisions.revision("suite", first.revision_digest)
    assert stored.payload_digest == first_portfolio.portfolio_digest
    assert stored.payload_size_bytes > 0
    assert stored.revision_digest == first.revision_digest

    _, _, reopened_control, reopened = _binding(tmp_path)
    diff = reopened.diff(first, second)
    impacts = {
        (row.program_id, row.node_id): row.state
        for row in diff.impacts
    }
    assert impacts[("paper-a", "main")] is api.ResearchImpactState.INVALIDATED
    assert impacts[("paper-a", "evaluate")] is api.ResearchImpactState.STALE
    assert impacts[("paper-a", "analysis")] is api.ResearchImpactState.STALE
    assert impacts[("paper-b", "main")] is api.ResearchImpactState.REUSABLE

    execution = api.ResearchExecutionTarget(
        "suite-confirmatory",
        second,
    ).for_node("paper-a", "main")
    resumed = reopened.resume(execution)
    assert resumed.action is api.ResearchControlAction.RESUME
    assert resumed.target == execution
    assert len(reopened_control.calls) == 1
    control_request, control_portfolio = reopened_control.calls[0]
    assert control_request.target.revision == second
    assert control_portfolio == second_portfolio


def test_branch_compare_and_swap_rejects_stale_human_or_agent_edit(
    tmp_path: Path,
) -> None:
    _, _, _, _, research_os = _binding(tmp_path)
    first = research_os.commit(_portfolio(_method_v1), message="first")
    research_os.branch("main", first)
    second = research_os.commit(
        _portfolio(_method_v2),
        parents=(first,),
        message="second",
    )
    research_os.branch("main", second, expected=first)

    with pytest.raises(PortfolioRevisionConflict, match="compare-and-swap"):
        research_os.branch("main", first, expected=first)


def test_explicit_resolved_merge_preserves_both_parent_revisions(
    tmp_path: Path,
) -> None:
    _, _, _, _, research_os = _binding(tmp_path)
    base = research_os.commit(_portfolio(_method_v1), message="base")
    left = research_os.commit(
        _portfolio(_method_v2),
        parents=(base,),
        message="left",
    )
    right = research_os.commit(
        _portfolio(_method_v1),
        parents=(base,),
        message="right metadata cut",
    )
    merged = research_os.merge(
        _portfolio(_method_v2),
        left,
        right,
        message="human resolved merge",
    )
    assert merged.parent_revision_digests == (
        left.revision_digest,
        right.revision_digest,
    )


def test_portfolio_backed_port_fails_closed_without_runtime_control(
    tmp_path: Path,
) -> None:
    port = PortfolioBackedResearchOSPort(
        SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3"),
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
    )
    bound = bind_research_os(port)
    revision = api.ResearchGraphRevision(
        "anything",
        "a" * 64,
        (),
        "unbound control test",
    )
    target = api.ResearchExecutionTarget("anything", revision)
    with pytest.raises(RuntimeError, match="control is not bound"):
        bound.run(target)

def test_platform_resolved_requirements_round_trip_through_artifact_cas(
    tmp_path: Path,
) -> None:
    builder = api.ResearchProgramBuilder("declarative")
    builder.model("planner", config={"role": "planner", "context": 8192})
    builder.environment("world", config={"family": "minecraft"})
    builder.dataset("tasks", config={"split": "test"})
    builder.protocol("protocol", config={"repetitions": 3})
    builder.resource_policy("resources", config={"accelerator": "gpu"})
    builder.study(
        "main",
        definitions=("planner", "world", "tasks", "protocol", "resources"),
    )
    portfolio = api.ResearchPortfolio("declarative-suite", (builder.freeze(),))

    _, _, _, _, research_os = _binding(tmp_path)
    revision = research_os.commit(portfolio, message="declarative cut")

    _, _, _, _, reopened = _binding(tmp_path)
    diff = reopened.diff(revision, revision)
    assert tuple(row.state for row in diff.impacts) == (
        api.ResearchImpactState.UNCHANGED,
    )

def test_top_level_portfolio_compiles_into_one_multi_paper_execution_graph(
    tmp_path: Path,
) -> None:
    paper_a = _paper_a(_method_v1)
    paper_b = _paper_b()
    cross = api.ResearchPortfolioDependency(
        api.ResearchNodeRef("paper-a", "analysis"),
        api.ResearchNodeRef("paper-b", "main"),
    )
    portfolio = api.ResearchPortfolio(
        "multi-paper",
        (paper_a, paper_b),
        (cross,),
    )
    _, _, _, _, research_os = _binding(tmp_path)
    revision = research_os.commit(portfolio, message="multi-paper graph")

    compilation = compile_research_portfolio_graph(revision, portfolio)
    plan = compilation.plan
    by_id = {row.node_id: row for row in plan.nodes}

    assert compilation.revision == revision
    assert compilation.portfolio == portfolio
    assert plan.research_revision_digest == revision.revision_digest
    assert set(by_id) == {
        "paper-a::main",
        "paper-a::evaluate",
        "paper-a::analysis",
        "paper-b::main",
    }
    assert by_id["paper-a::main"].depends_on_node_ids == ()
    assert by_id["paper-a::evaluate"].depends_on_node_ids == ("paper-a::main",)
    assert by_id["paper-a::analysis"].depends_on_node_ids == ("paper-a::evaluate",)
    assert by_id["paper-b::main"].depends_on_node_ids == ("paper-a::analysis",)
    assert all(len(row.semantic_digest) == 64 for row in plan.nodes)

def test_compiled_semantic_digests_invalidate_only_transitive_descendants(
    tmp_path: Path,
) -> None:
    _, _, _, _, research_os = _binding(tmp_path)
    first_portfolio = _portfolio(_method_v1)
    first_revision = research_os.commit(first_portfolio, message="first")
    second_portfolio = _portfolio(_method_v2)
    second_revision = research_os.commit(
        second_portfolio,
        parents=(first_revision,),
        message="second",
    )

    first = compile_research_portfolio_graph(
        first_revision,
        first_portfolio,
    )
    second = compile_research_portfolio_graph(
        second_revision,
        second_portfolio,
    )
    first_digests = {
        node.graph_node_id: node.semantic_digest
        for node in first.nodes
    }
    second_digests = {
        node.graph_node_id: node.semantic_digest
        for node in second.nodes
    }

    assert first_digests["paper-a::main"] != second_digests["paper-a::main"]
    assert (
        first_digests["paper-a::evaluate"]
        != second_digests["paper-a::evaluate"]
    )
    assert (
        first_digests["paper-a::analysis"]
        != second_digests["paper-a::analysis"]
    )
    assert first_digests["paper-b::main"] == second_digests["paper-b::main"]

