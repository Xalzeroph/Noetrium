from __future__ import annotations

from noetrium_platform.research.reproduction import ReproductionAssetKind
from research.reproductions.optimus1_minecraft.definition import REPRODUCTION
from research.reproductions.optimus1_minecraft.fidelity import (
    OPTIMUS1_REFERENCE_FIDELITY,
)


def test_optimus1_neurips2024_fidelity_freezes_hybrid_memory_architecture() -> None:
    fidelity = OPTIMUS1_REFERENCE_FIDELITY

    assert fidelity.venue == "NeurIPS 2024"
    assert fidelity.hybrid_multimodal_memory is True
    assert fidelity.hdkg_enabled is True
    assert fidelity.amep_enabled is True
    assert fidelity.knowledge_guided_planner is True
    assert fidelity.experience_driven_reflector is True
    assert fidelity.action_controller == "steve1"

    assert fidelity.hdkg_source == "minecraft_recipe_dependency_graph"
    assert fidelity.hdkg_retrieval == "goal_conditioned_subgraph_compile"
    assert fidelity.amep_plan_memory is True
    assert fidelity.amep_reflection_memory is True
    assert fidelity.amep_replan_memory is True
    assert fidelity.amep_reflection_labels == (
        "done",
        "continue",
        "replan",
    )
    assert fidelity.reflection_is_multimodal is True
    assert fidelity.replan_uses_error_conditioned_experience is True


def test_optimus1_preserves_paper_release_benchmark_identity_delta() -> None:
    fidelity = OPTIMUS1_REFERENCE_FIDELITY

    assert fidelity.paper_long_horizon_task_count == 67
    assert fidelity.official_release_config_task_count == 73
    assert fidelity.paper_task_group_count == 7
    assert fidelity.reported_metrics == (
        "success_rate",
        "average_steps",
        "average_time",
    )
    assert set(fidelity.headline_groups) == {
        "iron",
        "gold",
        "diamond",
        "redstone",
        "armor",
    }
    assert fidelity.official_release_planner_model == "gpt-4o"
    assert fidelity.official_release_controller_checkpoint == "steve1"


def test_optimus1_reproduction_keeps_unresolved_paper_cut_explicit() -> None:
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    assert REPRODUCTION.identity.method_id == "optimus1-minecraft"
    assert REPRODUCTION.catalog.benchmark_ids == ()
    kinds = tuple(asset.kind for asset in REPRODUCTION.assets)
    assert ReproductionAssetKind("fidelity") in kinds
    assert any(
        "67-task" in delta.description and "73" in delta.description
        for delta in REPRODUCTION.deltas
    )
