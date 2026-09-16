from research.reproductions.ai_scientist_v1 import (
    AI_SCIENTIST_V1_FIDELITY,
    AIScientistV1Stage,
)
from research.reproductions.ai_scientist_v2 import AI_SCIENTIST_V2_FIDELITY


def test_ai_scientist_v1_preserves_template_baseline_experiment_pipeline() -> None:
    fidelity = AI_SCIENTIST_V1_FIDELITY
    assert fidelity.paper_arxiv == "2408.06292"
    assert fidelity.idea_count_default == 50
    assert fidelity.idea_reflections == 3
    assert fidelity.baseline_run == 0
    assert fidelity.max_experiment_runs == 5
    assert fidelity.max_repair_iterations == 4
    assert fidelity.experiment_timeout_seconds == 7200
    assert fidelity.review_reflections == 5
    assert fidelity.review_ensemble_size == 5
    assert fidelity.template_dependent is True
    assert fidelity.novel_ideas_only is True
    assert fidelity.stage_order == (
        AIScientistV1Stage.IDEA_GENERATION,
        AIScientistV1Stage.NOVELTY_CHECK,
        AIScientistV1Stage.PROJECT_FORK,
        AIScientistV1Stage.EXPERIMENT,
        AIScientistV1Stage.PLOTTING,
        AIScientistV1Stage.WRITEUP,
        AIScientistV1Stage.REVIEW,
    )


def test_ai_scientist_v2_preserves_parallel_progressive_research_search() -> None:
    fidelity = AI_SCIENTIST_V2_FIDELITY
    assert fidelity.paper_arxiv == "2504.08066"
    assert fidelity.human_authored_template_required is False
    assert fidelity.parallel_workers == 4
    assert fidelity.stage_iteration_budgets == (20, 12, 12, 18)
    assert fidelity.generic_improvement_steps == 5
    assert fidelity.multi_seed_count == 3
    assert fidelity.execution_timeout_seconds == 3600
    assert fidelity.max_debug_depth == 3
    assert fidelity.debug_probability == 0.5
    assert fidelity.draft_count == 3
    assert fidelity.citation_rounds == 20
    assert fidelity.writeup_retries == 3
    assert fidelity.experiment_manager_guided_tree_search is True
    assert fidelity.text_and_vlm_review is True


def test_ai_scientist_v2_method_journal_never_replaces_platform_journal_authority() -> None:
    fidelity = AI_SCIENTIST_V2_FIDELITY
    assert fidelity.method_journal_source.endswith("treesearch/journal.py")
    assert fidelity.method_journal_role == "downstream_search_state"
    assert fidelity.kernel_journal_remains_platform_authority is True
