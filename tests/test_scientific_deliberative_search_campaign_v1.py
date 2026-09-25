from __future__ import annotations

from pathlib import Path

from research.campaigns.deliberative_search import (
    DELIBERATIVE_SEARCH_ACTIVE_LANES,
    DELIBERATIVE_SEARCH_WAVE1_LANES,
    DELIBERATIVE_SEARCH_WAVE2_LANES,
    DELIBERATIVE_SEARCH_WAVE3_LANES,
)


ROOT = Path(__file__).resolve().parents[1]

LANE_PACKAGES = {
    "react-alfworld": "react_alfworld",
    "reflexion-alfworld": "reflexion_alfworld",
    "tree-of-thoughts-game24": "tree_of_thoughts",
    "rap-blocksworld": "rap_reasoning",
    "lats-webshop": "lats_webshop",
    "tree-search-vwa": "tree_search_language_model_agents",
    "agent-q-surrogate": "agent_q_surrogate",
    "exact-vwa": "exact_vwa",
    "qlass-alfworld": "qlass_alfworld",
    "lits-math500": "lits_math500",
    "gats-synthetic-stress": "gats",
}


def test_active_deliberative_search_campaign_covers_all_typed_study_lanes() -> None:
    assert len(DELIBERATIVE_SEARCH_WAVE1_LANES) == 5
    assert len(DELIBERATIVE_SEARCH_WAVE2_LANES) == 5
    assert len(DELIBERATIVE_SEARCH_WAVE3_LANES) == 1
    waves = (
        set(DELIBERATIVE_SEARCH_WAVE1_LANES),
        set(DELIBERATIVE_SEARCH_WAVE2_LANES),
        set(DELIBERATIVE_SEARCH_WAVE3_LANES),
    )
    assert all(left.isdisjoint(right) for index, left in enumerate(waves) for right in waves[index + 1 :])
    assert DELIBERATIVE_SEARCH_ACTIVE_LANES == (
        DELIBERATIVE_SEARCH_WAVE1_LANES
        + DELIBERATIVE_SEARCH_WAVE2_LANES
        + DELIBERATIVE_SEARCH_WAVE3_LANES
    )
    assert set(DELIBERATIVE_SEARCH_ACTIVE_LANES) == set(LANE_PACKAGES)


def test_every_active_campaign_lane_has_typed_definition_source_and_study_assets() -> None:
    for lane_id in DELIBERATIVE_SEARCH_ACTIVE_LANES:
        package = LANE_PACKAGES[lane_id]
        root = ROOT / "research" / "reproductions" / package
        assert (root / "definition.py").is_file(), lane_id
        assert (root / "source.py").is_file(), lane_id
        assert (root / "study.py").is_file(), lane_id
