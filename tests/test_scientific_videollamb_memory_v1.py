from __future__ import annotations

from research.reproductions.videollamb_memory.fidelity import (
    VIDEOLLAMB_REFERENCE_FIDELITY,
)


def test_videollamb_iccv2025_fidelity_freezes_recurrent_memory_contract() -> None:
    fidelity = VIDEOLLAMB_REFERENCE_FIDELITY

    assert fidelity.venue == "ICCV 2025"
    assert fidelity.recurrent_memory_tokens is True
    assert fidelity.memory_bridge_layers is True
    assert fidelity.memory_cache_retrieval is True
    assert fidelity.scene_tiling is True
    assert fidelity.bridge_transformer_layers == 1
    assert fidelity.training_frames == 16
    assert fidelity.training_segments == 4
    assert fidelity.demonstrated_max_frames == 320
    assert fidelity.demonstrated_gpu == "NVIDIA A100"
    assert fidelity.linear_gpu_memory_scaling is True
    assert fidelity.training_free_streaming_captioning is True
    assert fidelity.videoqa_improvement_points == 4.2
    assert fidelity.egocentric_planning_improvement_points == 2.06
    assert fidelity.source_commit == "962837c5b310559de18b375eaee20561123bb54c"
