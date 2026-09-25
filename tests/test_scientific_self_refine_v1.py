from __future__ import annotations

from research.reproductions.self_refine import SELF_REFINE_FIDELITY


def test_self_refine_mechanism_fidelity_is_frozen() -> None:
    fidelity = SELF_REFINE_FIDELITY
    assert fidelity.mechanism == ("init", "feedback", "iterate")
    assert fidelity.training_free is True
    assert fidelity.same_model_reused_across_roles is True
    assert fidelity.task_specific_attempt_budget is True
    assert fidelity.task_specific_stop_condition is True
    assert fidelity.source_repository == "https://github.com/madaan/self-refine"
