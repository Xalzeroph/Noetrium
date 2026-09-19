from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)


ADACM2_CVPR_2025 = PublicationSourceLane(
    lane_id="cvpr_2025_camera_ready",
    venue="CVPR",
    year=2025,
    publication_id="man2025adacm2",
    publication_uri=(
        "https://openaccess.thecvf.com/content/CVPR2025/html/"
        "Man_AdaCM2_On_Understanding_Extremely_Long-Term_Video_"
        "with_Adaptive_Cross-Modality_Memory_CVPR_2025_paper.html"
    ),
    revision="CVPR 2025 camera-ready paper",
)


SOURCES = MethodSourceRegistry(
    lanes=(ADACM2_CVPR_2025,),
)


__all__ = [
    "ADACM2_CVPR_2025",
    "SOURCES",
]
