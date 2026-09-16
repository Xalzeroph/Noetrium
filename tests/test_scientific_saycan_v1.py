import math

import pytest

from research.reproductions.saycan import SAYCAN_FIDELITY, select_saycan_skill


def test_saycan_fidelity_pins_paper_scoring_rule() -> None:
    assert SAYCAN_FIDELITY.paper_arxiv == "2204.01691"
    assert SAYCAN_FIDELITY.language_score_transform == "exp"
    assert SAYCAN_FIDELITY.combined_score_rule == "exp(llm_log_score) * affordance_score"
    assert SAYCAN_FIDELITY.selection_rule == "argmax"
    assert SAYCAN_FIDELITY.skill_execution_is_external is True


def test_saycan_multiplies_language_probability_by_affordance_then_normalizes() -> None:
    selection = select_saycan_skill(
        {
            "pick apple": math.log(0.8),
            "open drawer": math.log(0.5),
        },
        {
            "pick apple": 0.25,
            "open drawer": 0.9,
        },
    )

    assert selection.selected_skill == "open drawer"
    rows = {row.skill: row for row in selection.scores}
    assert rows["pick apple"].combined_score == pytest.approx(0.2)
    assert rows["open drawer"].combined_score == pytest.approx(0.45)
    assert sum(row.normalized_score for row in selection.scores) == pytest.approx(1.0)


def test_saycan_affordance_can_veto_semantically_likely_skill() -> None:
    selection = select_saycan_skill(
        {"impossible": math.log(0.99), "feasible": math.log(0.2)},
        {"impossible": 0.0, "feasible": 1.0},
    )
    assert selection.selected_skill == "feasible"


def test_saycan_fails_closed_on_score_domain_or_skill_set_drift() -> None:
    with pytest.raises(ValueError, match="same non-empty skill set"):
        select_saycan_skill({"a": -1.0}, {"b": 0.5})
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        select_saycan_skill({"a": -1.0}, {"a": 1.1})
    with pytest.raises(ValueError, match="positive mass"):
        select_saycan_skill({"a": -1.0}, {"a": 0.0})
