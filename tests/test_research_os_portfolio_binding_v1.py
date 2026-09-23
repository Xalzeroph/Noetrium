from __future__ import annotations

from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.research_os import (
    PortfolioBackedResearchOSPort,
    bind_portfolio_research_os,
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
    def control(self, request):
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
    return revisions, blobs, bind_portfolio_research_os(
        revisions,
        blobs,
        control=_Control(),
    )


def test_durable_research_os_reopens_revision_graph_and_minimally_invalidates(
    tmp_path: Path,
) -> None:
    revisions, _, research_os = _binding(tmp_path)
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

    _, _, reopened = _binding(tmp_path)
    diff = reopened.diff(first, second)
    impacts = {
        (row.program_id, row.node_id): row.state
        for row in diff.impacts
    }
    assert impacts[("paper-a", "main")] is api.ResearchImpactState.INVALIDATED
    assert impacts[("paper-a", "evaluate")] is api.ResearchImpactState.STALE
    assert impacts[("paper-a", "analysis")] is api.ResearchImpactState.STALE
    assert impacts[("paper-b", "main")] is api.ResearchImpactState.REUSABLE

    resumed = reopened.resume("suite:paper-a:main")
    assert resumed.action is api.ResearchControlAction.RESUME


def test_branch_compare_and_swap_rejects_stale_human_or_agent_edit(
    tmp_path: Path,
) -> None:
    _, _, research_os = _binding(tmp_path)
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
    _, _, research_os = _binding(tmp_path)
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
    with pytest.raises(RuntimeError, match="control is not bound"):
        bound.run("anything")
