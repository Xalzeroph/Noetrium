from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)

REWIND_CVPR_2025 = PublicationSourceLane(
    lane_id="cvpr_2025_camera_ready",
    venue="CVPR",
    year=2025,
    publication_id="diko2025rewind",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2025/html/"
        "Diko_ReWind_Understanding_Long_Videos_with_"
        "Instructed_Learnable_Memory_CVPR_2025_paper.html"
    ),
    revision="CVPR 2025 camera-ready paper",
)

SOURCES = MethodSourceRegistry(
    lanes=(REWIND_CVPR_2025,),
)

__all__ = [
    "REWIND_CVPR_2025",
    "SOURCES",
]
