from __future__ import annotations

from research.reproductions.provenance import MethodSourceRegistry, PublicationSourceLane

EMBODIED_VIDEOAGENT_PUBLICATION = PublicationSourceLane(
    lane_id="iccv_2025",
    venue="ICCV",
    year=2025,
    publication_id="embodied-videoagent-iccv-2025",
    publication_uri="https://openaccess.thecvf.com/content/ICCV2025/html/Fan_Embodied_VideoAgent_Persistent_Memory_from_Egocentric_Videos_and_Embodied_Sensors_ICCV_2025_paper.html",
    revision="ICCV 2025 proceedings publication",
)

SOURCES = MethodSourceRegistry(lanes=(EMBODIED_VIDEOAGENT_PUBLICATION,))

__all__ = ["EMBODIED_VIDEOAGENT_PUBLICATION","SOURCES"]
