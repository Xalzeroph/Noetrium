from __future__ import annotations

from noetrium_platform.research.provenance import MethodSourceRegistry, PublicationSourceLane

WATCH_LEARN_PUBLICATION = PublicationSourceLane(
    lane_id="cvpr_2026",
    venue="CVPR",
    year=2026,
    publication_id="watch-learn-cvpr-2026",
    publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Song_Watch_and_Learn_Learning_to_Use_Computers_from_Online_Videos_CVPR_2026_paper.html",
    revision="CVPR 2026 proceedings publication",
)

SOURCES = MethodSourceRegistry(lanes=(WATCH_LEARN_PUBLICATION,))

__all__ = ["WATCH_LEARN_PUBLICATION","SOURCES"]
