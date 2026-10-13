from __future__ import annotations

from research.reproductions.vca_video.fidelity import VCA_REFERENCE_FIDELITY


def test_vca_iccv2025_fidelity_contract_freezes_core_semantics() -> None:
    fidelity = VCA_REFERENCE_FIDELITY

    assert fidelity.venue == "ICCV 2025"
    assert fidelity.training_free is True
    assert fidelity.shared_vlm_for_reward_and_exploration is True
    assert fidelity.tree_search is True
    assert fidelity.reward_history_conditioning is True
    assert fidelity.fixed_size_memory is True
    assert fidelity.non_greedy_segment_choice is True
    assert fidelity.temperature == 0.5
    assert fidelity.reference_model == "gpt-4o-august-2024"
    assert fidelity.egoschema_memory_frames == 8
    assert fidelity.lvbench_memory_frames == 16
    assert fidelity.egoschema_task_count == 500
    assert fidelity.lvbench_task_count == 1549
    assert fidelity.mmbench_video_task_count == 1998
    assert fidelity.videomme_long_task_count == 900
    assert fidelity.egoschema_reported_accuracy == 0.736
    assert fidelity.egoschema_reported_average_frames == 7.2
    assert fidelity.lvbench_reported_accuracy == 0.413
    assert fidelity.lvbench_reported_average_frames == 20.0
