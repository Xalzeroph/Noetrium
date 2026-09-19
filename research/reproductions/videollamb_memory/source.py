from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)


VIDEOLLAMB_PAPER_ERA_COMMIT = "962837c5b310559de18b375eaee20561123bb54c"

VIDEOLLAMB_ICCV_2025 = PublicationSourceLane(
    lane_id="iccv_2025_camera_ready",
    venue="ICCV",
    year=2025,
    publication_id="videollamb-iccv-2025",
    publication_uri=(
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Wang_VideoLLaMB_Long_Streaming_Video_Understanding_with_"
        "Recurrent_Memory_Bridges_ICCV_2025_paper.html"
    ),
    revision="ICCV 2025 camera-ready paper",
)

VIDEOLLAMB_PAPER_ERA_EXECUTABLE = MethodSourceLane(
    lane_id="official_paper_era_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/bigai-nlco/VideoLLaMB",
    commit=VIDEOLLAMB_PAPER_ERA_COMMIT,
    artifacts=(
        "llava/model/multimodal_encoder/languagebind/rmt_video/modeling_video.py",
        "llava/model/multimodal_projector/rmt_r_transformer_projector.py",
        "llava/model/multimodal_projector/self_retriever.py",
        "llava/model/multimodal_projector/self_segment.py",
        "llava/train/train_mem.py",
        "scripts/eval/egoschema.sh",
        "scripts/eval/egoplan.sh",
        "scripts/eval/mvbench.sh",
        "scripts/eval/nextqa.sh",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(VIDEOLLAMB_ICCV_2025, VIDEOLLAMB_PAPER_ERA_EXECUTABLE),
)


__all__ = [
    "SOURCES",
    "VIDEOLLAMB_ICCV_2025",
    "VIDEOLLAMB_PAPER_ERA_COMMIT",
    "VIDEOLLAMB_PAPER_ERA_EXECUTABLE",
]
