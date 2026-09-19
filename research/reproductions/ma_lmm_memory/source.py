from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

MALMM_AUDITED_COMMIT = "6ad50f3efcaca7776d2e1e5f1be32e09ceff9910"
MALMM_COMPATIBILITY_COMMIT = "f9467665132bc258ae4119d0dc80ea02c4b5bd60"

MALMM_CVPR_2024 = PublicationSourceLane(
    lane_id="cvpr_2024_final",
    venue="CVPR",
    year=2024,
    publication_id="ma-lmm-cvpr-2024",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2024/html/"
        "He_MA-LMM_Memory-Augmented_Large_Multimodal_Model_for_"
        "Long-Term_Video_Understanding_CVPR_2024_paper.html"
    ),
    revision="CVPR 2024 final paper",
)

MALMM_PAPER_ERA_EXECUTABLE = MethodSourceLane(
    lane_id="paper_era_official_initial",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/boheumd/MA-LMM",
    commit=MALMM_AUDITED_COMMIT,
    artifacts=(
        "lavis/models/blip2_models/blip2.py",
        "lavis/models/blip2_models/blip2_vicuna_instruct.py",
        "lavis/configs/models/blip2/blip2_instruct_vicuna7b.yaml",
        "run_scripts/lvu/train.sh",
        "run_scripts/msvd/train_qa.sh",
        "run_scripts/msvd/train_cap.sh",
    ),
)

MALMM_COMPATIBILITY_BUGFIX = MethodSourceLane(
    lane_id="compatibility_video_path_bugfix",
    kind=MethodSourceLaneKind.LATER_RELEASED_EXECUTABLE,
    repository="https://github.com/boheumd/MA-LMM",
    commit=MALMM_COMPATIBILITY_COMMIT,
    artifacts=(
        "lavis/models/blip2_models/blip2_vicuna_instruct.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        MALMM_CVPR_2024,
        MALMM_PAPER_ERA_EXECUTABLE,
        MALMM_COMPATIBILITY_BUGFIX,
    ),
)

__all__ = [
    "MALMM_AUDITED_COMMIT",
    "MALMM_COMPATIBILITY_BUGFIX",
    "MALMM_COMPATIBILITY_COMMIT",
    "MALMM_CVPR_2024",
    "MALMM_PAPER_ERA_EXECUTABLE",
    "SOURCES",
]
