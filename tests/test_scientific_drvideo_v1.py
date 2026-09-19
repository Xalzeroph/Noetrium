from __future__ import annotations

from research.reproductions.drvideo.fidelity import DRVIDEO_REFERENCE_FIDELITY


def test_drvideo_cvpr2025_fidelity_freezes_document_agent_pipeline() -> None:
    fidelity = DRVIDEO_REFERENCE_FIDELITY

    assert fidelity.venue == "CVPR 2025"
    assert fidelity.video_document_conversion is True
    assert fidelity.text_space_semantic_retrieval is True
    assert fidelity.question_conditioned_augmentation is True
    assert fidelity.multi_stage_agent_loop is True
    assert fidelity.chain_of_thought_answering is True

    assert fidelity.paper_initial_top_k == 5
    assert fidelity.official_code_initial_top_k == 20
    assert fidelity.max_agent_rounds == 2
    assert fidelity.augmentation_types == ("caption", "vqa")
    assert fidelity.maximum_added_frames_per_round == 3

    assert fidelity.egoschema_sampling_fps == 0.5
    assert fidelity.moviechat_sampling_fps == 0.5
    assert fidelity.videomme_sampling_fps == 0.2
    assert fidelity.egoschema_public_task_count == 500

    assert fidelity.egoschema_reported_accuracy == 0.664
    assert fidelity.moviechat_global_reported_accuracy == 0.931
    assert fidelity.moviechat_breakpoint_reported_accuracy == 0.564
    assert fidelity.videomme_long_without_subtitles_accuracy == 0.517
    assert fidelity.videomme_long_with_subtitles_accuracy == 0.717
