from noetrium_platform.foundation.kernel.kernel import canonical_digest
from research.benchmarks.gats_synthetic import (
    GATS_STRESS_CATEGORIES,
    GATS_STRESS_SPLIT,
    GATS_STRESS_TASK_COUNT,
    GATS_STRESS_TASKS_PER_CATEGORY,
    GatsStressTaskRecord,
    build_gats_stress_task_set,
)
from research.reproductions.gats import (
    GATS_REPRODUCIBILITY_FIDELITY,
    build_gats_stress_b20_study,
)


def _benchmark():
    records = tuple(
        GatsStressTaskRecord(
            category=category,
            index=index,
            content_digest=canonical_digest(
                {"gats-stress": category, "index": index}
            ),
        )
        for category in GATS_STRESS_CATEGORIES
        for index in range(GATS_STRESS_TASKS_PER_CATEGORY)
    )
    return build_gats_stress_task_set(
        records,
        source_digest=canonical_digest({"gats-stress-source": 1}),
    )


def test_gats_stress_cut_is_exactly_twelve_categories_by_ten_tasks() -> None:
    benchmark = _benchmark()
    selected = benchmark.selected_tasks(GATS_STRESS_SPLIT)
    assert len(selected) == GATS_STRESS_TASK_COUNT == 120
    assert selected[0].task_id == "gats-stress:trap_heavy:00"
    assert selected[9].task_id == "gats-stress:trap_heavy:09"
    assert selected[10].task_id == "gats-stress:deep_horizon:00"


def test_gats_source_fidelity_separates_main_nondeterminism_from_stress_lane() -> None:
    fidelity = GATS_REPRODUCIBILITY_FIDELITY
    assert fidelity.source.kind.value == "official_executable"
    assert fidelity.main_task_generation_seeded_before_generation is False
    assert fidelity.main_generator_uses_random_choice_and_shuffle is True
    assert fidelity.stress_uses_layered_world_model is False
    assert fidelity.stress_transition_semantics == "direct_action_apply_plus_state_value_ucb"
    assert fidelity.stress_gats_budgets == (10, 20, 50)
    assert fidelity.stress_seeds == (42, 123, 456)


def test_gats_stress_b20_study_keeps_provenance_outside_execution_design() -> None:
    study = build_gats_stress_b20_study(_benchmark())
    assert not hasattr(study, "method_source_lane")
    assert GATS_REPRODUCIBILITY_FIDELITY.source.kind.value == "official_executable"
    assert study.binding_requirements.model_roles == ()
    assert study.execution_policy.trial_budget.max_steps == 35
