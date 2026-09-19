from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

MOVIECHAT_INITIAL_RELEASE_COMMIT = "20fe48055acbb9f95dcf628fd90caacbe418d2d5"
MOVIECHAT_AUDITED_COMMIT = "f73f49233ea315bddc659ab3d1e358e0130eadb7"

MOVIECHAT_CVPR_2024 = PublicationSourceLane(
    lane_id="cvpr_2024_final",
    venue="CVPR",
    year=2024,
    publication_id="moviechat-cvpr-2024",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2024/html/"
        "Song_MovieChat_From_Dense_Token_to_Sparse_Memory_for_"
        "Long_Video_CVPR_2024_paper.html"
    ),
    revision="CVPR 2024 final paper",
)

MOVIECHAT_INITIAL_EXECUTABLE = MethodSourceLane(
    lane_id="initial_public_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/wenhaochai/MovieChat",
    commit=MOVIECHAT_INITIAL_RELEASE_COMMIT,
    artifacts=(
        "MovieChat/models/moviechat.py",
        "inference.py",
    ),
)

MOVIECHAT_PAPER_ERA_EXECUTABLE = MethodSourceLane(
    lane_id="paper_era_final_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/wenhaochai/MovieChat",
    commit=MOVIECHAT_AUDITED_COMMIT,
    artifacts=(
        "MovieChat/models/moviechat.py",
        "eval_configs/MovieChat.yaml",
        "eval_code/result_prepare/run_inference_qa_moviechat.py",
        "eval_code/Acc_score/run_eval_qa_moviechat.py",
        "inference.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        MOVIECHAT_CVPR_2024,
        MOVIECHAT_INITIAL_EXECUTABLE,
        MOVIECHAT_PAPER_ERA_EXECUTABLE,
    ),
)

__all__ = [
    "MOVIECHAT_AUDITED_COMMIT",
    "MOVIECHAT_CVPR_2024",
    "MOVIECHAT_INITIAL_EXECUTABLE",
    "MOVIECHAT_INITIAL_RELEASE_COMMIT",
    "MOVIECHAT_PAPER_ERA_EXECUTABLE",
    "SOURCES",
]
