from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    execute_research_portfolio,
    preflight_research_portfolio,
)


def _bootstrap():
    return None


def _portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.definition(
        "bootstrap",
        kind=api.ResearchDefinitionKind.CUSTOM,
        implementation=_bootstrap,
    )
    builder.node(
        "root",
        kind=api.ResearchNodeKind.CUSTOM,
        definitions=("bootstrap",),
    )
    return api.ResearchPortfolio("paper", (builder.freeze(),))


def test_single_program_and_multi_program_use_cardinality_agnostic_execution(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio()
    authorities = ResearchExecutionAuthorities.provider_neutral()

    preflight = preflight_research_portfolio(
        portfolio,
        state_root=tmp_path / "state",
        authorities=authorities,
    )
    assert preflight.portfolio_id == "paper"
    assert preflight.selected_node_ids == ("paper::root",)

    result = execute_research_portfolio(
        portfolio,
        state_root=tmp_path / "state",
        authorities=authorities,
    )
    assert result.portfolio_id == "paper"
    assert result.receipt.state == "succeeded"
    assert result.revision.revision_digest == preflight.revision_digest


def test_portfolio_execution_identity_changes_with_authority_cut(
    tmp_path: Path,
) -> None:
    portfolio = _portfolio()
    left = ResearchExecutionAuthorities.provider_neutral()
    right = ResearchExecutionAuthorities("a" * 64)

    left_preflight = preflight_research_portfolio(
        portfolio,
        state_root=tmp_path / "left",
        authorities=left,
    )
    right_preflight = preflight_research_portfolio(
        portfolio,
        state_root=tmp_path / "right",
        authorities=right,
    )
    assert left_preflight.revision_digest != right_preflight.revision_digest
