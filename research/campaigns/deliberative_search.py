from __future__ import annotations

from noetrium_platform.research.experimentation.api import (
    CompiledResearchCampaign,
    ResearchCampaignCompilationUnit,
    compile_research_campaign,
)

DELIBERATIVE_SEARCH_WAVE1_CAMPAIGN_ID = "deliberative-search-wave1"
DELIBERATIVE_SEARCH_WAVE1_LANES = (
    "react-alfworld",
    "reflexion-alfworld",
    "tree-of-thoughts-game24",
    "rap-blocksworld",
    "lats-webshop",
)

DELIBERATIVE_SEARCH_WAVE2_CAMPAIGN_ID = "deliberative-search-wave2"
DELIBERATIVE_SEARCH_WAVE2_LANES = (
    "tree-search-vwa",
    "agent-q-surrogate",
    "exact-vwa",
    "qlass-alfworld",
    "lits-math500",
)

DELIBERATIVE_SEARCH_WAVE3_CAMPAIGN_ID = "deliberative-search-wave3"
DELIBERATIVE_SEARCH_WAVE3_LANES = (
    "gats-synthetic-stress",
)

DELIBERATIVE_SEARCH_ACTIVE_CAMPAIGN_ID = "deliberative-search-active"
DELIBERATIVE_SEARCH_ACTIVE_LANES = (
    DELIBERATIVE_SEARCH_WAVE1_LANES
    + DELIBERATIVE_SEARCH_WAVE2_LANES
    + DELIBERATIVE_SEARCH_WAVE3_LANES
)


def _compile_exact(
    campaign_id: str,
    expected_lanes: tuple[str, ...],
    units: tuple[ResearchCampaignCompilationUnit, ...],
) -> CompiledResearchCampaign:
    if type(units) is not tuple or any(
        type(row) is not ResearchCampaignCompilationUnit for row in units
    ):
        raise TypeError("search-lineage campaign units must be typed")
    by_lane = {row.lane_id: row for row in units}
    if len(by_lane) != len(units):
        raise ValueError("search-lineage campaign lane identities must be unique")
    expected = set(expected_lanes)
    actual = set(by_lane)
    if actual != expected:
        raise ValueError(
            "search-lineage campaign units must exactly cover declared lanes; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    return compile_research_campaign(
        campaign_id,
        tuple(by_lane[lane_id] for lane_id in expected_lanes),
    )


def compile_deliberative_search_wave1(
    units: tuple[ResearchCampaignCompilationUnit, ...],
) -> CompiledResearchCampaign:
    return _compile_exact(
        DELIBERATIVE_SEARCH_WAVE1_CAMPAIGN_ID,
        DELIBERATIVE_SEARCH_WAVE1_LANES,
        units,
    )


def compile_deliberative_search_wave2(
    units: tuple[ResearchCampaignCompilationUnit, ...],
) -> CompiledResearchCampaign:
    return _compile_exact(
        DELIBERATIVE_SEARCH_WAVE2_CAMPAIGN_ID,
        DELIBERATIVE_SEARCH_WAVE2_LANES,
        units,
    )


def compile_deliberative_search_wave3(
    units: tuple[ResearchCampaignCompilationUnit, ...],
) -> CompiledResearchCampaign:
    return _compile_exact(
        DELIBERATIVE_SEARCH_WAVE3_CAMPAIGN_ID,
        DELIBERATIVE_SEARCH_WAVE3_LANES,
        units,
    )


def compile_deliberative_search_active(
    units: tuple[ResearchCampaignCompilationUnit, ...],
) -> CompiledResearchCampaign:
    """Compile all currently typed executable/scaffolded primary lineage lanes."""

    return _compile_exact(
        DELIBERATIVE_SEARCH_ACTIVE_CAMPAIGN_ID,
        DELIBERATIVE_SEARCH_ACTIVE_LANES,
        units,
    )


__all__ = [
    "DELIBERATIVE_SEARCH_ACTIVE_CAMPAIGN_ID",
    "DELIBERATIVE_SEARCH_ACTIVE_LANES",
    "DELIBERATIVE_SEARCH_WAVE1_CAMPAIGN_ID",
    "DELIBERATIVE_SEARCH_WAVE1_LANES",
    "DELIBERATIVE_SEARCH_WAVE2_CAMPAIGN_ID",
    "DELIBERATIVE_SEARCH_WAVE2_LANES",
    "DELIBERATIVE_SEARCH_WAVE3_CAMPAIGN_ID",
    "DELIBERATIVE_SEARCH_WAVE3_LANES",
    "compile_deliberative_search_active",
    "compile_deliberative_search_wave1",
    "compile_deliberative_search_wave2",
    "compile_deliberative_search_wave3",
]
