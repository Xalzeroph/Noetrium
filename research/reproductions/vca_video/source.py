from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)


VCA_ICCV_2025 = PublicationSourceLane(
    lane_id="iccv_2025_camera_ready",
    venue="ICCV",
    year=2025,
    publication_id="vca-video-iccv-2025",
    publication_uri=(
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Yang_VCA_Video_Curious_Agent_for_Long_Video_Understanding_"
        "ICCV_2025_paper.html"
    ),
    revision="ICCV 2025 camera-ready paper",
)

SOURCES = MethodSourceRegistry(lanes=(VCA_ICCV_2025,))


__all__ = ["SOURCES", "VCA_ICCV_2025"]
