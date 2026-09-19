from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)


DRVIDEO_OFFICIAL_COMMIT = "986d232133e9717a547905d32198f552ce202b5e"

DRVIDEO_CVPR_2025 = PublicationSourceLane(
    lane_id="cvpr_2025_camera_ready",
    venue="CVPR",
    year=2025,
    publication_id="drvideo-cvpr-2025",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2025/html/"
        "Ma_DrVideo_Document_Retrieval_Based_Long_Video_"
        "Understanding_CVPR_2025_paper.html"
    ),
    revision="CVPR 2025 camera-ready paper",
)

DRVIDEO_OFFICIAL_RELEASE = MethodSourceLane(
    lane_id="official_release_2025_08_11",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/Upper9527/DrVideo",
    commit=DRVIDEO_OFFICIAL_COMMIT,
    artifacts=(
        "main.py",
        "prompts.py",
        "model.py",
        "dataset.py",
        "eval.py",
        "models/blip2_model.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(DRVIDEO_CVPR_2025, DRVIDEO_OFFICIAL_RELEASE),
)


__all__ = [
    "DRVIDEO_CVPR_2025",
    "DRVIDEO_OFFICIAL_COMMIT",
    "DRVIDEO_OFFICIAL_RELEASE",
    "SOURCES",
]
